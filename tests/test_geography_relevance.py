"""Real geographic relevance in the Review Package's support index
(WO-010-R6 §8, §9).

Prior to this work order, ``analysis.review_package.build_support_index``
carried only the coarse ``scope_supported`` label (``asset``/``facility``/
``node``/``route``/``lane``/``country``/``region``/``global``), and the three
relevance checks (``lane_support_relevance_problems``,
``scenario_support_problems``, ``preparedness_applicability_problems``)
treated ``country``/``region``/``global`` as an automatic pass for *any*
Lane. That meant a Panama country-wide notice could support a Thailand Lane,
and a global indicator could independently establish a Thailand-specific
observed condition. These tests exercise the real-ID-based replacement
directly against ``build_support_index`` and the relevance checks, without
going through a full schema-valid ChatGPT output.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.review_package import (  # noqa: E402
    build_input_package,
    build_support_index,
    lane_support_relevance_problems,
)
from tests.positive_path import TEST_REGISTRY, manual_notice_evidence  # noqa: E402


def _lane(lane_id, *, country_ids=(), node_ids=(), chokepoint_ids=(), **overrides):
    entry = {
        "lane_id": lane_id,
        "dataset": "current_publication",
        "overall_direction": "insufficient_evidence",
        "attention_level": "insufficient_evidence",
        "domain_directions": {},
        "domain_indicator_ids": {},
        "indicator_ids": [],
        "active_event_ids": [],
        "external_driver_event_ids": [],
        "chokepoint_exposure": [],
        "data_gaps": [],
        "country_ids": list(country_ids),
        "node_ids": list(node_ids),
        "chokepoint_ids": list(chokepoint_ids),
    }
    entry.update(overrides)
    return entry


def _event(event_id="EVT-1", *, country_ids=(), node_ids=(), chokepoint_ids=(), lane_relevance=()):
    return {
        "event_id": event_id,
        "event_class": "direct_operational_event",
        "country_ids": list(country_ids),
        "node_ids": list(node_ids),
        "chokepoint_ids": list(chokepoint_ids),
        "geography_ids": [],
        "modes": [],
        "lane_relevance": list(lane_relevance),
    }


def _package(*, lanes, events, evidence_scope, event_id="EVT-1", evidence_id="EVD-1"):
    return build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=lanes,
        events=events,
        evidence=[
            {
                **manual_notice_evidence(evidence_id=evidence_id, event_id=event_id),
                "scope_supported": evidence_scope,
            }
        ],
        previous_assessments=[],
        data_gaps=[],
    )


# ---------------------------------------------------------------------------
# build_support_index carries real geography (§8)
# ---------------------------------------------------------------------------


def test_the_support_index_carries_country_ids_geography_ids_and_scope_type():
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"])],
        events=[_event(country_ids=["TH"])],
        evidence_scope="country",
    )
    index = build_support_index(package)
    entry = index["EVD-1"]
    assert entry["country_ids"] == ["TH"]
    assert entry["scope_type"] == "country"


# ---------------------------------------------------------------------------
# Negative: unrelated-country evidence does not support a Lane (§9, §10)
# ---------------------------------------------------------------------------


def test_country_scoped_evidence_from_an_unrelated_country_does_not_support_a_lane():
    """Panama country-wide evidence must not support a Thailand Lane."""
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"])],
        events=[_event(country_ids=["PA"])],
        evidence_scope="country",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    problems = lane_support_relevance_problems(output, package, registry=TEST_REGISTRY)
    assert any("does not link to this lane" in item for item in problems), problems


def test_global_evidence_does_not_automatically_support_a_lane():
    """A global-scoped indicator/notice is no longer an automatic pass for
    any Lane -- it must still clear a real link."""
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"])],
        events=[_event(country_ids=[])],
        evidence_scope="global",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    problems = lane_support_relevance_problems(output, package, registry=TEST_REGISTRY)
    assert any("does not link to this lane" in item for item in problems), problems


def test_facility_evidence_does_not_support_an_unrelated_lane():
    package = _package(
        lanes=[
            _lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"]),
            _lane("LANE-OCEAN-TH-JPKR", country_ids=["TH"], active_event_ids=["EVT-1"]),
        ],
        events=[_event(country_ids=["TH"])],
        evidence_scope="facility",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    problems = lane_support_relevance_problems(output, package, registry=TEST_REGISTRY)
    assert any("does not link to this lane" in item for item in problems), problems


# ---------------------------------------------------------------------------
# Positive: real geography and explicit links (§9, §10)
# ---------------------------------------------------------------------------


def test_thailand_country_evidence_supports_a_thailand_lane():
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"])],
        events=[_event(country_ids=["TH"])],
        evidence_scope="country",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    assert lane_support_relevance_problems(output, package, registry=TEST_REGISTRY) == []


def test_chokepoint_evidence_supports_the_lane_it_is_exposed_through():
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"], chokepoint_ids=["CHK-SUEZ"])],
        events=[_event(country_ids=[], chokepoint_ids=["CHK-SUEZ"])],
        evidence_scope="route",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    assert lane_support_relevance_problems(output, package, registry=TEST_REGISTRY) == []


def test_an_explicit_reviewed_lane_relevance_link_supports_the_lane_even_with_no_geo_overlap():
    """The event names no country/node/chokepoint overlapping the Lane at
    all, but its own reviewed lane_relevance explicitly names this evidence
    for this Lane -- an explicit reviewed Lane relevance link, condition (b)
    of WO-010-R6 §9."""
    package = _package(
        lanes=[_lane("LANE-OCEAN-TH-NEUR", country_ids=["TH"])],
        events=[
            _event(
                country_ids=[],
                lane_relevance=[
                    {
                        "lane_id": "LANE-OCEAN-TH-NEUR",
                        "relevance": "low",
                        "basis": "reviewed aggregation basis",
                        "evidence_ids": ["EVD-1"],
                    }
                ],
            )
        ],
        evidence_scope="global",
    )
    output = {
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ]
    }
    assert lane_support_relevance_problems(output, package, registry=TEST_REGISTRY) == []
