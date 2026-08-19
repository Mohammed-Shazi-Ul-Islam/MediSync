"""
app/services/specialist_router.py

Module 03 — Specialist Router: Rule + AI Hybrid Engine.

Architecture (two-layer hybrid):
  ┌─────────────────────────────────────────┐
  │  SpecialistRuleEngine                   │  ← deterministic, O(1)
  │  Keyword + red-flag scoring rulebook    │
  │  → (specialist, rule_score) per type    │
  └────────────────┬────────────────────────┘
                   │ rule_score ≥ RULE_CONFIDENCE_THRESHOLD?
                   │  YES → return immediately (fast path)
                   │  NO  → call semantic layer
                   ▼
  ┌─────────────────────────────────────────┐
  │  SpecialistSemanticRouter               │  ← ChromaDB "specialist_profiles"
  │  Embed symptom cluster → cosine search  │
  │  → (specialist, semantic_score)         │
  └────────────────┬────────────────────────┘
                   │
                   ▼
  ┌─────────────────────────────────────────┐
  │  Score fusion                           │
  │  fused = rule × 0.6 + semantic × 0.4   │
  │  → RoutingDecision                      │
  └─────────────────────────────────────────┘

Emergency Override (independent check):
  If TriageResult.urgency_level == "critical" AND any hard-red-flag keyword
  matches the symptom text → escalate_to_emergency = True, specialist forced
  to "emergency_medicine", method = "emergency_override".

Singleton usage:
  from app.services.specialist_router import hybrid_router
  decision: RoutingDecision = hybrid_router.route(triage_result)
"""

from __future__ import annotations

import logging
from functools import cached_property

import chromadb
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import get_settings
from app.schemas.routing import (
    SPECIALIST_DISPLAY_NAMES,
    RoutingDecision,
    SpecialistType,
)
from app.schemas.triage import TriageResult
from app.services.specialist_kb import SPECIALIST_KB

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_RULE_CONFIDENCE_THRESHOLD = 0.80   # Above this, skip semantic layer
_TOP_K_SPECIALIST_DOCS     = 3      # ChromaDB neighbours to retrieve
_RULE_WEIGHT               = 0.60   # Weight for rule score in fusion
_SEMANTIC_WEIGHT           = 0.40   # Weight for semantic score in fusion
_EMBED_MODEL               = "models/embedding-001"

# ── Hard Red-Flag Keywords → Force Emergency Medicine ─────────────────────────
# These patterns in red_flags or symptom text trigger an unconditional
# escalate_to_emergency = True regardless of rule/semantic scores.

_EMERGENCY_OVERRIDE_FLAGS: frozenset[str] = frozenset({
    "stroke", "stemi", "heart attack", "myocardial infarction", "cardiac arrest",
    "anaphylaxis", "anaphylactic", "airway obstruction", "cannot breathe", "stridor",
    "subarachnoid", "sah", "thunderclap", "worst headache",
    "aortic dissection", "dissection", "ruptured", "rupture",
    "tension pneumothorax", "collapsed lung",
    "septic shock", "sepsis",
    "loss of consciousness", "unconscious", "unresponsive",
    "face drooping", "arm weakness", "facial droop",
    "status epilepticus",
    "hypoglycaemic coma", "diabetic coma",
    "meningococcal", "petechial rash",
    "epiglottitis", "throat swelling",
})


# ── Rule Book ─────────────────────────────────────────────────────────────────

class _SpecialistRule:
    """
    Configuration object for one specialist type in the rule engine.

    Attributes:
        required_keywords    Symptom-text keywords that make this specialist a candidate.
                             ANY single match scores base_keyword_score.
        red_flag_boosters    Stronger keywords from TriageResult.red_flags that boost score.
        condition_keywords   Condition names from relevant_conditions that signal this specialist.
        urgency_affinity     Urgency levels where this specialist is appropriate.
                             Mismatched urgency applies a 0.10 penalty.
        base_keyword_score   Starting score when any required_keyword matches.
        red_flag_boost       Per-matched-booster additive increment.
        condition_boost      Per-matched-condition additive increment.
    """

    def __init__(
        self,
        required_keywords: list[str],
        red_flag_boosters: list[str],
        condition_keywords: list[str],
        urgency_affinity: list[str],
        base_keyword_score: float = 0.50,
        red_flag_boost: float = 0.15,
        condition_boost: float = 0.10,
    ) -> None:
        self.required_keywords  = [kw.lower() for kw in required_keywords]
        self.red_flag_boosters  = [kw.lower() for kw in red_flag_boosters]
        self.condition_keywords = [kw.lower() for kw in condition_keywords]
        self.urgency_affinity   = urgency_affinity
        self.base_keyword_score = base_keyword_score
        self.red_flag_boost     = red_flag_boost
        self.condition_boost    = condition_boost


RULE_BOOK: dict[str, _SpecialistRule] = {

    SpecialistType.EMERGENCY_MEDICINE.value: _SpecialistRule(
        required_keywords=[
            "critical", "unconscious", "unresponsive", "cardiac arrest",
            "airway", "cannot breathe", "collapse", "shock", "emergency",
        ],
        red_flag_boosters=[
            "cardiac arrest", "airway obstruction", "anaphylaxis", "ruptured",
            "dissection", "thunderclap", "worst headache", "face drooping",
            "petechial", "septic shock", "status epilepticus",
        ],
        condition_keywords=[
            "STEMI", "Aortic Dissection", "Anaphylaxis", "Sepsis",
            "Subarachnoid Haemorrhage", "Ruptured AAA", "Tension Pneumothorax",
            "Bacterial Meningitis", "Ischaemic Stroke",
        ],
        urgency_affinity=["critical"],
        base_keyword_score=0.60,
        red_flag_boost=0.20,
        condition_boost=0.15,
    ),

    SpecialistType.CARDIOLOGIST.value: _SpecialistRule(
        required_keywords=[
            "chest", "cardiac", "heart", "palpitation", "palpitations",
            "heartbeat", "arrhythmia", "atrial", "fibrillation", "angina",
            "coronary", "myocardial", "heart failure", "oedema",
        ],
        red_flag_boosters=[
            "crushing chest pain", "jaw pain", "left arm pain", "diaphoresis",
            "sweating", "irregular heartbeat", "heart failure", "orthopnoea",
            "decompensated",
        ],
        condition_keywords=[
            "Unstable Angina", "NSTEMI", "Cardiac Arrhythmia", "AFib",
            "Acute Heart Failure", "STEMI",
        ],
        urgency_affinity=["critical", "moderate"],
        base_keyword_score=0.55,
        red_flag_boost=0.15,
        condition_boost=0.10,
    ),

    SpecialistType.NEUROLOGIST.value: _SpecialistRule(
        required_keywords=[
            "headache", "dizziness", "vertigo", "seizure", "convulsion",
            "weakness", "numbness", "tingling", "vision", "speech",
            "memory", "tremor", "migraine", "epilepsy", "neurological",
        ],
        red_flag_boosters=[
            "thunderclap headache", "worst headache", "face droop",
            "arm weakness", "speech slurred", "FAST", "mini-stroke",
            "loss of consciousness", "jerking",
        ],
        condition_keywords=[
            "TIA", "Migraine", "Seizure", "Ischaemic Stroke",
        ],
        urgency_affinity=["critical", "moderate", "routine"],
        base_keyword_score=0.50,
        red_flag_boost=0.15,
        condition_boost=0.10,
    ),

    SpecialistType.NEUROSURGEON.value: _SpecialistRule(
        required_keywords=[
            "saddle anaesthesia", "saddle numbness", "urinary retention",
            "bowel incontinence", "cauda equina", "spinal cord compression",
            "intracranial", "aneurysm", "brain bleed", "subdural",
        ],
        red_flag_boosters=[
            "cauda equina", "saddle numbness", "loss of bladder control",
            "spinal cord", "intracranial haemorrhage", "aneurysm rupture",
        ],
        condition_keywords=[
            "Cauda Equina Syndrome", "Subarachnoid Haemorrhage",
        ],
        urgency_affinity=["critical"],
        base_keyword_score=0.65,
        red_flag_boost=0.20,
        condition_boost=0.15,
    ),

    SpecialistType.PULMONOLOGIST.value: _SpecialistRule(
        required_keywords=[
            "breathing", "breath", "lung", "copd", "emphysema", "asthma",
            "wheezing", "wheeze", "respiratory", "sputum", "haemoptysis",
            "coughing blood", "breathlessness", "dyspnoea",
        ],
        red_flag_boosters=[
            "haemoptysis", "coughing blood", "COPD exacerbation",
            "progressive breathlessness", "oxygen", "hypoxia",
        ],
        condition_keywords=[
            "COPD Exacerbation", "Pneumonia", "Acute Severe Asthma",
        ],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.50,
        red_flag_boost=0.12,
        condition_boost=0.10,
    ),

    SpecialistType.GASTROENTEROLOGIST.value: _SpecialistRule(
        required_keywords=[
            "abdominal", "epigastric", "bowel", "stomach", "nausea",
            "vomiting", "diarrhoea", "diarrhea", "constipation",
            "pancreatitis", "liver", "jaundice", "rectal", "blood in stool",
        ],
        red_flag_boosters=[
            "epigastric pain radiating to back", "blood in stool", "black tarry stool",
            "vomiting blood", "haematemesis", "jaundice", "guarding", "rigidity",
        ],
        condition_keywords=[
            "Acute Pancreatitis", "Gastroenteritis",
        ],
        urgency_affinity=["critical", "moderate"],
        base_keyword_score=0.48,
        red_flag_boost=0.14,
        condition_boost=0.10,
    ),

    SpecialistType.GENERAL_SURGEON.value: _SpecialistRule(
        required_keywords=[
            "appendix", "appendicitis", "right iliac fossa", "cholecystitis",
            "gallbladder", "bowel obstruction", "hernia", "peritonitis",
            "surgical abdomen", "gallstone",
        ],
        red_flag_boosters=[
            "rebound tenderness", "guarding", "peritonism", "vomiting bile",
            "absolute constipation", "no flatus", "right iliac fossa",
            "murphy sign",
        ],
        condition_keywords=[
            "Appendicitis", "Acute Cholecystitis", "Bowel Obstruction",
        ],
        urgency_affinity=["critical", "moderate"],
        base_keyword_score=0.55,
        red_flag_boost=0.18,
        condition_boost=0.12,
    ),

    SpecialistType.ENDOCRINOLOGIST.value: _SpecialistRule(
        required_keywords=[
            "diabetes", "insulin", "blood sugar", "glucose", "thyroid",
            "endocrine", "hormonal", "adrenal", "dka", "ketoacidosis",
            "polydipsia", "polyuria", "fruity breath",
        ],
        red_flag_boosters=[
            "diabetic ketoacidosis", "DKA", "fruity breath",
            "high blood sugar", "low blood sugar", "thyroid storm",
        ],
        condition_keywords=[
            "DKA", "Hypoglycaemia",
        ],
        urgency_affinity=["critical", "moderate", "routine"],
        base_keyword_score=0.52,
        red_flag_boost=0.15,
        condition_boost=0.10,
    ),

    SpecialistType.UROLOGIST.value: _SpecialistRule(
        required_keywords=[
            "urinary", "urine", "kidney", "renal", "bladder", "uti",
            "loin", "flank", "groin", "haematuria", "blood in urine",
            "stone", "kidney stone", "prostate",
        ],
        red_flag_boosters=[
            "blood in urine", "haematuria", "loin-to-groin pain",
            "kidney stone", "renal colic", "urinary retention",
        ],
        condition_keywords=[
            "Renal Colic", "UTI / Pyelonephritis",
        ],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.52,
        red_flag_boost=0.14,
        condition_boost=0.10,
    ),

    SpecialistType.VASCULAR_SURGEON.value: _SpecialistRule(
        required_keywords=[
            "dvt", "deep vein", "leg swelling", "calf pain", "varicose",
            "aortic", "aneurysm", "arterial", "claudication", "limb ischaemia",
            "peripheral vascular",
        ],
        red_flag_boosters=[
            "pulsatile mass", "cold pulseless limb", "ruptured aorta",
            "leg swelling and pain", "DVT", "acute limb ischaemia",
        ],
        condition_keywords=[
            "DVT", "Ruptured AAA",
        ],
        urgency_affinity=["critical", "moderate"],
        base_keyword_score=0.50,
        red_flag_boost=0.16,
        condition_boost=0.10,
    ),

    SpecialistType.PSYCHIATRIST.value: _SpecialistRule(
        required_keywords=[
            "anxiety", "panic", "depression", "psychiatric", "mental health",
            "suicidal", "self-harm", "psychosis", "hallucination", "paranoia",
            "mood", "fear of dying",
        ],
        red_flag_boosters=[
            "suicidal ideation", "self-harm", "acute psychosis",
            "panic attack", "fear of dying",
        ],
        condition_keywords=[
            "Panic Attack",
        ],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.50,
        red_flag_boost=0.15,
        condition_boost=0.10,
    ),

    SpecialistType.GENERAL_PRACTITIONER.value: _SpecialistRule(
        required_keywords=[
            "cold", "flu", "cough", "sore throat", "runny nose", "fever",
            "headache", "back pain", "fatigue", "mild", "routine", "viral",
            "gastroenteritis", "hay fever", "allergic rhinitis",
        ],
        red_flag_boosters=[],  # GP has no red-flag boosters — no high-acuity triggers
        condition_keywords=[
            "Viral URTI", "Influenza", "Gastroenteritis", "Tension Headache",
            "Allergic Rhinitis", "Non-specific Back Pain", "UTI / Pyelonephritis",
            "Pneumonia",
        ],
        urgency_affinity=["routine"],
        base_keyword_score=0.45,
        red_flag_boost=0.0,
        condition_boost=0.08,
    ),

    SpecialistType.ORTHOPEDIST.value: _SpecialistRule(
        required_keywords=[
            "fracture", "bone", "joint", "knee", "hip", "shoulder",
            "ligament", "tendon", "sprain", "musculoskeletal", "orthopaedic",
            "arthritis", "sports injury",
        ],
        red_flag_boosters=[
            "fracture", "dislocation", "cannot weight bear",
            "deformity after trauma",
        ],
        condition_keywords=[],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.50,
        red_flag_boost=0.14,
        condition_boost=0.08,
    ),

    SpecialistType.RHEUMATOLOGIST.value: _SpecialistRule(
        required_keywords=[
            "joint pain", "arthritis", "rheumatoid", "gout", "lupus",
            "autoimmune", "morning stiffness", "swollen joints", "synovitis",
            "inflammation",
        ],
        red_flag_boosters=[
            "hot swollen joint", "morning stiffness > 1 hour",
            "butterfly rash", "gout", "vasculitis",
        ],
        condition_keywords=[],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.48,
        red_flag_boost=0.12,
        condition_boost=0.08,
    ),

    SpecialistType.DERMATOLOGIST.value: _SpecialistRule(
        required_keywords=[
            "rash", "skin", "itch", "pruritus", "eczema", "psoriasis",
            "hives", "urticaria", "mole", "blister", "cellulitis",
            "shingles", "dermatitis",
        ],
        red_flag_boosters=[
            "spreading rash", "non-blanching rash", "blistering skin",
            "rapidly spreading cellulitis",
        ],
        condition_keywords=[],
        urgency_affinity=["moderate", "routine"],
        base_keyword_score=0.48,
        red_flag_boost=0.12,
        condition_boost=0.08,
    ),
}


# ── Rule Engine ────────────────────────────────────────────────────────────────

class SpecialistRuleEngine:
    """
    Deterministic rule-based specialist scorer.

    Iterates RULE_BOOK against a TriageResult and returns a scored list
    of (specialist_code, confidence) tuples, sorted descending.

    Scoring formula (per specialist):
      score = base_keyword_score                          (if any keyword matches)
            + red_flag_boost × number_of_booster_matches (capped by 3 matches)
            + condition_boost × number_of_condition_matches
            - 0.10                                        (if urgency_affinity mismatch)
      Final score is clamped to [0.0, 1.0].
    """

    def score(self, triage_result: TriageResult) -> list[tuple[str, float]]:
        """
        Score all specialist types against a TriageResult.

        Args:
            triage_result: The full TriageResult from Module 02.

        Returns:
            Sorted list of (specialist_code, score) pairs, highest first.
            Only includes specialists with score > 0.
        """
        # Build a unified text blob for keyword matching
        symptom_names   = [s.name.lower() for s in triage_result.extracted_symptoms]
        red_flags_lower = [f.lower() for f in triage_result.red_flags]
        conditions_lower = [c.lower() for c in triage_result.relevant_conditions]
        full_text_lower  = triage_result.reasoning.lower() if triage_result.reasoning else ""

        # Join everything into one searchable string
        all_symptom_text = " ".join(symptom_names + red_flags_lower + [full_text_lower])

        urgency = triage_result.urgency_level  # "critical" | "moderate" | "routine"

        scores: list[tuple[str, float]] = []

        for specialist_code, rule in RULE_BOOK.items():
            # ── Step 1: Check if any required keyword is present ──────────────
            keyword_hit = any(kw in all_symptom_text for kw in rule.required_keywords)
            if not keyword_hit:
                continue  # This specialist is not a candidate

            score = rule.base_keyword_score

            # ── Step 2: Red flag boosters ─────────────────────────────────────
            booster_matches = sum(
                1 for booster in rule.red_flag_boosters
                if booster in all_symptom_text
            )
            # Cap red flag contribution at 3 boosters to avoid runaway scores
            score += rule.red_flag_boost * min(booster_matches, 3)

            # ── Step 3: Condition name matches ────────────────────────────────
            condition_matches = sum(
                1 for ck in rule.condition_keywords
                if ck.lower() in conditions_lower
            )
            score += rule.condition_boost * min(condition_matches, 2)

            # ── Step 4: Urgency affinity penalty ─────────────────────────────
            if urgency not in rule.urgency_affinity:
                score -= 0.10

            # ── Clamp ─────────────────────────────────────────────────────────
            score = round(max(0.0, min(1.0, score)), 3)
            scores.append((specialist_code, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        logger.debug(f"[RULE ENGINE] Scores: {scores[:5]}")
        return scores


# ── Semantic Router ────────────────────────────────────────────────────────────

class SpecialistSemanticRouter:
    """
    ChromaDB-backed semantic specialist router.

    Uses the 'specialist_profiles' collection (separate from 'medical_kb').
    Embeds a combined symptom cluster string and finds the closest specialist
    profile documents via cosine similarity.

    The semantic score for each specialist is derived from the best-matching
    document cosine similarity for that specialist type.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._chroma_client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    @cached_property
    def _embeddings(self) -> GoogleGenerativeAIEmbeddings:
        """Lazy-initialised Google embeddings model (shared embed model with triage_service)."""
        api_key = self._settings.gemini_api_key
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — semantic routing requires the embeddings model."
            )
        return GoogleGenerativeAIEmbeddings(
            model=_EMBED_MODEL,
            google_api_key=api_key,
        )

    def _get_or_create_collection(self) -> chromadb.Collection:
        """Return the specialist_profiles ChromaDB collection, creating if needed."""
        if self._collection is not None:
            return self._collection

        persist_dir      = self._settings.chroma_persist_dir
        collection_name  = self._settings.chroma_specialist_collection_name

        logger.info(f"[ROUTER] Connecting to ChromaDB specialist collection at '{persist_dir}'")
        self._chroma_client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def seed_specialist_profiles(self) -> None:
        """
        Idempotent: Seed ChromaDB with specialist profile documents.

        Analogous to triage_service.seed_knowledge_base() — checks count first.
        """
        collection = self._get_or_create_collection()
        existing_count = collection.count()

        if existing_count >= len(SPECIALIST_KB):
            logger.info(
                f"[ROUTER] Specialist ChromaDB already has {existing_count} docs "
                f"(KB has {len(SPECIALIST_KB)}). Skipping seed."
            )
            return

        logger.info(
            f"[ROUTER] Seeding specialist ChromaDB: {existing_count} existing → "
            f"adding {len(SPECIALIST_KB) - existing_count} new docs"
        )

        texts     = [entry["text"] for entry in SPECIALIST_KB]
        metadatas = [entry["metadata"] for entry in SPECIALIST_KB]
        ids       = [f"sp_{i:04d}" for i in range(len(SPECIALIST_KB))]

        logger.info("[ROUTER] Generating embeddings for specialist KB…")
        embeddings = self._embeddings.embed_documents(texts)

        collection.upsert(
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"[ROUTER] ✓ Specialist ChromaDB seeded with {len(SPECIALIST_KB)} docs")

    def route(self, symptom_cluster: str) -> list[tuple[str, float]]:
        """
        Embed the symptom cluster and return top specialist matches with scores.

        Args:
            symptom_cluster: Combined text of symptoms + red flags + reasoning.

        Returns:
            List of (specialist_code, semantic_score) sorted descending.
            semantic_score = cosine similarity (1 − cosine distance).
        """
        collection = self._get_or_create_collection()

        if collection.count() == 0:
            logger.warning("[ROUTER] Specialist ChromaDB is empty — semantic routing skipped")
            return []

        query_embedding = self._embeddings.embed_query(symptom_cluster)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(_TOP_K_SPECIALIST_DOCS, collection.count()),
            include=["metadatas", "distances"],
        )

        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        # Aggregate by specialist — take the best (lowest distance) per specialist
        best_per_specialist: dict[str, float] = {}
        for meta, dist in zip(metadatas, distances):
            specialist = meta.get("specialist", "general_practitioner")
            similarity = round(1.0 - dist, 3)
            if specialist not in best_per_specialist or similarity > best_per_specialist[specialist]:
                best_per_specialist[specialist] = similarity

        ranked = sorted(best_per_specialist.items(), key=lambda x: x[1], reverse=True)
        logger.debug(f"[ROUTER] Semantic scores: {ranked}")
        return ranked


# ── Emergency Override Check ───────────────────────────────────────────────────

def _check_emergency_override(triage_result: TriageResult) -> bool:
    """
    Returns True if the triage result contains a hard red flag that unconditionally
    requires emergency medicine, regardless of routing scores.

    Conditions:
      1. urgency_level must be "critical"
      2. At least one _EMERGENCY_OVERRIDE_FLAGS keyword appears in red_flags,
         symptom names, or the reasoning field.
    """
    if triage_result.urgency_level != "critical":
        return False

    # Build a combined text to search
    red_flags_text = " ".join(f.lower() for f in triage_result.red_flags)
    symptom_text   = " ".join(s.name.lower() for s in triage_result.extracted_symptoms)
    reasoning_text = (triage_result.reasoning or "").lower()
    conditions_text = " ".join(c.lower() for c in triage_result.relevant_conditions)

    combined = f"{red_flags_text} {symptom_text} {reasoning_text} {conditions_text}"

    for flag in _EMERGENCY_OVERRIDE_FLAGS:
        if flag in combined:
            logger.info(f"[ROUTER] Emergency override triggered by flag: '{flag}'")
            return True

    return False


# ── Hybrid Orchestrator ────────────────────────────────────────────────────────

class HybridSpecialistRouter:
    """
    Orchestrates the full two-layer routing pipeline.

    Usage:
        from app.services.specialist_router import hybrid_router
        decision = hybrid_router.route(triage_result)
    """

    def __init__(self) -> None:
        self._rule_engine     = SpecialistRuleEngine()
        self._semantic_router = SpecialistSemanticRouter()

    def seed_specialist_profiles(self) -> None:
        """Delegate to semantic router's seeding method."""
        self._semantic_router.seed_specialist_profiles()

    # ── Main Entry Point ───────────────────────────────────────────────────────

    def route(self, triage_result: TriageResult) -> RoutingDecision:
        """
        Run the full hybrid routing pipeline.

        Algorithm:
          1. Check for emergency override → immediately return emergency_medicine.
          2. Run rule engine → get (specialist, score) ranked list.
          3. If top rule score ≥ RULE_CONFIDENCE_THRESHOLD → return rule_only decision.
          4. Run semantic layer → get (specialist, score) ranked list.
          5. Fuse scores and return best hybrid decision.

        Args:
            triage_result: The TriageResult from Module 02.

        Returns:
            RoutingDecision with all fields populated.
        """
        logger.info(
            f"[ROUTER] Routing triage result — urgency={triage_result.urgency_level}, "
            f"symptoms={[s.name for s in triage_result.extracted_symptoms[:3]]}"
        )

        # ── Step 1: Emergency Override ─────────────────────────────────────────
        if _check_emergency_override(triage_result):
            return self._emergency_override_decision(triage_result)

        # ── Step 2: Rule Engine ────────────────────────────────────────────────
        rule_scores = self._rule_engine.score(triage_result)

        top_rule_specialist, top_rule_score = (
            rule_scores[0] if rule_scores else (SpecialistType.GENERAL_PRACTITIONER.value, 0.0)
        )

        logger.info(
            f"[ROUTER] Rule engine top result: specialist={top_rule_specialist}, "
            f"score={top_rule_score}"
        )

        # ── Step 3: Rule-only fast path ────────────────────────────────────────
        if top_rule_score >= _RULE_CONFIDENCE_THRESHOLD:
            alternatives = [s for s, _ in rule_scores[1:3]]
            return self._build_decision(
                specialist      = top_rule_specialist,
                confidence      = top_rule_score,
                method          = "rule_only",
                rule_score      = top_rule_score,
                semantic_score  = 0.0,
                alternatives    = alternatives,
                reasoning       = self._build_reasoning(
                    triage_result, top_rule_specialist, "rule_only", top_rule_score, None
                ),
                escalate        = False,
            )

        # ── Step 4: Semantic Layer ─────────────────────────────────────────────
        # Build symptom cluster string for embedding
        symptom_cluster = self._build_symptom_cluster(triage_result)

        try:
            semantic_scores = self._semantic_router.route(symptom_cluster)
        except Exception as e:
            logger.warning(f"[ROUTER] Semantic routing failed, falling back to rule: {e}")
            semantic_scores = []

        if not semantic_scores:
            # No semantic results — fall back to best rule result
            alternatives = [s for s, _ in rule_scores[1:3]]
            return self._build_decision(
                specialist      = top_rule_specialist,
                confidence      = top_rule_score,
                method          = "rule_only",
                rule_score      = top_rule_score,
                semantic_score  = 0.0,
                alternatives    = alternatives,
                reasoning       = self._build_reasoning(
                    triage_result, top_rule_specialist, "rule_only", top_rule_score, None
                ),
                escalate        = False,
            )

        top_semantic_specialist, top_semantic_score = semantic_scores[0]

        # ── Step 5: Score Fusion ───────────────────────────────────────────────
        # Build a unified specialist set from both layers
        all_specialists: set[str] = {s for s, _ in rule_scores} | {s for s, _ in semantic_scores}

        # For each specialist, compute fused score
        rule_score_map     = dict(rule_scores)
        semantic_score_map = dict(semantic_scores)

        fused_scores: list[tuple[str, float]] = []
        for sp in all_specialists:
            rs = rule_score_map.get(sp, 0.0)
            ss = semantic_score_map.get(sp, 0.0)
            fused = round(_RULE_WEIGHT * rs + _SEMANTIC_WEIGHT * ss, 3)
            fused_scores.append((sp, fused))

        fused_scores.sort(key=lambda x: x[1], reverse=True)

        best_specialist, best_fused_score = fused_scores[0]
        alternatives = [s for s, _ in fused_scores[1:3]]

        method = "hybrid" if rule_scores and semantic_scores else (
            "rule_only" if rule_scores else "semantic_only"
        )

        reasoning = self._build_reasoning(
            triage_result,
            best_specialist,
            method,
            top_rule_score,
            top_semantic_score,
        )

        logger.info(
            f"[ROUTER] ✓ Hybrid routing complete: specialist={best_specialist}, "
            f"fused_score={best_fused_score}, method={method}"
        )

        return self._build_decision(
            specialist      = best_specialist,
            confidence      = best_fused_score,
            method          = method,
            rule_score      = rule_score_map.get(best_specialist, 0.0),
            semantic_score  = semantic_score_map.get(best_specialist, 0.0),
            alternatives    = alternatives,
            reasoning       = reasoning,
            escalate        = False,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_symptom_cluster(triage_result: TriageResult) -> str:
        """
        Construct a rich text string from the TriageResult for semantic embedding.

        Combines symptom names, red flags, relevant conditions, and reasoning
        into a single dense query string.
        """
        parts = []

        if triage_result.extracted_symptoms:
            symptoms = ", ".join(s.name for s in triage_result.extracted_symptoms)
            parts.append(f"Symptoms: {symptoms}")

        if triage_result.red_flags:
            parts.append(f"Red flags: {', '.join(triage_result.red_flags)}")

        if triage_result.relevant_conditions:
            parts.append(f"Relevant conditions: {', '.join(triage_result.relevant_conditions)}")

        if triage_result.reasoning:
            parts.append(f"Clinical reasoning: {triage_result.reasoning}")

        return ". ".join(parts)

    @staticmethod
    def _build_reasoning(
        triage_result: TriageResult,
        specialist: str,
        method: str,
        rule_score: float,
        semantic_score: float | None,
    ) -> str:
        """Generate a human-readable explanation for the routing decision."""
        display = SPECIALIST_DISPLAY_NAMES.get(specialist, specialist)
        urgency = triage_result.urgency_level
        symptoms = ", ".join(s.name for s in triage_result.extracted_symptoms[:3])

        if method == "rule_only":
            return (
                f"Routed to {display} based on deterministic symptom-keyword matching "
                f"(confidence {rule_score:.0%}). Patient presents with {symptoms or 'reported symptoms'} "
                f"— a {urgency}-urgency profile consistent with {display} scope."
            )
        elif method == "semantic_only":
            return (
                f"Routed to {display} via semantic similarity matching across specialist profiles "
                f"(semantic score {semantic_score:.2f}). Rule engine found no strong keyword match; "
                f"AI embedding analysis identified {display} as the best specialist fit for "
                f"the reported {urgency}-urgency presentation."
            )
        else:  # hybrid
            return (
                f"Routed to {display} via hybrid rule + semantic analysis "
                f"(rule score {rule_score:.2f}, semantic score {semantic_score:.2f}). "
                f"Patient's {urgency}-urgency presentation with symptoms [{symptoms}] "
                f"best matches {display} across both scoring layers."
            )

    def _emergency_override_decision(self, triage_result: TriageResult) -> RoutingDecision:
        """Build a RoutingDecision for a hard emergency override."""
        specialist = SpecialistType.EMERGENCY_MEDICINE.value
        display    = SPECIALIST_DISPLAY_NAMES[specialist]
        symptoms   = ", ".join(s.name for s in triage_result.extracted_symptoms[:3])
        flags      = ", ".join(triage_result.red_flags[:3])

        reasoning = (
            f"EMERGENCY OVERRIDE: Critical red flags detected [{flags}] in a {triage_result.urgency_level}-"
            f"urgency report. Patient must be seen immediately by {display}. "
            f"Normal routing bypassed — call 911 or go to the nearest emergency department now."
        )
        return self._build_decision(
            specialist     = specialist,
            confidence     = 1.0,
            method         = "emergency_override",
            rule_score     = 1.0,
            semantic_score = 0.0,
            alternatives   = [],
            reasoning      = reasoning,
            escalate       = True,
        )

    @staticmethod
    def _build_decision(
        specialist: str,
        confidence: float,
        method: str,
        rule_score: float,
        semantic_score: float,
        alternatives: list[str],
        reasoning: str,
        escalate: bool,
    ) -> RoutingDecision:
        """Construct and return a RoutingDecision object."""
        return RoutingDecision(
            specialist              = specialist,
            specialist_display_name = SPECIALIST_DISPLAY_NAMES.get(specialist, specialist),
            confidence              = round(confidence, 3),
            routing_method          = method,
            rule_score              = round(rule_score, 3),
            semantic_score          = round(semantic_score, 3),
            reasoning               = reasoning,
            alternative_specialists = alternatives,
            escalate_to_emergency   = escalate,
        )


# ── Module-level singleton ─────────────────────────────────────────────────────

hybrid_router = HybridSpecialistRouter()
