#!/usr/bin/env python3
"""Build the static Dashboard data for GitHub Pages.

Every payload is assembled in memory first and only written once all of them
succeed. That is what makes a failed build safe: if anything raises, the
previously published ``dashboard/public/data`` is left exactly as it was, so a
collection or validation failure degrades to "the last reviewed version is
still up" rather than to a broken or half-written site.

The output is plain JSON read by a vendored, dependency-free script. The
browser never talks to DuckDB or to any service.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.events import (  # noqa: E402
    active_events,
    event_qualifies_for_current_publication,
)
from analysis.indicators import derive_series  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    HISTORICAL_VALIDATION,
    TECHNICAL_DEMO,
    is_fixture,
    record_origin,
)

PUBLIC = ROOT / "dashboard/public"
DATA = PUBLIC / "data"

#: Same pinned cutoff the analysis build uses, so freshness shown on the
#: Dashboard matches the freshness the assessments were computed against.
DATA_CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)
DATA_CUTOFF_ISO = DATA_CUTOFF.isoformat().replace("+00:00", "Z")

METHODOLOGY_VERSION = "0.8"

_LANE_SLUGS = {
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
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _series_points(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chart-ready points that keep missing periods visible as gaps."""
    points = []
    for record in sorted(records, key=lambda item: item["provenance"]["period_end"] or ""):
        measurement = record["measurement"]
        points.append(
            {
                "period": record["provenance"]["period_end"],
                "value": measurement["value"],
                "value_status": measurement["value_status"],
                "unit": measurement["unit"],
            }
        )
    return points


def _records_for(
    observations: dict[str, list[dict[str, Any]]], **match: Any
) -> list[dict[str, Any]]:
    result = []
    for records in observations.values():
        for record in records:
            identifier = record.get("series_id") or record.get("indicator_id")
            if match.get("series_id") and identifier != match["series_id"]:
                continue
            if match.get("lane_id") and record["placement"].get("lane_id") != match["lane_id"]:
                continue
            result.append(record)
    return result


def build_payloads() -> dict[str, Any]:
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    dimensions = _load(ROOT / "data/reference/dimensions.json")
    lanes = _load(ROOT / "data/reference/lanes.json")["lanes"]
    lane_by_id = {lane["lane_id"]: lane for lane in lanes}
    assessments = _load(ROOT / "data/assessments/lane_assessments.json")["assessments"]
    demo_assessments = _load(ROOT / "data/assessments/demo_lane_assessments.json")["assessments"]
    demo_thailand = _load(ROOT / "data/assessments/demo_thailand_assessment.json")
    thailand = _load(ROOT / "data/assessments/thailand_assessment.json")
    cases = _load(ROOT / "data/validation/historical_cases.json")["cases"]
    cutoff_by_event = {case["event"]["event_id"]: case["assessment_cutoff"] for case in cases}
    case_id_by_event = {case["event"]["event_id"]: case["case_id"] for case in cases}
    events = _load(ROOT / "data/events/events.json")["events"]
    evidence = _load(ROOT / "data/events/event_evidence.json")["evidence"]
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    indicators = _load(ROOT / "data/indicators/latest.json")["indicators"]
    source_status = _load(ROOT / "data/source_status/latest.json")
    validation = _load(ROOT / "data/validation/validation_report.json")

    observations = {
        family: _load(ROOT / f"data/observations/{family}.json")["records"]
        for family in (
            "indicator_observations",
            "trade_observations",
            "port_observations",
            "cost_observations",
        )
    }

    # ---- Thailand Logistics Situation ------------------------------------
    situation = {
        "dataset": CURRENT_PUBLICATION,
        "generated_at": DATA_CUTOFF_ISO,
        "data_cutoff_at": thailand["data_cutoff_at"],
        "methodology_version": METHODOLOGY_VERSION,
        "overall_direction": thailand["overall_direction"],
        "evidence_coverage": thailand["evidence_coverage"],
        "coverage_message": thailand["coverage_message"],
        "live_coverage_statement": (
            "Live coverage is INSUFFICIENT. No source in the registry is enabled and none "
            "has completed a controlled live validation, so the platform holds no "
            "live-retrieved or human-reviewed evidence at all. Every current reading below "
            "is therefore 'insufficient evidence' -- which is a coverage gap, not a finding "
            "that conditions are normal. Synthetic and historical-validation fixtures are "
            "shown only in the separately labelled Technical demonstration panels and never "
            "contribute to a current reading."
        ),
        "qualified_observation_count": sum(
            1
            for records in observations.values()
            for record in records
            if not is_fixture(record_origin(record))
        ),
        "qualified_event_count": sum(
            1 for event in events if event_qualifies_for_current_publication(event, evidence_by_id)
        ),
        "key_changes": thailand["key_changes"],
        "lanes_requiring_attention": [
            {
                **entry,
                "name": lane_by_id[entry["lane_id"]]["name"],
                "resolution": lane_by_id[entry["lane_id"]]["resolution"],
            }
            for entry in thailand["lanes_requiring_attention"]
        ],
        "active_verified_events": thailand["active_verified_events"],
        "admitted_external_drivers": thailand["admitted_external_drivers"],
        "contextual_external_drivers": thailand["contextual_external_drivers"],
        "discovery_leads": thailand["discovery_leads"],
        "major_data_gaps": thailand["major_data_gaps"],
        "demo_summary": {
            "dataset": TECHNICAL_DEMO,
            "label": "Technical demonstration — synthetic fixtures, not current intelligence",
            "overall_direction": demo_thailand["overall_direction"],
            "lanes_requiring_attention": len(demo_thailand["lanes_requiring_attention"]),
        },
        "cost_pressure": [
            {
                "dataset": TECHNICAL_DEMO,
                "series_id": indicator["series_id"],
                "source_id": indicator.get("source_id"),
                "intended_source_id": indicator.get("intended_source_id"),
                "evidence_origin": indicator.get("evidence_origin"),
                "current_value": indicator["current_value"],
                "current_period": indicator["current_period"],
                "unit": indicator["unit"],
                "month_over_month_pct": indicator["month_over_month_pct"],
                "freshness": indicator["freshness"],
            }
            for indicator in indicators
            if indicator["series_id"]
            in {
                "thailand_diesel_retail_price",
                "usd_thb_reference_rate",
                "container_freight_benchmark",
            }
        ],
    }

    # ---- Ocean Logistics --------------------------------------------------
    port_series = []
    for series_id in (
        "laem_chabang_container_throughput",
        "bangkok_port_container_throughput",
        "thailand_port_calls",
    ):
        records = _records_for(observations, series_id=series_id)
        if not records:
            continue
        derivation = derive_series(
            series_id,
            records,
            max_stale_minutes=20160,
            now=DATA_CUTOFF,
            origin=record_origin(records[0]),
        )
        port_series.append(
            {
                **derivation.to_dict(),
                "dataset": TECHNICAL_DEMO,
                "source_id": records[0]["provenance"]["source_id"],
                "intended_source_id": records[0]["provenance"].get("intended_source_id"),
                "evidence_origin": record_origin(records[0]),
                "metric": records[0]["metric"],
                "operational_interpretation": records[0]["operational_interpretation"],
                "resolution": records[0]["resolution"],
                "node_id": records[0]["placement"].get("node_id"),
                "source_limitations": records[0]["provenance"]["known_limitations"],
                "points": _series_points(records),
            }
        )

    ocean = {
        "dataset": CURRENT_PUBLICATION,
        "generated_at": DATA_CUTOFF_ISO,
        "demo_port_series": port_series,
        "demo_label": (
            "Technical demonstration — derived from synthetic fixtures. These panels "
            "exercise the analysis engine and describe no real-world condition."
        ),
        "port_interpretation_note": (
            "Every port series here is a VOLUME measure. Rising throughput means more cargo "
            "moved; it is not congestion. No congestion, berth-delay, yard-congestion or "
            "truck-delay statement is made anywhere in this Dashboard, because no "
            "operational-condition source is monitored."
        ),
        "lanes": [
            {
                "lane_id": lane["lane_id"],
                "name": lane["name"],
                "mode": lane["mode"],
                "direction": lane["direction"],
                "resolution": lane["resolution"],
                "origin": lane["origin_scope"]["label"],
                "destination": lane["destination_scope"]["label"],
                "country_ids": lane["country_ids"],
                "node_ids": lane.get("node_ids", []),
                "chokepoint_ids": lane.get("chokepoint_ids", []),
                "selection_evidence": lane["selection_evidence"],
                "data_period_used": lane["data_period_used"],
                "known_limitations": lane["known_limitations"],
                "review_date": lane["review_date"],
                "status": lane["status"],
                "demo_assessment": next(
                    (
                        {
                            "dataset": TECHNICAL_DEMO,
                            "assessment_id": item["assessment_id"],
                            "overall_direction": item["overall_direction"],
                            "attention_level": item["attention_level"],
                            "domain_assessments": item["domain_assessments"],
                            "scenarios": item.get("scenarios"),
                            "preparedness_options": item.get("preparedness_options", []),
                        }
                        for item in demo_assessments
                        if item["lane_id"] == lane["lane_id"]
                    ),
                    None,
                ),
                "assessment": next(
                    (
                        {
                            "dataset": CURRENT_PUBLICATION,
                            "assessment_id": item["assessment_id"],
                            "overall_direction": item["overall_direction"],
                            "attention_level": item["attention_level"],
                            "domain_assessments": item["domain_assessments"],
                            "active_event_ids": item["active_event_ids"],
                            "external_driver_event_ids": item["external_driver_event_ids"],
                            "chokepoint_exposure": item.get("chokepoint_exposure", []),
                            "data_gaps": item["data_gaps"],
                            "scenarios": item.get("scenarios"),
                            "preparedness_options": item.get("preparedness_options", []),
                        }
                        for item in assessments
                        if item["lane_id"] == lane["lane_id"]
                    ),
                    None,
                ),
            }
            for lane in lanes
        ],
        "chokepoints": dimensions["chokepoints"],
        "nodes": dimensions["logistics_nodes"],
        "current_operational_notices": [],
        "current_notice_statement": (
            "No qualified operational notice is recorded. No notice channel is monitored "
            "live and no human-reviewed notice has been entered, so this is an absence of "
            "records rather than evidence that no notice was published."
        ),
        "demo_operational_notices": [
            {
                "dataset": HISTORICAL_VALIDATION,
                "evidence_id": item["evidence_id"],
                "evidence_origin": item["evidence_origin"],
                "retrieval_status": item["retrieval_status"],
                "intended_source_id": item.get("intended_source_id"),
                "assessment_cutoff": cutoff_by_event.get(item["event_id"]),
                "case_id": case_id_by_event.get(item["event_id"]),
                "event_id": item["event_id"],
                "source_name": item["source_name"],
                "source_class": item["source_class"],
                "source_url": item.get("source_url"),
                "claim": item["claim"],
                "publication_date": item.get("publication_date"),
                "retrieved_at": item["retrieved_at"],
                "licence_status": item["licence_status"],
                "known_limitations": item["known_limitations"],
            }
            for item in evidence
            if item["claim_type"] == "official_notice"
        ],
        "current_capacity_and_service_evidence": [],
        "demo_capacity_and_service_evidence": [
            {
                "dataset": HISTORICAL_VALIDATION,
                "assessment_cutoff": cutoff_by_event.get(event["event_id"]),
                "event_id": event["event_id"],
                "title": event["title"],
                "area": impact["area"],
                "status": impact["status"],
                "severity": impact["severity"],
                "evidence_strength": impact["evidence_strength"],
                "confidence": impact["confidence"],
                "known_limitations": impact["known_limitations"],
            }
            for event in events
            for impact in event["impact_assessments"]
            if impact["area"] in {"capacity", "service"}
            and impact["status"] in {"observed", "potential"}
            and impact["severity"] != "none"
        ],
    }

    # ---- Trade and Flow ---------------------------------------------------
    trade_lanes = []
    for lane in lanes:
        slug = _LANE_SLUGS[lane["lane_id"]]
        entry: dict[str, Any] = {
            "lane_id": lane["lane_id"],
            "name": lane["name"],
            "resolution": lane["resolution"],
            "partner_scope_note": (
                f"Lane resolution is {lane['resolution']}. The platform holds no Thailand "
                "port-pair statistics, so this must not be read as a port-pair figure."
            ),
            "flows": [],
        }
        for direction in ("export", "import"):
            series_id = f"th_{direction}_value_{slug}"
            records = _records_for(observations, series_id=series_id, lane_id=lane["lane_id"])
            if not records:
                continue
            derivation = derive_series(
                series_id,
                records,
                max_stale_minutes=105120,
                now=DATA_CUTOFF,
                origin=record_origin(records[0]),
            )
            entry["flows"].append(
                {
                    **derivation.to_dict(),
                    "dataset": TECHNICAL_DEMO,
                    "source_id": records[0]["provenance"]["source_id"],
                    "intended_source_id": records[0]["provenance"].get("intended_source_id"),
                    "evidence_origin": record_origin(records[0]),
                    "flow_direction": direction,
                    "partner_label": records[0]["partner_label"],
                    "partner_scope": records[0]["partner_scope"],
                    "measure": records[0]["measure"],
                    "source_limitations": records[0]["provenance"]["known_limitations"],
                    "points": _series_points(records),
                }
            )
        trade_lanes.append(entry)

    trade = {
        "dataset": TECHNICAL_DEMO,
        "demo_label": (
            "Technical demonstration — every series below is a synthetic fixture standing in "
            "for a production candidate. No Thailand trade statistic has been retrieved."
        ),
        "generated_at": DATA_CUTOFF_ISO,
        "current_statement": (
            "No qualified Thailand trade observation exists, so no current trade reading is "
            "published."
        ),
        "lane_flows": trade_lanes,
        "revision_note": (
            "Published trade statistics can be revised. Every observation carries a revision "
            "number and, where the source provides one, a revision timestamp; the derived "
            "readings report whether the current period is original or revised."
        ),
        "lane_selection_note": (
            "Lane selection methodology is documented in docs/ocean_lane_selection.md. No "
            "quantitative Thailand trade ranking was retrieved, so lanes were selected on "
            "documented structural criteria and every lane records that limitation."
        ),
    }

    # ---- Cost and Freight Pressure ---------------------------------------
    cost_series = []
    for series_id in (
        "thailand_diesel_retail_price",
        "brent_crude_price",
        "container_freight_benchmark",
    ):
        records = _records_for(observations, series_id=series_id)
        if not records:
            continue
        derivation = derive_series(
            series_id,
            records,
            max_stale_minutes=10080,
            now=DATA_CUTOFF,
            origin=record_origin(records[0]),
        )
        cost_series.append(
            {
                **derivation.to_dict(),
                "dataset": TECHNICAL_DEMO,
                "source_id": records[0]["provenance"]["source_id"],
                "intended_source_id": records[0]["provenance"].get("intended_source_id"),
                "evidence_origin": record_origin(records[0]),
                "cost_family": records[0]["cost_family"],
                "benchmark_class": records[0]["benchmark_class"],
                "quotation_claim": records[0]["quotation_claim"],
                "route_scope": records[0]["route_scope"],
                "applies_to_thailand": records[0]["applies_to_thailand"],
                "source_limitations": records[0]["provenance"]["known_limitations"],
                "points": _series_points(records),
            }
        )

    fx_records = _records_for(observations, series_id="usd_thb_reference_rate")
    fx = derive_series(
        "usd_thb_reference_rate",
        fx_records,
        max_stale_minutes=10080,
        now=DATA_CUTOFF,
        origin=record_origin(fx_records[0]),
    )

    cost = {
        "dataset": TECHNICAL_DEMO,
        "demo_label": (
            "Technical demonstration — every series below is a synthetic fixture standing in "
            "for a production candidate. No fuel, FX or freight figure has been retrieved."
        ),
        "generated_at": DATA_CUTOFF_ISO,
        "current_statement": (
            "No qualified cost observation exists, so no current cost or freight pressure "
            "reading is published."
        ),
        "cost_series": cost_series,
        "fx": {
            **fx.to_dict(),
            "dataset": TECHNICAL_DEMO,
            "source_id": fx_records[0]["provenance"]["source_id"],
            "intended_source_id": fx_records[0]["provenance"].get("intended_source_id"),
            "evidence_origin": record_origin(fx_records[0]),
            "points": _series_points(fx_records),
        },
        "benchmark_limitations": [
            "The container freight series is a market benchmark for a third route, published "
            "here only as a directional indicator.",
            "It is not a Thailand shipment quotation, not a Thailand average, and not a rate "
            "any shipper was charged.",
            "No qualified dataset covering Thailand-origin freight rates exists in this "
            "registry, so no Thailand freight average is published anywhere in the platform.",
            "Retail diesel is a domestic cost-context series. It is not a bunker fuel price.",
            "A crude benchmark is upstream energy context; pass-through to bunker cost and "
            "then to freight cost is neither immediate nor proportional.",
        ],
        "surcharge_note": (
            "No surcharge or fee series is published. No source in this registry that "
            "publishes carrier surcharges has been qualified, so the platform records that "
            "as a coverage gap rather than estimating one."
        ),
    }

    # ---- Events and External Drivers --------------------------------------
    def _event_view(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "dataset": event.get("dataset"),
            "evidence_origin": record_origin(event),
            "assessment_cutoff": cutoff_by_event.get(event["event_id"]),
            "case_id": case_id_by_event.get(event["event_id"]),
            "active_as_of": event.get("active_as_of"),
            "active_basis": event.get("active_basis"),
            "event_id": event["event_id"],
            "title": event["title"],
            "event_class": event["event_class"],
            "event_type": event["event_type"],
            "lifecycle_status": event["lifecycle_status"],
            "event_date": event.get("event_date"),
            "publication_date": event.get("publication_date"),
            "retrieval_date": event["retrieval_date"],
            "geography_ids": event["geography_ids"],
            "chokepoint_ids": event.get("chokepoint_ids", []),
            "node_ids": event.get("node_ids", []),
            "modes": event["modes"],
            "thailand_relevance": event["thailand_relevance"],
            "thailand_relevance_basis": event.get("thailand_relevance_basis", []),
            "lane_relevance": event["lane_relevance"],
            "transmission_chain": event["transmission_chain"],
            "event_severity": event.get("event_severity"),
            "impact_assessments": event["impact_assessments"],
            "conflicting_evidence": event.get("conflicting_evidence", []),
            "negative_operational_evidence": event.get("negative_operational_evidence", False),
            "publication_status": event["publication_status"],
            "human_review": event["human_review"],
            "closure_basis": event.get("closure_basis"),
            "last_reviewed_at": event["last_reviewed_at"],
            "known_limitations": event.get("known_limitations", []),
            "evidence": [
                {
                    "evidence_id": eid,
                    "evidence_origin": evidence_by_id[eid]["evidence_origin"],
                    "retrieval_status": evidence_by_id[eid]["retrieval_status"],
                    "strength_basis": evidence_by_id[eid]["strength_basis"],
                    "intended_source_id": evidence_by_id[eid].get("intended_source_id"),
                    "source_name": evidence_by_id[eid]["source_name"],
                    "source_class": evidence_by_id[eid]["source_class"],
                    "source_url": evidence_by_id[eid].get("source_url"),
                    "claim": evidence_by_id[eid]["claim"],
                    "claim_type": evidence_by_id[eid]["claim_type"],
                    "evidence_role": evidence_by_id[eid]["evidence_role"],
                    "strength": evidence_by_id[eid]["strength"],
                    "publication_date": evidence_by_id[eid].get("publication_date"),
                    "retrieved_at": evidence_by_id[eid]["retrieved_at"],
                    "known_limitations": evidence_by_id[eid]["known_limitations"],
                }
                for eid in event["evidence_ids"]
                if eid in evidence_by_id
            ],
        }

    current_active = active_events(events, evidence_by_id, cutoff=DATA_CUTOFF)
    event_payload = {
        "dataset": CURRENT_PUBLICATION,
        "generated_at": DATA_CUTOFF_ISO,
        "current_direct_operational_events": [
            _event_view(event)
            for event in current_active
            if event["event_class"] == "direct_operational_event"
        ],
        "current_external_drivers": [
            _event_view(event)
            for event in current_active
            if event["event_class"] == "external_driver"
        ],
        "current_statement": (
            "No qualified event is recorded. Every event the platform holds is a historical "
            "validation fixture with an assessment cutoff in the past; none is evidence of a "
            "current condition, and none appears above."
        ),
        "demo_label": (
            "Historical validation — each case is assessed at its own cutoff, shown on the "
            "card. These exercise the event model and describe no current condition."
        ),
        "demo_direct_operational_events": [
            _event_view(event)
            for event in events
            if event["event_class"] == "direct_operational_event"
        ],
        "demo_admitted_external_drivers": [
            _event_view(event)
            for event in events
            if event["event_class"] == "external_driver"
            and event["transmission_chain"]["completeness"] == "complete"
        ],
        "demo_contextual_external_drivers": [
            _event_view(event)
            for event in events
            if event["event_class"] == "external_driver"
            and event["transmission_chain"]["completeness"] != "complete"
        ],
        "demo_discovery_leads": [
            _event_view(event) for event in events if event["event_class"] == "discovery_lead"
        ],
        "lifecycle_note": (
            "An external driver stays contextual until a Logistics transmission mechanism is "
            "stated. A discovery lead may surface an item but can never be the sole evidence "
            "for a material impact conclusion."
        ),
    }

    # ---- AI Outlook and Preparedness --------------------------------------
    approved_dir = ROOT / "data/assessments/approved"
    approved = [_load(path) for path in sorted(approved_dir.glob("*.json"))]
    ai_outlook = {
        "generated_at": DATA_CUTOFF_ISO,
        "approved_assessments": approved,
        "review_status": "no_approved_assessment" if not approved else "approved",
        "status_message": (
            "No human-approved AI assessment exists. The human-triggered ChatGPT workflow, "
            "its input and output contracts, its rejection rules and its approval gate are "
            "implemented and tested, but producing an assessment requires a human to run a "
            "package through ChatGPT out-of-band. This section shows only human-approved "
            "assessments, so it is empty rather than speculative."
            if not approved
            else "Showing human-approved assessments only."
        ),
        "boundary_note": (
            "This repository calls no AI API. High or Critical conclusions can never be "
            "published without an explicit human-review record."
        ),
        "dataset": CURRENT_PUBLICATION,
        "current_outlooks": [
            {
                "dataset": CURRENT_PUBLICATION,
                "lane_id": item["lane_id"],
                "lane_name": lane_by_id[item["lane_id"]]["name"],
                "attention_level": item["attention_level"],
                "scenarios": item.get("scenarios"),
                "preparedness_options": item.get("preparedness_options", []),
            }
            for item in assessments
        ],
        "demo_label": (
            "Technical demonstration — generated from synthetic fixtures to exercise the "
            "scenario engine. Not a current outlook."
        ),
        "demo_outlooks": [
            {
                "dataset": TECHNICAL_DEMO,
                "lane_id": item["lane_id"],
                "lane_name": lane_by_id[item["lane_id"]]["name"],
                "attention_level": item["attention_level"],
                "scenarios": item.get("scenarios"),
                "preparedness_options": item.get("preparedness_options", []),
            }
            for item in demo_assessments
        ],
        "deterministic_note": (
            "The outlooks below are a deterministic analytical product derived from the "
            "documented threshold rules, open events and data gaps. They are not an AI "
            "assessment and are shown separately from one. With zero qualified evidence the "
            "current outlooks state only what coverage is missing and what would have to "
            "happen before an assessment could begin."
        ),
    }

    # ---- Sources and Methodology ------------------------------------------
    health_by_id = {item["source_id"]: item for item in source_status["sources"]}
    sources_payload = {
        "generated_at": DATA_CUTOFF_ISO,
        "policy": registry["policy"],
        "registry_version": registry["version"],
        "last_reviewed_at": registry["last_reviewed_at"],
        "overall_status": source_status["overall_status"],
        "coverage_message": source_status["coverage_message"],
        "capabilities": source_status["capabilities"],
        "sources": [
            {
                "source_id": source["id"],
                "name": source["name"],
                "owner": source["owner"],
                "source_class": source["source_class"],
                "landing_url": source["landing_url"],
                "endpoint": source["endpoint"],
                "access_method": source["access_method"],
                "format": source["format"],
                "machine_readable_status": source["machine_readable_status"],
                "licence_status": source["licence_status"],
                "terms_url": source.get("terms_url"),
                "publication_cadence": (source.get("qualification") or {}).get(
                    "publication_cadence"
                ),
                "observed_freshness": (source.get("qualification") or {}).get("observed_freshness"),
                "data_period": (source.get("qualification") or {}).get("data_period"),
                "access_cost": (source.get("qualification") or {}).get("access_cost"),
                "reuse_status": (source.get("qualification") or {}).get("reuse_status"),
                "redistribution_status": (source.get("qualification") or {}).get(
                    "redistribution_status"
                ),
                "logistics_role": (source.get("qualification") or {}).get("logistics_role", []),
                "prototype_eligibility": (source.get("qualification") or {}).get(
                    "prototype_eligibility"
                ),
                "live_validation_status": (source.get("enablement") or {}).get(
                    "live_validation_status"
                ),
                "blockers": (source.get("enablement") or {}).get("blockers", []),
                "enabled": source["enabled"],
                "required_for_publication": source["required_for_publication"],
                "known_limitations": source["known_limitations"],
                "health": health_by_id.get(source["id"]),
            }
            for source in registry["sources"]
        ],
        "methodology": {
            "version": METHODOLOGY_VERSION,
            "documents": [
                "docs/bundle1_architecture.md",
                "docs/data_model_and_persistence.md",
                "docs/evidence_provenance_and_datasets.md",
                "docs/source_qualification_report.md",
                "docs/source_enablement_decisions.md",
                "docs/ocean_lane_selection.md",
                "docs/indicator_definitions.md",
                "docs/freight_proxy_limitations.md",
                "docs/port_pressure_interpretation.md",
                "docs/event_lifecycle.md",
                "docs/external_driver_admission.md",
                "docs/chatgpt_review_workflow.md",
                "docs/human_review_process.md",
                "docs/historical_validation.md",
                "docs/dashboard_user_guide.md",
                "docs/operations_runbook.md",
                "docs/security_and_privacy_boundary.md",
                "docs/known_data_gaps.md",
                "docs/air_land_extension_points.md",
            ],
            "paid_source_dependency": 0,
            "ai_api_used": False,
        },
        "validation_summary": validation["metrics"],
        "validation_overall": validation["overall"],
    }

    return {
        "thailand_situation.json": situation,
        "ocean.json": ocean,
        "trade.json": trade,
        "cost.json": cost,
        "events.json": event_payload,
        "ai_outlook.json": ai_outlook,
        "sources.json": sources_payload,
        "indicators.json": _load(ROOT / "data/indicators/latest.json"),
        "source_status.json": source_status,
        "current_events.json": _load(ROOT / "data/reviewed/current_events.json"),
        "solutions.json": _load(ROOT / "innovation/solution_register.json"),
        "build_status.json": {
            "built_at": DATA_CUTOFF_ISO,
            "fixture_generated_at": DATA_CUTOFF_ISO,
            "qualified_evidence": False,
            "methodology_version": METHODOLOGY_VERSION,
            "data_cutoff_at": DATA_CUTOFF_ISO,
            "live_coverage": "insufficient",
            "paid_source_dependency": 0,
            "ai_api_used": False,
        },
    }


def main() -> int:
    # Assemble everything before touching the published directory: a failure
    # here leaves the last successfully built Dashboard in place.
    payloads = build_payloads()

    DATA.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (DATA / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Dashboard data built at {PUBLIC}")
    for name in sorted(payloads):
        size = (DATA / name).stat().st_size
        print(f"  {name:<28} {size:>9,} bytes")
    print(f"\nLive coverage: {payloads['build_status.json']['live_coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
