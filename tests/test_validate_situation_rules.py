"""Failing-test proofs for every scripts/validate.py rule WO-049 / Issue #92
item 10 adds (plus item 6's status-change-vs-contradiction rule and item 8's
impact_assessment basis-field rule), implemented in
analysis/situation_validation.py.

Matches the rigor tests/test_validate_claim_rules.py established for
WO-047's own rules: a genuine failing case and a genuine passing case for
each rule, checked against *stored* record fields rather than a bare
recomputation of the function that produced them (an independent reviewer
of WO-047's post-review round caught a tautological test of exactly that
shape and required it be replaced with a real one -- this module does not
repeat that mistake).
"""

from __future__ import annotations

from analysis.grading import GRADE_RANK
from analysis.situation_validation import (
    conduit_authority_gate_problems,
    confirmed_requires_authority_coverage_problems,
    conflicting_evidence_resolution_basis_problems,
    explainability_walk_problems,
    impact_assessment_basis_problems,
    is_status_change,
    item_strength_a_requires_authority_coverage_problems,
    shared_independence_group_without_basis_problems,
    status_basis_required_problems,
    status_change_classification_problems,
)

# ---------------------------------------------------------------------------
# Minimal builders
# ---------------------------------------------------------------------------


def _document(**overrides) -> dict:
    base = {
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "publisher": "Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
        "canonical_url": "https://example.invalid/notice",
        "independence_group": "IG-PUB-PORT-AUTHORITY-OF-AURELIA",
        "independence_basis": None,
        "published_at": "2026-08-10T08:00:00Z",
        "publisher_authority": None,
    }
    base.update(overrides)
    return base


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-20260810-0001",
        "document_id": "DOC-20260810-001",
        "event_ids": ["EVT-20260810-001"],
        "claim_type": "official_notice",
        "assertion": {
            "subject_type": "node",
            "subject_ref": "NODE-THLCH",
            "predicate": "berths_suspended",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        },
        "node_ids": ["NODE-THLCH"],
        "chokepoint_ids": [],
        "country_ids": [],
        "corroboration_status": "not_assessed",
        "event_start_at": "2026-08-10T06:00:00Z",
    }
    base.update(overrides)
    return base


def _event(**overrides) -> dict:
    base = {
        "event_id": "EVT-20260810-001",
        "claim_ids": ["CLM-20260810-0001"],
        "evidence_grade": None,
        "conflicting_evidence": [],
    }
    base.update(overrides)
    return base


_AUTHORITY = {
    "authority_scope": {
        "node_ids": ["NODE-THLCH"],
        "chokepoint_ids": [],
        "country_ids": [],
        "predicate_classes": ["berth_or_facility_availability"],
    },
    "decided_by": "document_review",
    "decided_at": "2026-08-10T07:00:00Z",
    "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
    "basis": "STRUCTURAL EXAMPLE authority scope.",
}


# ---------------------------------------------------------------------------
# Rule: the explainability walk
# ---------------------------------------------------------------------------


def test_explainability_walk_fails_on_document_with_no_canonical_url():
    situations = [
        {
            "situation_id": "SIT-SEA-CTY-TH-20260810T000000Z",
            "status": "elevated_watch",
            "status_basis": [
                {"event_id": "EVT-20260810-001", "rule_id": "R3", "contribution": "x"}
            ],
        }
    ]
    events_by_id = {"EVT-20260810-001": _event(evidence_grade="CONFIRMED")}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    documents_by_id = {"DOC-20260810-001": _document(canonical_url=None)}
    problems = explainability_walk_problems(
        situations, events_by_id, claims_by_id, documents_by_id, {"MANUAL_NOTICE_INTAKE"}
    )
    assert any("canonical_url" in problem for problem in problems)


def test_explainability_walk_fails_on_unresolved_source():
    situations = [
        {
            "situation_id": "SIT-SEA-CTY-TH-20260810T000000Z",
            "status": "elevated_watch",
            "status_basis": [
                {"event_id": "EVT-20260810-001", "rule_id": "R3", "contribution": "x"}
            ],
        }
    ]
    events_by_id = {"EVT-20260810-001": _event(evidence_grade="CONFIRMED")}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    documents_by_id = {"DOC-20260810-001": _document()}
    problems = explainability_walk_problems(
        situations, events_by_id, claims_by_id, documents_by_id, set()
    )
    assert any("does not resolve in the source registry" in problem for problem in problems)


def test_explainability_walk_passes_when_every_link_resolves():
    situations = [
        {
            "situation_id": "SIT-SEA-CTY-TH-20260810T000000Z",
            "status": "elevated_watch",
            "status_basis": [
                {"event_id": "EVT-20260810-001", "rule_id": "R3", "contribution": "x"}
            ],
        }
    ]
    events_by_id = {"EVT-20260810-001": _event(evidence_grade="CONFIRMED")}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    documents_by_id = {"DOC-20260810-001": _document()}
    problems = explainability_walk_problems(
        situations, events_by_id, claims_by_id, documents_by_id, {"MANUAL_NOTICE_INTAKE"}
    )
    assert problems == []


def test_explainability_walk_skips_insufficient_current_evidence():
    situations = [
        {
            "situation_id": "SIT-SEA-CTY-TH-20260810T000000Z",
            "status": "insufficient_current_evidence",
            "status_basis": [],
        }
    ]
    assert explainability_walk_problems(situations, {}, {}, {}, set()) == []


# ---------------------------------------------------------------------------
# Rule: grade_override upward-refusal (analysis/grading.py, wired here too)
# ---------------------------------------------------------------------------


def test_grade_rank_makes_upward_override_detectable():
    assert GRADE_RANK["CONFIRMED"] > GRADE_RANK["REPORTED"]


# ---------------------------------------------------------------------------
# Rule: authority_covers required for grade A / CONFIRMED
# ---------------------------------------------------------------------------


def test_confirmed_without_authority_coverage_fails():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event(evidence_grade="CONFIRMED")
    problems = confirmed_requires_authority_coverage_problems(
        [event], claims_by_id, documents_by_id
    )
    assert any("CONFIRMED but no contributing claim" in problem for problem in problems)


def test_confirmed_with_authority_coverage_passes():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=_AUTHORITY)}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event(evidence_grade="CONFIRMED")
    assert (
        confirmed_requires_authority_coverage_problems([event], claims_by_id, documents_by_id) == []
    )


def test_non_confirmed_grade_is_not_checked():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    event = _event(evidence_grade="REPORTED")
    assert (
        confirmed_requires_authority_coverage_problems([event], claims_by_id, documents_by_id) == []
    )


def test_item_strength_a_requires_authority_coverage_fails():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    record = {"evidence_id": "EVD-20260810-0001", "strength": "A"}
    problems = item_strength_a_requires_authority_coverage_problems(
        [record], claims_by_id, documents_by_id
    )
    assert any("authority_covers is False" in problem for problem in problems)


def test_item_strength_a_requires_authority_coverage_passes():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=_AUTHORITY)}
    claims_by_id = {"CLM-20260810-0001": _claim()}
    record = {"evidence_id": "EVD-20260810-0001", "strength": "A"}
    assert (
        item_strength_a_requires_authority_coverage_problems(
            [record], claims_by_id, documents_by_id
        )
        == []
    )


# ---------------------------------------------------------------------------
# Rule: the conduit rule
# ---------------------------------------------------------------------------


def test_conduit_rule_fails_on_officially_confirmed_claim_with_no_authority():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claim = _claim(corroboration_status="officially_confirmed")
    registry = {
        "sources": [
            {
                "id": "MANUAL_NOTICE_INTAKE",
                "governance": {"channel_role": "conduit"},
            }
        ]
    }
    problems = conduit_authority_gate_problems([claim], documents_by_id, {}, registry)
    assert any("officially_confirmed" in problem for problem in problems)


def test_conduit_rule_fails_on_confirmed_event_with_no_authority():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claim = _claim()
    events_by_id = {"EVT-20260810-001": _event(evidence_grade="CONFIRMED")}
    registry = {
        "sources": [{"id": "MANUAL_NOTICE_INTAKE", "governance": {"channel_role": "conduit"}}]
    }
    problems = conduit_authority_gate_problems([claim], documents_by_id, events_by_id, registry)
    assert any("evidence_grade is CONFIRMED" in problem for problem in problems)


def test_conduit_rule_passes_when_authority_recorded():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=_AUTHORITY)}
    claim = _claim(corroboration_status="officially_confirmed")
    events_by_id = {"EVT-20260810-001": _event(evidence_grade="CONFIRMED")}
    registry = {
        "sources": [{"id": "MANUAL_NOTICE_INTAKE", "governance": {"channel_role": "conduit"}}]
    }
    assert conduit_authority_gate_problems([claim], documents_by_id, events_by_id, registry) == []


def test_conduit_rule_does_not_apply_to_originator_channel_source():
    documents_by_id = {"DOC-20260810-001": _document(publisher_authority=None)}
    claim = _claim(corroboration_status="officially_confirmed")
    registry = {
        "sources": [
            {"id": "MANUAL_NOTICE_INTAKE", "governance": {"channel_role": "originator_channel"}}
        ]
    }
    assert conduit_authority_gate_problems([claim], documents_by_id, {}, registry) == []


# ---------------------------------------------------------------------------
# Rule: no two distinct publishers share a derived independence_group
# ---------------------------------------------------------------------------


def test_shared_group_without_basis_fails():
    documents = [
        _document(document_id="DOC-A", publisher="Publisher A", independence_group="IG-PUB-SHARED"),
        _document(document_id="DOC-B", publisher="Publisher B", independence_group="IG-PUB-SHARED"),
    ]
    problems = shared_independence_group_without_basis_problems(documents)
    assert len(problems) == 2


def test_shared_group_with_basis_passes():
    documents = [
        _document(
            document_id="DOC-A",
            publisher="Publisher A",
            independence_group="IG-PUB-SHARED",
            independence_basis="A reviewed common-ownership relationship.",
        ),
        _document(
            document_id="DOC-B",
            publisher="Publisher B",
            independence_group="IG-PUB-SHARED",
            independence_basis="A reviewed common-ownership relationship.",
        ),
    ]
    assert shared_independence_group_without_basis_problems(documents) == []


def test_same_publisher_sharing_a_group_is_fine():
    documents = [
        _document(document_id="DOC-A", publisher="Publisher A", independence_group="IG-PUB-A"),
        _document(document_id="DOC-B", publisher="Publisher A", independence_group="IG-PUB-A"),
    ]
    assert shared_independence_group_without_basis_problems(documents) == []


# ---------------------------------------------------------------------------
# Rule: mode_situation.status_basis non-empty
# ---------------------------------------------------------------------------


def test_status_basis_required_fails_when_empty_for_non_insufficient_status():
    situations = [{"situation_id": "SIT-1", "status": "elevated_watch", "status_basis": []}]
    problems = status_basis_required_problems(situations)
    assert any("requires a non-empty status_basis" in problem for problem in problems)


def test_status_basis_required_passes_when_populated():
    situations = [
        {
            "situation_id": "SIT-1",
            "status": "elevated_watch",
            "status_basis": [{"event_id": "EVT-1", "rule_id": "R3", "contribution": "x"}],
        }
    ]
    assert status_basis_required_problems(situations) == []


def test_status_basis_not_required_for_insufficient_current_evidence():
    situations = [
        {"situation_id": "SIT-1", "status": "insufficient_current_evidence", "status_basis": []}
    ]
    assert status_basis_required_problems(situations) == []


# ---------------------------------------------------------------------------
# Item 6: the status-change-vs-contradiction rule
# ---------------------------------------------------------------------------


def test_is_status_change_true_when_newer_authoritative_resolving_claim():
    older = _claim(
        claim_id="CLM-OLD",
        document_id="DOC-OLD",
        event_start_at="2026-08-01T00:00:00Z",
        claim_type="official_notice",
    )
    newer = _claim(
        claim_id="CLM-NEW",
        document_id="DOC-NEW",
        event_start_at="2026-08-05T00:00:00Z",
        claim_type="official_notice",
    )
    claims_by_id = {"CLM-OLD": older, "CLM-NEW": newer}
    documents_by_id = {
        "DOC-OLD": _document(document_id="DOC-OLD", published_at="2026-08-01T00:00:00Z"),
        "DOC-NEW": _document(
            document_id="DOC-NEW",
            published_at="2026-08-05T00:00:00Z",
            publisher_authority=_AUTHORITY,
        ),
    }
    assert is_status_change(["CLM-OLD"], ["CLM-NEW"], claims_by_id, documents_by_id) is True


def test_is_status_change_false_when_newer_claim_is_a_bare_report():
    older = _claim(claim_id="CLM-OLD", document_id="DOC-OLD", event_start_at="2026-08-01T00:00:00Z")
    newer = _claim(
        claim_id="CLM-NEW",
        document_id="DOC-NEW",
        event_start_at="2026-08-05T00:00:00Z",
        claim_type="reported_claim",
    )
    claims_by_id = {"CLM-OLD": older, "CLM-NEW": newer}
    documents_by_id = {
        "DOC-OLD": _document(document_id="DOC-OLD", published_at="2026-08-01T00:00:00Z"),
        "DOC-NEW": _document(
            document_id="DOC-NEW",
            published_at="2026-08-05T00:00:00Z",
            publisher_authority=_AUTHORITY,
        ),
    }
    assert is_status_change(["CLM-OLD"], ["CLM-NEW"], claims_by_id, documents_by_id) is False


def test_is_status_change_false_when_not_newer():
    older = _claim(claim_id="CLM-OLD", document_id="DOC-OLD", event_start_at="2026-08-05T00:00:00Z")
    newer = _claim(claim_id="CLM-NEW", document_id="DOC-NEW", event_start_at="2026-08-01T00:00:00Z")
    claims_by_id = {"CLM-OLD": older, "CLM-NEW": newer}
    documents_by_id = {
        "DOC-OLD": _document(document_id="DOC-OLD", published_at="2026-08-05T00:00:00Z"),
        "DOC-NEW": _document(
            document_id="DOC-NEW",
            published_at="2026-08-01T00:00:00Z",
            publisher_authority=_AUTHORITY,
        ),
    }
    assert is_status_change(["CLM-OLD"], ["CLM-NEW"], claims_by_id, documents_by_id) is False


def test_status_change_classification_fails_when_mislabelled():
    """STRUCTURAL EXAMPLE: an unresolved status_change-type contradiction
    whose newest side_b claim is actually a bare, unnamed news report --
    it does not qualify as a real status change and must be flagged."""
    older = _claim(claim_id="CLM-OLD", document_id="DOC-OLD", event_start_at="2026-08-01T00:00:00Z")
    newer = _claim(
        claim_id="CLM-NEW",
        document_id="DOC-NEW",
        event_start_at="2026-08-05T00:00:00Z",
        claim_type="reported_claim",
        attributed_to={"name": None, "role": "operators", "is_named": False},
    )
    claims_by_id = {"CLM-OLD": older, "CLM-NEW": newer}
    documents_by_id = {
        "DOC-OLD": _document(document_id="DOC-OLD", published_at="2026-08-01T00:00:00Z"),
        "DOC-NEW": _document(document_id="DOC-NEW", published_at="2026-08-05T00:00:00Z"),
    }
    event = {
        "event_id": "EVT-SYNTH-101",
        "conflicting_evidence": [
            {
                "description": "STRUCTURAL EXAMPLE.",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "unresolved",
                "contradiction_type": "status_change",
                "claim_ids_side_a": ["CLM-OLD"],
                "claim_ids_side_b": ["CLM-NEW"],
            }
        ],
    }
    problems = status_change_classification_problems([event], claims_by_id, documents_by_id)
    assert any("does not satisfy the status-change" in problem for problem in problems)


def test_status_change_classification_passes_when_genuinely_a_status_change():
    older = _claim(claim_id="CLM-OLD", document_id="DOC-OLD", event_start_at="2026-08-01T00:00:00Z")
    newer = _claim(
        claim_id="CLM-NEW",
        document_id="DOC-NEW",
        event_start_at="2026-08-05T00:00:00Z",
        claim_type="official_notice",
    )
    claims_by_id = {"CLM-OLD": older, "CLM-NEW": newer}
    documents_by_id = {
        "DOC-OLD": _document(document_id="DOC-OLD", published_at="2026-08-01T00:00:00Z"),
        "DOC-NEW": _document(
            document_id="DOC-NEW",
            published_at="2026-08-05T00:00:00Z",
            publisher_authority=_AUTHORITY,
        ),
    }
    event = {
        "event_id": "EVT-SYNTH-101",
        "conflicting_evidence": [
            {
                "description": "STRUCTURAL EXAMPLE.",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "resolved_as_status_change",
                "resolution_basis": "STRUCTURAL EXAMPLE resolution basis.",
                "contradiction_type": "status_change",
                "claim_ids_side_a": ["CLM-OLD"],
                "claim_ids_side_b": ["CLM-NEW"],
            }
        ],
    }
    assert status_change_classification_problems([event], claims_by_id, documents_by_id) == []


# ---------------------------------------------------------------------------
# conflicting_evidence.resolution_basis
# ---------------------------------------------------------------------------


def test_resolution_basis_required_when_not_unresolved_fails():
    event = {
        "event_id": "EVT-1",
        "conflicting_evidence": [
            {
                "description": "x",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "resolved_by_primary_source",
                "resolution_basis": None,
            }
        ],
    }
    problems = conflicting_evidence_resolution_basis_problems([event])
    assert any("requires a non-empty resolution_basis" in problem for problem in problems)


def test_resolution_basis_not_required_when_unresolved():
    event = {
        "event_id": "EVT-1",
        "conflicting_evidence": [
            {
                "description": "x",
                "evidence_ids": ["EVD-A", "EVD-B"],
                "resolution_status": "unresolved",
                "resolution_basis": None,
            }
        ],
    }
    assert conflicting_evidence_resolution_basis_problems([event]) == []


# ---------------------------------------------------------------------------
# Item 8: the impact_assessment basis fields
# ---------------------------------------------------------------------------


def _impact(**overrides) -> dict:
    base = {
        "area": "transport",
        "status": "insufficient_evidence",
        "severity": "none",
        "relevance": "none",
        "evidence_strength": None,
        "confidence": "low",
        "evidence_ids": [],
        "known_limitations": [],
    }
    base.update(overrides)
    return base


def test_impact_basis_fails_on_elevated_watch_with_no_trigger():
    event = {
        "event_id": "EVT-1",
        "dataset": "current_publication",
        "impact_assessments": [_impact(status="elevated_watch", watch_trigger=None)],
    }
    problems = impact_assessment_basis_problems([event])
    assert any("elevated_watch" in problem and "watch_trigger" in problem for problem in problems)


def test_impact_basis_fails_on_no_material_with_no_basis():
    event = {
        "event_id": "EVT-1",
        "dataset": "current_publication",
        "impact_assessments": [_impact(status="no_material", no_material_basis=None)],
    }
    problems = impact_assessment_basis_problems([event])
    assert any("no_material" in problem and "no_material_basis" in problem for problem in problems)


def test_impact_basis_fails_on_not_relevant_with_no_basis():
    event = {
        "event_id": "EVT-1",
        "dataset": "current_publication",
        "impact_assessments": [_impact(status="not_relevant", not_relevant_basis=None)],
    }
    problems = impact_assessment_basis_problems([event])
    assert any(
        "not_relevant" in problem and "not_relevant_basis" in problem for problem in problems
    )


def test_impact_basis_passes_when_basis_recorded():
    event = {
        "event_id": "EVT-1",
        "dataset": "current_publication",
        "impact_assessments": [
            _impact(status="elevated_watch", watch_trigger="STRUCTURAL EXAMPLE trigger."),
            _impact(status="no_material", area="cost", no_material_basis="STRUCTURAL EXAMPLE."),
            _impact(
                status="not_relevant",
                area="warehouse",
                not_relevant_basis="STRUCTURAL EXAMPLE.",
            ),
        ],
    }
    assert impact_assessment_basis_problems([event]) == []


def test_impact_basis_not_checked_outside_current_publication_dataset():
    """The exact real-repository case this rule must not break: EVT-20240614-002
    is a historical_validation-dataset fixture, committed before these basis
    fields existed, carrying status: no_material on nine areas with no
    no_material_basis recorded. This rule must not flag it."""
    event = {
        "event_id": "EVT-20240614-002",
        "dataset": "historical_validation",
        "impact_assessments": [_impact(status="no_material", no_material_basis=None)],
    }
    assert impact_assessment_basis_problems([event]) == []


def test_impact_basis_not_checked_for_other_statuses():
    event = {
        "event_id": "EVT-1",
        "dataset": "current_publication",
        "impact_assessments": [_impact(status="insufficient_evidence")],
    }
    assert impact_assessment_basis_problems([event]) == []
