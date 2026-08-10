"""3 new historical-validation-style cases (WO-049 / Issue #92 item 13),
per the recommendation comment. Expressed as ordinary pytest cases against
analysis/grading.py, analysis/situations.py and scripts/manual_intake.py
rather than as new entries in data/validation/historical_cases.json /
scripts/run_historical_validation.py -- the same documented reason WO-047
gave for its own 4 STRUCTURAL EXAMPLE cases in
tests/test_validate_claim_rules.py: that harness's case shape (case_id,
event, expectations keyed to logistics_event/event_evidence fields) has no
place to express a Document/Claim/mode_situation-level expectation like "two
Documents from one real publisher collapse to one independence group" or "a
mode_situation status changes when a contributor goes stale". Each case
below is still a concrete, deterministic, offline-runnable proof; each is
clearly labelled STRUCTURAL EXAMPLE and uses only synthetic identifiers,
matching the convention in Issue #88's Section 19 structural example.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from analysis.grading import compute_evidence_grade
from analysis.situations import compute_mode_situation
from scripts.manual_intake import build_manual_intake
from tests.test_build_situations import (
    _synthetic_claim,
    _synthetic_document,
    _synthetic_event,
    _synthetic_event_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))


def test_case_a_syndicated_pair_yields_one_independence_group(registry):
    """STRUCTURAL EXAMPLE (a): two Documents from the SAME real underlying
    publisher, transcribed through the same conduit under two differently
    worded display names (a syndication-style pair, not two distinct
    origins), must yield ONE independence group when the operator supplies
    the same underlying_publisher_identity_key for both -- the B-1 fix
    (WO-049 / Issue #92 item 1), proven end to end through
    scripts/manual_intake.py rather than by hand-constructing Document
    dicts."""
    base_kwargs = dict(
        source_id="MANUAL_NOTICE_INTAKE",
        document_type="official_notice",
        published_at="2026-08-10T08:00:00Z",
        published_at_precision="datetime",
        reviewer_record="Jane Reviewer (STRUCTURAL EXAMPLE)",
        reviewed_at="2026-08-10T09:00:00Z",
        manual_review_event_id="MAN-20260810T090000Z-MANUAL_NOTICE_INTAKE",
        claims=[
            {
                "claim_text": "STRUCTURAL EXAMPLE: berths 3-5 suspended.",
                "claim_type": "official_notice",
                "claim_scope": "facility",
                "primary_for_this_claim": True,
            }
        ],
        registry=registry,
        underlying_publisher_identity_key="PORT-AUTHORITY-OF-AURELIA",
    )
    document_a, _claims_a = build_manual_intake(
        **{
            **base_kwargs,
            "title": "STRUCTURAL EXAMPLE notice, official channel",
            "publisher": "Port Authority of Aurelia",
            "canonical_url": "https://notices.aurelia-port.example.invalid/2026/08/001",
            "document_id": "DOC-20260810-301",
        }
    )
    document_b, _claims_b = build_manual_intake(
        **{
            **base_kwargs,
            "title": "STRUCTURAL EXAMPLE notice, press-office mirror",
            "publisher": "PAA Press Office (STRUCTURAL EXAMPLE)",
            "canonical_url": "https://press.aurelia-port.example.invalid/2026/08/001",
            "document_id": "DOC-20260810-302",
        }
    )
    assert document_a["independence_group"] == document_b["independence_group"]
    assert document_a["independence_group"] != "IG-MANUAL_NOTICE_INTAKE"


def test_case_b_unresolved_status_change_contradiction_caps_grade_and_mixes_evidence(registry):
    """STRUCTURAL EXAMPLE (b): an unresolved status_change-type contradiction
    caps the Development's evidence_grade at REPORTED (never CONFIRMED or
    CORROBORATED, design part 1 Section 2.7) and produces mode_situation's
    'mixed_evidence' status (design part 2 Section 3.5 rule 2) rather than a
    confident verdict on either side."""
    document = _synthetic_document()
    claim = _synthetic_claim()
    evidence = _synthetic_event_evidence()
    event = _synthetic_event()
    event["situation_state"] = "UNCERTAIN"
    event["conflicting_evidence"] = [
        {
            "description": (
                "STRUCTURAL EXAMPLE: a news report says berths have resumed; the authority's "
                "notice states the suspension remains in force."
            ),
            "evidence_ids": ["EVD-20260810-9001", "EVD-SYNTH-9002"],
            "resolution_status": "unresolved",
            "contradiction_type": "status_change",
            "claim_ids_side_a": ["CLM-20260810-9001"],
            "claim_ids_side_b": ["CLM-SYNTH-9002"],
        }
    ]

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
    assert situation["status"] == "mixed_evidence"
    assert situation["status_basis"]
    assert situation["status_basis"][0]["rule_id"] == "R2"
    assert situation["excluded_event_ids"] == []

    # The contradiction excludes the sole primary claim from the CONFIRMED
    # candidate set outright (compute_evidence_grade's own "confirming" list
    # comprehension filters on `not capping_contradiction`), so the grade
    # lands on REPORTED via the REPORTED entry rule rather than via the
    # explicit post-hoc cap -- either way, CONFIRMED/CORROBORATED are
    # unreachable while the contradiction stands, which is what this proves.
    grade, grade_basis = compute_evidence_grade(
        event,
        {claim["claim_id"]: claim},
        {document["document_id"]: document},
        registry,
        now=_NOW,
    )
    assert grade == "REPORTED"
    assert grade_basis


def test_case_c_stale_contributor_excluded_not_treated_as_resolved(registry):
    """STRUCTURAL EXAMPLE (c): a claim past its source's max_stale_minutes is
    excluded from a mode_situation computation via Gate 0 condition 7 --
    it is neither treated as still-live evidence, nor does its staleness
    get mistaken for the Development having been resolved (situation_state
    stays ACTIVE on the underlying record; mode_situation simply does not
    count it)."""
    # MANUAL_NOTICE_INTAKE's max_stale_minutes is 43200 (30d), so the
    # freshness clock's stale/expired boundary is 4x that -- 120d. This
    # document is ~131d old as of _NOW, past that boundary, so it is
    # 'expired', not merely 'stale' (either state is excluded by Gate 0
    # condition 7 the same way; the label just needs to say the right one).
    document = dict(_synthetic_document(), published_at="2026-04-01T06:00:00Z")  # ~131d, expired
    claim = _synthetic_claim()
    evidence = _synthetic_event_evidence()
    event = _synthetic_event()
    assert event["situation_state"] == "ACTIVE"  # unchanged by staleness

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
    assert situation["contributing_event_ids"] == []
    assert len(situation["excluded_event_ids"]) == 1
    assert "Gate 0 condition 7" in situation["excluded_event_ids"][0]["exclusion_reason"]
    # The event's own record is untouched -- exclusion is a mode_situation-level
    # filtering decision, never a rewrite of the underlying Development.
    assert event["situation_state"] == "ACTIVE"
