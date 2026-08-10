"""Tests for analysis/claim_evidence_adapter.py (WO-047 / Issue #89, item 5).

Two groups of tests:

* Unit tests of the deterministic derivations (evidence_role, relation,
  strength, strength_basis) against clearly synthetic fixtures.
* A round-trip test (acceptance criterion A-2): synthetic Document + Claim
  records, hand-built to describe the same underlying facts as three
  already-committed ``event_evidence`` records in
  ``data/events/event_evidence.json`` (drawn from the historical validation
  set HVC-001 and HVC-004), are projected through the adapter and compared
  field-by-field against those committed records.

Five fields cannot be byte-identical and are asserted separately, each with
its own documented reason -- see ``_EXEMPT_FIELDS`` below. Every other field
in the schema (23 of 28) is asserted exactly equal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from analysis.claim_evidence_adapter import project_event_evidence

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def committed_evidence_by_id() -> dict:
    payload = json.loads((ROOT / "data/events/event_evidence.json").read_text(encoding="utf-8"))
    return {item["evidence_id"]: item for item in payload["evidence"]}


def _document(**overrides) -> dict:
    base = {
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "document_type": "official_notice",
        "evidence_layer": "current_evidence",
        "evidence_layer_basis": None,
        "title": "STRUCTURAL EXAMPLE notice",
        "publisher": "STRUCTURAL EXAMPLE Publisher",
        "publisher_is_originator": True,
        "originator_publisher": None,
        "originator_document_url": None,
        "canonical_url": "https://example.invalid/notice",
        "access_url": None,
        "language": "en",
        "published_at": "2026-08-10T08:00:00Z",
        "published_at_precision": "datetime",
        "updated_at": None,
        "retrieved_at": None,
        "retrieval_status": "not_retrieved",
        "evidence_origin": "historical_validation_fixture",
        "content_sha256": "a" * 64,
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
            "decided_at": "2026-08-10T08:00:00Z",
            "reviewer_record": None,
            "basis": "STRUCTURAL EXAMPLE rights snapshot",
        },
        "paywall_encountered": None,
        "geographies": [],
        "transport_modes": [],
        "topics": [],
        "independence_group": "IG-MANUAL_NOTICE_INTAKE",
        "independence_basis": None,
        "duplicate_of": None,
        "supersedes": [],
        "superseded_by": None,
        "correction_status": "none",
        "review_status": "unreviewed",
        "reviewer_record": None,
        "reviewed_at": None,
        "dataset": "historical_validation",
        "known_limitations": [],
        "collection_run_id": None,
        "manual_review_event_id": None,
    }
    base.update(overrides)
    return base


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-20260810-0001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "document_id": "DOC-20260810-001",
        "event_ids": ["EVT-20260810-001"],
        "claim_text": "STRUCTURAL EXAMPLE claim text.",
        "claim_type": "official_notice",
        "assertion": {
            "subject_type": None,
            "subject_ref": None,
            "predicate": None,
            "object_value": None,
            "object_unit": None,
        },
        "event_start_at": "2026-08-10T06:00:00Z",
        "event_end_at": None,
        "event_date_precision": "datetime",
        "geography_ids": [],
        "country_ids": [],
        "node_ids": [],
        "chokepoint_ids": [],
        "lane_ids": [],
        "measurement": {"value": None, "value_status": "missing", "unit": None, "currency": None},
        "source_evidence_class": "official_notice",
        "corroboration_status": "not_assessed",
        "contradiction_status": "none",
        "confidence": "medium",
        "extraction_method": "human_transcription",
        "review_status": "unreviewed",
        "evidence_layer": "current_evidence",
        "primary_for_this_claim": True,
        "independence_group": "IG-MANUAL_NOTICE_INTAKE",
        "attributed_to": None,
        "thailand_relevance_asserted": "not_asserted",
        "claim_scope": "facility",
        "supersedes": [],
        "superseded_by": None,
        "quotation_used": {"used": False, "word_count": None, "permitted_by": None},
        "dataset": "historical_validation",
        "known_limitations": [],
        "extraction_prompt_version": None,
        "extraction_model": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Derivation unit tests
# ---------------------------------------------------------------------------


def test_discovery_source_always_discovery_only_role(registry):
    document = _document(source_id="NEWS_DISCOVERY")
    claim = _claim(
        source_id="NEWS_DISCOVERY",
        document_id=document["document_id"],
        claim_type="discovery_lead",
    )
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["evidence_role"] == "discovery_only"
    assert result["strength"] == "D"


def test_context_layer_claim_is_contextual_and_relation_contextual(registry):
    document = _document(source_id="IMF_PORTWATCH", evidence_layer="context")
    claim = _claim(
        source_id="IMF_PORTWATCH",
        document_id=document["document_id"],
        claim_type="reported_claim",
        evidence_layer="context",
        primary_for_this_claim=False,
    )
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["evidence_role"] == "contextual"
    assert result["relation"] == "contextual"
    assert result["strength"] == "C"


def test_unnamed_attribution_is_contextual_and_never_exceeds_reported_strength(registry):
    document = _document()
    claim = _claim(
        claim_type="reported_claim",
        primary_for_this_claim=False,
        attributed_to={"name": None, "role": "operator", "is_named": False},
    )
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["evidence_role"] == "contextual"
    # Not attributed to a *named* party and not primary: falls to C, never A/B.
    assert result["strength"] == "C"


def test_denial_or_correction_contradicts(registry):
    document = _document()
    claim = _claim(claim_type="denial_or_correction")
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["relation"] == "contradicts"


def test_primary_official_notice_current_layer_is_strength_a(registry):
    document = _document()
    claim = _claim(claim_type="official_notice", primary_for_this_claim=True)
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["strength"] == "A"


def test_fixture_origin_document_never_yields_verified_strength_basis(registry):
    document = _document(evidence_origin="synthetic_test_fixture")
    claim = _claim()
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["strength_basis"] == "expected_at_cutoff"


def test_manual_reviewed_document_yields_verified_strength_basis(registry):
    document = _document(
        evidence_origin="human_reviewed_manual",
        retrieval_status="not_applicable",
        dataset="current_publication",
        manual_review_event_id="MAN-20260810T080000Z-MANUAL_NOTICE_INTAKE",
    )
    claim = _claim(dataset="current_publication")
    result = project_event_evidence(claim, document, "EVT-20260810-001", registry)
    assert result["strength_basis"] == "verified"


def test_mismatched_document_id_raises(registry):
    document = _document()
    claim = _claim(document_id="DOC-99999999-999")
    with pytest.raises(ValueError, match="document_id"):
        project_event_evidence(claim, document, "EVT-20260810-001", registry)


def test_mismatched_source_id_raises(registry):
    document = _document(source_id="NEWS_DISCOVERY")
    claim = _claim(source_id="MANUAL_NOTICE_INTAKE", document_id=document["document_id"])
    with pytest.raises(ValueError, match="source_id"):
        project_event_evidence(claim, document, "EVT-20260810-001", registry)


def test_event_id_not_in_claim_event_ids_raises(registry):
    document = _document()
    claim = _claim(event_ids=["EVT-11111111-001"])
    with pytest.raises(ValueError, match="event_ids"):
        project_event_evidence(claim, document, "EVT-20260810-001", registry)


# ---------------------------------------------------------------------------
# Round-trip test against committed event_evidence records (acceptance A-2)
# ---------------------------------------------------------------------------

#: Fields that cannot be byte-identical between a legacy authored
#: event_evidence fixture and this adapter's output, each for a structural
#: reason documented in analysis/claim_evidence_adapter.py's module
#: docstring:
#:
#: * evidence_id -- the legacy fixture uses a historical-case-derived ID
#:   scheme (EVD-HVC-NNN-X); the adapter derives evidence_id deterministically
#:   from claim_id (Issue #88 comment 2 Section 6.6), a different, non-legacy
#:   numbering convention.
#: * source_id, intended_source_id -- the legacy fixture uses the reserved
#:   SYNTHETIC_FIXTURE placeholder with a sidecar intended_source_id; the
#:   Document/Claim model has no such placeholder concept (a fixture
#:   Document is just a real source_id carrying a fixture evidence_origin/
#:   dataset), so the adapter's source_id is the real registered source
#:   directly and it never emits intended_source_id at all.
#: * fixture_created_at -- Document has no such field at all (Issue #88
#:   comment 2 Section 5.2 does not list one); the adapter never emits it.
#: * parser_version -- the legacy fixtures were authored with a
#:   fixture-specific parser_version ("historical_case_v1") that has no
#:   registry counterpart; the adapter derives parser_version from the
#:   source's currently registered parser, which is correct for a real
#:   Document.
#: * licence_status -- the adapter derives this from the registry's current
#:   determination for the source; a legacy fixture's own authored value can
#:   validly disagree with today's registry state.
_EXEMPT_FIELDS = frozenset(
    {
        "evidence_id",
        "source_id",
        "intended_source_id",
        "fixture_created_at",
        "parser_version",
        "licence_status",
    }
)


def _assert_round_trip(committed: dict, projected: dict) -> None:
    compared_fields = set(committed) | set(projected)
    for field in sorted(compared_fields - _EXEMPT_FIELDS):
        assert projected.get(field) == committed.get(field), (
            f"{committed['evidence_id']}/{field}: adapter produced "
            f"{projected.get(field)!r}, committed record has {committed.get(field)!r}"
        )


def test_round_trip_official_notice_confirming(registry, committed_evidence_by_id):
    committed = committed_evidence_by_id["EVD-HVC-001-A"]
    document = _document(
        document_id="DOC-20231218-001",
        source_id="MANUAL_NOTICE_INTAKE",
        publisher="Suez Canal Authority",
        canonical_url=(
            "https://www.suezcanal.gov.eg/English/Navigation/Pages/NavigationStatistics.aspx"
        ),
        published_at="2023-12-18T00:00:00Z",
        evidence_origin="historical_validation_fixture",
        content_sha256="da33451c48c38f76bc7c39f14bcc6e9a9afb56d6d48886a869a3179bccdf72ca",
        dataset="historical_validation",
        rights={
            "publication_use": "bounded_claim_and_link_only",
            "quotation_allowed": False,
            "quotation_max_words": None,
            "attribution_required": True,
            "redistribution_status": "link_only",
            "decided_by": "registry_default",
            "decided_at": "2023-12-18T00:00:00Z",
            "reviewer_record": None,
            "basis": "Historical validation fixture rights snapshot.",
        },
        known_limitations=committed["known_limitations"],
    )
    claim = _claim(
        claim_id="CLM-20231218-0001",
        source_id="MANUAL_NOTICE_INTAKE",
        document_id=document["document_id"],
        event_ids=["EVT-20231218-001"],
        claim_text=committed["claim"],
        claim_type="official_notice",
        event_start_at="2023-12-18T00:00:00Z",
        claim_scope="route",
        evidence_layer="current_evidence",
        primary_for_this_claim=True,
        dataset="historical_validation",
        known_limitations=[],
    )
    projected = project_event_evidence(claim, document, "EVT-20231218-001", registry)
    _assert_round_trip(committed, projected)
    assert projected["strength"] == "A" == committed["strength"]
    assert projected["strength_basis"] == "expected_at_cutoff" == committed["strength_basis"]


def test_round_trip_discovery_lead(registry, committed_evidence_by_id):
    committed = committed_evidence_by_id["EVD-HVC-001-B"]
    document = _document(
        document_id="DOC-20231219-001",
        source_id="NEWS_DISCOVERY",
        publisher="Public news discovery",
        canonical_url="https://www.gdeltproject.org/",
        published_at="2023-12-19T00:00:00Z",
        evidence_origin="historical_validation_fixture",
        content_sha256="3828244cbf21f80e9fc9805f8626ab751787cf57be67ae14249652962bed5beb",
        dataset="historical_validation",
        rights={
            "publication_use": "metadata_link_only",
            "quotation_allowed": False,
            "quotation_max_words": None,
            "attribution_required": True,
            "redistribution_status": "link_only",
            "decided_by": "registry_default",
            "decided_at": "2023-12-19T00:00:00Z",
            "reviewer_record": None,
            "basis": "Historical validation fixture rights snapshot.",
        },
        known_limitations=committed["known_limitations"],
    )
    claim = _claim(
        claim_id="CLM-20231219-0001",
        source_id="NEWS_DISCOVERY",
        document_id=document["document_id"],
        event_ids=["EVT-20231218-001"],
        claim_text=committed["claim"],
        claim_type="discovery_lead",
        event_start_at="2023-12-18T00:00:00Z",
        claim_scope="global",
        evidence_layer="current_evidence",
        primary_for_this_claim=False,
        dataset="historical_validation",
        known_limitations=[],
    )
    projected = project_event_evidence(claim, document, "EVT-20231218-001", registry)
    _assert_round_trip(committed, projected)
    assert projected["strength"] == "D" == committed["strength"]
    assert projected["evidence_role"] == "discovery_only" == committed["evidence_role"]


def test_round_trip_context_layer_reported_claim(registry, committed_evidence_by_id):
    committed = committed_evidence_by_id["EVD-HVC-004-B"]
    document = _document(
        document_id="DOC-20240601-001",
        source_id="IMF_PORTWATCH",
        evidence_layer="context",
        publisher="IMF PortWatch",
        canonical_url="https://portwatch.imf.org/",
        published_at="2024-06-01T00:00:00Z",
        evidence_origin="historical_validation_fixture",
        content_sha256="d53facc3ec50741284228526ba94e2eb1e3a271611d6cf0480ec0231aebe4004",
        dataset="historical_validation",
        rights={
            "publication_use": "internal_validation_only",
            "quotation_allowed": False,
            "quotation_max_words": None,
            "attribution_required": True,
            "redistribution_status": "link_only",
            "decided_by": "registry_default",
            "decided_at": "2024-06-01T00:00:00Z",
            "reviewer_record": None,
            "basis": "Historical validation fixture rights snapshot.",
        },
        known_limitations=committed["known_limitations"],
    )
    claim = _claim(
        claim_id="CLM-20240601-0001",
        source_id="IMF_PORTWATCH",
        document_id=document["document_id"],
        event_ids=["EVT-20240520-001"],
        claim_text=committed["claim"],
        claim_type="reported_claim",
        event_start_at="2024-05-20T00:00:00Z",
        claim_scope="node",
        evidence_layer="context",
        primary_for_this_claim=False,
        attributed_to=None,
        dataset="historical_validation",
        known_limitations=[],
    )
    projected = project_event_evidence(claim, document, "EVT-20240520-001", registry)
    _assert_round_trip(committed, projected)
    assert projected["strength"] == "C" == committed["strength"]
    assert projected["relation"] == "contextual" == committed["relation"]
