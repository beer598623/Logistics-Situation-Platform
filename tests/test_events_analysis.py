"""Event clustering, transmission chains and the evidence rules."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from analysis.events import (
    TITLE_SIMILARITY_THRESHOLD,
    active_events,
    canonicalize_url,
    cluster_id_from_key,
    cluster_key,
    evaluate_transmission_chain,
    event_domain_direction,
    event_qualifies_for_current_publication,
    external_driver_admission,
    has_negative_operational_evidence,
    has_non_discovery_evidence,
    is_active_at,
    normalize_title,
    should_cluster,
    title_similarity,
    validate_event,
)

IMPACT_AREAS = (
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


def impacts(**overrides):
    base = {
        "status": "insufficient_evidence",
        "severity": "none",
        "relevance": "none",
        "geographic_scope": "test",
        "time_horizon": "unknown",
        "expected_duration": "unknown",
        "transmission_mechanism": [],
        "evidence_ids": [],
        "evidence_strength": "C",
        "confidence": "low",
        "known_limitations": [],
    }
    return [{"area": area, **base, **overrides.get(area, {})} for area in IMPACT_AREAS]


def make_event(**overrides):
    chain = {
        "external_driver": None,
        "operational_change": "A terminal closed.",
        "logistics_mechanism": "Closure removes the terminal from the rotation.",
        "observable_indicator": "Port authority notice.",
        "outcome": "Observed suspension.",
    }
    chain.update(overrides.pop("transmission_chain", {}))
    completeness, missing = evaluate_transmission_chain(
        overrides.get("event_class", "direct_operational_event"), chain
    )
    event = {
        "event_id": "EVT-20260101-001",
        "title": "Terminal closure at Example Port",
        "event_class": "direct_operational_event",
        "event_type": "port_or_terminal_closure",
        "lifecycle_status": "verified_event",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-CTY-SG"],
        "country_ids": ["SG"],
        "operator_or_entity": "Example Port",
        "modes": ["sea"],
        "thailand_relevance": "none_established",
        "thailand_relevance_basis": [],
        "evidence_ids": ["EVD-TEST-001"],
        "conflicting_evidence": [],
        "transmission_chain": {**chain, "completeness": completeness, "missing_links": missing},
        "impact_assessments": impacts(**overrides.pop("impacts", {})),
        "negative_operational_evidence": False,
        "human_review": {
            "required": False,
            "status": "not_required",
            "reviewer_record": None,
            "reviewed_at": None,
        },
        "publication_status": "Watchlist",
        "closure_basis": None,
    }
    event.update(overrides)
    event["clustering"] = {
        "cluster_key": cluster_key(event),
        "cluster_id": None,
        "canonical_source_url": None,
        "title_normalized": event["title"].lower(),
        "merge_status": "unmatched",
    }
    return event


def evidence(**overrides):
    item = {
        "evidence_id": "EVD-TEST-001",
        "claim_type": "official_notice",
        "evidence_role": "confirming",
        "strength": "A",
    }
    item.update(overrides)
    return {item["evidence_id"]: item}


# ---------------------------------------------------------------------------
# URL canonicalization
# ---------------------------------------------------------------------------


def test_canonicalization_strips_tracking_parameters_and_trailing_slash():
    assert (
        canonicalize_url("HTTPS://WWW.Example.com:443/notice/1/?utm_source=rss&id=7#frag")
        == "https://example.com/notice/1?id=7"
    )


def test_canonicalization_strips_url_userinfo():
    assert "secret" not in canonicalize_url("https://user:secret@example.com/a")


def test_a_non_absolute_url_canonicalizes_to_none_rather_than_a_partial_string():
    assert canonicalize_url("/notice/1") is None
    assert canonicalize_url("") is None
    assert canonicalize_url(None) is None


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def test_same_source_record_clusters():
    left = {"source_id": "PAT_NOTICE", "source_record_id": "N-1"}
    right = {"source_id": "PAT_NOTICE", "source_record_id": "N-1"}
    decision = should_cluster(left, right)
    assert decision.should_merge and decision.rule == "same_source_record"


def test_same_canonical_url_clusters_across_tracking_parameters():
    left = {"canonical_source_url": "https://example.com/n/1?utm_source=a"}
    right = {"canonical_source_url": "https://www.example.com/n/1/"}
    assert should_cluster(left, right).rule == "same_canonical_url"


def test_same_country_alone_does_not_cluster():
    """Two unrelated events in one country must not merge."""
    left = {
        "event_type": "port_restriction",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-CTY-SG"],
        "title": "Berth 3 draft restriction during survey work",
    }
    right = {
        "event_type": "strike",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-CTY-SG"],
        "title": "Tug operators announce industrial action",
    }
    decision = should_cluster(left, right)
    assert not decision.should_merge
    assert decision.rule == "insufficient_common_attributes"


def test_same_conflict_alone_does_not_cluster():
    left = {
        "event_type": "war_or_security",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-RGN-MEGULF"],
        "title": "Vessel diverted after security incident near the strait",
    }
    right = {
        "event_type": "war_or_security",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-RGN-MEGULF"],
        "title": "Sanctions package announced covering refined product exports",
    }
    assert not should_cluster(left, right).should_merge


def test_same_type_date_geography_and_operator_clusters():
    common = {
        "event_type": "port_restriction",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-CTY-SG"],
        "operator_or_entity": "Example Port",
    }
    assert (
        should_cluster(
            {**common, "title": "Draft restriction announced"},
            {**common, "title": "Port limits vessel draft"},
        ).rule
        == "same_entity_type_date_geography"
    )


def test_high_title_similarity_with_matching_type_date_geography_clusters():
    common = {
        "event_type": "canal_restriction",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-WTR-PANAMA"],
    }
    decision = should_cluster(
        {**common, "title": "Canal authority reduces daily transit slots"},
        {**common, "title": "Authority reduces daily canal transit slots"},
    )
    assert decision.should_merge
    assert decision.rule == "title_similarity_with_type_date_geography"


def test_low_title_similarity_does_not_cluster():
    common = {
        "event_type": "canal_restriction",
        "event_date": "2026-01-01",
        "geography_ids": ["GEO-WTR-PANAMA"],
    }
    decision = should_cluster(
        {**common, "title": "Canal authority reduces daily transit slots"},
        {**common, "title": "Tolls revised for neopanamax vessels"},
    )
    assert not decision.should_merge


def test_title_similarity_is_deterministic_and_bounded():
    assert title_similarity("Port closure at A", "Port closure at A") == 1.0
    assert title_similarity("", "anything") == 0.0
    assert 0.0 <= title_similarity("a b c", "b c d") <= 1.0


def test_normalize_title_removes_generic_words_and_punctuation():
    assert normalize_title("The Port of A — UPDATE: closure!") == "port closure"


def test_cluster_key_is_stable_and_ids_derive_from_it():
    event = make_event()
    key = cluster_key(event)
    assert key == cluster_key(copy.deepcopy(event))
    assert cluster_id_from_key(key) == f"CLU-{key[:16]}"


def test_cluster_key_changes_when_a_controlled_field_changes():
    event = make_event()
    other = make_event(event_date="2026-02-02")
    assert cluster_key(event) != cluster_key(other)


# ---------------------------------------------------------------------------
# Transmission chains
# ---------------------------------------------------------------------------


def test_a_direct_operational_event_needs_no_upstream_external_driver():
    completeness, missing = evaluate_transmission_chain(
        "direct_operational_event",
        {
            "external_driver": None,
            "operational_change": "x",
            "logistics_mechanism": "y",
            "observable_indicator": "z",
            "outcome": "w",
        },
    )
    assert completeness == "complete"
    assert missing == []


def test_an_external_driver_needs_every_link():
    completeness, missing = evaluate_transmission_chain(
        "external_driver",
        {
            "external_driver": "x",
            "operational_change": None,
            "logistics_mechanism": None,
            "observable_indicator": None,
            "outcome": None,
        },
    )
    assert completeness == "incomplete"
    assert missing == [
        "operational_change",
        "logistics_mechanism",
        "observable_indicator",
        "outcome",
    ]


def test_a_discovery_lead_has_no_chain_rather_than_an_incomplete_one():
    completeness, missing = evaluate_transmission_chain("discovery_lead", {})
    assert completeness == "not_applicable"
    assert missing == []


def test_unknown_event_class_raises():
    with pytest.raises(ValueError, match="Unknown event class"):
        evaluate_transmission_chain("something_else", {})


def test_an_incomplete_external_driver_is_contextual_not_excluded():
    event = make_event(
        event_class="external_driver",
        transmission_chain={"external_driver": "x", "operational_change": None},
    )
    admitted, reason = external_driver_admission(event)
    assert not admitted
    assert "remains contextual" in reason


def test_a_complete_external_driver_is_admitted():
    event = make_event(
        event_class="external_driver",
        transmission_chain={"external_driver": "x"},
    )
    admitted, _ = external_driver_admission(event)
    assert admitted


# ---------------------------------------------------------------------------
# Evidence rules
# ---------------------------------------------------------------------------


def test_discovery_only_evidence_cannot_support_a_material_impact():
    event = make_event(
        impacts={
            "transport": {
                "status": "observed",
                "severity": "moderate",
                "transmission_mechanism": ["mechanism"],
            }
        }
    )
    problems = validate_event(event, evidence(evidence_role="discovery_only"))
    assert any("discovery source may detect a lead" in problem for problem in problems)


def test_a_material_impact_backed_by_confirming_evidence_passes():
    event = make_event(
        impacts={
            "transport": {
                "status": "observed",
                "severity": "moderate",
                "transmission_mechanism": ["mechanism"],
            }
        }
    )
    assert validate_event(event, evidence()) == []


def test_has_non_discovery_evidence():
    assert has_non_discovery_evidence([{"evidence_role": "confirming"}])
    assert not has_non_discovery_evidence([{"evidence_role": "discovery_only"}])


def test_unknown_evidence_reference_is_rejected():
    event = make_event(evidence_ids=["EVD-DOES-NOT-EXIST"])
    event["clustering"]["cluster_key"] = cluster_key(event)
    problems = validate_event(event, evidence())
    assert any("unknown evidence IDs" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Impact rules
# ---------------------------------------------------------------------------


def test_a_material_impact_without_a_transmission_mechanism_is_rejected():
    event = make_event(impacts={"cost": {"status": "potential", "severity": "moderate"}})
    problems = validate_event(event, evidence())
    assert any("no transmission mechanism" in problem for problem in problems)


def test_no_material_requires_negative_operational_evidence():
    event = make_event(impacts={"cost": {"status": "no_material"}})
    problems = validate_event(event, evidence())
    assert any("negative operational evidence" in problem for problem in problems)


def test_no_material_is_accepted_when_negative_evidence_exists():
    event = make_event(
        impacts={"cost": {"status": "no_material"}}, negative_operational_evidence=True
    )
    assert validate_event(event, evidence()) == []


def test_high_severity_requires_primary_grade_evidence():
    event = make_event(
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "high",
                "evidence_strength": "C",
                "transmission_mechanism": ["mechanism"],
            }
        },
        human_review={
            "required": True,
            "status": "pending",
            "reviewer_record": None,
            "reviewed_at": None,
        },
    )
    problems = validate_event(event, evidence())
    assert any("primary-grade evidence" in problem for problem in problems)


def test_high_severity_requires_a_human_review_flag():
    event = make_event(
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "high",
                "evidence_strength": "A",
                "transmission_mechanism": ["mechanism"],
            }
        }
    )
    problems = validate_event(event, evidence())
    assert any("human_review.required to be true" in problem for problem in problems)


def test_high_severity_cannot_reach_the_main_dashboard_without_approval():
    event = make_event(
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "high",
                "evidence_strength": "A",
                "transmission_mechanism": ["mechanism"],
            }
        },
        human_review={
            "required": True,
            "status": "pending",
            "reviewer_record": None,
            "reviewed_at": None,
        },
        publication_status="Main dashboard",
    )
    problems = validate_event(event, evidence())
    assert any("without an approved human-review record" in problem for problem in problems)


def test_an_incomplete_external_driver_cannot_claim_a_material_impact():
    event = make_event(
        event_class="external_driver",
        transmission_chain={"external_driver": "x", "operational_change": None},
        impacts={
            "cost": {
                "status": "potential",
                "severity": "moderate",
                "transmission_mechanism": ["mechanism"],
            }
        },
    )
    problems = validate_event(event, evidence())
    assert any("transmission chain is" in problem for problem in problems)


def test_a_closed_event_must_record_a_closure_basis():
    event = make_event(lifecycle_status="closed")
    problems = validate_event(event, evidence())
    assert any("closure basis" in problem for problem in problems)


def test_asserted_thailand_relevance_requires_a_basis():
    event = make_event(thailand_relevance="medium")
    problems = validate_event(event, evidence())
    assert any("without a recorded basis" in problem for problem in problems)


def test_a_tampered_cluster_key_is_detected():
    event = make_event()
    event["clustering"]["cluster_key"] = "0" * 64
    problems = validate_event(event, evidence())
    assert any("cluster_key does not match" in problem for problem in problems)


def test_declared_completeness_must_match_the_computed_chain():
    event = make_event()
    event["transmission_chain"]["completeness"] = "incomplete"
    problems = validate_event(event, evidence())
    assert any("compute to" in problem for problem in problems)


def test_similarity_threshold_is_high_enough_to_avoid_casual_merges():
    assert TITLE_SIMILARITY_THRESHOLD >= 0.5


# ---------------------------------------------------------------------------
# WO-010-R1 §3: an event is active only when something says it still is.
# ---------------------------------------------------------------------------

CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)


def _live_evidence(**overrides):
    item = {
        "evidence_id": "EVD-TEST-001",
        "claim_type": "official_notice",
        "evidence_role": "confirming",
        "strength": "A",
        "evidence_origin": "live_retrieved",
        "retrieval_status": "retrieved",
        "retrieved_at": "2026-07-20T00:00:00Z",
    }
    item.update(overrides)
    return {item["evidence_id"]: item}


def _fixture_evidence(**overrides):
    return _live_evidence(
        evidence_origin="historical_validation_fixture",
        retrieval_status="not_retrieved",
        retrieved_at=None,
        **overrides,
    )


def _current_event(**overrides):
    return make_event(
        dataset="current_publication",
        active_as_of="2026-07-20T00:00:00Z",
        active_basis="Port authority notice re-checked on 2026-07-20 and still in force.",
        **overrides,
    )


def test_a_historical_fixture_is_never_an_active_event():
    """The whole R1 defect in one case: a 2021 case with a null end date used
    to stay 'active' indefinitely and reach the current view."""
    event = make_event(
        dataset="historical_validation",
        event_date="2021-03-23",
        event_end_date=None,
        active_as_of=None,
        active_basis=None,
    )
    decision = is_active_at(event, _fixture_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "historical_validation" in decision.reason
    assert active_events([event], _fixture_evidence(), cutoff=CUTOFF) == []


def test_a_closed_event_is_not_active():
    event = _current_event(
        lifecycle_status="closed",
        closure_basis="The terminal reopened and the authority withdrew the notice.",
    )
    decision = is_active_at(event, _live_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "closure basis" in decision.reason or "not an active status" in decision.reason


def test_an_event_that_ended_before_the_cutoff_is_not_active():
    event = _current_event(event_end_date="2026-05-01")
    decision = is_active_at(event, _live_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "ended on 2026-05-01" in decision.reason


def test_an_event_without_an_active_as_of_basis_is_not_active():
    """A null ``event_end_date`` is silence, not a confirmation."""
    event = make_event(
        dataset="current_publication",
        event_end_date=None,
        active_as_of=None,
        active_basis=None,
    )
    decision = is_active_at(event, _live_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "null event end date is not itself evidence" in decision.reason


def test_a_stale_confirmation_falls_out_of_the_active_window():
    event = make_event(
        dataset="current_publication",
        active_as_of="2026-01-01T00:00:00Z",
        active_basis="Confirmed in January and not re-checked since.",
    )
    decision = is_active_at(event, _live_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "confirmation window" in decision.reason


def test_a_reviewed_event_with_a_recent_confirmation_is_active():
    event = _current_event()
    decision = is_active_at(event, _live_evidence(), cutoff=CUTOFF)
    assert decision.is_active is True
    assert active_events([event], _live_evidence(), cutoff=CUTOFF) == [event]


def test_fixture_evidence_alone_cannot_make_an_event_active():
    event = _current_event()
    decision = is_active_at(event, _fixture_evidence(), cutoff=CUTOFF)
    assert decision.is_active is False
    assert "fixture evidence cannot establish a current condition" in decision.reason


def test_a_historical_chokepoint_notice_does_not_create_a_current_notice():
    """A 2021 canal notice is evidence that a notice was published in 2021.
    It is not evidence that a notice is in force now."""
    event = make_event(
        dataset="historical_validation",
        event_type="chokepoint_disruption",
        chokepoint_ids=["CHK-SUEZ"],
        active_as_of=None,
        active_basis=None,
    )
    assert active_events([event], _fixture_evidence(), cutoff=CUTOFF) == []
    assert event_qualifies_for_current_publication(event, _fixture_evidence()) is False


def test_an_event_assembled_from_fixtures_cannot_join_the_current_dataset():
    event = _current_event()
    problems = validate_event(event, _fixture_evidence())
    assert any("cannot establish a current condition" in problem for problem in problems)


def test_an_active_as_of_time_with_no_basis_is_rejected():
    event = make_event(
        dataset="current_publication",
        active_as_of="2026-07-20T00:00:00Z",
        active_basis=None,
    )
    problems = validate_event(event, _live_evidence())
    assert any("no basis" in problem for problem in problems)


# ---------------------------------------------------------------------------
# WO-010-R1 §4: missing impact evidence is not a stable condition.
# ---------------------------------------------------------------------------

LANE = "LANE-OCEAN-TH-NEUR"
CAPACITY_AREAS = ("capacity", "service")


def _lane_event(**overrides):
    overrides.setdefault("lane_relevance", [{"lane_id": LANE, "relevance": "direct", "basis": "x"}])
    return make_event(**overrides)


def test_no_event_at_all_is_insufficient_not_stable():
    direction, event_ids, evidence_ids, limitations = event_domain_direction(
        LANE, [], CAPACITY_AREAS
    )
    assert direction == "insufficient_evidence"
    assert event_ids == [] and evidence_ids == []
    assert "absence of evidence rather than evidence of normal operation" in limitations[0]


def test_an_event_whose_domain_was_never_assessed_is_insufficient():
    """The corrected rule. An event exists, it touches the lane, and nobody
    looked at capacity or service. That is not calm; it is silence."""
    event = _lane_event()
    direction, event_ids, evidence_ids, limitations = event_domain_direction(
        LANE, [event], CAPACITY_AREAS
    )
    assert direction == "insufficient_evidence"
    assert event_ids == [event["event_id"]]
    assert evidence_ids == []
    assert any(
        "absence of an adverse record is not evidence that conditions are normal" in limitation
        for limitation in limitations
    )


def test_an_assessed_event_with_no_negative_evidence_is_still_insufficient():
    event = _lane_event(
        impacts={
            "capacity": {"status": "insufficient_evidence", "severity": "none"},
            "service": {"status": "insufficient_evidence", "severity": "none"},
        }
    )
    direction, _, _, _ = event_domain_direction(LANE, [event], CAPACITY_AREAS)
    assert direction == "insufficient_evidence"


def test_only_a_discovery_lead_is_insufficient():
    event = _lane_event(
        event_class="discovery_lead",
        transmission_chain={
            "external_driver": None,
            "operational_change": None,
            "logistics_mechanism": None,
            "observable_indicator": None,
            "outcome": None,
        },
    )
    direction, _, _, limitations = event_domain_direction(LANE, [event], CAPACITY_AREAS)
    assert direction == "insufficient_evidence"
    assert any("lead cannot support a direction" in limitation for limitation in limitations)


def test_explicit_negative_operational_evidence_supports_stable():
    """``stable`` is a finding: somebody checked capacity and service and
    recorded that there was no material effect."""
    event = _lane_event(
        negative_operational_evidence=True,
        impacts={
            "capacity": {
                "status": "no_material",
                "severity": "none",
                "evidence_ids": ["EVD-TEST-001"],
            },
            "service": {
                "status": "no_material",
                "severity": "none",
                "evidence_ids": ["EVD-TEST-001"],
            },
        },
    )
    direction, _, evidence_ids, limitations = event_domain_direction(LANE, [event], CAPACITY_AREAS)
    assert direction == "stable"
    assert evidence_ids == ["EVD-TEST-001"]
    assert any("explicit negative operational evidence" in limit for limit in limitations)


def test_an_observed_adverse_impact_is_deteriorating():
    event = _lane_event(
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "moderate",
                "evidence_ids": ["EVD-TEST-001"],
                "transmission_mechanism": ["Terminal closure removes capacity."],
            }
        }
    )
    direction, _, evidence_ids, _ = event_domain_direction(LANE, [event], CAPACITY_AREAS)
    assert direction == "deteriorating"
    assert evidence_ids == ["EVD-TEST-001"]


def test_negative_evidence_for_another_domain_does_not_settle_this_one():
    """``negative_operational_evidence`` is a flag on the event. It only
    licenses a negative conclusion for the areas actually assessed."""
    event = _lane_event(
        negative_operational_evidence=True,
        impacts={
            "cost": {
                "status": "no_material",
                "severity": "none",
                "evidence_ids": ["EVD-TEST-001"],
            }
        },
    )
    assert has_negative_operational_evidence(event, CAPACITY_AREAS) is False
    direction, _, _, _ = event_domain_direction(LANE, [event], CAPACITY_AREAS)
    assert direction == "insufficient_evidence"


def test_missing_event_data_never_produces_routine_attention():
    """Attention level is derived from the domain directions, so the whole
    chain has to hold: no evidence must not come out the other end as
    'routine, nothing to see'."""
    from analysis.assessments import attention_level

    direction = event_domain_direction(LANE, [], CAPACITY_AREAS)[0]
    domains = [{"domain": f"domain_{index}", "direction": direction} for index in range(9)]
    assert {domain["direction"] for domain in domains} == {"insufficient_evidence"}
    assert attention_level(domains, active_operational_event_ids=[]) == "insufficient_evidence"
