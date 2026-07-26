"""The positive current-publication path (WO-010-R2).

R1 proved the boundary rejects. Every record in the repository is a fixture,
so every current list came out empty -- which is indistinguishable from a
hard-coded empty list unless something also proves that a *qualifying* record
gets through.

These tests build qualifying records in memory (``tests/positive_path.py``),
push them through the same production code the Dashboard uses, and check that
they arrive. The committed repository is untouched: no source is enabled, no
file under ``data/`` gains a live record, and the published Dashboard still
reports insufficient coverage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.events import (  # noqa: E402
    active_events,
    event_domain_direction,
    event_qualifies_for_current_publication,
    is_active_at,
)
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    DERIVED_VALUES_ONLY,
    HISTORICAL_VALIDATION,
    PUBLISH_BOUNDED_CLAIM,
    PUBLISH_DERIVED_VALUE,
    PUBLISH_LINK_ONLY,
    PUBLISH_RAW_VALUE,
    RAW_VALUES_PERMITTED,
    TECHNICAL_DEMO,
    publication_use_problems,
    qualified_records,
    qualifies_for_current_publication,
    record_publication_use,
    series_homogeneity_problems,
)
from scripts.build_analysis import (  # noqa: E402
    build_current_indicators,
    build_current_lane_assessments,
    build_current_thailand_assessment,
    current_capability_coverage,
    current_chokepoint_exposure,
)
from scripts.build_dashboard import (  # noqa: E402
    _current_series_payload,
    publishable_assessment_problems,
)
from tests.positive_path import (  # noqa: E402
    CUTOFF,
    TEST_DERIVED_ONLY_SOURCE,
    TEST_LINK_ONLY_SOURCE,
    TEST_NOTICE_SOURCE,
    TEST_REGISTRY,
    TEST_TRADE_SOURCE,
    current_operational_event,
    live_trade_observation,
    live_trade_series,
    manual_notice_evidence,
)

LANE_ID = "LANE-OCEAN-TH-NEUR"


def _lanes():
    return json.loads((ROOT / "data/reference/lanes.json").read_text(encoding="utf-8"))["lanes"]


def _lane(lane_id=LANE_ID):
    return next(lane for lane in _lanes() if lane["lane_id"] == lane_id)


def _source_status():
    return json.loads((ROOT / "data/source_status/latest.json").read_text(encoding="utf-8"))


def _domain(assessment, name):
    return next(item for item in assessment["domain_assessments"] if item["domain"] == name)


# ---------------------------------------------------------------------------
# §1 Qualification is a decision about the whole record
# ---------------------------------------------------------------------------


def test_a_live_record_in_the_current_dataset_qualifies():
    record = live_trade_observation(period_key="2026-06", value=1.0)
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert decision.eligible is True
    assert bool(decision) is True
    assert TEST_TRADE_SOURCE in decision.reason


def test_a_live_record_in_the_historical_dataset_does_not_qualify():
    """The origin is impeccable and the dataset is wrong. Origin alone was the
    R1 test, and it would have passed this record straight through."""
    record = live_trade_observation(period_key="2026-06", value=1.0, dataset=HISTORICAL_VALIDATION)
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "historical_validation" in decision.reason


def test_a_live_record_in_the_technical_demo_dataset_does_not_qualify():
    record = live_trade_observation(period_key="2026-06", value=1.0, dataset=TECHNICAL_DEMO)
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "technical_demo" in decision.reason


def test_a_fixture_in_the_current_dataset_does_not_qualify():
    """Mislabelling a fixture as current must not launder it."""
    record = live_trade_observation(
        period_key="2026-06",
        value=1.0,
        evidence_origin="synthetic_test_fixture",
        retrieval_status="not_retrieved",
        retrieved_at=None,
    )
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "cannot carry current intelligence" in decision.reason


def test_an_unknown_origin_does_not_qualify():
    record = live_trade_observation(period_key="2026-06", value=1.0, evidence_origin="assumed")
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "not a recognised origin" in decision.reason


def test_a_live_record_claiming_no_retrieval_does_not_qualify():
    record = live_trade_observation(
        period_key="2026-06", value=1.0, retrieval_status="not_retrieved", retrieved_at=None
    )
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "must record retrieval_status 'retrieved'" in decision.reason


def test_a_manual_record_qualifies_only_through_the_controlled_intake():
    """``TEST_NOTICE_SOURCE`` is disabled. It qualifies because it is an
    explicitly allowed manual intake -- not because manual records are exempt."""
    item = manual_notice_evidence()
    assert qualifies_for_current_publication(
        item, registry=TEST_REGISTRY, publication_use=PUBLISH_BOUNDED_CLAIM
    )

    disallowed = {
        **TEST_REGISTRY,
        "sources": [
            {
                **source,
                "qualification": {
                    **source["qualification"],
                    "manual_intake_status": "not_allowed",
                },
            }
            if source["id"] == TEST_NOTICE_SOURCE
            else source
            for source in TEST_REGISTRY["sources"]
        ],
    }
    decision = qualifies_for_current_publication(
        item, registry=disallowed, publication_use=PUBLISH_BOUNDED_CLAIM
    )
    assert not decision
    assert "not an allowed human-reviewed manual intake" in decision.reason


def test_a_manual_record_may_not_claim_a_retrieval():
    item = manual_notice_evidence(retrieval_status="retrieved")
    decision = qualifies_for_current_publication(
        item, registry=TEST_REGISTRY, publication_use=PUBLISH_BOUNDED_CLAIM
    )
    assert not decision
    assert "manual, non-network retrieval status" in decision.reason


def test_a_record_from_an_unregistered_source_does_not_qualify():
    record = live_trade_observation(period_key="2026-06", value=1.0, source_id="NOT_IN_REGISTRY")
    decision = qualifies_for_current_publication(record, registry=TEST_REGISTRY)
    assert not decision
    assert "not in the source registry" in decision.reason


def test_a_series_incompatible_with_its_source_role_does_not_qualify():
    """A trade series from a source that declares only notice roles is a
    mapping error, not a publishable observation.

    The link-only source is used here because it is *enabled* and declares a
    trade role; swapping its role for a notice role isolates the compatibility
    check from the enablement check.
    """
    registry = {
        **TEST_REGISTRY,
        "sources": [
            {
                **source,
                "qualification": {
                    **source["qualification"],
                    "logistics_role": ["official_operational_notice"],
                },
            }
            if source["id"] == TEST_LINK_ONLY_SOURCE
            else source
            for source in TEST_REGISTRY["sources"]
        ],
    }
    record = live_trade_observation(
        period_key="2026-06", value=1.0, source_id=TEST_LINK_ONLY_SOURCE
    )
    decision = qualifies_for_current_publication(
        record, registry=registry, publication_use=PUBLISH_LINK_ONLY
    )
    assert not decision
    assert "incompatible with a trade observations record" in decision.reason


def test_without_a_registry_nothing_qualifies():
    """The registry-dependent conditions cannot be skipped by omitting the
    registry: the decision is negative and says so."""
    record = live_trade_observation(period_key="2026-06", value=1.0)
    decision = qualifies_for_current_publication(record)
    assert not decision
    assert "no source registry was supplied" in decision.reason


# ---------------------------------------------------------------------------
# §7 Publication use: enablement is not permission to republish
# ---------------------------------------------------------------------------


def test_a_link_only_source_may_not_publish_values():
    record = live_trade_observation(
        period_key="2026-06", value=1.0, source_id=TEST_LINK_ONLY_SOURCE
    )
    assert not qualifies_for_current_publication(
        record, registry=TEST_REGISTRY, publication_use=PUBLISH_RAW_VALUE
    )
    assert not qualifies_for_current_publication(
        record, registry=TEST_REGISTRY, publication_use=PUBLISH_DERIVED_VALUE
    )
    # A link is all its terms permit, and a link is permitted.
    assert qualifies_for_current_publication(
        record, registry=TEST_REGISTRY, publication_use=PUBLISH_LINK_ONLY
    )


def test_a_bounded_claim_source_may_not_publish_a_derived_value():
    item = manual_notice_evidence()
    assert qualifies_for_current_publication(
        item, registry=TEST_REGISTRY, publication_use=PUBLISH_BOUNDED_CLAIM
    )
    assert not qualifies_for_current_publication(
        item, registry=TEST_REGISTRY, publication_use=PUBLISH_DERIVED_VALUE
    )


def _source(**qualification):
    return {
        "id": "CANDIDATE",
        "access_method": "download",
        "enabled": False,
        "qualification": {
            "reuse_status": "permitted_with_attribution",
            "redistribution_status": "permitted",
            "publication_use": "raw_values_permitted",
            "rate_limit": "60/hour",
            **qualification,
        },
        "enablement": {"schedule_justified": True},
    }


@pytest.mark.parametrize(
    "qualification,expected",
    [
        ({"redistribution_status": "link_only"}, "exceeds what redistribution_status"),
        ({"redistribution_status": "derived_only"}, "exceeds what redistribution_status"),
        ({"redistribution_status": "unknown"}, "exceeds what redistribution_status"),
        ({"redistribution_status": "prohibited"}, "exceeds what redistribution_status"),
        (
            {"reuse_status": "unknown", "publication_use": "derived_values_only"},
            "nothing beyond a metadata link may be published",
        ),
        ({"publication_use": None}, "records no publication_use"),
        ({"publication_use": "whatever_we_like"}, "not a recognised value"),
    ],
)
def test_an_incompatible_publication_use_is_rejected(qualification, expected):
    problems = publication_use_problems(_source(**qualification))
    assert any(expected in problem for problem in problems), problems


def test_an_unresolved_rate_limit_cannot_justify_a_schedule():
    source = _source(rate_limit=None)
    source["access_method"] = "api"
    problems = publication_use_problems(source)
    assert any("rate limits are unresolved" in problem for problem in problems)


def test_a_manual_intake_must_identify_its_underlying_publisher():
    source = _source(manual_intake_status="allowed", redistribution_status="link_only")
    source["qualification"]["publication_use"] = "bounded_claim_and_link_only"
    source["access_method"] = "manual"
    problems = publication_use_problems(source)
    assert any("identify the underlying publisher" in problem for problem in problems)


def test_an_enabled_source_that_may_publish_nothing_is_rejected():
    source = _source(publication_use="internal_validation_only")
    source["enabled"] = True
    problems = publication_use_problems(source)
    assert any("nothing it provides could be published" in problem for problem in problems)


def test_the_committed_registry_passes_its_own_publication_use_rules():
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    for source in registry["sources"]:
        if source["id"] in {"TMD_CAP", "GDACS"}:
            continue
        assert publication_use_problems(source) == [], source["id"]


# ---------------------------------------------------------------------------
# §4 A qualified observation actually drives the current analysis
# ---------------------------------------------------------------------------


@pytest.fixture
def qualified_trade():
    """26 monthly observations: enough history for the year-over-year rule."""
    return {
        "trade_observations": live_trade_series(periods=26, growth=0.02),
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }


def test_a_qualified_series_survives_the_production_filter(qualified_trade):
    kept = qualified_records(
        qualified_trade["trade_observations"],
        registry=TEST_REGISTRY,
        publication_use=PUBLISH_DERIVED_VALUE,
    )
    assert len(kept) == 26


def test_a_qualified_series_drives_its_current_lane_domain(qualified_trade):
    assessments = build_current_lane_assessments(
        _lanes(), qualified_trade, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    trade = _domain(lane, "thailand_trade_flow")

    assert trade["direction"] != "insufficient_evidence"
    assert trade["threshold_rule_id"] == "TH-TRADE-YOY-V1"
    assert trade["data_period"]
    assert trade["freshness"]["status"] in {"fresh", "stale", "very_stale"}
    assert lane["dataset"] == CURRENT_PUBLICATION


def test_one_qualified_series_does_not_make_unrelated_domains_sufficient(qualified_trade):
    """A trade series says nothing about fuel, FX, freight or port activity."""
    assessments = build_current_lane_assessments(
        _lanes(), qualified_trade, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    for domain in (
        "port_maritime_activity",
        "freight_benchmark_direction",
        "fuel_pressure",
        "fx_pressure",
        "capacity_evidence",
    ):
        assert _domain(lane, domain)["direction"] == "insufficient_evidence", domain


def test_a_qualified_series_only_affects_the_lane_it_belongs_to(qualified_trade):
    assessments = build_current_lane_assessments(
        _lanes(), qualified_trade, [], {}, _source_status(), TEST_REGISTRY
    )
    others = [item for item in assessments if item["lane_id"] != LANE_ID]
    assert others
    for lane in others:
        assert _domain(lane, "thailand_trade_flow")["direction"] == "insufficient_evidence"


def test_a_series_with_too_few_periods_stays_insufficient():
    """``TH-TRADE-YOY-V1`` needs 13 observations. Twelve qualified records are
    still not enough evidence, and the rule -- not the filter -- says so."""
    short = {
        "trade_observations": live_trade_series(periods=6, growth=0.02),
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    assessments = build_current_lane_assessments(
        _lanes(), short, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    assert _domain(lane, "thailand_trade_flow")["direction"] == "insufficient_evidence"


def test_scope_limitations_travel_with_a_qualified_series(qualified_trade):
    assessments = build_current_lane_assessments(
        _lanes(), qualified_trade, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    limitations = " ".join(_domain(lane, "thailand_trade_flow")["known_limitations"])
    assert "all-mode total" in limitations


def test_qualified_counts_are_computed_not_declared(qualified_trade):
    assessments = build_current_lane_assessments(
        _lanes(), qualified_trade, [], {}, _source_status(), TEST_REGISTRY
    )
    indicators = build_current_indicators(qualified_trade, TEST_REGISTRY)
    thailand = build_current_thailand_assessment(
        assessments, qualified_trade, [], {}, _source_status(), TEST_REGISTRY, indicators
    )
    assert thailand["qualified_observation_count"] == 26
    assert thailand["current_indicator_count"] == len(indicators) == 1
    assert thailand["qualified_event_count"] == 0
    assert thailand["current_lane_coverage"]["lanes_with_any_qualified_domain"] == 1
    assert thailand["current_lane_coverage"]["lane_ids_with_any_qualified_domain"] == [LANE_ID]


def test_capability_coverage_is_computed_from_the_filtered_records(qualified_trade):
    coverage = {
        item["capability"]: item for item in current_capability_coverage(qualified_trade, [])
    }
    assert coverage["thailand_trade_flow"]["status"] == "sufficient"
    assert coverage["thailand_trade_flow"]["qualified_record_count"] == 26
    assert coverage["cost_and_freight_context"]["status"] == "insufficient"


def test_a_current_series_reaches_the_dashboard_as_current_not_demo(qualified_trade):
    payload = _current_series_payload(
        "th_export_value_neur", qualified_trade["trade_observations"], TEST_REGISTRY
    )
    assert payload is not None
    assert payload["dataset"] == CURRENT_PUBLICATION
    assert payload["source_id"] == TEST_TRADE_SOURCE
    assert payload["evidence_origin"] == "live_retrieved"
    # A real-world freshness label, because a retrieved record is a claim
    # about the world and its publisher can genuinely have fallen behind.
    assert payload["freshness"]["status"] in {"fresh", "stale", "very_stale"}


def test_a_demoted_series_never_reaches_the_current_derivation():
    """The same records, marked technical_demo, produce nothing current."""
    demoted = {
        "trade_observations": live_trade_series(periods=26, dataset=TECHNICAL_DEMO),
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    kept = {
        family: qualified_records(
            records, registry=TEST_REGISTRY, publication_use=PUBLISH_DERIVED_VALUE
        )
        for family, records in demoted.items()
    }
    assert sum(len(records) for records in kept.values()) == 0
    assessments = build_current_lane_assessments(
        _lanes(), kept, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    assert _domain(lane, "thailand_trade_flow")["direction"] == "insufficient_evidence"


# ---------------------------------------------------------------------------
# §5 A human-reviewed notice drives the current event outputs
# ---------------------------------------------------------------------------


@pytest.fixture
def manual_event():
    evidence = manual_notice_evidence()
    event = current_operational_event(
        chokepoint_ids=("CHK-MALACCA",),
        lane_id="LANE-OCEAN-TH-ASEAN-SG",
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "moderate",
                "evidence_ids": ["EVD-MANUAL-001"],
                "transmission_mechanism": ["Berth closure removes capacity."],
                "evidence_strength": "A",
                "confidence": "medium",
            }
        },
    )
    return event, {evidence["evidence_id"]: evidence}


def test_a_human_reviewed_notice_makes_its_event_current(manual_event):
    event, evidence_by_id = manual_event
    assert event_qualifies_for_current_publication(event, evidence_by_id, registry=TEST_REGISTRY)
    decision = is_active_at(event, evidence_by_id, cutoff=CUTOFF, registry=TEST_REGISTRY)
    assert decision.is_active is True
    assert active_events([event], evidence_by_id, cutoff=CUTOFF, registry=TEST_REGISTRY) == [event]


def test_a_current_notice_creates_an_event_driven_lane_direction(manual_event):
    event, _ = manual_event
    direction, event_ids, evidence_ids, _ = event_domain_direction(
        "LANE-OCEAN-TH-ASEAN-SG", [event], ("capacity",)
    )
    assert direction == "deteriorating"
    assert event_ids == [event["event_id"]]
    assert evidence_ids == ["EVD-MANUAL-001"]


def test_a_current_notice_creates_a_current_chokepoint_status(manual_event):
    event, evidence_by_id = manual_event
    lane = {"lane_id": "LANE-OCEAN-TH-ASEAN-SG", "chokepoint_ids": ["CHK-MALACCA"]}
    exposure = current_chokepoint_exposure(lane, [event], evidence_by_id, TEST_REGISTRY)
    assert exposure[0]["status"] == "official_notice_active"
    assert event["event_id"] in exposure[0]["basis"]


def test_a_notice_on_a_non_active_event_creates_no_chokepoint_status(manual_event):
    """The notice qualifies; the event is not confirmed active. Both are
    required, so the chokepoint stays at insufficient evidence."""
    event, evidence_by_id = manual_event
    lane = {"lane_id": "LANE-OCEAN-TH-ASEAN-SG", "chokepoint_ids": ["CHK-MALACCA"]}
    exposure = current_chokepoint_exposure(lane, [], evidence_by_id, TEST_REGISTRY)
    assert exposure[0]["status"] == "insufficient_evidence"


def test_a_qualified_event_raises_its_lane_and_only_its_lane(manual_event):
    event, evidence_by_id = manual_event
    empty = {family: [] for family in ("trade_observations", "indicator_observations")}
    assessments = build_current_lane_assessments(
        _lanes(), empty, [event], evidence_by_id, _source_status(), TEST_REGISTRY
    )
    raised = [item for item in assessments if item["attention_level"] != "insufficient_evidence"]
    assert [item["lane_id"] for item in raised] == ["LANE-OCEAN-TH-ASEAN-SG"]
    assert raised[0]["active_event_ids"] == [event["event_id"]]


# ---------------------------------------------------------------------------
# §6 Negative cases
# ---------------------------------------------------------------------------


def test_an_old_event_with_no_recent_confirmation_is_not_current(manual_event):
    event, evidence_by_id = manual_event
    stale = {**event, "active_as_of": "2026-01-01T00:00:00Z"}
    decision = is_active_at(stale, evidence_by_id, cutoff=CUTOFF, registry=TEST_REGISTRY)
    assert not decision.is_active
    assert "confirmation window" in decision.reason


def test_an_event_supported_only_by_discovery_evidence_is_not_current(manual_event):
    event, _ = manual_event
    lead = manual_notice_evidence(evidence_id="EVD-LEAD-001", claim_type="reported_claim")
    lead["evidence_role"] = "discovery_only"
    direction, _, _, limitations = event_domain_direction(
        "LANE-OCEAN-TH-ASEAN-SG",
        [{**event, "event_class": "discovery_lead", "impact_assessments": []}],
        ("capacity",),
    )
    assert direction == "insufficient_evidence"
    assert any("lead cannot support a direction" in item for item in limitations)


def test_an_event_whose_evidence_is_all_fixture_is_not_current(manual_event):
    event, _ = manual_event
    fixture_evidence = manual_notice_evidence(
        dataset=HISTORICAL_VALIDATION, evidence_origin="historical_validation_fixture"
    )
    by_id = {fixture_evidence["evidence_id"]: fixture_evidence}
    assert not event_qualifies_for_current_publication(event, by_id, registry=TEST_REGISTRY)
    assert active_events([event], by_id, cutoff=CUTOFF, registry=TEST_REGISTRY) == []


# ---------------------------------------------------------------------------
# The publication gate, independent of the approval step
# ---------------------------------------------------------------------------


def _approved(**overrides):
    record = {
        "package_id": "PKG-20260724-001",
        "input_package_id": "PKG-20260724-001",
        "input_package_sha256": "c" * 64,
        "input_dataset": CURRENT_PUBLICATION,
        "input_evidence_origin_summary": {"human_reviewed_manual": 1},
        "validation_status": "passed",
        "superseded": False,
    }
    record.update(overrides)
    return record


def test_a_well_formed_approval_is_publishable():
    assert publishable_assessment_problems(_approved()) == []


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"input_dataset": TECHNICAL_DEMO}, "not a current-publication one"),
        ({"input_dataset": HISTORICAL_VALIDATION}, "not a current-publication one"),
        ({"input_package_sha256": None}, "bound to nothing"),
        ({"validation_status": "pending"}, "not 'passed'"),
        ({"superseded": True}, "superseded"),
        (
            {"input_evidence_origin_summary": {"synthetic_test_fixture": 2}},
            "fixture origin",
        ),
        (
            {"input_evidence_origin_summary": {"historical_validation_fixture": 1}},
            "fixture origin",
        ),
    ],
)
def test_the_publication_gate_withholds_an_unsound_approval(overrides, expected):
    problems = publishable_assessment_problems(_approved(**overrides))
    assert any(expected in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# WO-010-R3 §5 Raw vs derived publication paths
# ---------------------------------------------------------------------------


def _raw_record_ids(records):
    return frozenset(
        record["provenance"]["record_id"]
        for record in qualified_records(
            records, registry=TEST_REGISTRY, publication_use=PUBLISH_RAW_VALUE
        )
    )


def test_a_raw_permitted_source_publishes_its_current_value_and_points():
    records = live_trade_series(periods=26, growth=0.02, series_id="th_export_value_neur")
    payload = _current_series_payload(
        "th_export_value_neur", records, TEST_REGISTRY, raw_record_ids=_raw_record_ids(records)
    )
    assert payload["publication_use_applied"] == RAW_VALUES_PERMITTED
    assert payload["current_value"] is not None
    assert payload["points"] != []


def test_a_derived_only_source_drives_a_direction_but_publishes_no_raw_value():
    records = live_trade_series(
        periods=26,
        growth=0.02,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    payload = _current_series_payload(
        "th_export_value_neur", records, TEST_REGISTRY, raw_record_ids=_raw_record_ids(records)
    )
    assert payload["publication_use_applied"] == DERIVED_VALUES_ONLY
    # A derived-only source can still drive a direction ...
    assert payload["year_over_year_pct"] is not None
    # ... but never the raw reading or the raw points behind it.
    assert payload["current_value"] is None
    assert payload["previous_period_change"] is None
    assert payload["points"] == []


def test_omitting_raw_record_ids_defaults_every_series_to_derived_only():
    """A caller that forgets to pass ``raw_record_ids`` gets the safe default:
    nothing is treated as raw-permitted, rather than everything."""
    records = live_trade_series(periods=26, growth=0.02, series_id="th_export_value_neur")
    payload = _current_series_payload("th_export_value_neur", records, TEST_REGISTRY)
    assert payload["publication_use_applied"] == DERIVED_VALUES_ONLY
    assert payload["current_value"] is None
    assert payload["points"] == []


def test_changing_the_source_disposition_changes_the_payload_shape():
    records = live_trade_series(periods=26, growth=0.02, series_id="th_export_value_neur")
    raw_payload = _current_series_payload(
        "th_export_value_neur", records, TEST_REGISTRY, raw_record_ids=_raw_record_ids(records)
    )
    derived_records = live_trade_series(
        periods=26,
        growth=0.02,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    derived_payload = _current_series_payload(
        "th_export_value_neur",
        derived_records,
        TEST_REGISTRY,
        raw_record_ids=_raw_record_ids(derived_records),
    )
    assert raw_payload["current_value"] is not None
    assert derived_payload["current_value"] is None
    assert raw_payload["points"] != derived_payload["points"]


def test_a_link_only_source_never_reaches_a_current_series_payload_at_all():
    """A metadata-link-only numeric series is excluded upstream: it never
    qualifies for even PUBLISH_DERIVED_VALUE, so it never becomes a payload
    that could leak a numeric value under a 'link only' label."""
    records = live_trade_series(
        periods=26, growth=0.02, series_id="th_export_value_neur", source_id=TEST_LINK_ONLY_SOURCE
    )
    kept = qualified_records(records, registry=TEST_REGISTRY, publication_use=PUBLISH_DERIVED_VALUE)
    assert kept == []


def test_build_current_indicators_shapes_a_derived_only_series_the_same_way():
    records = live_trade_series(
        periods=26,
        growth=0.02,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    qualified = {
        "trade_observations": records,
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    raw_publishable = {
        family: qualified_records(items, registry=TEST_REGISTRY, publication_use=PUBLISH_RAW_VALUE)
        for family, items in qualified.items()
    }
    [indicator] = build_current_indicators(
        qualified, TEST_REGISTRY, raw_publishable_records=raw_publishable
    )
    assert indicator["publication_use_applied"] == DERIVED_VALUES_ONLY
    assert indicator["current_value"] is None
    assert indicator["year_over_year_pct"] is not None


def test_build_current_indicators_sets_geographic_scope():
    records = live_trade_series(periods=26, growth=0.02, series_id="th_export_value_neur")
    qualified = {
        "trade_observations": records,
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    [indicator] = build_current_indicators(qualified, TEST_REGISTRY)
    assert indicator["geographic_scope"] == "thailand"


# ---------------------------------------------------------------------------
# WO-010-R4 §5 Per-record publication-use enforcement: never records[0] alone
# ---------------------------------------------------------------------------


def test_homogeneous_records_from_one_source_raise_no_problem():
    records = live_trade_series(periods=5, growth=0.0, series_id="th_export_value_neur")
    assert series_homogeneity_problems(records, registry=TEST_REGISTRY) == []


def test_records_from_two_different_sources_are_not_homogeneous():
    raw_permitted = live_trade_observation(
        period_key="2026-06", value=1.0, series_id="th_export_value_neur"
    )
    derived_only = live_trade_observation(
        period_key="2026-07",
        value=1.1,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    problems = series_homogeneity_problems([raw_permitted, derived_only], registry=TEST_REGISTRY)
    assert any("source_id" in item for item in problems), problems
    assert any("publication_use" in item for item in problems), problems


def test_record_publication_use_reads_the_records_own_source():
    trade = live_trade_observation(period_key="2026-06", value=1.0)
    derived = live_trade_observation(
        period_key="2026-06", value=1.0, source_id=TEST_DERIVED_ONLY_SOURCE
    )
    assert record_publication_use(trade, registry=TEST_REGISTRY) == RAW_VALUES_PERMITTED
    assert record_publication_use(derived, registry=TEST_REGISTRY) == DERIVED_VALUES_ONLY


def test_a_mixed_series_is_excluded_from_current_indicators_not_combined():
    """Two sources contributing to the same series_id, one raw-permitted and
    one derived-only, must never be silently derived under records[0]'s
    terms -- WO-010-R4 §5 requires the whole series be excluded instead."""
    raw_permitted = live_trade_observation(
        period_key="2026-06", value=1.0, series_id="th_export_value_neur"
    )
    derived_only = live_trade_observation(
        period_key="2026-07",
        value=1.1,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    qualified = {
        "trade_observations": [raw_permitted, derived_only],
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    assert build_current_indicators(qualified, TEST_REGISTRY) == []


def test_a_mixed_series_produces_no_dashboard_payload_either():
    raw_permitted = live_trade_observation(
        period_key="2026-06", value=1.0, series_id="th_export_value_neur"
    )
    derived_only = live_trade_observation(
        period_key="2026-07",
        value=1.1,
        series_id="th_export_value_neur",
        source_id=TEST_DERIVED_ONLY_SOURCE,
    )
    assert (
        _current_series_payload(
            "th_export_value_neur", [raw_permitted, derived_only], TEST_REGISTRY
        )
        is None
    )


def test_a_mixed_series_produces_an_insufficient_evidence_lane_domain_not_a_crash():
    """WO-010-R5 §4: a mixed record set feeding a Lane-domain calculation
    comes out insufficient_evidence, with the homogeneity problem recorded
    as an explicit limitation -- neither combined under one record's terms
    nor a build failure."""
    raw_permitted = live_trade_observation(period_key="2026-06", value=1.0)
    derived_only = live_trade_observation(
        period_key="2026-07", value=1.1, source_id=TEST_DERIVED_ONLY_SOURCE
    )
    mixed = {
        "trade_observations": [raw_permitted, derived_only],
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    assessments = build_current_lane_assessments(
        _lanes(), mixed, [], {}, _source_status(), TEST_REGISTRY
    )
    lane = next(item for item in assessments if item["lane_id"] == LANE_ID)
    trade = _domain(lane, "thailand_trade_flow")
    assert trade["direction"] == "insufficient_evidence"
    assert trade["threshold_rule_id"] is None
    assert not trade["indicator_ids"]
    assert any("mixed record set" in limitation for limitation in trade["known_limitations"])
