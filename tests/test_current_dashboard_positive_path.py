"""Positive-path Dashboard rendering (WO-010-R3 §8).

Every prior positive-path test proved that a qualifying record survives the
*analysis* filter. None of them proved anything about what the Dashboard
actually renders once one exists -- and R2/R3's hard-coded zero-coverage
statements would have kept reading "no qualified observation" forever, even
after a qualifying record reached the payload, because nothing exercised
that path.

These tests build a full temporary copy of the committed ``data/`` tree,
inject one qualifying Thailand trade series and one qualifying human-reviewed
notice on a current event, recompute the two pre-built current assessment
files those injected records feed, and then call the real
``scripts.build_dashboard.build_payloads()`` against that copy. Nothing here
touches the committed repository: the copy lives under ``tmp_path`` and is
discarded when the test ends.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_dashboard as build_dashboard  # noqa: E402
from analysis.provenance import CURRENT_PUBLICATION, RAW_VALUES_PERMITTED  # noqa: E402
from scripts.build_analysis import (  # noqa: E402
    build_current_indicators,
    build_current_lane_assessments,
    build_current_thailand_assessment,
)
from tests.positive_path import (  # noqa: E402
    TEST_REGISTRY,
    current_operational_event,
    live_trade_series,
    manual_notice_evidence,
)


def _partial_source_status():
    """A Source Health snapshot consistent with the injected records: one
    capability qualified, the rest still uncovered. Built directly rather
    than loaded from the committed (zero-source) ``source_status/latest.json``,
    which knows nothing about TEST_REGISTRY's enabled test sources."""
    return {
        "overall_status": "limited",
        "coverage_message": (
            "Thailand trade flow is qualified from a test source at this cutoff; every other "
            "capability remains uncovered."
        ),
        "sources": [],
        "capabilities": [],
    }


def _real_lanes():
    return json.loads((ROOT / "data/reference/lanes.json").read_text(encoding="utf-8"))["lanes"]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def qualified_dashboard_payloads(tmp_path, monkeypatch):
    """The Dashboard rendered from a copy of the real data tree, with one
    qualifying trade series and one qualifying manual notice injected."""
    temp_root = tmp_path / "repo"
    shutil.copytree(ROOT / "data", temp_root / "data")
    shutil.copytree(ROOT / "innovation", temp_root / "innovation")
    (temp_root / "config").mkdir()
    (temp_root / "config" / "sources.yaml").write_text(
        yaml.safe_dump(TEST_REGISTRY, sort_keys=False), encoding="utf-8"
    )

    # ---- Inject one qualifying Thailand trade series -----------------------
    trade_records = live_trade_series(periods=26, growth=0.02, series_id="th_export_value_neur")
    trade_path = temp_root / "data/observations/trade_observations.json"
    trade_payload = json.loads(trade_path.read_text(encoding="utf-8"))
    trade_payload["records"] = trade_payload["records"] + trade_records
    _write_json(trade_path, trade_payload)

    # ---- Inject one qualifying human-reviewed notice on a current event ----
    evidence = manual_notice_evidence()
    event = current_operational_event(
        impacts={
            "capacity": {
                "status": "observed",
                "severity": "moderate",
                "evidence_ids": [evidence["evidence_id"]],
                "transmission_mechanism": ["Berth closure removes capacity."],
                "evidence_strength": "A",
                "confidence": "medium",
            }
        },
    )
    events_path = temp_root / "data/events/events.json"
    events_payload = json.loads(events_path.read_text(encoding="utf-8"))
    events_payload["events"] = events_payload["events"] + [event]
    _write_json(events_path, events_payload)

    evidence_path = temp_root / "data/events/event_evidence.json"
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_payload["evidence"] = evidence_payload["evidence"] + [evidence]
    _write_json(evidence_path, evidence_payload)

    # ---- Recompute the two pre-built current assessment files the injected
    # records feed, using the same production functions build_analysis.py
    # calls, so the situation banner and the lane cards reflect them too. ---
    qualified_observations = {
        "trade_observations": trade_records,
        "indicator_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    qualified_events = [event]
    evidence_by_id = {evidence["evidence_id"]: evidence}
    source_status = _partial_source_status()
    current_lane_assessments = build_current_lane_assessments(
        _real_lanes(),
        qualified_observations,
        qualified_events,
        evidence_by_id,
        source_status,
        TEST_REGISTRY,
    )
    current_indicators = build_current_indicators(qualified_observations, TEST_REGISTRY)
    current_thailand = build_current_thailand_assessment(
        current_lane_assessments,
        qualified_observations,
        qualified_events,
        evidence_by_id,
        source_status,
        TEST_REGISTRY,
        current_indicators,
    )

    lane_assessments_path = temp_root / "data/assessments/lane_assessments.json"
    lane_payload = json.loads(lane_assessments_path.read_text(encoding="utf-8"))
    lane_payload["assessments"] = current_lane_assessments
    _write_json(lane_assessments_path, lane_payload)

    _write_json(temp_root / "data/assessments/thailand_assessment.json", current_thailand)

    monkeypatch.setattr(build_dashboard, "ROOT", temp_root)
    return build_dashboard.build_payloads()


# ---------------------------------------------------------------------------
# §8 What a qualifying record actually renders as
# ---------------------------------------------------------------------------


def test_the_trade_panel_shows_the_qualified_flow_not_a_zero_coverage_statement(
    qualified_dashboard_payloads,
):
    trade = qualified_dashboard_payloads["trade.json"]
    assert trade["current_lane_flows"] != []
    assert "No qualified Thailand trade observation exists" not in trade["current_statement"]
    flow = trade["current_lane_flows"][0]["flows"][0]
    assert flow["current_value"] is not None
    assert flow["points"] != []


def test_the_qualified_flow_carries_current_not_demo_styling(qualified_dashboard_payloads):
    flow = qualified_dashboard_payloads["trade.json"]["current_lane_flows"][0]["flows"][0]
    assert flow["dataset"] == CURRENT_PUBLICATION
    assert flow["evidence_origin"] == "live_retrieved"


def test_the_qualified_flow_carries_its_publication_use_disposition(qualified_dashboard_payloads):
    flow = qualified_dashboard_payloads["trade.json"]["current_lane_flows"][0]["flows"][0]
    # TEST_TRADE_SOURCE is raw_values_permitted, so the raw value and the raw
    # chart points travel; a derived-only source would show neither (§5).
    assert flow["publication_use_applied"] == RAW_VALUES_PERMITTED
    assert flow["current_value"] is not None
    assert flow["points"] != []


def test_unrelated_capabilities_still_read_insufficient(qualified_dashboard_payloads):
    """Trade is qualified; cost is not. One qualified capability must not make
    an unrelated one look sufficient."""
    cost = qualified_dashboard_payloads["cost.json"]
    assert cost["current_cost_series"] == []
    assert "No qualified cost observation exists" in cost["current_statement"]


def test_the_notice_appears_without_the_dashboard_also_claiming_none_exists(
    qualified_dashboard_payloads,
):
    ocean = qualified_dashboard_payloads["ocean.json"]
    assert ocean["current_operational_notices"] != []
    assert "No qualified operational notice is recorded" not in ocean["current_notice_statement"]
    notice = ocean["current_operational_notices"][0]
    assert notice["dataset"] == CURRENT_PUBLICATION


def test_the_events_panel_shows_the_qualified_event_without_claiming_none_exists(
    qualified_dashboard_payloads,
):
    events = qualified_dashboard_payloads["events.json"]
    assert events["current_direct_operational_events"] != []
    assert "No qualified event is recorded" not in events["current_statement"]


def test_the_situation_banner_reflects_partial_not_zero_coverage(qualified_dashboard_payloads):
    situation = qualified_dashboard_payloads["thailand_situation.json"]
    assert situation["qualified_observation_count"] == 26
    assert "INSUFFICIENT" not in situation["live_coverage_statement"]
    assert "PARTIAL" in situation["live_coverage_statement"] or (
        "SUFFICIENT" in situation["live_coverage_statement"]
    )


def test_a_qualified_trade_series_carries_a_text_equivalent_alongside_its_points(
    qualified_dashboard_payloads,
):
    """A chart is never the only way the reading is exposed: every point is
    accompanied by plain-text fields a non-chart reader can consume."""
    flow = qualified_dashboard_payloads["trade.json"]["current_lane_flows"][0]["flows"][0]
    assert isinstance(flow["current_value"], float)
    assert flow["current_period"]
    assert flow["freshness"]["status"]
    for point in flow["points"]:
        assert {"period", "value", "value_status", "unit"} <= point.keys()


# ---------------------------------------------------------------------------
# The committed Dashboard, unaffected by any of the above
# ---------------------------------------------------------------------------


def test_the_committed_dashboard_remains_zero_live_source_and_insufficient():
    payloads = build_dashboard.build_payloads()
    situation = payloads["thailand_situation.json"]
    assert situation["evidence_coverage"] == "insufficient"
    assert situation["qualified_observation_count"] == 0
    assert "INSUFFICIENT" in situation["live_coverage_statement"]
    assert payloads["trade.json"]["current_lane_flows"] == []
    assert payloads["cost.json"]["current_cost_series"] == []
    assert payloads["ocean.json"]["current_operational_notices"] == []
    assert payloads["events.json"]["current_direct_operational_events"] == []
