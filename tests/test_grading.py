"""Tests for analysis/grading.py (WO-049 / Issue #92 items 3 and 7):
Development-level evidence_grade computation, grade_override's
downgrade-only rule, and situation_state transition proposals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from analysis.grading import (
    GRADE_RANK,
    compute_evidence_grade,
    compute_situation_state,
    eligible_claims,
    grade_override_problems,
    independent_group_count,
)

ROOT = Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))


def _document(**overrides) -> dict:
    base = {
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "evidence_layer": "current_evidence",
        "evidence_origin": "human_reviewed_manual",
        "retrieval_status": "not_applicable",
        "published_at": "2026-08-10T08:00:00Z",
        "retrieved_at": None,
        "updated_at": None,
        "independence_group": "IG-PUB-STRUCTURAL-EXAMPLE",
        "duplicate_of": None,
        "publisher_authority": {
            "authority_scope": {
                "node_ids": ["NODE-SYNTH-NGT"],
                "chokepoint_ids": [],
                "country_ids": [],
                "predicate_classes": ["berth_or_facility_availability"],
            },
            "decided_by": "document_review",
            "decided_at": "2026-08-10T07:00:00Z",
            "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
            "basis": "STRUCTURAL EXAMPLE authority scope.",
        },
    }
    base.update(overrides)
    return base


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-20260810-0001",
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "event_ids": ["EVT-20260810-001"],
        "claim_type": "official_notice",
        "assertion": {
            "subject_type": "node",
            "subject_ref": "NODE-SYNTH-NGT",
            "predicate": "berths_suspended",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        },
        "event_start_at": "2026-08-10T06:00:00Z",
        "event_end_at": None,
        "node_ids": ["NODE-SYNTH-NGT"],
        "chokepoint_ids": [],
        "country_ids": [],
        "primary_for_this_claim": True,
        "evidence_layer": "current_evidence",
        "independence_group": "IG-PUB-STRUCTURAL-EXAMPLE",
        "attributed_to": None,
        "contradiction_status": "none",
        "review_status": "approved",
        "dataset": "current_publication",
        "superseded_by": None,
        "assertion_group_id": None,
    }
    base.update(overrides)
    return base


def _event(**overrides) -> dict:
    base = {
        "event_id": "EVT-20260810-001",
        "claim_ids": ["CLM-20260810-0001"],
        "conflicting_evidence": [],
        "node_ids": ["NODE-SYNTH-NGT"],
        "active_as_of": None,
        "active_basis": None,
        "event_end_date": None,
        "first_seen_at": "2026-08-10T08:00:00Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# eligible_claims (Q(E))
# ---------------------------------------------------------------------------


def test_eligible_claims_excludes_non_current_publication_dataset(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim(dataset="historical_validation")}
    event = _event()
    assert eligible_claims(event, claims_by_id, documents_by_id, registry) == []


def test_eligible_claims_excludes_unapproved_review_status(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim(review_status="unreviewed")}
    event = _event()
    assert eligible_claims(event, claims_by_id, documents_by_id, registry) == []


def test_eligible_claims_includes_qualifying_claim(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event()
    result = eligible_claims(event, claims_by_id, documents_by_id, registry)
    assert [c["claim_id"] for c in result] == ["CLM-20260810-0001"]


def test_eligible_claims_excludes_source_not_enabled_for_public_claims(registry):
    documents_by_id = {"DOC-20260810-001": _document(source_id="NEWS_DISCOVERY")}
    claims_by_id = {"CLM-20260810-0001": _claim(source_id="NEWS_DISCOVERY")}
    event = _event()
    assert eligible_claims(event, claims_by_id, documents_by_id, registry) == []


# ---------------------------------------------------------------------------
# independent_group_count
# ---------------------------------------------------------------------------


def test_independent_group_count_excludes_duplicate_documents(registry):
    documents_by_id = {
        "DOC-20260810-001": _document(document_id="DOC-20260810-001"),
        "DOC-20260810-002": _document(
            document_id="DOC-20260810-002",
            independence_group="IG-PUB-OTHER",
            duplicate_of="DOC-20260810-001",
        ),
    }
    claims = [
        _claim(claim_id="CLM-A", document_id="DOC-20260810-001"),
        _claim(claim_id="CLM-B", document_id="DOC-20260810-002", independence_group="IG-PUB-OTHER"),
    ]
    assert independent_group_count(claims, documents_by_id) == 1


# ---------------------------------------------------------------------------
# compute_evidence_grade
# ---------------------------------------------------------------------------


def test_no_grade_when_q_empty(registry):
    grade, basis = compute_evidence_grade(_event(claim_ids=[]), {}, {}, registry, now=_NOW)
    assert grade is None
    assert basis


def test_no_grade_when_only_discovery_leads(registry):
    documents_by_id = {"DOC-20260810-001": _document(source_id="NEWS_DISCOVERY")}
    claims_by_id = {
        "CLM-20260810-0001": _claim(claim_type="discovery_lead", source_id="NEWS_DISCOVERY")
    }
    grade, _basis = compute_evidence_grade(
        _event(), claims_by_id, documents_by_id, registry, now=_NOW
    )
    assert grade is None


def test_confirmed_from_one_primary_authoritative_fresh_uncontradicted_claim(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    grade, basis = compute_evidence_grade(
        _event(), claims_by_id, documents_by_id, registry, now=_NOW
    )
    assert grade == "CONFIRMED"
    assert basis


def test_confirmed_pilot_is_not_promoted_by_a_second_independent_group(registry):
    """Design part 1 Section 2.9: adding a second, genuinely independent
    publisher leaves the grade CONFIRMED (there is nothing above it); it
    only raises confidence, which mode_situation computes separately."""
    documents_by_id = {
        "DOC-20260810-001": _document(document_id="DOC-20260810-001"),
        "DOC-20260810-002": _document(
            document_id="DOC-20260810-002",
            independence_group="IG-PUB-OTHER",
            publisher_authority=None,
        ),
    }
    claims_by_id = {
        "CLM-20260810-0001": _claim(claim_id="CLM-20260810-0001", document_id="DOC-20260810-001"),
        "CLM-20260810-0002": _claim(
            claim_id="CLM-20260810-0002",
            document_id="DOC-20260810-002",
            independence_group="IG-PUB-OTHER",
            claim_type="verified_fact",
        ),
    }
    event = _event(claim_ids=["CLM-20260810-0001", "CLM-20260810-0002"])
    grade, _basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    assert grade == "CONFIRMED"


def test_corroborated_from_two_independent_groups_no_primary_authority(registry):
    documents_by_id = {
        "DOC-20260810-001": _document(document_id="DOC-20260810-001", publisher_authority=None),
        "DOC-20260810-002": _document(
            document_id="DOC-20260810-002",
            independence_group="IG-PUB-OTHER",
            publisher_authority=None,
        ),
    }
    claims_by_id = {
        "CLM-20260810-0001": _claim(
            claim_id="CLM-20260810-0001",
            document_id="DOC-20260810-001",
            attributed_to={"name": "Named official", "role": "spokesperson", "is_named": True},
        ),
        "CLM-20260810-0002": _claim(
            claim_id="CLM-20260810-0002",
            document_id="DOC-20260810-002",
            independence_group="IG-PUB-OTHER",
            attributed_to={
                "name": "Another named official",
                "role": "spokesperson",
                "is_named": True,
            },
        ),
    }
    event = _event(claim_ids=["CLM-20260810-0001", "CLM-20260810-0002"])
    grade, basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    assert grade == "CORROBORATED"
    assert basis


def test_reported_from_single_group_current_evidence_claim(registry):
    documents_by_id = {
        "DOC-20260810-001": _document(publisher_authority=None),
    }
    claims_by_id = {
        "CLM-20260810-0001": _claim(
            claim_type="reported_claim",
            primary_for_this_claim=False,
            attributed_to={"name": None, "role": "operator", "is_named": False},
        )
    }
    grade, basis = compute_evidence_grade(
        _event(), claims_by_id, documents_by_id, registry, now=_NOW
    )
    assert grade == "REPORTED"
    assert basis


def test_analytical_inference_when_only_inference_claims(registry):
    documents_by_id = {"DOC-20260810-001": _document(evidence_layer="structural_research")}
    claims_by_id = {
        "CLM-20260810-0001": _claim(
            claim_type="analytical_inference", evidence_layer="structural_research"
        )
    }
    grade, basis = compute_evidence_grade(
        _event(), claims_by_id, documents_by_id, registry, now=_NOW
    )
    assert grade == "ANALYTICAL_INFERENCE"
    assert basis


def test_unresolved_status_change_contradiction_caps_confirmed_to_reported(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event(
        conflicting_evidence=[
            {
                "description": "STRUCTURAL EXAMPLE conflict.",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "unresolved",
                "contradiction_type": "status_change",
            }
        ]
    )
    grade, basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    # An unresolved status_change contradiction on the sole primary claim
    # prevents it from ever entering the CONFIRMED candidate set, so the
    # grade lands on REPORTED via that rule's own entry test rather than
    # via the explicit post-hoc cap -- either way, CONFIRMED is unreachable
    # while the contradiction stands, which is the property this proves.
    assert grade == "REPORTED"
    assert basis


def test_non_capping_contradiction_type_does_not_cap_grade(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event(
        conflicting_evidence=[
            {
                "description": "STRUCTURAL EXAMPLE conflict over magnitude only.",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "unresolved",
                "contradiction_type": "magnitude",
            }
        ]
    )
    grade, _basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    assert grade == "CONFIRMED"


def test_stale_contributor_caps_confirmed_to_reported(registry):
    """A fresh, primary, authoritative claim alone would be CONFIRMED; a
    second, stale contributing claim in the same Q(E) caps the Development
    grade to REPORTED (design part 1 Section 2.7: the OLDEST contributor
    governs the verification clock, not only the claim carrying the base
    grade)."""
    documents_by_id = {
        "DOC-20260810-001": _document(document_id="DOC-20260810-001"),
        "DOC-20260810-002": _document(
            document_id="DOC-20260810-002", published_at="2026-05-15T08:00:00Z"
        ),
    }
    claims_by_id = {
        "CLM-20260810-0001": _claim(claim_id="CLM-20260810-0001", document_id="DOC-20260810-001"),
        "CLM-20260810-0002": _claim(
            claim_id="CLM-20260810-0002",
            document_id="DOC-20260810-002",
            claim_type="verified_fact",
        ),
    }
    event = _event(claim_ids=["CLM-20260810-0001", "CLM-20260810-0002"])
    grade, basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    assert grade == "REPORTED"
    assert any("stale" in b for b in basis)


def test_ageing_contributor_caps_confirmed_to_corroborated(registry):
    documents_by_id = {
        "DOC-20260810-001": _document(document_id="DOC-20260810-001"),
        "DOC-20260810-002": _document(
            document_id="DOC-20260810-002", published_at="2026-06-20T08:00:00Z"
        ),
    }
    claims_by_id = {
        "CLM-20260810-0001": _claim(claim_id="CLM-20260810-0001", document_id="DOC-20260810-001"),
        "CLM-20260810-0002": _claim(
            claim_id="CLM-20260810-0002",
            document_id="DOC-20260810-002",
            claim_type="verified_fact",
        ),
    }
    event = _event(claim_ids=["CLM-20260810-0001", "CLM-20260810-0002"])
    grade, basis = compute_evidence_grade(event, claims_by_id, documents_by_id, registry, now=_NOW)
    assert grade == "CORROBORATED"
    assert any("ageing" in b for b in basis)


# ---------------------------------------------------------------------------
# grade_override: downgrade-only
# ---------------------------------------------------------------------------


def test_grade_override_downward_passes():
    event = {
        "event_id": "EVT-20260810-001",
        "evidence_grade": "CONFIRMED",
        "grade_override": {
            "to": "REPORTED",
            "reason": "STRUCTURAL EXAMPLE reason.",
            "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
            "at": "2026-08-10T09:00:00Z",
        },
    }
    assert grade_override_problems([event]) == []


def test_grade_override_upward_fails():
    event = {
        "event_id": "EVT-20260810-001",
        "evidence_grade": "REPORTED",
        "grade_override": {
            "to": "CONFIRMED",
            "reason": "STRUCTURAL EXAMPLE reason.",
            "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
            "at": "2026-08-10T09:00:00Z",
        },
    }
    problems = grade_override_problems([event])
    assert any("not strictly weaker" in problem for problem in problems)


def test_grade_override_lateral_fails():
    event = {
        "event_id": "EVT-20260810-001",
        "evidence_grade": "REPORTED",
        "grade_override": {
            "to": "REPORTED",
            "reason": "STRUCTURAL EXAMPLE reason.",
            "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
            "at": "2026-08-10T09:00:00Z",
        },
    }
    assert grade_override_problems([event])


def test_grade_override_absent_is_fine():
    event = {"event_id": "EVT-20260810-001", "evidence_grade": "CONFIRMED", "grade_override": None}
    assert grade_override_problems([event]) == []


def test_grade_rank_order():
    assert GRADE_RANK["CONFIRMED"] > GRADE_RANK["CORROBORATED"] > GRADE_RANK["REPORTED"]
    assert GRADE_RANK["REPORTED"] > GRADE_RANK["ANALYTICAL_INFERENCE"] > GRADE_RANK[None]


# ---------------------------------------------------------------------------
# compute_situation_state
# ---------------------------------------------------------------------------


def test_situation_state_active_from_confirmed_grade_with_active_basis(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [_claim()]
    event = _event(active_as_of="2026-08-10T08:00:00Z", active_basis="STRUCTURAL EXAMPLE basis")
    state, basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="CONFIRMED", now=_NOW
    )
    assert state == "ACTIVE"
    assert basis


def test_situation_state_developing_from_widening_claim(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [
        _claim(),
        _claim(
            claim_id="CLM-20260810-0002",
            event_start_at="2026-08-10T10:00:00Z",
            node_ids=["NODE-SYNTH-NGT", "NODE-SYNTH-OTHER"],
        ),
    ]
    event = _event(active_as_of="2026-08-10T08:00:00Z", active_basis="STRUCTURAL EXAMPLE basis")
    state, basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="CONFIRMED", now=_NOW
    )
    assert state == "DEVELOPING"
    assert basis


def test_situation_state_uncertain_from_unresolved_capping_contradiction(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [_claim()]
    event = _event(
        conflicting_evidence=[
            {
                "description": "STRUCTURAL EXAMPLE.",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "unresolved",
                "contradiction_type": "existence",
            }
        ]
    )
    state, basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="CONFIRMED", now=_NOW
    )
    assert state == "UNCERTAIN"
    assert basis


def test_situation_state_uncertain_from_stale_freshness(registry):
    documents_by_id = {"DOC-20260810-001": _document(published_at="2026-05-15T08:00:00Z")}
    claims = [_claim()]
    event = _event()
    state, _basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="REPORTED", now=_NOW
    )
    assert state == "UNCERTAIN"


def test_situation_state_emerging_from_first_approved_current_evidence_claim(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [_claim()]
    event = _event(first_seen_at="2026-08-10T08:00:00Z")
    state, basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="REPORTED", now=_NOW
    )
    assert state == "EMERGING"
    assert basis


def test_situation_state_resolved_proposal_from_qualifying_uncontradicted_claim(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [_claim(claim_type="denial_or_correction", contradiction_status="none")]
    event = _event(active_as_of=None, active_basis=None, first_seen_at=None)
    state, basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade="REPORTED", now=_NOW
    )
    assert state == "RESOLVED"
    assert basis


def test_situation_state_none_when_no_rule_fires(registry):
    documents_by_id = {"DOC-20260810-001": _document()}
    claims = [
        _claim(
            claim_type="reported_claim",
            contradiction_status="unresolved",
            evidence_layer="context",
            review_status="approved",
        )
    ]
    event = _event(first_seen_at=None)
    state, _basis = compute_situation_state(
        event, claims, documents_by_id, registry, grade=None, now=_NOW
    )
    assert state is None
