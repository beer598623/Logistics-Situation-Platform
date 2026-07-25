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

from analysis.assessments import (  # noqa: E402
    DOMAINS,
    build_domain_assessment,
    build_lane_assessment,
    direction_for_derivation,
)
from analysis.events import active_events, event_domain_direction  # noqa: E402
from analysis.indicators import SeriesDerivation, derive_series  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    TECHNICAL_DEMO,
    effective_source_id,
    publishable,
    record_origin,
)
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

#: Series carried in the technical-demonstration indicator export. Source
#: identity is NOT listed here: it is read from each record's own provenance.
#: WO-010 kept a hard-coded series-to-source table, and it drifted -- the
#: freight benchmark was attributed to a fuel publisher and FX to a
#: supply-chain index publisher. A table that can disagree with the data is a
#: table that eventually will.
_DEMO_SERIES = (
    "thailand_port_calls",
    "container_freight_benchmark",
    "thailand_diesel_retail_price",
    "usd_thb_reference_rate",
    "gscpi_index",
    "thailand_lsci",
)


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


def contract_freshness_bounds(
    registry: Mapping[str, Any], source_id: str
) -> tuple[int, int | None]:
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
    for series_id in _DEMO_SERIES:
        records = series_records(observations, series_id)
        if not records:
            continue
        provenance = records[0]["provenance"]
        # Source identity comes from the record, never from a lookup table.
        source_id = provenance["source_id"]
        intended = provenance.get("intended_source_id")
        max_stale, cadence = contract_freshness_bounds(
            registry, effective_source_id(records[0]) or source_id
        )
        baseline_definition = records[0].get("baseline_definition")
        derivation = derive_series(
            series_id,
            records,
            baseline_definition=baseline_definition,
            baseline_value=0.0 if baseline_definition else None,
            max_stale_minutes=max_stale,
            expected_cadence_minutes=cadence,
            now=DATA_CUTOFF,
            origin=record_origin(records[0]),
        )
        derivations[series_id] = derivation
        payload = derivation.to_dict()
        payload["source_id"] = source_id
        payload["intended_source_id"] = intended
        payload["evidence_origin"] = record_origin(records[0])
        payload["dataset"] = TECHNICAL_DEMO
        payload["source_limitations"] = list(provenance["known_limitations"])
        payloads[series_id] = payload
    return derivations, payloads


# ---------------------------------------------------------------------------
# Current publication (WO-010-R1)
# ---------------------------------------------------------------------------

#: What a reader is told wherever the current view has nothing to report.
NO_QUALIFIED_EVIDENCE = (
    "No live-retrieved or human-reviewed evidence exists for this lane. Synthetic and "
    "historical-validation fixtures exercise the analysis engine but are excluded from "
    "the current view, so there is nothing to assess -- which is a coverage gap, not a "
    "finding that conditions are normal."
)


def build_current_lane_assessments(
    lanes: Sequence[Mapping[str, Any]],
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    qualified_events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Lane assessments built from qualified evidence only.

    With zero qualified evidence every domain is ``insufficient_evidence``,
    every lane is ``insufficient_evidence`` overall, no lane reaches watch or
    elevated, and no chokepoint is reported as carrying an active notice. That
    is not a special case coded for the current state -- it falls out of
    feeding the same builder nothing but qualified records.
    """
    active = active_events(qualified_events, evidence_by_id, cutoff=DATA_CUTOFF)
    active_ids = sorted({event["event_id"] for event in active})
    assessments: list[dict[str, Any]] = []

    for lane in lanes:
        lane_id = lane["lane_id"]
        lane_active = sorted(
            {
                event["event_id"]
                for event in active
                if any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
            }
        )
        lane_drivers = sorted(
            {
                event["event_id"]
                for event in qualified_events
                if event["event_class"] == "external_driver"
                and any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
            }
        )

        domain_assessments = []
        for domain in DOMAINS:
            if domain in {
                "operational_event_status",
                "capacity_evidence",
                "transit_time_or_service_evidence",
            }:
                direction, _, evidence_ids, limitations = event_domain_direction(
                    lane_id, qualified_events, _EVENT_DOMAIN_AREAS[domain]
                )
            else:
                direction, evidence_ids, limitations = (
                    "insufficient_evidence",
                    [],
                    [NO_QUALIFIED_EVIDENCE],
                )
            domain_assessments.append(
                build_domain_assessment(
                    domain,
                    direction=direction,
                    basis=(
                        "Derived from qualified (retrieved or human-reviewed) records only. "
                        f"{len(qualified_observations.get('all', []))} such observations exist."
                    ),
                    evidence_ids=evidence_ids,
                    freshness={"status": "no_data", "as_of": None, "age_days": None},
                    known_limitations=[*limitations, NO_QUALIFIED_EVIDENCE],
                )
            )

        assessment = build_lane_assessment(
            lane,
            assessment_id=f"LAS-CUR-{lane_id.replace('LANE-', '')}-{DATA_CUTOFF:%Y%m%d}",
            generated_at=DATA_CUTOFF_ISO,
            data_cutoff_at=DATA_CUTOFF_ISO,
            domain_assessments=domain_assessments,
            active_event_ids=lane_active,
            external_driver_event_ids=lane_drivers,
            chokepoint_exposure=[
                {
                    "chokepoint_id": chokepoint_id,
                    "status": "insufficient_evidence",
                    "basis": (
                        "No notice channel is monitored and no qualified notice is recorded "
                        "for this chokepoint. Absence of a record is not absence of a notice."
                    ),
                }
                for chokepoint_id in lane.get("chokepoint_ids", [])
            ],
            data_gaps=[NO_QUALIFIED_EVIDENCE],
            known_limitations=[NO_QUALIFIED_EVIDENCE, *lane["known_limitations"]],
        )
        assessment["dataset"] = CURRENT_PUBLICATION
        assessment["scenarios"] = build_coverage_only_outlook(lane)
        assessment["preparedness_options"] = build_preparedness_options(lane, assessment)
        assessments.append(assessment)

    _ = active_ids
    return assessments


def build_current_thailand_assessment(
    lane_assessments: Sequence[Mapping[str, Any]],
    qualified_events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
) -> dict[str, Any]:
    """The Thailand Ocean view built from qualified evidence only."""
    active = active_events(qualified_events, evidence_by_id, cutoff=DATA_CUTOFF)
    attention = [
        assessment
        for assessment in lane_assessments
        if assessment["attention_level"] in {"watch", "elevated"}
    ]
    return {
        "assessment_id": f"THA-CUR-OCEAN-{DATA_CUTOFF:%Y%m%d}",
        "dataset": CURRENT_PUBLICATION,
        "subject": "thailand_ocean",
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": DATA_CUTOFF_ISO,
        "overall_direction": combine_directions(
            [assessment["overall_direction"] for assessment in lane_assessments]
        ),
        "evidence_coverage": source_status["overall_status"],
        "coverage_message": source_status["coverage_message"],
        "qualified_observation_count": 0,
        "qualified_event_count": len(qualified_events),
        "lanes_requiring_attention": [
            {
                "lane_id": assessment["lane_id"],
                "attention_level": assessment["attention_level"],
                "overall_direction": assessment["overall_direction"],
            }
            for assessment in attention
        ],
        "active_verified_events": [event["event_id"] for event in active],
        "admitted_external_drivers": [],
        "contextual_external_drivers": [],
        "discovery_leads": [],
        "key_changes": [
            "No current assessment can be produced: the platform holds no live-retrieved or "
            "human-reviewed evidence, so there is nothing to compare and nothing to report."
        ],
        "major_data_gaps": [
            "No source in the registry is enabled and none has completed a controlled live "
            "validation, so live coverage is insufficient.",
            "Every numeric series held by the platform is a synthetic test fixture and is "
            "excluded from this view.",
            "Every event held by the platform is a historical validation fixture with an "
            "assessment cutoff in the past and is excluded from this view.",
            "No Thailand-origin freight rate source is qualified, so no Thailand freight "
            "average is published anywhere in the platform.",
            "No operational-condition source is registered, so no congestion, waiting-time "
            "or berth-delay statement is made anywhere in the platform.",
        ],
        "methodology_version": "0.8",
    }


def build_coverage_only_outlook(lane: Mapping[str, Any]) -> dict[str, Any]:
    """The only outlook publishable with no qualified evidence.

    All three cases say the same thing, because with nothing observed there is
    nothing to differentiate them. What each case does carry is the trigger
    that would have to fire before an assessment could begin -- which is the
    genuinely useful content at zero coverage.
    """
    begin_trigger = [
        {
            "condition": (
                "a source covering this lane completes a controlled live validation and is "
                "enabled, or a human records a reviewed official notice for one of its "
                "nodes or chokepoints"
            ),
            "observable_via": (
                "the source registry's enablement records and the Sources and Methodology section"
            ),
        }
    ]
    narrative = (
        f"No outlook can be offered for {lane['name']}. The platform holds no qualified "
        "evidence for this lane, so its current state is unknown rather than unchanged. "
        "The trigger below is what would have to happen before any assessment could begin."
    )
    case = {
        "narrative": narrative,
        "time_horizon": "1-4_weeks",
        "trigger_conditions": begin_trigger,
        "evidence_ids": [],
        "confidence": "low",
        "data_gaps": [NO_QUALIFIED_EVIDENCE],
        "point_forecast_disclaimer": (
            "No numeric forecast is given anywhere in this platform, and with zero qualified "
            "evidence no qualitative direction is given either."
        ),
    }
    return {
        "outlook_id": f"OUT-CUR-{lane['lane_id'].replace('LANE-', '')}",
        "subject_type": "lane",
        "subject_id": lane["lane_id"],
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": DATA_CUTOFF_ISO,
        "base_case": dict(case),
        "deterioration_case": dict(case),
        "improvement_case": dict(case),
        "known_limitations": [
            "This is a coverage statement, not an outlook. All three cases are identical "
            "because with no qualified evidence there is nothing to differentiate them.",
            *lane.get("known_limitations", []),
        ],
    }


#: Which impact areas each event-derived domain reads.
_EVENT_DOMAIN_AREAS = {
    "operational_event_status": ("transport", "logistics", "import_export"),
    "capacity_evidence": ("capacity",),
    "transit_time_or_service_evidence": ("service", "transport"),
}


def build_lane_records(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
    events: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    source_status: Mapping[str, Any],
    derivations: Mapping[str, SeriesDerivation],
    *,
    dataset: str = TECHNICAL_DEMO,
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
            max_stale, cadence = contract_freshness_bounds(
                registry, effective_source_id(trade_records[0]) or ""
            )
            trade_derivation = derive_series(
                f"th_export_value_{_lane_slug(lane_id)}",
                trade_records,
                max_stale_minutes=max_stale,
                expected_cadence_minutes=cadence,
                now=DATA_CUTOFF,
                origin=record_origin(trade_records[0]),
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
            direction, event_ids, evidence_ids, limitations = event_domain_direction(
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
            assessment_id=(
                f"LAS-{'DEMO' if dataset == TECHNICAL_DEMO else 'CUR'}-"
                f"{lane_id.replace('LANE-', '')}-{DATA_CUTOFF:%Y%m%d}"
            ),
            generated_at=DATA_CUTOFF_ISO,
            data_cutoff_at=DATA_CUTOFF_ISO,
            domain_assessments=domain_assessments,
            active_event_ids=active_events,
            external_driver_event_ids=driver_events,
            chokepoint_exposure=chokepoint_exposure,
            data_gaps=data_gaps,
            known_limitations=[coverage_limitation, *lane["known_limitations"]],
        )
        assessment["dataset"] = dataset
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
        digest = hashlib.sha256(json.dumps(assessment, sort_keys=True).encode("utf-8")).hexdigest()
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
    evidence_by_id = {
        item["evidence_id"]: item
        for item in _load(ROOT / "data/events/event_evidence.json")["evidence"]
    }
    lanes = load_lanes()["lanes"]
    load_dimensions()

    source_status = evaluate_registry_health(registry, {}, now=DATA_CUTOFF)

    # --- current publication: qualified evidence only ----------------------
    qualified_observations = {
        family: publishable(records) for family, records in observations.items()
    }
    qualified_events = publishable(events)
    current_lane_assessments = build_current_lane_assessments(
        lanes, qualified_observations, qualified_events, evidence_by_id, source_status
    )
    current_thailand = build_current_thailand_assessment(
        current_lane_assessments, qualified_events, evidence_by_id, source_status
    )

    # --- technical demonstration: the engine exercised on fixtures ---------
    derivations, indicator_payloads = derive_all_series(observations, registry)
    demo_lane_assessments = build_lane_records(
        observations, events, registry, source_status, derivations, dataset=TECHNICAL_DEMO
    )
    demo_thailand = build_thailand_assessment(demo_lane_assessments, events, source_status)
    demo_thailand["dataset"] = TECHNICAL_DEMO
    demo_thailand["assessment_id"] = f"THA-DEMO-OCEAN-{DATA_CUTOFF:%Y%m%d}"

    history = build_history(current_lane_assessments, current_thailand)

    indicators = {
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": DATA_CUTOFF_ISO,
        "dataset": TECHNICAL_DEMO,
        "note": (
            "TECHNICAL DEMONSTRATION ONLY. Derived from labelled synthetic fixtures via "
            "scripts/build_analysis.py. Every series carries evidence_origin "
            "'synthetic_test_fixture' and source_id 'SYNTHETIC_FIXTURE'; none is a "
            "published statistic and none feeds the current-publication view. Missing "
            "periods are reported as gaps and are never counted as zero."
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
                "dataset": CURRENT_PUBLICATION,
                "generated_at": DATA_CUTOFF_ISO,
                "note": (
                    "Current-publication lane assessments, built from qualified "
                    "(live-retrieved or human-reviewed) evidence only."
                ),
                "assessments": current_lane_assessments,
            },
        ),
        (ASSESSMENT_DIR / "thailand_assessment.json", current_thailand),
        (
            ASSESSMENT_DIR / "demo_lane_assessments.json",
            {
                "version": "0.8",
                "dataset": TECHNICAL_DEMO,
                "generated_at": DATA_CUTOFF_ISO,
                "note": (
                    "TECHNICAL DEMONSTRATION ONLY. Built from synthetic fixtures and "
                    "historical validation cases to exercise the analysis engine. These "
                    "assessments describe the platform's behaviour, not the real world, and "
                    "never feed the current-publication view."
                ),
                "assessments": demo_lane_assessments,
            },
        ),
        (ASSESSMENT_DIR / "demo_thailand_assessment.json", demo_thailand),
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
