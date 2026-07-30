#!/usr/bin/env python3
"""Replay the historical validation cases through the platform's own analysis.

Gate J asks whether the intelligence workflow reaches the right conclusion on
cases whose outcome is already documented. This script answers that
mechanically: it takes each authored case, runs the built event through the
same ``analysis`` code the live pipeline uses, and compares the result against
the expectations the case declares -- transmission completeness, Thailand
relevance, lane relevance, evidence classification, per-area impact
disposition, and whether human review is required.

It then measures the behaviours the Work Order names, across every case at
once: traceability, unsupported causation, geography leakage, missing-as-zero,
event-versus-impact separation, scenario completeness, preparedness overreach,
and the correct use of "insufficient evidence" and "no material impact
detected".

Hindsight cannot leak in, because a case's expectations are compared only
against what the case itself records at its own cutoff.

Usage::

    python scripts/run_historical_validation.py [--write-report]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.assessments import (  # noqa: E402
    validate_preparedness_option,
    validate_scenario_outlook,
)
from analysis.events import (  # noqa: E402
    MATERIAL_IMPACT_STATUSES,
    evaluate_transmission_chain,
    external_driver_admission,
    has_non_discovery_evidence,
    validate_event,
)
from analysis.reference import lane_by_id, resolve_lane_relevance  # noqa: E402

CASES_PATH = ROOT / "data" / "validation" / "historical_cases.json"
REPORT_PATH = ROOT / "data" / "validation" / "validation_report.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_case(
    case: dict[str, Any],
    event: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    """Compare one built event against its case's declared expectations."""
    failures: list[str] = []
    case_id = case["case_id"]
    expected = case["expectations"]

    completeness, _ = evaluate_transmission_chain(event["event_class"], event["transmission_chain"])
    if completeness != expected["expected_transmission_completeness"]:
        failures.append(
            f"{case_id}: transmission completeness is {completeness!r}, expected "
            f"{expected['expected_transmission_completeness']!r}"
        )

    if event["thailand_relevance"] != expected["expected_thailand_relevance"]:
        failures.append(
            f"{case_id}: Thailand relevance is {event['thailand_relevance']!r}, expected "
            f"{expected['expected_thailand_relevance']!r}"
        )

    resolved = {entry["lane_id"] for entry in event["lane_relevance"]}
    missing_lanes = set(expected["expected_lane_ids"]) - resolved
    if missing_lanes:
        failures.append(f"{case_id}: expected lane relevance not resolved: {sorted(missing_lanes)}")

    claim_types = {
        evidence_by_id[eid]["claim_type"] for eid in event["evidence_ids"] if eid in evidence_by_id
    }
    missing_classes = set(expected["expected_evidence_classification"]) - claim_types
    if missing_classes:
        failures.append(
            f"{case_id}: expected evidence classification(s) absent: {sorted(missing_classes)}"
        )

    by_area = {impact["area"]: impact for impact in event["impact_assessments"]}
    for area, expected_status in expected["expected_impact_disposition"].items():
        actual = by_area[area]["status"]
        if actual != expected_status:
            failures.append(
                f"{case_id}/{area}: impact status is {actual!r}, expected {expected_status!r}"
            )

    problems = validate_event(event, evidence_by_id)
    expected_problems = expected.get("expected_validation_problems", [])
    if bool(problems) != bool(expected_problems):
        failures.append(
            f"{case_id}: validate_event returned {problems or 'no problems'}, expected "
            f"{expected_problems or 'no problems'}"
        )

    return failures


def measure(
    events: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    lane_assessments: list[dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
    indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure the Gate J behaviours across every case at once."""
    impacts = [(event, impact) for event in events for impact in event["impact_assessments"]]
    material = [
        (event, impact)
        for event, impact in impacts
        if impact["status"] in MATERIAL_IMPACT_STATUSES and impact["severity"] != "none"
    ]

    traceable = sum(
        1
        for _, impact in impacts
        if not (set(impact.get("evidence_ids", [])) - set(evidence_by_id))
    )
    unsupported_causation = [
        f"{event['event_id']}/{impact['area']}"
        for event, impact in material
        if not impact.get("transmission_mechanism")
    ]

    geography_leakage = []
    for event in events:
        legitimate = set(
            resolve_lane_relevance(
                country_ids=event.get("country_ids", []),
                node_ids=event.get("node_ids", []),
                chokepoint_ids=event.get("chokepoint_ids", []),
            )
        )
        for entry in event["lane_relevance"]:
            if entry["lane_id"] not in legitimate:
                geography_leakage.append(f"{event['event_id']} -> {entry['lane_id']}")
            else:
                lane = lane_by_id(entry["lane_id"])
                touches = (
                    set(event.get("country_ids", [])) & set(lane["country_ids"])
                    or set(event.get("node_ids", [])) & set(lane.get("node_ids", []))
                    or set(event.get("chokepoint_ids", [])) & set(lane.get("chokepoint_ids", []))
                )
                if not touches:
                    geography_leakage.append(
                        f"{event['event_id']} -> {entry['lane_id']} (no shared reference entity)"
                    )

    missing_as_zero = [
        record["provenance"]["record_id"]
        for records in observations.values()
        for record in records
        if record["measurement"]["value_status"] != "available"
        and record["measurement"]["value"] is not None
    ]
    missing_as_zero.extend(
        f"indicator:{indicator['series_id']}"
        for indicator in indicators
        if indicator["periods_missing"] > 0 and indicator["current_value"] == 0
    )

    severity_order = ["none", "low", "moderate", "high", "critical"]
    separation_examples = []
    for event in events:
        if event.get("event_severity") in {None, "not_assessed"}:
            continue
        worst_impact = max(
            (impact["severity"] for impact in event["impact_assessments"]),
            key=severity_order.index,
        )
        if worst_impact != event["event_severity"]:
            separation_examples.append(
                f"{event['event_id']}: event severity {event['event_severity']} vs worst "
                f"impact severity {worst_impact}"
            )

    scenario_problems: list[str] = []
    preparedness_problems: list[str] = []
    complete_outlooks = 0
    for assessment in lane_assessments:
        outlook = assessment.get("scenarios")
        if outlook:
            problems = validate_scenario_outlook(outlook)
            scenario_problems.extend(problems)
            if not problems:
                complete_outlooks += 1
        for option in assessment.get("preparedness_options", []):
            preparedness_problems.extend(validate_preparedness_option(option))

    insufficient_uses = [
        f"{event['event_id']}/{impact['area']}"
        for event, impact in impacts
        if impact["status"] == "insufficient_evidence"
    ]
    no_material_uses = [
        f"{event['event_id']}/{impact['area']}"
        for event, impact in impacts
        if impact["status"] == "no_material"
    ]
    no_material_without_negative_evidence = [
        f"{event['event_id']}/{impact['area']}"
        for event, impact in impacts
        if impact["status"] == "no_material" and not event.get("negative_operational_evidence")
    ]

    discovery_only_material = [
        event["event_id"]
        for event in events
        if any(
            impact["status"] in MATERIAL_IMPACT_STATUSES and impact["severity"] != "none"
            for impact in event["impact_assessments"]
        )
        and not has_non_discovery_evidence(
            [evidence_by_id[eid] for eid in event["evidence_ids"] if eid in evidence_by_id]
        )
    ]

    inadmissible_drivers = [
        event["event_id"]
        for event in events
        if not external_driver_admission(event)[0]
        and any(
            impact["status"] in MATERIAL_IMPACT_STATUSES and impact["severity"] != "none"
            for impact in event["impact_assessments"]
        )
    ]

    return {
        "traceability_rate": round(traceable / len(impacts), 4) if impacts else None,
        "impacts_assessed": len(impacts),
        "material_impacts": len(material),
        "unsupported_causation_count": len(unsupported_causation),
        "unsupported_causation_rate": round(len(unsupported_causation) / len(material), 4)
        if material
        else 0.0,
        "unsupported_causation_examples": unsupported_causation,
        "geography_leakage_count": len(geography_leakage),
        "geography_leakage_examples": geography_leakage,
        "missing_as_zero_count": len(missing_as_zero),
        "missing_as_zero_examples": missing_as_zero,
        "event_impact_separation_examples": separation_examples,
        "scenario_completeness_rate": round(complete_outlooks / len(lane_assessments), 4)
        if lane_assessments
        else None,
        "scenario_problems": scenario_problems,
        "preparedness_overreach_count": len(preparedness_problems),
        "preparedness_overreach_examples": preparedness_problems,
        "insufficient_evidence_uses": len(insufficient_uses),
        "no_material_uses": len(no_material_uses),
        "no_material_without_negative_evidence": no_material_without_negative_evidence,
        "material_impact_on_discovery_only_evidence": discovery_only_material,
        "material_impact_on_inadmissible_driver": inadmissible_drivers,
    }


def run() -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
    cases = _load(CASES_PATH)["cases"]
    events = {
        event["event_id"]: event for event in _load(ROOT / "data/events/events.json")["events"]
    }
    evidence_by_id = {
        item["evidence_id"]: item
        for item in _load(ROOT / "data/events/event_evidence.json")["evidence"]
    }
    lane_assessments = _load(ROOT / "data/assessments/lane_assessments.json")["assessments"]
    observations = {
        family: _load(ROOT / f"data/observations/{family}.json")["records"]
        for family in (
            "indicator_observations",
            "trade_observations",
            "port_observations",
            "cost_observations",
        )
    }
    indicators = _load(ROOT / "data/indicators/latest.json")["indicators"]

    failures: list[str] = []
    case_results: list[dict[str, Any]] = []
    for case in cases:
        event = events.get(case["event"]["event_id"])
        if event is None:
            failures.append(f"{case['case_id']}: no built event for {case['event']['event_id']}")
            continue
        case_failures = check_case(case, event, evidence_by_id)
        failures.extend(case_failures)
        case_results.append(
            {
                "case_id": case["case_id"],
                "event_id": event["event_id"],
                "title": event["title"],
                "assessment_cutoff": case["assessment_cutoff"],
                "event_class": event["event_class"],
                "transmission_completeness": event["transmission_chain"]["completeness"],
                "thailand_relevance": event["thailand_relevance"],
                "lane_relevance": [entry["lane_id"] for entry in event["lane_relevance"]],
                "facts_known_at_cutoff": case["expectations"]["facts_known_at_cutoff"],
                "hindsight_limitation": case["expectations"]["hindsight_limitation"],
                "result": "pass" if not case_failures else "fail",
                "failures": case_failures,
            }
        )

    metrics = measure(
        list(events.values()), evidence_by_id, lane_assessments, observations, indicators
    )
    return failures, metrics, case_results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    failures, metrics, case_results = run()

    for result in case_results:
        marker = "PASS" if result["result"] == "pass" else "FAIL"
        print(f"[{marker}] {result['case_id']} {result['event_id']} — {result['title'][:70]}")
        for failure in result["failures"]:
            print(f"       {failure}")

    print("\nMeasured behaviours")
    for key in sorted(metrics):
        if key.endswith("_examples") and not metrics[key]:
            continue
        print(f"  {key:<45} {metrics[key]}")

    if args.write_report:
        REPORT_PATH.write_text(
            json.dumps(
                {
                    "version": "0.8",
                    "generated_at": "2026-07-24T00:00:00Z",
                    "note": (
                        "Produced by scripts/run_historical_validation.py. Each case is "
                        "assessed only against what it records at its own cutoff; later "
                        "knowledge is excluded by construction."
                    ),
                    "cases": case_results,
                    "metrics": metrics,
                    "overall": "pass" if not failures else "fail",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nReport written to {REPORT_PATH.relative_to(ROOT)}")

    if failures:
        print(f"\n{len(failures)} expectation(s) not met.")
        return 1
    print("\nAll historical validation expectations met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
