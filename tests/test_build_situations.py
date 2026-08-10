"""Tests for scripts/build_situations.py and analysis/situations.py
(WO-049 / Issue #92 item 5).

Two groups: the negative path against the real, committed repository (all
ten events are historical_validation, so the answer must be
'insufficient_current_evidence' by filtering, not by a literal -- the same
proof pattern tests/test_current_positive_path.py already established for
the existing current view, acceptance criterion A-7); and the positive path,
built entirely from synthetic STRUCTURAL EXAMPLE fixtures, proving rule 3's
second clause (a CONFIRMED development whose nine impact areas are all still
insufficient_evidence yields 'elevated_watch') -- the rule the recommendation
comment names as making WO-049's first real output reachable with zero
review-package round trip.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.contracts import schema_errors  # noqa: E402
from analysis.situations import compute_mode_situation  # noqa: E402
from scripts.build_situations import DATA_CUTOFF, build_situations  # noqa: E402

_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Negative path: the real, committed repository
# ---------------------------------------------------------------------------


def test_real_repository_yields_insufficient_current_evidence_by_filtering():
    payload = build_situations()
    assert len(payload["situations"]) == 1
    situation = payload["situations"][0]
    assert situation["status"] == "insufficient_current_evidence"
    events = json.loads((ROOT / "data/events/events.json").read_text(encoding="utf-8"))["events"]
    assert len(situation["excluded_event_ids"]) == len(events)
    assert situation["contributing_event_ids"] == []
    assert situation["material_event_count"] == 0


def test_real_repository_situation_validates_against_schema():
    payload = build_situations()
    for situation in payload["situations"]:
        errors = schema_errors(situation, "mode_situation.schema.json")
        assert errors == [], errors


def test_build_situations_check_matches_committed_file():
    """scripts/build_situations.py --check's own comparison, exercised
    directly: the committed data/situations/situations.json must be exactly
    what a fresh build produces."""
    committed = json.loads((ROOT / "data/situations/situations.json").read_text(encoding="utf-8"))
    assert committed == build_situations()


# ---------------------------------------------------------------------------
# Positive path: synthetic STRUCTURAL EXAMPLE fixtures
# ---------------------------------------------------------------------------

_AREAS = (
    "warehouse",
    "logistics",
    "transport",
    "import_export",
    "inventory",
    "cost",
    "capacity",
    "service",
    "business_continuity",
)


def _insufficient_impact_assessments() -> list[dict]:
    base = {
        "status": "insufficient_evidence",
        "severity": "none",
        "relevance": "none",
        "geographic_scope": "facility",
        "time_horizon": "unknown",
        "expected_duration": "unknown",
        "transmission_mechanism": [],
        "evidence_ids": [],
        "evidence_strength": "C",
        "confidence": "low",
        "known_limitations": [],
    }
    return [{"area": area, **base} for area in _AREAS]


def _synthetic_document() -> dict:
    return {
        "document_id": "DOC-20260810-901",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "document_type": "official_notice",
        "evidence_layer": "current_evidence",
        "evidence_layer_basis": None,
        "title": "Berths 3-5 suspended for structural inspection (STRUCTURAL EXAMPLE)",
        "publisher": "Port Authority of Aurelia (STRUCTURAL EXAMPLE -- not a real authority)",
        "publisher_is_originator": True,
        "originator_publisher": None,
        "originator_document_url": None,
        "canonical_url": "https://notices.aurelia-port.example.invalid/2026/08/berth-suspension",
        "access_url": None,
        "language": "en",
        "published_at": "2026-08-10T06:00:00Z",
        "published_at_precision": "datetime",
        "updated_at": None,
        "retrieved_at": None,
        "retrieval_status": "not_applicable",
        "evidence_origin": "human_reviewed_manual",
        "content_sha256": "b" * 64,
        "content_hash_scope": "authored_claim_record",
        "stored_content": "none",
        "stored_content_location": None,
        "rights": {
            "publication_use": "bounded_claim_and_link_only",
            "quotation_allowed": False,
            "quotation_max_words": None,
            "attribution_required": True,
            "redistribution_status": "link_only",
            "decided_by": "registry_default",
            "decided_at": "2026-08-10T07:00:00Z",
            "reviewer_record": None,
            "basis": "MANUAL_NOTICE_INTAKE registry default publication_use.",
        },
        "paywall_encountered": None,
        "geographies": ["GEO-CTY-TH"],
        "transport_modes": ["sea"],
        "topics": ["terminal_or_facility_closure"],
        "independence_group": "IG-PUB-PORT-AUTHORITY-OF-AURELIA",
        "independence_basis": (
            "Derived from underlying publisher identity (conduit source), not from source_id."
        ),
        "duplicate_of": None,
        "supersedes": [],
        "superseded_by": None,
        "correction_status": "none",
        "review_status": "accepted",
        "reviewer_record": "STRUCTURAL EXAMPLE reviewer",
        "reviewed_at": "2026-08-10T07:00:00Z",
        "dataset": "current_publication",
        "known_limitations": [
            "STRUCTURAL EXAMPLE fixture. Never a report about real current conditions."
        ],
        "collection_run_id": None,
        "manual_review_event_id": "MAN-20260810T070000Z-MANUAL_NOTICE_INTAKE",
        "publisher_authority": {
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
        },
    }


def _synthetic_claim() -> dict:
    return {
        "claim_id": "CLM-20260810-9001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "document_id": "DOC-20260810-901",
        "event_ids": ["EVT-20260810-901"],
        "claim_text": "STRUCTURAL EXAMPLE: berths 3-5 at the terminal are suspended.",
        "claim_type": "official_notice",
        "assertion": {
            "subject_type": "node",
            "subject_ref": "NODE-THLCH",
            "predicate": "berths_suspended",
            "object_value": "3-5",
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        },
        "event_start_at": "2026-08-10T06:00:00Z",
        "event_end_at": None,
        "event_date_precision": "datetime",
        "geography_ids": ["GEO-CTY-TH"],
        "country_ids": ["TH"],
        "node_ids": ["NODE-THLCH"],
        "chokepoint_ids": [],
        "lane_ids": [],
        "measurement": {"value": None, "value_status": "missing", "unit": None, "currency": None},
        "source_evidence_class": "official_notice",
        "corroboration_status": "not_assessed",
        "contradiction_status": "none",
        "confidence": "high",
        "extraction_method": "human_transcription",
        "review_status": "approved",
        "evidence_layer": "current_evidence",
        "primary_for_this_claim": True,
        "independence_group": "IG-PUB-PORT-AUTHORITY-OF-AURELIA",
        "attributed_to": None,
        "thailand_relevance_asserted": "asserted_by_source",
        "claim_scope": "node",
        "supersedes": [],
        "superseded_by": None,
        "quotation_used": {"used": False, "word_count": None, "permitted_by": None},
        "dataset": "current_publication",
        "known_limitations": [
            "STRUCTURAL EXAMPLE fixture. Never a report about real current conditions."
        ],
        "extraction_prompt_version": None,
        "extraction_model": None,
        "assertion_group_id": "AGRP-20260810-0001",
    }


def _synthetic_event_evidence() -> dict:
    return {
        "evidence_id": "EVD-20260810-9001",
        "event_id": "EVT-20260810-901",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "source_name": "Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
        "source_class": "official",
        "source_url": "https://notices.aurelia-port.example.invalid/2026/08/berth-suspension",
        "source_record_id": None,
        "claim": "STRUCTURAL EXAMPLE: berths 3-5 at the terminal are suspended.",
        "claim_type": "official_notice",
        "evidence_role": "confirming",
        "relation": "supports",
        "strength": "A",
        "scope_supported": "node",
        "event_date": "2026-08-10",
        "publication_date": "2026-08-10",
        "retrieval_status": "not_applicable",
        "retrieved_at": None,
        "revised_at": None,
        "evidence_origin": "human_reviewed_manual",
        "dataset": "current_publication",
        "content_sha256": "b" * 64,
        "content_hash_scope": "authored_claim_record",
        "strength_basis": "verified",
        "parser_version": "manual_notice_v1",
        "source_revision": None,
        "licence_status": "reviewed",
        "redistribution_status": "link_only",
        "raw_snapshot_path": None,
        "known_limitations": [],
        "collection_run_id": None,
        "manual_review_event_id": "MAN-20260810T070000Z-MANUAL_NOTICE_INTAKE",
    }


def _synthetic_event() -> dict:
    return {
        "event_id": "EVT-20260810-901",
        "canonical_event_id": "CEVT-" + "9" * 16,
        "title": "Berths 3-5 suspended for structural inspection (STRUCTURAL EXAMPLE)",
        "event_class": "direct_operational_event",
        "event_type": "port_or_terminal_closure",
        "lifecycle_status": "verified_event",
        "event_date": "2026-08-10",
        "event_end_date": None,
        "publication_date": "2026-08-10",
        "retrieval_date": "2026-08-10T07:00:00Z",
        "geography_ids": ["GEO-CTY-TH"],
        "country_ids": ["TH"],
        "node_ids": ["NODE-THLCH"],
        "chokepoint_ids": [],
        "modes": ["sea"],
        "operator_or_entity": "Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
        "lane_relevance": [],
        "thailand_relevance": "low",
        "thailand_relevance_basis": ["STRUCTURAL EXAMPLE basis."],
        "evidence_ids": ["EVD-20260810-9001"],
        "conflicting_evidence": [],
        "transmission_chain": {
            "external_driver": None,
            "operational_change": "Berths 3-5 suspended.",
            "logistics_mechanism": None,
            "observable_indicator": None,
            "outcome": None,
            "completeness": "incomplete",
            "missing_links": ["logistics_mechanism", "observable_indicator", "outcome"],
        },
        "event_severity": "moderate",
        "impact_assessments": _insufficient_impact_assessments(),
        "negative_operational_evidence": False,
        "known_limitations": [
            "STRUCTURAL EXAMPLE fixture. Never a report about real current conditions."
        ],
        "last_reviewed_at": "2026-08-10T07:00:00Z",
        "closure_basis": None,
        "publication_status": "Main dashboard",
        "human_review": {
            "required": False,
            "status": "not_required",
            "reviewer_record": None,
            "reviewed_at": None,
        },
        "clustering": {
            "cluster_id": None,
            "cluster_key": "0" * 64,
            "canonical_source_url": None,
            "title_normalized": "berths structural inspection",
            "merge_status": "unmatched",
        },
        "methodology_version": "0.8",
        "dataset": "current_publication",
        "active_as_of": "2026-08-10T06:00:00Z",
        "active_basis": "STRUCTURAL EXAMPLE: official notice states the suspension is in force.",
        "situation_state": "ACTIVE",
        "claim_ids": ["CLM-20260810-9001"],
        "evidence_grade": None,
        "verified_facts": ["CLM-20260810-9001"],
        "reported_claims": [],
        "analytical_inferences": [],
        "conflicting_claims": [],
    }


def test_synthetic_fixtures_are_schema_valid():
    assert schema_errors(_synthetic_document(), "document.schema.json") == []
    assert schema_errors(_synthetic_claim(), "claim.schema.json") == []
    assert schema_errors(_synthetic_event_evidence(), "event_evidence.schema.json") == []
    assert schema_errors(_synthetic_event(), "logistics_event.schema.json") == []


def test_confirmed_development_all_insufficient_areas_yields_elevated_watch(registry):
    """The rule the recommendation comment names as making the first real
    current-situation output reachable with zero review-package round trip
    (design part 2 Section 3.5 rule 3's second clause)."""
    document = _synthetic_document()
    claim = _synthetic_claim()
    evidence = _synthetic_event_evidence()
    event = _synthetic_event()

    situation = compute_mode_situation(
        mode="sea",
        geography_id="GEO-CTY-TH",
        country_code="TH",
        events=[event],
        evidence_by_id={evidence["evidence_id"]: evidence},
        claims_by_id={claim["claim_id"]: claim},
        documents_by_id={document["document_id"]: document},
        registry=registry,
        as_of=_NOW,
    )
    assert schema_errors(situation, "mode_situation.schema.json") == []
    assert situation["status"] == "elevated_watch"
    assert situation["status_basis"]
    assert situation["status_basis"][0]["rule_id"] == "R3"
    assert situation["excluded_event_ids"] == []
    assert situation["evidence_composition"]["independent_group_count"] == 1


def test_feeding_one_qualifying_record_changes_the_answer(registry):
    """The A-7 pattern: the negative path (no qualifying record) and the
    positive path (one qualifying record) must produce genuinely different
    answers -- proving the filter is real, not a literal."""
    empty = compute_mode_situation(
        mode="sea",
        geography_id="GEO-CTY-TH",
        country_code="TH",
        events=[],
        evidence_by_id={},
        claims_by_id={},
        documents_by_id={},
        registry=registry,
        as_of=_NOW,
    )
    document = _synthetic_document()
    claim = _synthetic_claim()
    evidence = _synthetic_event_evidence()
    event = _synthetic_event()
    populated = compute_mode_situation(
        mode="sea",
        geography_id="GEO-CTY-TH",
        country_code="TH",
        events=[event],
        evidence_by_id={evidence["evidence_id"]: evidence},
        claims_by_id={claim["claim_id"]: claim},
        documents_by_id={document["document_id"]: document},
        registry=registry,
        as_of=_NOW,
    )
    assert empty["status"] == "insufficient_current_evidence"
    assert populated["status"] != empty["status"]


def test_no_material_impact_detected_is_unreachable_without_coverage(registry):
    """A-8: even a fixture asserting negative operational evidence cannot
    reach 'no_material_impact_detected' while the coverage minimum (>=1
    qualifying Document from an enabled_for_public_claims, current_evidence
    source) is unmet."""
    situation = compute_mode_situation(
        mode="sea",
        geography_id="GEO-CTY-TH",
        country_code="TH",
        events=[],
        evidence_by_id={},
        claims_by_id={},
        documents_by_id={},
        registry=registry,
        as_of=_NOW,
    )
    assert situation["status"] != "no_material_impact_detected"
    assert situation["coverage_basis"]["qualifying_document_count"] == 0


def test_stale_contributor_excluded_from_mode_situation_not_treated_as_live(registry):
    """STRUCTURAL EXAMPLE (e): a claim past its source's max_stale_minutes
    is excluded from the mode_situation computation via Gate 0 condition 7,
    rather than treated as still-live evidence."""
    document = dict(_synthetic_document(), published_at="2026-05-01T06:00:00Z")
    claim = _synthetic_claim()
    evidence = _synthetic_event_evidence()
    event = _synthetic_event()

    situation = compute_mode_situation(
        mode="sea",
        geography_id="GEO-CTY-TH",
        country_code="TH",
        events=[event],
        evidence_by_id={evidence["evidence_id"]: evidence},
        claims_by_id={claim["claim_id"]: claim},
        documents_by_id={document["document_id"]: document},
        registry=registry,
        as_of=_NOW,
    )
    assert situation["status"] == "insufficient_current_evidence"
    assert situation["excluded_event_ids"] == [
        {
            "event_id": "EVT-20260810-901",
            "exclusion_reason": (
                "freshness_state 'stale' is not among the eligible set ['ageing', 'fresh'] "
                "(Gate 0 condition 7)"
            ),
        }
    ]


def test_data_cutoff_matches_build_analysis_and_build_dashboard():
    """The same pinned as-of time other current-publication builds use, so
    a mode_situation computed in the same build shares it."""
    assert DATA_CUTOFF == datetime(2026, 7, 24, tzinfo=UTC)
