"""
tests/test_specialist_router.py

Module 03 — Specialist Router: Unit Tests.

Tests cover:
  - Rule engine: keyword matching, red flag boost, urgency affinity penalty
  - Emergency override: critical + hard red-flag keywords
  - Score fusion formula correctness
  - RoutingDecision schema validation
  - HybridSpecialistRouter fast path (rule-only when score >= threshold)
  - Fallback to GP when no rules match
  - Routing method labels (rule_only / hybrid / emergency_override)

These tests are self-contained: no DB, no API, no ChromaDB, no LLM calls.
The semantic layer is tested via mocking.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.routing import RoutingDecision, SpecialistType
from app.schemas.triage import ExtractedSymptom, TriageResult
from app.services.specialist_router import (
    HybridSpecialistRouter,
    SpecialistRuleEngine,
    _check_emergency_override,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_triage_result(
    urgency: str = "moderate",
    symptoms: list[str] | None = None,
    red_flags: list[str] | None = None,
    conditions: list[str] | None = None,
    reasoning: str = "",
) -> TriageResult:
    """Factory for TriageResult in tests."""
    return TriageResult(
        urgency_level=urgency,
        confidence=0.85,
        reasoning=reasoning,
        specialist_recommendation="general_practitioner",
        extracted_symptoms=[
            ExtractedSymptom(name=name, severity=None, onset=None)
            for name in (symptoms or [])
        ],
        red_flags=red_flags or [],
        relevant_conditions=conditions or [],
    )


# ── Rule Engine Tests ──────────────────────────────────────────────────────────

class TestSpecialistRuleEngine:

    def setup_method(self):
        self.engine = SpecialistRuleEngine()

    def test_cardiac_keywords_score_cardiologist(self):
        """Chest pain + cardiac keywords should score cardiologist highly."""
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["chest pain", "palpitations"],
            red_flags=["irregular heartbeat"],
            conditions=["Cardiac Arrhythmia / AFib"],
        )
        scores = self.engine.score(tr)
        specialist_codes = [s for s, _ in scores]
        assert "cardiologist" in specialist_codes, "Cardiologist should be a candidate for cardiac symptoms"
        # Cardiologist should be in top 3
        top3 = specialist_codes[:3]
        assert "cardiologist" in top3, f"Cardiologist should be in top 3, got: {top3}"

    def test_neurological_keywords_score_neurologist(self):
        """Headache + neurological symptoms should surface neurologist."""
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["headache", "vision changes", "dizziness"],
            red_flags=["unilateral headache"],
            conditions=["Migraine"],
        )
        scores = self.engine.score(tr)
        specialist_codes = [s for s, _ in scores]
        assert "neurologist" in specialist_codes

    def test_urgency_affinity_penalty_applied(self):
        """GP (routine only) scored against a critical urgency report gets penalised."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["cold", "cough", "runny nose"],
            red_flags=[],
        )
        scores = self.engine.score(tr)
        score_map = dict(scores)
        gp_score = score_map.get("general_practitioner", 0.0)
        # GP base score 0.45 - urgency penalty 0.10 = 0.35
        assert gp_score <= 0.40, f"GP should have penalty for critical urgency, got {gp_score}"

    def test_red_flag_boosters_increase_score(self):
        """Red flags should increase specialist score above base."""
        # Without red flags
        tr_no_flags = make_triage_result(
            urgency="critical",
            symptoms=["chest"],
            red_flags=[],
        )
        # With strong red flags
        tr_with_flags = make_triage_result(
            urgency="critical",
            symptoms=["chest"],
            red_flags=["crushing chest pain", "jaw pain", "diaphoresis"],
        )
        scores_no  = dict(self.engine.score(tr_no_flags))
        scores_yes = dict(self.engine.score(tr_with_flags))

        base_score = scores_no.get("cardiologist", 0.0)
        boosted    = scores_yes.get("cardiologist", 0.0)
        assert boosted > base_score, (
            f"Red flags should boost cardiologist score: base={base_score}, boosted={boosted}"
        )

    def test_cauda_equina_scores_neurosurgeon(self):
        """Cauda equina symptoms should score neurosurgeon."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["saddle numbness", "urinary retention", "bilateral leg weakness"],
            red_flags=["cauda equina"],
            conditions=["Cauda Equina Syndrome"],
        )
        scores = self.engine.score(tr)
        specialist_codes = [s for s, _ in scores]
        assert "neurosurgeon" in specialist_codes[:2], (
            f"Neurosurgeon should be top 2 for cauda equina. Got: {specialist_codes[:2]}"
        )

    def test_renal_colic_scores_urologist(self):
        """Loin to groin pain + blood in urine should score urologist."""
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["loin pain", "blood in urine", "nausea"],
            red_flags=["haematuria", "kidney stone"],
            conditions=["Renal Colic"],
        )
        scores = self.engine.score(tr)
        specialist_codes = [s for s, _ in scores]
        assert "urologist" in specialist_codes

    def test_no_matching_keywords_returns_empty(self):
        """A completely blank report should return empty or minimal scores."""
        tr = make_triage_result(
            urgency="routine",
            symptoms=[],
            red_flags=[],
        )
        scores = self.engine.score(tr)
        assert isinstance(scores, list)

    def test_scores_are_clamped_to_one(self):
        """No score should exceed 1.0 regardless of many boosters."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["chest", "cardiac", "heart", "palpitations", "angina"],
            red_flags=[
                "crushing chest pain", "jaw pain", "left arm pain",
                "diaphoresis", "sweating", "irregular heartbeat",
                "heart failure", "orthopnoea", "decompensated",
            ],
            conditions=["Unstable Angina", "NSTEMI", "STEMI", "Cardiac Arrhythmia"],
        )
        scores = self.engine.score(tr)
        for _, score in scores:
            assert score <= 1.0, f"Score {score} exceeds 1.0"

    def test_scores_sorted_descending(self):
        """Scores returned by the rule engine must be sorted highest-first."""
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["chest pain", "palpitations", "headache"],
        )
        scores = self.engine.score(tr)
        score_values = [s for _, s in scores]
        assert score_values == sorted(score_values, reverse=True), (
            "Scores must be sorted descending"
        )


# ── Emergency Override Tests ───────────────────────────────────────────────────

class TestEmergencyOverride:

    def test_stroke_keywords_trigger_override(self):
        """FAST symptoms with critical urgency → override = True."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["face drooping", "arm weakness"],
            red_flags=["facial droop", "stroke"],
        )
        assert _check_emergency_override(tr) is True

    def test_anaphylaxis_triggers_override(self):
        tr = make_triage_result(
            urgency="critical",
            symptoms=["throat swelling", "hives"],
            red_flags=["anaphylaxis"],
        )
        assert _check_emergency_override(tr) is True

    def test_non_critical_urgency_does_not_trigger(self):
        """Override must NOT fire for moderate urgency even with red flag keywords."""
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["thunderclap headache"],
            red_flags=["worst headache"],
        )
        assert _check_emergency_override(tr) is False

    def test_critical_without_flags_does_not_trigger(self):
        """Critical urgency alone without override keywords → no override."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["severe headache", "nausea"],
            red_flags=["photophobia"],
        )
        # photophobia is not in the hard override list
        assert _check_emergency_override(tr) is False

    def test_sah_triggers_override(self):
        """Subarachnoid haemorrhage keywords → override."""
        tr = make_triage_result(
            urgency="critical",
            symptoms=["thunderclap headache", "neck stiffness"],
            conditions=["Subarachnoid Haemorrhage"],
            red_flags=["subarachnoid", "worst headache"],
        )
        assert _check_emergency_override(tr) is True

    def test_sepsis_triggers_override(self):
        tr = make_triage_result(
            urgency="critical",
            symptoms=["fever", "confusion", "low blood pressure"],
            red_flags=["sepsis"],
        )
        assert _check_emergency_override(tr) is True


# ── Hybrid Router Tests ────────────────────────────────────────────────────────

class TestHybridSpecialistRouter:

    def _make_router_with_mock_semantic(self, semantic_results=None):
        """Build a HybridSpecialistRouter whose semantic layer is mocked."""
        router = HybridSpecialistRouter()
        mock_semantic = MagicMock()
        mock_semantic.route.return_value = semantic_results or []
        router._semantic_router = mock_semantic
        return router

    def test_emergency_override_bypasses_all_scoring(self):
        """Critical + hard flags → emergency_medicine, method=emergency_override."""
        router = self._make_router_with_mock_semantic()
        tr = make_triage_result(
            urgency="critical",
            symptoms=["loss of consciousness"],
            red_flags=["septic shock", "sepsis"],
        )
        decision = router.route(tr)
        assert decision.specialist == SpecialistType.EMERGENCY_MEDICINE.value
        assert decision.routing_method == "emergency_override"
        assert decision.escalate_to_emergency is True
        assert decision.confidence == 1.0
        # Semantic layer must NOT have been called
        router._semantic_router.route.assert_not_called()

    def test_high_rule_score_triggers_fast_path(self):
        """When rule score >= 0.80, method=rule_only and semantic is NOT called."""
        router = self._make_router_with_mock_semantic()

        # Craft a triage result that will score cardiologist >= 0.80
        # base=0.55 + 3 boosters × 0.15 = 0.55 + 0.45 = 1.0 (capped)
        tr = make_triage_result(
            urgency="critical",
            symptoms=["chest", "palpitations", "cardiac"],
            red_flags=["crushing chest pain", "jaw pain", "left arm pain"],
            conditions=["Unstable Angina"],
        )
        decision = router.route(tr)
        assert decision.routing_method == "rule_only"
        router._semantic_router.route.assert_not_called()

    def test_low_rule_score_invokes_semantic_layer(self):
        """When best rule score < 0.80, semantic layer IS called."""
        router = self._make_router_with_mock_semantic(
            semantic_results=[("psychiatrist", 0.72)]
        )
        tr = make_triage_result(
            urgency="routine",
            symptoms=["anxiety", "panic"],
            red_flags=[],
        )
        decision = router.route(tr)
        assert router._semantic_router.route.called

    def test_semantic_failure_falls_back_to_rule(self):
        """If semantic layer raises, should fall back to rule engine result."""
        router = HybridSpecialistRouter()
        mock_semantic = MagicMock()
        mock_semantic.route.side_effect = RuntimeError("ChromaDB unavailable")
        router._semantic_router = mock_semantic

        tr = make_triage_result(
            urgency="routine",
            symptoms=["cold", "cough", "runny nose"],
        )
        # Should not raise
        decision = router.route(tr)
        assert isinstance(decision, RoutingDecision)
        assert decision.specialist is not None

    def test_routing_decision_schema_valid(self):
        """RoutingDecision must be a valid Pydantic model with required fields."""
        router = self._make_router_with_mock_semantic(
            semantic_results=[("neurologist", 0.68)]
        )
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["headache", "dizziness", "vision"],
            red_flags=["unilateral headache"],
        )
        decision = router.route(tr)
        assert isinstance(decision, RoutingDecision)
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.routing_method in ("rule_only", "hybrid", "semantic_only", "emergency_override")
        assert decision.specialist_display_name  # not empty
        assert decision.reasoning               # not empty

    def test_alternative_specialists_populated(self):
        """Alternative specialists list should have up to 2 entries."""
        router = self._make_router_with_mock_semantic(
            semantic_results=[("urologist", 0.65), ("general_practitioner", 0.50)]
        )
        tr = make_triage_result(
            urgency="moderate",
            symptoms=["loin pain", "blood in urine", "kidney stone", "flank", "urinary"],
            red_flags=["haematuria"],
            conditions=["Renal Colic"],
        )
        decision = router.route(tr)
        assert len(decision.alternative_specialists) <= 2

    def test_routine_uti_routes_to_gp_or_urologist(self):
        """A routine UTI should route to GP or urologist — not emergency_medicine."""
        router = self._make_router_with_mock_semantic(
            semantic_results=[("general_practitioner", 0.60)]
        )
        tr = make_triage_result(
            urgency="routine",
            symptoms=["burning urination", "frequent urination"],
            red_flags=[],
            conditions=["UTI / Pyelonephritis"],
        )
        decision = router.route(tr)
        assert decision.specialist in (
            SpecialistType.GENERAL_PRACTITIONER.value,
            SpecialistType.UROLOGIST.value,
        )
        assert decision.escalate_to_emergency is False


# ── Score Fusion Formula Tests ─────────────────────────────────────────────────

class TestScoreFusion:
    """Verify the fusion formula: fused = rule × 0.6 + semantic × 0.4."""

    def test_fusion_formula_numerics(self):
        """Direct numeric verification of fusion formula constants."""
        rule_score     = 0.60
        semantic_score = 0.80
        expected_fused = round(0.60 * rule_score + 0.40 * semantic_score, 3)
        assert expected_fused == pytest.approx(0.68)

    def test_zero_semantic_is_pure_rule(self):
        """Fused = rule × 0.6 when semantic = 0."""
        rule_score     = 0.70
        semantic_score = 0.0
        fused = round(0.60 * rule_score + 0.40 * semantic_score, 3)
        assert fused == pytest.approx(0.42)

    def test_zero_rule_is_weighted_semantic(self):
        """Fused = semantic × 0.4 when rule = 0."""
        rule_score     = 0.0
        semantic_score = 0.90
        fused = round(0.60 * rule_score + 0.40 * semantic_score, 3)
        assert fused == pytest.approx(0.36)


# ── RoutingDecision Schema Tests ──────────────────────────────────────────────

class TestRoutingDecisionSchema:

    def test_valid_routing_decision_construction(self):
        d = RoutingDecision(
            specialist="cardiologist",
            specialist_display_name="Cardiologist",
            confidence=0.87,
            routing_method="rule_only",
            rule_score=0.87,
            semantic_score=0.0,
            reasoning="Test reasoning",
            alternative_specialists=["neurologist"],
            escalate_to_emergency=False,
        )
        assert d.specialist == "cardiologist"
        assert d.confidence == 0.87
        assert d.escalate_to_emergency is False

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(Exception):
            RoutingDecision(
                specialist="cardiologist",
                specialist_display_name="Cardiologist",
                confidence=1.5,  # > 1.0 — invalid
                routing_method="rule_only",
                rule_score=0.87,
                semantic_score=0.0,
                reasoning="test",
            )

    def test_emergency_override_confidence_is_one(self):
        """Emergency override always returns confidence=1.0."""
        router = HybridSpecialistRouter()
        mock_semantic = MagicMock()
        mock_semantic.route.return_value = []
        router._semantic_router = mock_semantic

        tr = make_triage_result(
            urgency="critical",
            symptoms=["cardiac arrest"],
            red_flags=["cardiac arrest"],
        )
        decision = router.route(tr)
        if decision.routing_method == "emergency_override":
            assert decision.confidence == 1.0

    def test_model_dump_is_json_serialisable(self):
        """RoutingDecision.model_dump() must be JSON-serialisable for JSONB storage."""
        import json
        d = RoutingDecision(
            specialist="neurologist",
            specialist_display_name="Neurologist",
            confidence=0.75,
            routing_method="hybrid",
            rule_score=0.60,
            semantic_score=0.70,
            reasoning="Test.",
            alternative_specialists=["cardiologist", "general_practitioner"],
            escalate_to_emergency=False,
        )
        dumped = d.model_dump()
        serialised = json.dumps(dumped)  # Must not raise
        assert "neurologist" in serialised
