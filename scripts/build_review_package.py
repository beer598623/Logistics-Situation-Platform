#!/usr/bin/env python3
"""Build the bounded ChatGPT review package a human exports by hand.

No AI API is called. This writes a JSON file; a human opens it, runs it
through ChatGPT themselves, and saves the structured reply into
``data/review/inbound/`` for ``scripts/import_review.py`` to validate.

**The default surface is ``current_publication``.** WO-010 built one combined
package containing every record the repository held, which meant a synthetic
series and a 2021 historical case were handed to ChatGPT alongside a request
for a current assessment -- and nothing downstream could tell the difference
afterwards. A current package now contains only records that qualify for
current publication; everything else is filtered out and counted.

A demonstration package is still useful for exercising the workflow, but it is
a different artifact with a different purpose recorded inside it, and the
approval gate refuses to publish one as current.

Usage::

    python scripts/build_review_package.py [--package-id PKG-YYYYMMDD-NNN]
                                           [--surface current_publication|technical_demo]
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

from analysis.events import active_events, external_driver_admission  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    PUBLISH_BOUNDED_CLAIM,
    TECHNICAL_DEMO,
    qualified_records,
    qualifies_for_current_publication,
    record_dataset,
)
from analysis.review_package import build_input_package  # noqa: E402

PACKAGE_DIR = ROOT / "data" / "review" / "packages"
DATA_CUTOFF_DEFAULT = "2026-07-24T00:00:00Z"

SURFACES = (CURRENT_PUBLICATION, TECHNICAL_DEMO)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cutoff() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 7, 24, tzinfo=UTC)


def _bounded_event(event: dict[str, Any]) -> dict[str, Any]:
    """Reduce an event to what the assessment actually needs.

    Impact assessments are carried as a compact area/status/severity summary
    rather than in full: the reviewer is being asked to assess the evidence,
    not to read the platform's own conclusions back to it.
    """
    return {
        "event_id": event["event_id"],
        "dataset": record_dataset(event),
        "title": event["title"],
        "event_class": event["event_class"],
        "event_type": event["event_type"],
        "lifecycle_status": event["lifecycle_status"],
        "event_date": event.get("event_date"),
        "publication_date": event.get("publication_date"),
        "active_as_of": event.get("active_as_of"),
        "active_basis": event.get("active_basis"),
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
    and no raw response, snapshot or article body exists to carry. Provenance
    travels with the item so the validator on the way back can decide whether
    it was citable, rather than only whether its ID existed.
    """
    return {
        "evidence_id": item["evidence_id"],
        "event_id": item["event_id"],
        "dataset": record_dataset(item),
        "evidence_origin": item["evidence_origin"],
        "retrieval_status": item["retrieval_status"],
        "source_id": item["source_id"],
        "intended_source_id": item.get("intended_source_id"),
        "source_name": item["source_name"],
        "source_class": item["source_class"],
        "source_url": item.get("source_url"),
        "claim": item["claim"],
        "claim_type": item["claim_type"],
        "evidence_role": item["evidence_role"],
        "relation": item["relation"],
        "strength": item["strength"],
        "strength_basis": item["strength_basis"],
        "scope_supported": item["scope_supported"],
        "publication_date": item.get("publication_date"),
        "retrieved_at": item["retrieved_at"],
        "licence_status": item["licence_status"],
        "known_limitations": item.get("known_limitations", []),
    }


def _bounded_lane(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "lane_id": assessment["lane_id"],
        "dataset": assessment.get("dataset"),
        "overall_direction": assessment["overall_direction"],
        "attention_level": assessment["attention_level"],
        "domain_directions": {
            item["domain"]: item["direction"] for item in assessment["domain_assessments"]
        },
        # Which indicator series actually drove each domain, so a returned
        # lane_assessments entry can cite the exact indicator_ids the
        # platform's own math used rather than any indicator merely present
        # elsewhere in the package.
        "domain_indicator_ids": {
            item["domain"]: list(item.get("indicator_ids", []))
            for item in assessment["domain_assessments"]
            if item.get("indicator_ids")
        },
        "indicator_ids": sorted(
            {
                indicator_id
                for item in assessment["domain_assessments"]
                for indicator_id in item.get("indicator_ids", [])
            }
        ),
        "active_event_ids": assessment["active_event_ids"],
        "external_driver_event_ids": assessment["external_driver_event_ids"],
        "chokepoint_exposure": assessment.get("chokepoint_exposure", []),
        "data_gaps": assessment["data_gaps"],
    }


def _bounded_indicator(indicator: dict[str, Any]) -> dict[str, Any]:
    return {
        "series_id": indicator["series_id"],
        "dataset": indicator.get("dataset"),
        "source_id": indicator.get("source_id"),
        "evidence_origin": indicator.get("evidence_origin"),
        # Whether this series describes Thailand directly or a global/proxy
        # benchmark. Set once, at the point the platform knows which source
        # produced the record, so the validator never has to re-guess scope
        # from a series name.
        "geographic_scope": indicator.get("geographic_scope", "thailand"),
        "publication_use_applied": indicator.get("publication_use_applied"),
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


#: What a reviewer is told when the current package has nothing in it. Stated
#: inside the package so the instruction travels with the data rather than
#: depending on whoever pastes it remembering to add the caveat.
ZERO_COVERAGE_INSTRUCTIONS = (
    "This package contains no qualified current evidence: no numeric indicator, no active "
    "operational event, no external driver and no evidence record. No current directional "
    "conclusion can be produced from it. Every lane is 'insufficient evidence', which is a "
    "coverage gap and not a finding that conditions are normal. Do not infer a direction, a "
    "severity or an impact from the absence of records, and do not substitute general "
    "knowledge for the missing evidence: an assessment drawn from outside this package "
    "cannot be traced and will be rejected."
)


def build(package_id: str, *, surface: str = CURRENT_PUBLICATION) -> dict[str, Any]:
    """Assemble a package for one publication surface.

    Filtering is the whole mechanism. The current package is not "the combined
    package minus some things we remembered to remove" -- it is built by
    running every candidate record through the same qualification decision the
    Dashboard uses, and counting what did not pass.
    """
    import yaml

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    source_status = _load(ROOT / "data/source_status/latest.json")
    events = _load(ROOT / "data/events/events.json")["events"]
    evidence = _load(ROOT / "data/events/event_evidence.json")["evidence"]
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    history = _load(ROOT / "data/assessments/assessment_history.json")["entries"]

    if surface == CURRENT_PUBLICATION:
        indicators = _load(ROOT / "data/indicators/current.json")["indicators"]
        lanes = _load(ROOT / "data/assessments/lane_assessments.json")["assessments"]
        thailand = _load(ROOT / "data/assessments/thailand_assessment.json")

        qualified_evidence = qualified_records(
            evidence, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
        qualified_evidence_ids = {item["evidence_id"] for item in qualified_evidence}

        selected_events = active_events(events, evidence_by_id, cutoff=_cutoff(), registry=registry)
        # An external driver only reaches the package once a transmission
        # mechanism is stated. A contextual driver is not a current driver.
        drivers = [
            event
            for event in events
            if event["event_class"] == "external_driver"
            and record_dataset(event) == CURRENT_PUBLICATION
            and external_driver_admission(event)[0]
            and any(
                qualifies_for_current_publication(
                    evidence_by_id[eid],
                    registry=registry,
                    publication_use=PUBLISH_BOUNDED_CLAIM,
                )
                for eid in event.get("evidence_ids", [])
                if eid in evidence_by_id
            )
        ]
        selected = [
            event for event in selected_events if event["event_class"] == "direct_operational_event"
        ] + drivers
        selected_ids = {event["event_id"] for event in selected}

        # Only evidence that actually supports a selected event travels.
        package_evidence = [item for item in qualified_evidence if item["event_id"] in selected_ids]
        excluded = (
            len(evidence)
            - len(package_evidence)
            + len(events)
            - len(selected)
            + len(_load(ROOT / "data/indicators/latest.json")["indicators"])
        )
        _ = qualified_evidence_ids
        # Only human-approved *current* assessments are carried back in.
        previous = [
            entry
            for entry in history
            if entry.get("action") == "approved"
            and entry.get("subject_type") == "approved_assessment"
        ]
        data_gaps = list(thailand["major_data_gaps"])
        if not indicators and not selected and not package_evidence:
            data_gaps.insert(0, ZERO_COVERAGE_INSTRUCTIONS)
    else:
        indicators = _load(ROOT / "data/indicators/latest.json")["indicators"]
        lanes = _load(ROOT / "data/assessments/demo_lane_assessments.json")["assessments"]
        thailand = _load(ROOT / "data/assessments/demo_thailand_assessment.json")
        selected = list(events)
        package_evidence = list(evidence)
        excluded = 0
        previous = list(history)
        data_gaps = list(thailand["major_data_gaps"])

    package = build_input_package(
        package_id=package_id,
        generated_at=DATA_CUTOFF_DEFAULT,
        data_cutoff_at=thailand.get("data_cutoff_at") or DATA_CUTOFF_DEFAULT,
        source_health=source_status,
        key_indicators=[_bounded_indicator(item) for item in indicators],
        lane_status=[_bounded_lane(item) for item in lanes],
        events=[_bounded_event(item) for item in selected],
        evidence=[_bounded_evidence(item) for item in package_evidence],
        previous_assessments=[
            {
                "history_id": entry["history_id"],
                "subject_type": entry["subject_type"],
                "subject_id": entry["subject_id"],
                "recorded_at": entry["recorded_at"],
                "action": entry["action"],
                "summary": entry["summary"],
            }
            for entry in previous
        ],
        data_gaps=data_gaps,
        dataset=surface,
        source_cutoff=DATA_CUTOFF_DEFAULT,
        excluded_fixture_record_count=max(excluded, 0),
    )
    return package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", default="PKG-20260724-001")
    parser.add_argument(
        "--surface",
        default=CURRENT_PUBLICATION,
        choices=list(SURFACES),
        help=(
            "Which publication surface to build from. The default is the current view; "
            "a technical_demo package exercises the workflow and can never be approved "
            "into the current Dashboard."
        ),
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    package = build(args.package_id, surface=args.surface)
    target = Path(args.output) if args.output else PACKAGE_DIR / f"{args.package_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

    shown = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
    print(f"Review package written to {shown}")
    print(f"  dataset        : {package['dataset']}")
    print(f"  purpose        : {package['package_purpose']}")
    print(f"  package_sha256 : {package['package_sha256']}")
    print(f"  data cutoff    : {package['data_cutoff_at']}")
    print(f"  source cutoff  : {package['source_cutoff']}")
    print(
        f"  events         : {len(package['active_operational_events'])} operational, "
        f"{len(package['external_drivers'])} drivers/leads"
    )
    print(f"  indicators     : {len(package['key_indicators'])}")
    print(f"  evidence items : {len(package['evidence_records'])}")
    print(f"  lanes          : {len(package['lane_status'])}")
    print(
        "  excluded       : "
        f"{package['provenance_summary']['excluded_fixture_record_count']} fixture/"
        "non-current records filtered out"
    )
    if args.surface == TECHNICAL_DEMO:
        print()
        print("This is a DEMONSTRATION package. An assessment produced from it cannot be")
        print("approved into the current AI Outlook; the approval gate refuses it.")
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
