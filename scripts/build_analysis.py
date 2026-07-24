#!/usr/bin/env python3
"""Derive indicators, lane assessments and the Thailand assessment.

Reads the version-controlled observations, events and reference data; applies
the documented threshold rules in ``analysis/thresholds.py``; and writes the
derived assessment records that the Dashboard and the ChatGPT review package
both consume.

The build is deterministic. "Now" is pinned to ``DATA_CUTOFF`` rather than the
wall clock, so the committed outputs are stable and a reviewer can regenerate
them and get the same bytes. ``tests/test_derived_outputs.py`` asserts that.

Usage::

    python scripts/build_analysis.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.assessments import DOMAINS, build_domain_assessment, build_lane_assessment  # noqa: E402
from analysis.assessments import direction_for_derivation  # noqa: E402
from analysis.indicators import SeriesDerivation, derive_series  # noqa: E402
from analysis.reference import load_dimensions, load_lanes  # noqa: E402
from analysis.scenarios import build_lane_outlook, build_preparedness_options  # noqa: E402
from analysis.thresholds import combine_directions  # noqa: E402
from collectors.registry import load_registry  # noqa: E402
from collectors.source_health import evaluate_registry_health  # noqa: E402

#: Pinned build time. Freshness ages, and therefore published directions, are
#: computed against this instant rather than the wall clock so that the
#: committed derived records stay reproducible.
DATA_CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)
DATA_CUTOFF_ISO = DATA_CUTOFF.isoformat().replace("+00:00", "Z")

OBSERVATION_DIR = ROOT / "data" / "observations"
EVENTS_PATH = ROOT / "data" / "events" / "events.json"
ASSESSMENT_DIR = ROOT / "data" / "assessments"
INDICATOR_PATH = ROOT / "data" / "indicators" / "latest.json"
SOURCE_STATUS_PATH = ROOT / "data" / "source_status" / "latest.json"

#: Lane-independent series used by every lane, with the rule that reads them.
_SHARED_DOMAIN_SERIES = {
    "port_maritime_activity": ("thailand_port_calls", "PORT-VOLUME-YOY-V1"),
    "freight_benchmark_direction": ("container_freight_benchmark", "FREIGHT-BENCHMARK-MOM-V1"),
    "fuel_pressure": ("thailand_diesel_retail_price", "FUEL-MOM-V1"),
    "fx_pressure": ("usd_thb_reference_rate", "FX-MOM-V1"),
}

_SOURCE_BY_SERIES = {
    "thailand_port_calls": "IMF_PORTWATCH",
    "container_freight_benchmark": "EPPO_FUEL",
    "thailand_diesel_retail_price": "EPPO_FUEL",
    "usd_thb_reference_rate": "GSCPI",
    "gscpi_index": "GSCPI",
    "thailand_lsci": "GSCPI",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_observations() -> dict[str, list[dict[str, Any]]]:
    families = {}
    for family in ("indicator", "trade", "port", "cost"):
        payload = _load(OBSERVATION_DIR / f"{family}_observations.json")
        families[f"{family}_observations"] = payload["records"]
    return families


def series_records(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
    series_id: str,
    *,
    lane_id: str | None = None,
) -> list[dict[str, Any]]:
    """All records for one series, optionally restricted to one lane."""
    matched: list[dict[str, Any]] = []
    for records in observations.values():
        for record in records:
            identifier = record.get("series_id") or record.get("indicator_id")
            if identifier != series_id:
                continue
            if lane_id is not None and record["placement"].get("lane_id") != lane_id:
                continue
            matched.append(dict(record))
    return matched


def contract_freshness_bounds(registry: Mapping[str, Any], source_id: str) -> tuple[int, int | None]:
    for source in registry["sources"]:
        if source["id"] == source_id:
            return int(source["max_stale_minutes"]), source.get("expected_cadence_minutes")
    return 52560, None


def derive_all_series(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
    registry: Mapping[str, Any],
) -> tuple[dict[str, SeriesDerivation], dict[str, dict[str, Any]]]:
    """Derive every non-lane-scoped series once.

    Returns the derivation objects (used to apply threshold rules) and their
    serialisable payloads (used for the indicator export), so no derivation
    ever has to be reconstructed from its own JSON.
    """
    derivations: dict[str, SeriesDerivation] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for series_id, source_id in _SOURCE_BY_SERIES.items():
        records = series_records(observations, series_id)
        if not records:
            continue
        baseline_definition = records[0].get("baseline_definition")
        max_stale, cadence = contract_freshness_bounds(registry, source_id)
        derivation = derive_series(
            series_id,
            records,
            baseline_definition=baseline_definition,
            baseline_value=0.0 if baseline_definition else None,
            max_stale_minutes=max_stale,
            expected_cadence_minutes=cadence,
            now=DATA_CUTOFF,
        )
        derivations[series_id] = derivation
        payload = derivation.to_dict()
        payload["source_id"] = source_id
        payload["source_limitations"] = list(records[0]["provenance"]["known_limitations"])
        payloads[series_id] = payload
    return derivations, payloads


def _event_domain_direction(
    lane_id: str,
    events: Sequence[Mapping[str, Any]],
    areas: Sequence[str],
) -> tuple[str, list[str], list[str], list[str]]:
    """Direction for an event-driven domain, plus the evidence behind it.

    Returns ``(direction, event_ids, evidence_ids, limitations)``. A lane with
    only discovery leads against it gets ``insufficient_evidence``, never
    ``stable``: a lead is not an observation of calm.
    """
    relevant = [
        event
        for event in events
        if any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
    ]
    if not relevant:
        return (
            "insufficient_evidence",
            [],
            [],
            ["No event of any class is recorded against this lane, which is an absence of "
             "evidence rather than evidence of normal operation."],
        )

    leads_only = all(event["event_class"] == "discovery_lead" for event in relevant)
    if leads_only:
        return (
            "insufficient_evidence",
            [event["event_id"] for event in relevant],
            [],
            ["Only discovery-class leads are recorded against this lane; a lead cannot "
             "support a direction."],
        )

    adverse = []
    evidence_ids: list[str] = []
    for event in relevant:
        for impact in event["impact_assessments"]:
            if impact["area"] in areas and impact["status"] in {"observed", "potential"}:
                if impact["severity"] != "none":
                    adverse.append(event["event_id"])
                    evidence_ids.extend(impact.get("evidence_ids", []))
    event_ids = sorted({event["event_id"] for event in relevant})
    if adverse:
        return (
            "deteriorating",
            event_ids,
            sorted(set(evidence_ids)),
            ["Direction reflects observed or potential impact recorded against this lane; "
             "it is not a measurement of current operating conditions."],
        )
    return (
        "stable",
        event_ids,
        sorted(set(evidence_ids)),
        ["Events are recorded against this lane but none carries an observed or potential "
         "impact in these areas."],
    )


def build_lane_records(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
    events: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    source_status: Mapping[str, Any],
    derivations: Mapping[str, SeriesDerivation],
) -> list[dict[str, Any]]:
    lanes = load_lanes()["lanes"]
    assessments: list[dict[str, Any]] = []

    coverage_limitation = (
        f"Overall source coverage is {source_status['overall_status']}: no source in the "
        "registry is enabled, so every reading below is derived from labelled synthetic "
        "fixtures and describes the platform's behaviour, not the real world."
    )

    for lane in lanes:
        lane_id = lane["lane_id"]
        domain_assessments: list[dict[str, Any]] = []

        trade_records = series_records(
            observations, f"th_export_value_{_lane_slug(lane_id)}", lane_id=lane_id
        )
        if trade_records:
            max_stale, cadence = contract_freshness_bounds(registry, "TH_CUSTOMS")
            trade_derivation = derive_series(
                f"th_export_value_{_lane_slug(lane_id)}",
                trade_records,
                max_stale_minutes=max_stale,
                expected_cadence_minutes=cadence,
                now=DATA_CUTOFF,
            )
            direction, _ = direction_for_derivation(trade_derivation, "TH-TRADE-YOY-V1")
            domain_assessments.append(
                build_domain_assessment(
                    "thailand_trade_flow",
                    direction=direction,
                    basis="Year-over-year change in Thailand export value recorded for this lane.",
                    threshold_rule_id="TH-TRADE-YOY-V1",
                    indicator_ids=[trade_derivation.series_id],
                    data_period=trade_derivation.current_period,
                    freshness=trade_derivation.freshness.to_dict(),
                    revision_status=trade_derivation.revision_status,
                    known_limitations=[*trade_derivation.limitations, coverage_limitation],
                )
            )
        else:
            domain_assessments.append(
                build_domain_assessment(
                    "thailand_trade_flow",
                    direction="insufficient_evidence",
                    basis="No trade series is recorded for this lane.",
                    known_limitations=[coverage_limitation],
                )
            )

        for domain, (series_id, rule_id) in _SHARED_DOMAIN_SERIES.items():
            derivation = derivations.get(series_id)
            if derivation is None:
                domain_assessments.append(
                    build_domain_assessment(
                        domain,
                        direction="insufficient_evidence",
                        basis=f"No observation exists for series {series_id}.",
                        known_limitations=[coverage_limitation],
                    )
                )
                continue
            direction, _ = direction_for_derivation(derivation, rule_id)
            domain_assessments.append(
                build_domain_assessment(
                    domain,
                    direction=direction,
                    basis=f"Applied threshold rule {rule_id} to series {series_id}.",
                    threshold_rule_id=rule_id,
                    indicator_ids=[series_id],
                    data_period=derivation.current_period,
                    freshness=derivation.freshness.to_dict(),
                    revision_status=derivation.revision_status,
                    known_limitations=[*derivation.limitations, coverage_limitation],
                )
            )

        for domain, areas in (
            ("operational_event_status", ("transport", "logistics", "import_export")),
            ("capacity_evidence", ("capacity",)),
            ("transit_time_or_service_evidence", ("service", "transport")),
        ):
            direction, event_ids, evidence_ids, limitations = _event_domain_direction(
                lane_id, events, areas
            )
            domain_assessments.append(
                build_domain_assessment(
                    domain,
                    direction=direction,
                    basis=(
                        f"Derived from events recorded against this lane: "
                        f"{', '.join(event_ids) if event_ids else 'none'}."
                    ),
                    evidence_ids=evidence_ids,
                    known_limitations=[*limitations, coverage_limitation],
                )
            )

        domain_assessments.append(
            build_domain_assessment(
                "source_freshness_and_coverage",
                direction="insufficient_evidence"
                if source_status["overall_status"] == "insufficient"
                else "stable",
                basis=source_status["coverage_message"],
                known_limitations=[
                    coverage_limitation,
                    "No source in the registry has completed a controlled live validation.",
                ],
            )
        )

        active_events = sorted(
            {
                event["event_id"]
                for event in events
                if event["event_class"] == "direct_operational_event"
                and event["lifecycle_status"] not in {"closed", "insufficient_evidence"}
                and any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
            }
        )
        driver_events = sorted(
            {
                event["event_id"]
                for event in events
                if event["event_class"] == "external_driver"
                and any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
            }
        )

        chokepoint_exposure = [
            {
                "chokepoint_id": chokepoint_id,
                "status": "official_notice_active"
                if any(
                    chokepoint_id in event.get("chokepoint_ids", [])
                    and event["lifecycle_status"]
                    in {"verified_event", "operational_impact_observed"}
                    for event in events
                )
                else "no_notice",
                "basis": (
                    "An official operational notice is recorded against this chokepoint."
                    if any(
                        chokepoint_id in event.get("chokepoint_ids", [])
                        and event["lifecycle_status"]
                        in {"verified_event", "operational_impact_observed"}
                        for event in events
                    )
                    else "No notice is recorded. The platform monitors no live notice channel, "
                    "so this is an absence of records rather than an absence of notices."
                ),
            }
            for chokepoint_id in lane.get("chokepoint_ids", [])
        ]

        data_gaps = sorted(
            {
                limitation
                for item in domain_assessments
                for limitation in item["known_limitations"]
                if "insufficient" in limitation.lower()
                or "no usable" in limitation.lower()
                or "unavailable" in limitation.lower()
            }
        )

        assessment = build_lane_assessment(
            lane,
            assessment_id=f"LAS-{lane_id.replace('LANE-', '')}-{DATA_CUTOFF:%Y%m%d}",
            generated_at=DATA_CUTOFF_ISO,
            data_cutoff_at=DATA_CUTOFF_ISO,
            domain_assessments=domain_assessments,
            active_event_ids=active_events,
            external_driver_event_ids=driver_events,
            chokepoint_exposure=chokepoint_exposure,
            data_gaps=data_gaps,
            known_limitations=[coverage_limitation, *lane["known_limitations"]],
        )
        assessment["scenarios"] = build_lane_outlook(
            lane, assessment, generated_at=DATA_CUTOFF_ISO, data_cutoff_at=DATA_CUTOFF_ISO
        )
        assessment["preparedness_options"] = build_preparedness_options(lane, assessment)
        assessments.append(assessment)

    return assessments


def _lane_slug(lane_id: str) -> str:
    return {
        "LANE-OCEAN-TH-EASIA-CN": "easia_cn",
        "LANE-OCEAN-TH-JPKR": "jpkr",
        "LANE-OCEAN-TH-ASEAN-SG": "asean_sg",
        "LANE-OCEAN-TH-SASIA": "sasia",
        "LANE-OCEAN-TH-MEGULF": "megulf",
        "LANE-OCEAN-TH-NEUR": "neur",
        "LANE-OCEAN-TH-MED": "med",
        "LANE-OCEAN-TH-USWC": "uswc",
        "LANE-OCEAN-TH-USEC": "usec",
        "LANE-OCEAN-TH-OCEANIA": "oceania",
        "LANE-OCEAN-TH-DOMESTIC": "domestic",
    }[lane_id]


def build_thailand_assessment(
    lane_assessments: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    source_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Roll the lanes up into one Thailand Ocean view, transparently."""
    directions = [assessment["overall_direction"] for assessment in lane_assessments]
    attention = [
        assessment for assessment in lane_assessments if assessment["attention_level"] != "routine"
    ]
    verified_events = [
        event["event_id"]
        for event in events
        if event["event_class"] == "direct_operational_event"
        and event["lifecycle_status"]
        in {"verified_event", "operational_impact_observed", "reported_event"}
    ]
    admitted_drivers = [
        event["event_id"]
        for event in events
        if event["event_class"] == "external_driver"
        and event["transmission_chain"]["completeness"] == "complete"
    ]
    contextual_drivers = [
        event["event_id"]
        for event in events
        if event["event_class"] == "external_driver"
        and event["transmission_chain"]["completeness"] != "complete"
    ]
    leads = [event["event_id"] for event in events if event["event_class"] == "discovery_lead"]

    return {
        "assessment_id": f"THA-OCEAN-{DATA_CUTOFF:%Y%m%d}",
        "subject": "thailand_ocean",
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": DATA_CUTOFF_ISO,
        "overall_direction": combine_directions(directions),
        "evidence_coverage": source_status["overall_status"],
        "coverage_message": source_status["coverage_message"],
        "lanes_requiring_attention": [
            {
                "lane_id": assessment["lane_id"],
                "attention_level": assessment["attention_level"],
                "overall_direction": assessment["overall_direction"],
            }
            for assessment in sorted(
                attention,
                key=lambda item: ["elevated", "watch", "insufficient_evidence"].index(
                    item["attention_level"]
                ),
            )
        ],
        "active_verified_events": verified_events,
        "admitted_external_drivers": admitted_drivers,
        "contextual_external_drivers": contextual_drivers,
        "discovery_leads": leads,
        "key_changes": [
            "First publication of the Ocean module under WO-010. There is no previous "
            "assessment to compare against, so no change can be reported.",
        ],
        "major_data_gaps": [
            "No source in the registry is enabled and none has completed a controlled live "
            "validation, so live coverage is insufficient.",
            "All numeric series are labelled synthetic test fixtures and describe no real "
            "published statistic.",
            "No Thailand-origin freight rate source is qualified, so no Thailand freight "
            "average is published anywhere in the platform.",
            "No transit-time or schedule-reliability source is qualified, so service quality "
            "is assessed only through recorded events.",
            "No operational-condition source is monitored live, so no real-time congestion "
            "statement is made anywhere in the platform.",
        ],
        "methodology_version": "0.8",
    }


def build_history(
    lane_assessments: Sequence[Mapping[str, Any]],
    thailand: Mapping[str, Any],
) -> dict[str, Any]:
    entries = []
    for index, assessment in enumerate(lane_assessments, start=1):
        digest = hashlib.sha256(
            json.dumps(assessment, sort_keys=True).encode("utf-8")
        ).hexdigest()
        entries.append(
            {
                "history_id": f"HIST-{DATA_CUTOFF:%Y%m%d}-{index:03d}",
                "subject_type": "lane_assessment",
                "subject_id": assessment["lane_id"],
                "revision_number": 0,
                "recorded_at": DATA_CUTOFF_ISO,
                "action": "created",
                "content_sha256": digest,
                "supersedes_history_id": None,
                "summary": (
                    f"First assessment of {assessment['lane_id']}: "
                    f"{assessment['overall_direction']}, attention "
                    f"{assessment['attention_level']}."
                ),
                "changed_fields": [],
                "reviewer_record": None,
                "archive_path": None,
            }
        )
    entries.append(
        {
            "history_id": f"HIST-{DATA_CUTOFF:%Y%m%d}-900",
            "subject_type": "thailand_assessment",
            "subject_id": thailand["assessment_id"],
            "revision_number": 0,
            "recorded_at": DATA_CUTOFF_ISO,
            "action": "created",
            "content_sha256": hashlib.sha256(
                json.dumps(thailand, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "supersedes_history_id": None,
            "summary": (
                f"First Thailand Ocean assessment: {thailand['overall_direction']}, evidence "
                f"coverage {thailand['evidence_coverage']}."
            ),
            "changed_fields": [],
            "reviewer_record": None,
            "archive_path": None,
        }
    )
    return {"version": "0.8", "generated_at": DATA_CUTOFF_ISO, "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify without writing.")
    args = parser.parse_args()

    registry = load_registry()
    observations = load_observations()
    events = _load(EVENTS_PATH)["events"]
    load_dimensions()

    source_status = evaluate_registry_health(registry, {}, now=DATA_CUTOFF)
    derivations, indicator_payloads = derive_all_series(observations, registry)
    lane_assessments = build_lane_records(
        observations, events, registry, source_status, derivations
    )
    thailand = build_thailand_assessment(lane_assessments, events, source_status)
    history = build_history(lane_assessments, thailand)

    indicators = {
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": DATA_CUTOFF_ISO,
        "note": (
            "Derived from labelled synthetic fixtures via scripts/build_analysis.py. Every "
            "series carries evidence_class 'synthetic_test_fixture'; none is a published "
            "statistic. Missing periods are reported as gaps and are never counted as zero."
        ),
        "indicators": [indicator_payloads[key] for key in sorted(indicator_payloads)],
    }

    outputs = [
        (INDICATOR_PATH, indicators),
        (SOURCE_STATUS_PATH, source_status),
        (
            ASSESSMENT_DIR / "lane_assessments.json",
            {
                "version": "0.8",
                "generated_at": DATA_CUTOFF_ISO,
                "assessments": lane_assessments,
            },
        ),
        (ASSESSMENT_DIR / "thailand_assessment.json", thailand),
        (ASSESSMENT_DIR / "assessment_history.json", history),
    ]

    stale = []
    for path, payload in outputs:
        rendered = json.dumps(payload, indent=2) + "\n"
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")

    if args.check:
        if stale:
            print("Derived analysis records are out of date:")
            for name in stale:
                print(f"  - {name}")
            return 1
        print("Derived analysis records are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
