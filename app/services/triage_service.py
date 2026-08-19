"""
app/services/triage_service.py

Module 02 — AI Triage Engine

This service implements the full LangChain + Gemini + ChromaDB RAG pipeline.

Architecture:
    raw_text
      → GoogleGenerativeAIEmbeddings (embed query)
      → ChromaDB similarity search (top-K medical KB documents)
      → PromptTemplate (system prompt + retrieved context + patient text)
      → ChatGoogleGenerativeAI (Gemini 1.5 Flash)
      → PydanticOutputParser → TriageResult

Key design decisions:
  - TriageService is a singleton — ChromaDB and the LangChain chain are built
    once on first use (lazy initialisation via @cached_property) to avoid the
    overhead of rebuilding embeddings on every Celery task invocation.
  - seed_knowledge_base() is idempotent — it checks the existing document count
    before inserting, so repeated calls (e.g. on Docker restart) are safe.
  - The prompt explicitly requests JSON output matching the TriageResult schema
    using PydanticOutputParser.get_format_instructions(). This dramatically
    improves structured output reliability vs. ad-hoc prompting.
  - If the LLM returns malformed JSON we catch the parse error and fall back to
    a safe MODERATE urgency result so the Celery task never fails silently.
"""

from __future__ import annotations

import json
import logging
import textwrap
import uuid
from functools import cached_property
from typing import TYPE_CHECKING

import chromadb
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from app.config import get_settings
from app.schemas.triage import ExtractedSymptom, TriageResult
from app.services.medical_kb import MEDICAL_KB

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_TOP_K_DOCS = 5  # Number of KB documents to retrieve per query
_LLM_MODEL = "gemini-1.5-flash"
_EMBED_MODEL = "models/embedding-001"


# ── System Prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are MediSync, an expert AI medical triage assistant.
    Your role is to analyse patient-reported symptoms and classify urgency level.

    IMPORTANT RULES:
    1. You are NOT a doctor. You do NOT diagnose. You TRIAGE (classify urgency).
    2. Always err on the side of caution — if in doubt, classify as 'moderate'.
    3. Any symptom suggesting stroke, MI, anaphylaxis, or airway compromise → 'critical'.
    4. Extract ONLY symptoms explicitly mentioned by the patient. Do NOT infer unstated symptoms.
    5. Your response MUST be valid JSON matching the schema below — nothing else.

    URGENCY DEFINITIONS:
    - critical  → Life-threatening, needs emergency care NOW (call 911 / go to ER immediately)
    - moderate  → Needs a doctor within hours or today (urgent care / same-day appointment)
    - routine   → Can wait for a scheduled appointment (within days / self-care appropriate)

    MEDICAL KNOWLEDGE CONTEXT (retrieved from knowledge base):
    {kb_context}

    {format_instructions}
""")

_HUMAN_PROMPT = textwrap.dedent("""\
    Patient Report:
    ---------------
    {raw_text}

    Patient's self-reported severity: {severity_hint}

    Please analyse this symptom report and return your structured triage assessment.
""")


# ── Triage Service ─────────────────────────────────────────────────────────────

class TriageService:
    """
    Singleton service encapsulating the full RAG triage pipeline.

    Usage:
        from app.services.triage_service import triage_service
        result: TriageResult = triage_service.run_triage_pipeline(raw_text, severity_hint)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._chroma_client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    # ── ChromaDB Setup ─────────────────────────────────────────────────────────

    @cached_property
    def _embeddings(self) -> GoogleGenerativeAIEmbeddings:
        """Lazy-initialised Google embeddings model."""
        api_key = self._settings.gemini_api_key
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file: GEMINI_API_KEY=your-key"
            )
        return GoogleGenerativeAIEmbeddings(
            model=_EMBED_MODEL,
            google_api_key=api_key,
        )

    @cached_property
    def _llm(self) -> ChatGoogleGenerativeAI:
        """Lazy-initialised Gemini LLM."""
        api_key = self._settings.gemini_api_key
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file: GEMINI_API_KEY=your-key"
            )
        return ChatGoogleGenerativeAI(
            model=_LLM_MODEL,
            google_api_key=api_key,
            temperature=0.1,  # Low temp for consistent, structured output
            convert_system_message_to_human=True,  # Required for Gemini
        )

    def _get_or_create_collection(self) -> chromadb.Collection:
        """Return the ChromaDB collection, creating it if it doesn't exist."""
        if self._collection is not None:
            return self._collection

        persist_dir = self._settings.chroma_persist_dir
        collection_name = self._settings.chroma_collection_name

        logger.info(f"[TRIAGE] Connecting to ChromaDB at '{persist_dir}'")
        self._chroma_client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # Cosine similarity for text embeddings
        )
        return self._collection

    def seed_knowledge_base(self) -> None:
        """
        Idempotent: Seed ChromaDB with the medical knowledge base.

        Checks existing document count first — only inserts if collection is empty
        or has fewer docs than the current KB (handles KB updates on restart).
        """
        collection = self._get_or_create_collection()
        existing_count = collection.count()

        if existing_count >= len(MEDICAL_KB):
            logger.info(
                f"[TRIAGE] ChromaDB already has {existing_count} docs "
                f"(KB has {len(MEDICAL_KB)}). Skipping seed."
            )
            return

        logger.info(
            f"[TRIAGE] Seeding ChromaDB: {existing_count} existing → "
            f"adding {len(MEDICAL_KB) - existing_count} new docs"
        )

        # Build documents to embed
        texts = [entry["text"] for entry in MEDICAL_KB]
        metadatas = [entry["metadata"] for entry in MEDICAL_KB]
        ids = [f"kb_{i:04d}" for i in range(len(MEDICAL_KB))]

        # Generate embeddings via Google API
        logger.info("[TRIAGE] Generating embeddings for medical KB (this may take 10–30s on first run)...")
        embeddings = self._embeddings.embed_documents(texts)

        # Upsert into ChromaDB (safe to call on partially-populated collections)
        collection.upsert(
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"[TRIAGE] ✓ ChromaDB seeded with {len(MEDICAL_KB)} medical KB documents")

    # ── RAG Retrieval ──────────────────────────────────────────────────────────

    def _retrieve_context(self, query: str) -> tuple[str, list[str]]:
        """
        Embed the query and retrieve the top-K most semantically similar
        documents from ChromaDB.

        Returns:
            (formatted_context_string, list_of_condition_names)
        """
        collection = self._get_or_create_collection()

        if collection.count() == 0:
            logger.warning("[TRIAGE] ChromaDB collection is empty — running without KB context")
            return "No medical knowledge base context available.", []

        # Embed the patient's symptom text
        query_embedding = self._embeddings.embed_query(query)

        # Similarity search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(_TOP_K_DOCS, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        # Format retrieved context for the prompt
        context_parts = []
        condition_names = []
        for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances)):
            similarity = round(1 - dist, 3)  # Cosine distance → similarity
            condition = meta.get("condition", "Unknown")
            urgency = meta.get("urgency", "?")
            specialist = meta.get("specialist", "?")
            condition_names.append(condition)
            context_parts.append(
                f"[{i + 1}] {condition} (urgency={urgency}, specialist={specialist}, similarity={similarity})\n"
                f"    {doc[:300]}..."
            )

        context = "\n\n".join(context_parts)
        return context, condition_names

    # ── LangChain Chain ────────────────────────────────────────────────────────

    def _build_prompt(self, kb_context: str, format_instructions: str) -> ChatPromptTemplate:
        """Build the ChatPromptTemplate with system + human messages."""
        system_template = _SYSTEM_PROMPT.format(
            kb_context=kb_context,
            format_instructions=format_instructions,
        )
        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(_HUMAN_PROMPT),
        ])

    # ── Main Pipeline ──────────────────────────────────────────────────────────

    def run_triage_pipeline(
        self,
        raw_text: str,
        severity_hint: str = "unknown",
    ) -> TriageResult:
        """
        Full RAG triage pipeline.

        Args:
            raw_text:      The patient's free-text symptom description.
            severity_hint: Patient's self-reported severity (mild/moderate/severe).

        Returns:
            TriageResult with urgency_level, extracted_symptoms, etc.
        """
        logger.info(f"[TRIAGE] Running pipeline on text: '{raw_text[:80]}...'")

        # Step 1: Retrieve relevant medical KB context
        kb_context, relevant_conditions = self._retrieve_context(raw_text)
        logger.info(f"[TRIAGE] Retrieved {len(relevant_conditions)} KB docs: {relevant_conditions}")

        # Step 2: Set up output parser with format instructions
        parser = PydanticOutputParser(pydantic_object=TriageResult)
        format_instructions = parser.get_format_instructions()

        # Step 3: Build prompt
        prompt = self._build_prompt(kb_context, format_instructions)

        # Step 4: Build LCEL chain
        chain = prompt | self._llm

        # Step 5: Invoke chain
        logger.info("[TRIAGE] Invoking Gemini LLM...")
        response = chain.invoke({
            "raw_text": raw_text,
            "severity_hint": severity_hint,
        })

        # Step 6: Parse structured output
        raw_content = response.content.strip()
        logger.debug(f"[TRIAGE] Raw LLM response: {raw_content[:500]}")

        # Strip markdown code fences if present (Gemini sometimes wraps in ```json)
        if raw_content.startswith("```"):
            lines = raw_content.splitlines()
            raw_content = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_content

        try:
            result = parser.parse(raw_content)
            # Inject retrieved condition names into the result
            if not result.relevant_conditions:
                result.relevant_conditions = relevant_conditions
            logger.info(
                f"[TRIAGE] ✓ Pipeline complete: urgency={result.urgency_level}, "
                f"confidence={result.confidence}, specialist={result.specialist_recommendation}"
            )
            return result

        except Exception as parse_error:
            logger.error(
                f"[TRIAGE] ✗ Failed to parse LLM output: {parse_error}\n"
                f"Raw output: {raw_content[:1000]}"
            )
            # Safe fallback — return moderate so the report is not stuck
            return self._fallback_result(raw_text, relevant_conditions, str(parse_error))

    def _fallback_result(
        self,
        raw_text: str,
        relevant_conditions: list[str],
        error_message: str,
    ) -> TriageResult:
        """
        Return a safe fallback TriageResult when LLM output cannot be parsed.
        Logs the issue and flags it in the reasoning field.
        """
        logger.warning("[TRIAGE] Using fallback triage result due to parse error")
        return TriageResult(
            urgency_level="moderate",
            confidence=0.0,
            reasoning=(
                f"AI parsing failed — defaulting to moderate urgency for safety. "
                f"Error: {error_message[:100]}. Manual review required."
            ),
            specialist_recommendation="general_practitioner",
            extracted_symptoms=[],
            red_flags=["[AI parse error — manual review required]"],
            relevant_conditions=relevant_conditions,
        )

    # ── Report Serialisation ───────────────────────────────────────────────────

    @staticmethod
    def result_to_db_dict(result: TriageResult) -> dict:
        """
        Convert a TriageResult to a JSON-serialisable dict for JSONB storage.
        Uses model_dump (Pydantic v2) for nested serialisation.
        """
        return result.model_dump()


# ── Module-level singleton ─────────────────────────────────────────────────────

triage_service = TriageService()
