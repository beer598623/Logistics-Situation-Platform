#!/usr/bin/env python3
"""Build the bounded ChatGPT review package a human exports by hand.

No AI API is called. This writes a JSON file; a human opens it, runs it
through ChatGPT themselves, and saves the structured reply into
``data/review/inbound/`` for ``scripts/import_review.py`` to validate.

Usage::

    python scripts/build_review_package.py [--package-id PKG-YYYYMMDD-NNN]
                                           [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.review_package import build_input_package  # noqa: E402

PACKAGE_DIR = ROOT / "data" / "review" / "packages"
DATA_CUTOFF_DEFAULT = "2026-07-24T00:00:00Z"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _bounded_event(event: dict[str, Any]) -> dict[str, Any]:
    """Reduce an event to what the assessment actually needs.

    Impact assessments are carried as a compact area/status/severity summary
    rather than in full: the reviewer is being asked to assess the evidence,
    not to read the platform's own conclusions back to it.
    """
    return {
        "event_id": event["event_id"],
        "title": event["title"],
        "event_class": event["event_class"],
        "event_type": event["event_type"],
        "lifecycle_status": event["lifecycle_status"],
        "event_date": event.get("event_date"),
        "publication_date": event.get("publication_date"),
        "geography_ids": event["geography_ids"],
        "chokepoint_ids": event.get("chokepoint_ids", []),
        "node_ids": event.get("node_ids", []),
        "modes": event["modes"],
        "thailand_relevance": event["thailand_relevance"],
        "thailand_relevance_basis": event.get("thailand_relevance_basis", []),
        "lane_relevance": event.get("lane_relevance", []),
        "transmission_chain": event["transmission_chain"],
        "evidence_ids": event["evidence_ids"],
        "current_impact_summary": [
            {
                "area": impact["area"],
                "status": impact["status"],
                "severity": impact["severity"],
            }
            for impact in event["impact_assessments"]
        ],
        "known_limitations": event.get("known_limitations", []),
        "conflicting_evidence": event.get("conflicting_evidence", []),
    }


def _bounded_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Carry only what an assessment may cite.

    The claim is already capped at 600 characters by the evidence contract,
    and no raw response, snapshot or article body exists to carry.
    """
    return {
        "evidence_id": item["evidence_id"],
        "event_id": item["event_id"],
        "source_id": item["source_id"],
        "source_name": item["source_name"],
        "source_class": item["source_class"],
        "source_url": item.get("source_url"),
        "claim": item["claim"],
        "claim_type": item["claim_type"],
        "evidence_role": item["evidence_role"],
        "relation": item["relation"],
        "strength": item["strength"],
        "scope_supported": item["scope_supported"],
        "publication_date": item.get("publication_date"),
        "retrieved_at": item["retrieved_at"],
        "licence_status": item["licence_status"],
        "known_limitations": item.get("known_limitations", []),
    }


def _bounded_lane(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "lane_id": assessment["lane_id"],
        "overall_direction": assessment["overall_direction"],
        "attention_level": assessment["attention_level"],
        "domain_directions": {
            item["domain"]: item["direction"] for item in assessment["domain_assessments"]
        },
        "active_event_ids": assessment["active_event_ids"],
        "external_driver_event_ids": assessment["external_driver_event_ids"],
        "chokepoint_exposure": assessment.get("chokepoint_exposure", []),
        "data_gaps": assessment["data_gaps"],
    }


def _bounded_indicator(indicator: dict[str, Any]) -> dict[str, Any]:
    return {
        "series_id": indicator["series_id"],
        "source_id": indicator.get("source_id"),
        "current_value": indicator["current_value"],
        "current_period": indicator["current_period"],
        "unit": indicator["unit"],
        "month_over_month_pct": indicator["month_over_month_pct"],
        "year_over_year_pct": indicator["year_over_year_pct"],
        "rolling_average": indicator["rolling_average"],
        "deviation_from_baseline": indicator["deviation_from_baseline"],
        "baseline_definition": indicator["baseline_definition"],
        "freshness": indicator["freshness"],
        "revision_status": indicator["revision_status"],
        "periods_available": indicator["periods_available"],
        "periods_missing": indicator["periods_missing"],
        "evidence_classes": indicator["evidence_classes"],
        "limitations": indicator["limitations"] + indicator.get("source_limitations", []),
    }


def build(package_id: str) -> dict[str, Any]:
    source_status = _load(ROOT / "data/source_status/latest.json")
    indicators = _load(ROOT / "data/indicators/latest.json")["indicators"]
    lanes = _load(ROOT / "data/assessments/lane_assessments.json")["assessments"]
    events = _load(ROOT / "data/events/events.json")["events"]
    evidence = _load(ROOT / "data/events/event_evidence.json")["evidence"]
    thailand = _load(ROOT / "data/assessments/thailand_assessment.json")
    history = _load(ROOT / "data/assessments/assessment_history.json")["entries"]

    return build_input_package(
        package_id=package_id,
        generated_at=DATA_CUTOFF_DEFAULT,
        data_cutoff_at=thailand["data_cutoff_at"] or DATA_CUTOFF_DEFAULT,
        source_health=source_status,
        key_indicators=[_bounded_indicator(item) for item in indicators],
        lane_status=[_bounded_lane(item) for item in lanes],
        events=[_bounded_event(item) for item in events],
        evidence=[_bounded_evidence(item) for item in evidence],
        previous_assessments=[
            {
                "history_id": entry["history_id"],
                "subject_type": entry["subject_type"],
                "subject_id": entry["subject_id"],
                "recorded_at": entry["recorded_at"],
                "action": entry["action"],
                "summary": entry["summary"],
            }
            for entry in history
        ],
        data_gaps=thailand["major_data_gaps"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", default="PKG-20260724-001")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    package = build(args.package_id)
    target = Path(args.output) if args.output else PACKAGE_DIR / f"{args.package_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

    shown = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
    print(f"Review package written to {shown}")
    print(f"  package_sha256 : {package['package_sha256']}")
    print(f"  data cutoff    : {package['data_cutoff_at']}")
    print(
        f"  events         : {len(package['active_operational_events'])} operational, "
        f"{len(package['external_drivers'])} drivers/leads"
    )
    print(f"  evidence items : {len(package['evidence_records'])}")
    print(f"  lanes          : {len(package['lane_status'])}")
    print()
    print("Next steps (human-triggered; this repository calls no AI API):")
    print("  1. Open the package and paste it into ChatGPT with the output instructions it")
    print("     contains, asking for a reply matching schemas/review_package_output.schema.json.")
    print("  2. Save the structured reply to data/review/inbound/<package-id>.json.")
    print("  3. Run: python scripts/import_review.py --package-id " + args.package_id)
    print(
        "  4. Run: python scripts/review_decision.py --package-id "
        + args.package_id
        + " --decision approve --reviewer '<name or record>'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
