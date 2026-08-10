"""Failing-test proofs for every scripts/validate.py rule WO-047 / Issue #89
item 7 adds, implemented in analysis/claims.py.

Each rule below has a passing case and a failing case, so a reviewer who
deletes the rule from analysis/claims.py (or its wiring in
scripts/validate.py) sees the corresponding failing-case test start passing
when it should not -- i.e. these are the "confirm it fails without your
validation rule" proofs the Work Order asks for, expressed as ordinary
assertions against the pure functions rather than as a script diff.

This module also carries the 4 new historical-validation-style cases Issue
#89 item 9 asks for (labelled STRUCTURAL EXAMPLE, synthetic identifiers
only), each directly exercising one of the rules above rather than
retrofitting the existing data/validation/historical_cases.json harness
(which is built around logistics_event + event_evidence records, not
Document/Claim -- see the module docstring below the rule tests for why this
shape was chosen instead).
"""

from __future__ import annotations

from analysis.claims import (
    ai_date_invention_problems,
    claim_document_consistency_problems,
    corroboration_independence_problems,
    independence_confirmation_problems,
    l3_firewall_problems,
    regional_scope_thailand_relevance_problems,
    resolved_situation_state_problems,
)

# ---------------------------------------------------------------------------
# Minimal claim/document/event builders -- only the fields each test cares
# about are meaningful; everything else is a valid, inert default.
# ---------------------------------------------------------------------------


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-20260810-0001",
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "claim_type": "official_notice",
        "claim_scope": "facility",
        "evidence_layer": "current_evidence",
        "independence_group": "IG-MANUAL_NOTICE_INTAKE",
        "primary_for_this_claim": False,
        "corroboration_status": "not_assessed",
        "extraction_method": "human_transcription",
        "event_start_at": None,
        "event_date_precision": "unknown",
        "thailand_relevance_asserted": "not_asserted",
    }
    base.update(overrides)
    return base


def _document(**overrides) -> dict:
    base = {
        "document_id": "DOC-20260810-001",
        "source_id": "MANUAL_NOTICE_INTAKE",
        "evidence_layer": "current_evidence",
        "independence_group": "IG-MANUAL_NOTICE_INTAKE",
    }
    base.update(overrides)
    return base


def _event(**overrides) -> dict:
    base = {
        "event_id": "EVT-20260810-001",
        "verified_facts": [],
        "claim_ids": [],
        "situation_state": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Rule: L3 firewall
# ---------------------------------------------------------------------------


def test_l3_claim_in_verified_facts_fails():
    claims_by_id = {"CLM-20260810-0001": _claim(evidence_layer="structural_research")}
    event = _event(verified_facts=["CLM-20260810-0001"])
    problems = l3_firewall_problems([event], claims_by_id)
    assert any("verified_facts" in problem for problem in problems)


def test_current_evidence_claim_in_verified_facts_passes():
    claims_by_id = {"CLM-20260810-0001": _claim(evidence_layer="current_evidence")}
    event = _event(verified_facts=["CLM-20260810-0001"])
    assert l3_firewall_problems([event], claims_by_id) == []


def test_l3_only_claim_set_with_active_situation_state_fails():
    claims_by_id = {"CLM-20260810-0001": _claim(evidence_layer="structural_research")}
    event = _event(claim_ids=["CLM-20260810-0001"], situation_state="ACTIVE")
    problems = l3_firewall_problems([event], claims_by_id)
    assert any("L3-only" in problem for problem in problems)


def test_l3_only_claim_set_with_uncertain_situation_state_passes():
    claims_by_id = {"CLM-20260810-0001": _claim(evidence_layer="structural_research")}
    event = _event(claim_ids=["CLM-20260810-0001"], situation_state="UNCERTAIN")
    assert l3_firewall_problems([event], claims_by_id) == []


def test_l3_only_claim_set_with_no_situation_state_passes():
    claims_by_id = {"CLM-20260810-0001": _claim(evidence_layer="structural_research")}
    event = _event(claim_ids=["CLM-20260810-0001"], situation_state=None)
    assert l3_firewall_problems([event], claims_by_id) == []


def test_mixed_l1_and_l3_claim_set_with_active_state_passes():
    claims_by_id = {
        "CLM-20260810-0001": _claim(evidence_layer="structural_research"),
        "CLM-20260810-0002": _claim(
            claim_id="CLM-20260810-0002", evidence_layer="current_evidence"
        ),
    }
    event = _event(claim_ids=["CLM-20260810-0001", "CLM-20260810-0002"], situation_state="ACTIVE")
    assert l3_firewall_problems([event], claims_by_id) == []


# ---------------------------------------------------------------------------
# Rule: independence counting (officially_confirmed requires primary)
# ---------------------------------------------------------------------------


def test_officially_confirmed_without_primary_fails():
    claim = _claim(corroboration_status="officially_confirmed", primary_for_this_claim=False)
    problems = independence_confirmation_problems([claim])
    assert any("officially_confirmed" in problem for problem in problems)


def test_officially_confirmed_with_primary_passes():
    claim = _claim(corroboration_status="officially_confirmed", primary_for_this_claim=True)
    assert independence_confirmation_problems([claim]) == []


def test_uncorroborated_without_primary_passes():
    claim = _claim(corroboration_status="uncorroborated", primary_for_this_claim=False)
    assert independence_confirmation_problems([claim]) == []


# ---------------------------------------------------------------------------
# Rule: no AI-invented dates
# ---------------------------------------------------------------------------


def test_ai_claim_null_date_with_non_unknown_precision_fails():
    claim = _claim(
        extraction_method="ai_proposed_unreviewed",
        event_start_at=None,
        event_date_precision="date",
    )
    problems = ai_date_invention_problems([claim])
    assert any("null event_start_at" in problem for problem in problems)


def test_ai_claim_null_date_with_unknown_precision_passes():
    claim = _claim(
        extraction_method="ai_proposed_unreviewed",
        event_start_at=None,
        event_date_precision="unknown",
    )
    assert ai_date_invention_problems([claim]) == []


def test_ai_claim_dated_with_unknown_precision_fails():
    claim = _claim(
        extraction_method="ai_proposed_human_approved",
        event_start_at="2026-08-10T06:00:00Z",
        event_date_precision="unknown",
    )
    problems = ai_date_invention_problems([claim])
    assert any("states event_start_at" in problem for problem in problems)


def test_ai_claim_dated_with_real_precision_passes():
    claim = _claim(
        extraction_method="ai_proposed_human_approved",
        event_start_at="2026-08-10T06:00:00Z",
        event_date_precision="datetime",
    )
    assert ai_date_invention_problems([claim]) == []


def test_human_transcribed_claim_is_exempt_regardless_of_date_precision_mismatch():
    """The rule only applies to ai_* extraction methods -- a human transcriber
    stating a null date with a non-unknown precision is a different (data
    entry) problem, not the AI-invention problem this rule targets."""
    claim = _claim(
        extraction_method="human_transcription", event_start_at=None, event_date_precision="date"
    )
    assert ai_date_invention_problems([claim]) == []


# ---------------------------------------------------------------------------
# Rule: RESOLVED situation_state gating
# ---------------------------------------------------------------------------


def test_resolved_with_no_claim_ids_fails():
    event = _event(situation_state="RESOLVED", claim_ids=[])
    problems = resolved_situation_state_problems([event], {})
    assert any("claim_ids is empty" in problem for problem in problems)


def test_resolved_with_only_reported_claim_fails():
    claims_by_id = {"CLM-20260810-0001": _claim(claim_type="reported_claim")}
    event = _event(situation_state="RESOLVED", claim_ids=["CLM-20260810-0001"])
    problems = resolved_situation_state_problems([event], claims_by_id)
    assert any("claim_type in" in problem for problem in problems)


def test_resolved_with_official_notice_passes():
    claims_by_id = {"CLM-20260810-0001": _claim(claim_type="official_notice")}
    event = _event(situation_state="RESOLVED", claim_ids=["CLM-20260810-0001"])
    assert resolved_situation_state_problems([event], claims_by_id) == []


def test_resolved_with_denial_or_correction_passes():
    claims_by_id = {"CLM-20260810-0001": _claim(claim_type="denial_or_correction")}
    event = _event(situation_state="RESOLVED", claim_ids=["CLM-20260810-0001"])
    assert resolved_situation_state_problems([event], claims_by_id) == []


def test_active_situation_state_is_not_gated_by_this_rule():
    event = _event(situation_state="ACTIVE", claim_ids=[])
    assert resolved_situation_state_problems([event], {}) == []


def test_resolved_referencing_unknown_claim_fails():
    event = _event(situation_state="RESOLVED", claim_ids=["CLM-99999999-0001"])
    problems = resolved_situation_state_problems([event], {})
    assert any("do not resolve" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Rule: regional-scope claims cannot assert Thailand relevance unchallenged
# ---------------------------------------------------------------------------


def test_region_scope_asserted_by_source_fails():
    claim = _claim(claim_scope="region", thailand_relevance_asserted="asserted_by_source")
    problems = regional_scope_thailand_relevance_problems([claim])
    assert any("region" in problem for problem in problems)


def test_region_scope_inferred_by_platform_passes():
    claim = _claim(claim_scope="region", thailand_relevance_asserted="inferred_by_platform")
    assert regional_scope_thailand_relevance_problems([claim]) == []


def test_country_scope_asserted_by_source_passes():
    claim = _claim(claim_scope="country", thailand_relevance_asserted="asserted_by_source")
    assert regional_scope_thailand_relevance_problems([claim]) == []


# ---------------------------------------------------------------------------
# Rule: claim <-> document consistency (frozen evidence_layer/independence_group)
# ---------------------------------------------------------------------------


def test_claim_document_mismatch_fails():
    documents_by_id = {"DOC-20260810-001": _document(evidence_layer="context")}
    claim = _claim(document_id="DOC-20260810-001", evidence_layer="current_evidence")
    problems = claim_document_consistency_problems([claim], documents_by_id)
    assert any("evidence_layer" in problem for problem in problems)


def test_claim_document_match_passes():
    documents_by_id = {"DOC-20260810-001": _document(evidence_layer="current_evidence")}
    claim = _claim(document_id="DOC-20260810-001", evidence_layer="current_evidence")
    assert claim_document_consistency_problems([claim], documents_by_id) == []


def test_claim_with_unresolvable_document_fails():
    problems = claim_document_consistency_problems([_claim(document_id="DOC-99999999-999")], {})
    assert any("does not resolve" in problem for problem in problems)


def test_quotation_used_without_document_permission_fails():
    documents_by_id = {
        "DOC-20260810-001": _document(rights={"quotation_allowed": False}),
    }
    claim = _claim(
        document_id="DOC-20260810-001",
        quotation_used={"used": True, "word_count": 12, "permitted_by": "editorial guidance"},
    )
    problems = claim_document_consistency_problems([claim], documents_by_id)
    assert any("quotation_used.used is true" in problem for problem in problems)


def test_quotation_used_with_document_permission_passes():
    documents_by_id = {
        "DOC-20260810-001": _document(rights={"quotation_allowed": True}),
    }
    claim = _claim(
        document_id="DOC-20260810-001",
        quotation_used={"used": True, "word_count": 12, "permitted_by": "editorial guidance"},
    )
    assert claim_document_consistency_problems([claim], documents_by_id) == []


def test_quotation_not_used_passes_regardless_of_document_rights():
    documents_by_id = {
        "DOC-20260810-001": _document(rights={"quotation_allowed": False}),
    }
    claim = _claim(
        document_id="DOC-20260810-001",
        quotation_used={"used": False, "word_count": None, "permitted_by": None},
    )
    assert claim_document_consistency_problems([claim], documents_by_id) == []


# ---------------------------------------------------------------------------
# The 600-char claim-text cap (Issue #89 item 7): already schema-enforced by
# claim.schema.json's claim_text maxLength: 600, matching event_evidence.claim.
# No redundant validate.py rule is added; this test confirms the schema
# itself, rather than a script-level rule, is what catches an oversized claim.
# ---------------------------------------------------------------------------


def test_claim_text_over_600_chars_fails_schema_not_a_validate_rule():
    from analysis.contracts import schema_errors

    claim = _claim(claim_text="x" * 601)
    claim.setdefault(
        "assertion",
        {
            "subject_type": None,
            "subject_ref": None,
            "predicate": None,
            "object_value": None,
            "object_unit": None,
        },
    )
    claim.setdefault("event_ids", [])
    claim.setdefault("event_end_at", None)
    claim.setdefault("geography_ids", [])
    claim.setdefault("country_ids", [])
    claim.setdefault("node_ids", [])
    claim.setdefault("chokepoint_ids", [])
    claim.setdefault("lane_ids", [])
    claim.setdefault(
        "measurement", {"value": None, "value_status": "missing", "unit": None, "currency": None}
    )
    claim.setdefault("source_evidence_class", "official_notice")
    claim.setdefault("contradiction_status", "none")
    claim.setdefault("confidence", "low")
    claim.setdefault("review_status", "unreviewed")
    claim.setdefault("attributed_to", None)
    claim.setdefault("supersedes", [])
    claim.setdefault("superseded_by", None)
    claim.setdefault("quotation_used", {"used": False, "word_count": None, "permitted_by": None})
    claim.setdefault("dataset", "technical_demo")
    claim.setdefault("known_limitations", [])
    errors = schema_errors(claim, "claim.schema.json")
    assert any("claim_text" in error or "maxLength" in error for error in errors)


# ---------------------------------------------------------------------------
# Rights fail-closed composition (Issue #89 item 7): already proven directly
# in tests/test_claim_evidence_adapter.py's document-schema round trip and in
# the earlier ad-hoc schema check performed while authoring document.schema.json.
# Restated here as its own named test for a stable, discoverable reference.
# ---------------------------------------------------------------------------


def test_document_with_no_rights_block_fails_schema_validation():
    from analysis.contracts import schema_errors

    document = _document()
    document.update(
        {
            "document_type": "official_notice",
            "title": "x",
            "publisher": "y",
            "publisher_is_originator": True,
            "published_at": None,
            "published_at_precision": "unknown",
            "retrieved_at": None,
            "retrieval_status": "not_applicable",
            "evidence_origin": "human_reviewed_manual",
            "content_sha256": "a" * 64,
            "content_hash_scope": "authored_claim_record",
            "stored_content": "none",
            "stored_content_location": None,
            "geographies": [],
            "transport_modes": [],
            "topics": [],
            "correction_status": "none",
            "review_status": "unreviewed",
            "dataset": "technical_demo",
            "known_limitations": [],
            "manual_review_event_id": "MAN-20260810T090000Z-MANUAL_NOTICE_INTAKE",
        }
    )
    # 'rights' deliberately omitted.
    errors = schema_errors(document, "document.schema.json")
    assert any("rights" in error for error in errors)


def test_document_with_rights_missing_publication_use_fails_schema_validation():
    from analysis.contracts import schema_errors

    document = _document()
    document.update(
        {
            "document_type": "official_notice",
            "title": "x",
            "publisher": "y",
            "publisher_is_originator": True,
            "published_at": None,
            "published_at_precision": "unknown",
            "retrieved_at": None,
            "retrieval_status": "not_applicable",
            "evidence_origin": "human_reviewed_manual",
            "content_sha256": "a" * 64,
            "content_hash_scope": "authored_claim_record",
            "stored_content": "none",
            "stored_content_location": None,
            "rights": {
                # publication_use deliberately omitted
                "quotation_allowed": False,
                "quotation_max_words": None,
                "attribution_required": True,
                "redistribution_status": "unknown",
                "decided_by": "registry_default",
                "decided_at": "2026-08-10T09:00:00Z",
                "reviewer_record": None,
                "basis": "x",
            },
            "geographies": [],
            "transport_modes": [],
            "topics": [],
            "correction_status": "none",
            "review_status": "unreviewed",
            "dataset": "technical_demo",
            "known_limitations": [],
            "manual_review_event_id": "MAN-20260810T090000Z-MANUAL_NOTICE_INTAKE",
        }
    )
    errors = schema_errors(document, "document.schema.json")
    assert any("publication_use" in error for error in errors)


# ---------------------------------------------------------------------------
# Issue #89 item 9: 4 labelled historical-validation-style cases.
#
# These are expressed as ordinary pytest cases against analysis/claims.py and
# schemas/{document,claim}.schema.json rather than as new entries in
# data/validation/historical_cases.json / scripts/run_historical_validation.py:
# that harness's case shape (case_id, event, expectations keyed to
# logistics_event/event_evidence fields such as expected_impact_disposition)
# has no place to express a Document/Claim-level expectation like "N
# documents collapse to 1 independence group" or "an L3 claim set caps the
# grade". Retrofitting it would either stretch its schema past what it
# actually models, or add Document/Claim-shaped fields to a case format
# whose entire purpose is comparing built logistics_event/event_evidence
# records against declared expectations. Each case below is still a
# concrete, deterministic, offline-runnable proof; each is clearly labelled
# STRUCTURAL EXAMPLE and uses only synthetic identifiers, matching the
# convention in Issue #88's Section 19 structural example.
# ---------------------------------------------------------------------------


def _synthetic_document(
    document_id: str,
    *,
    publisher_is_originator: bool,
    independence_group: str,
    canonical_url: str,
    originator_document_url: str | None = None,
) -> dict:
    return {
        "document_id": document_id,
        "source_id": "MANUAL_NOTICE_INTAKE",
        "publisher_is_originator": publisher_is_originator,
        "independence_group": independence_group,
        "evidence_layer": "current_evidence",
        "canonical_url": canonical_url,
        "originator_document_url": originator_document_url,
    }


def test_case_syndication_cluster_does_not_corroborate_independently():
    """STRUCTURAL EXAMPLE (a): two claims from documents where one has
    publisher_is_originator: false pointing at the other must NOT produce
    corroborated_independent -- it must be corroborated_dependent (Issue #88
    comment 2 Section 6.5: "corroborated_dependent: ... all trace to one
    originator_document_url. This is not corroboration"). This exercises
    corroboration_independence_problems directly: a syndication pair
    wrongly marked corroborated_independent is flagged; the honest
    corroborated_dependent marking is not.
    """
    doc_a = _synthetic_document(
        "DOC-SYNTH-001",
        publisher_is_originator=True,
        independence_group="SYNTH-IG-GSW",
        canonical_url="https://example.invalid/synth/gsw-original",
    )
    doc_b = _synthetic_document(
        "DOC-SYNTH-002",
        publisher_is_originator=False,
        independence_group="SYNTH-IG-AGGREGATOR",
        canonical_url="https://example.invalid/synth/gsw-syndicated",
        originator_document_url="https://example.invalid/synth/gsw-original",
    )
    documents_by_id = {"DOC-SYNTH-001": doc_a, "DOC-SYNTH-002": doc_b}

    claim_a = _claim(
        claim_id="CLM-SYNTH-0001",
        document_id="DOC-SYNTH-001",
        independence_group="SYNTH-IG-GSW",
        event_ids=["EVT-SYNTH-003"],
        corroboration_status="uncorroborated",
    )
    # Misuse: doc_b's independence_group differs from doc_a's, but doc_b is a
    # syndication of doc_a (its originator_document_url IS doc_a's
    # canonical_url) -- a distinct independence_group alone is not enough;
    # the syndication link must also be checked, or a source that merely
    # republishes under a different byline would wrongly count as independent.
    claim_b_misused = _claim(
        claim_id="CLM-SYNTH-0002",
        document_id="DOC-SYNTH-002",
        independence_group="SYNTH-IG-AGGREGATOR",
        event_ids=["EVT-SYNTH-003"],
        corroboration_status="corroborated_independent",
    )
    problems = corroboration_independence_problems([claim_a, claim_b_misused], documents_by_id)
    assert any("CLM-SYNTH-0002" in problem for problem in problems)

    # The honest marking for the same pair raises no problem.
    claim_b_honest = _claim(
        claim_id="CLM-SYNTH-0002",
        document_id="DOC-SYNTH-002",
        independence_group="SYNTH-IG-AGGREGATOR",
        event_ids=["EVT-SYNTH-003"],
        corroboration_status="corroborated_dependent",
    )
    assert corroboration_independence_problems([claim_a, claim_b_honest], documents_by_id) == []


def test_genuinely_independent_corroboration_passes():
    """Two claims from distinct independence_groups, neither a syndication
    of the other, sharing an event_id: corroborated_independent is honest
    and raises no problem."""
    doc_a = _synthetic_document(
        "DOC-SYNTH-010",
        publisher_is_originator=True,
        independence_group="SYNTH-IG-PORT-AUTHORITY",
        canonical_url="https://example.invalid/synth/notice-a",
    )
    doc_b = _synthetic_document(
        "DOC-SYNTH-011",
        publisher_is_originator=True,
        independence_group="SYNTH-IG-SHIPPING-NEWS",
        canonical_url="https://example.invalid/synth/notice-b",
    )
    documents_by_id = {"DOC-SYNTH-010": doc_a, "DOC-SYNTH-011": doc_b}
    claim_a = _claim(
        claim_id="CLM-SYNTH-0010",
        document_id="DOC-SYNTH-010",
        independence_group="SYNTH-IG-PORT-AUTHORITY",
        event_ids=["EVT-SYNTH-004"],
        corroboration_status="corroborated_independent",
    )
    claim_b = _claim(
        claim_id="CLM-SYNTH-0011",
        document_id="DOC-SYNTH-011",
        independence_group="SYNTH-IG-SHIPPING-NEWS",
        event_ids=["EVT-SYNTH-004"],
        corroboration_status="corroborated_independent",
    )
    assert corroboration_independence_problems([claim_a, claim_b], documents_by_id) == []


def test_corroborated_independent_with_no_event_ids_fails():
    claim = _claim(corroboration_status="corroborated_independent", event_ids=[])
    problems = corroboration_independence_problems([claim], {})
    assert any("no event_ids" in problem for problem in problems)


def test_corroborated_independent_with_no_cluster_fails():
    """A claim naming an event_id but no other claim sharing it: nothing
    actually corroborates it."""
    claim = _claim(corroboration_status="corroborated_independent", event_ids=["EVT-SYNTH-005"])
    problems = corroboration_independence_problems([claim], {})
    assert any("CLM-20260810-0001" in problem for problem in problems)


def test_case_unresolved_contradiction_blocks_resolved_state():
    """STRUCTURAL EXAMPLE (b): a claim with an unresolved contradiction does
    not let its event reach a settled/confirmed state -- concretely, an
    event cannot be situation_state RESOLVED on the strength of a claim
    whose contradiction_status is 'unresolved', even if that claim's
    claim_type otherwise qualifies (official_notice)."""
    claim = _claim(
        claim_id="CLM-SYNTH-0003",
        claim_type="official_notice",
        contradiction_status="unresolved",
    )
    event = _event(
        event_id="EVT-SYNTH-001", situation_state="RESOLVED", claim_ids=["CLM-SYNTH-0003"]
    )
    problems = resolved_situation_state_problems([event], {"CLM-SYNTH-0003": claim})
    assert any("contradiction_status 'unresolved'" in problem for problem in problems)

    # The same claim, once its contradiction is resolved, does qualify.
    resolved_claim = dict(claim, contradiction_status="resolved_by_primary_source")
    assert resolved_situation_state_problems([event], {"CLM-SYNTH-0003": resolved_claim}) == []


def test_case_l3_only_claim_set_cannot_support_active_situation_state():
    """STRUCTURAL EXAMPLE (c): an L3-only claim set cannot produce any
    evidence_grade above ANALYTICAL_INFERENCE-equivalent and cannot support
    an active situation_state -- the L3 firewall's second rule, directly."""
    claims_by_id = {
        "CLM-SYNTH-0004": _claim(
            claim_id="CLM-SYNTH-0004",
            claim_type="structural_finding",
            evidence_layer="structural_research",
        )
    }
    event = _event(event_id="EVT-SYNTH-002", claim_ids=["CLM-SYNTH-0004"], situation_state="ACTIVE")
    problems = l3_firewall_problems([event], claims_by_id)
    assert problems, "an L3-only claim set must not be allowed to carry situation_state ACTIVE"


def test_case_region_scope_claim_does_not_unlock_asserted_thailand_relevance():
    """STRUCTURAL EXAMPLE (d): a claim with claim_scope: region does not, by
    itself, allow thailand_relevance_asserted: asserted_by_source to stand
    unchallenged."""
    claim = _claim(
        claim_id="CLM-SYNTH-0005",
        claim_scope="region",
        thailand_relevance_asserted="asserted_by_source",
    )
    problems = regional_scope_thailand_relevance_problems([claim])
    assert problems, (
        "a region-scope claim must not be allowed asserted_by_source Thailand relevance"
    )
