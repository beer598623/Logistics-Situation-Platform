#!/usr/bin/env python3
"""Validate repository schemas and cross-record policy constraints.

Schema validity is the floor, not the ceiling. The semantic checks below are
where the platform's actual rules live: missing data must never become zero,
a material impact must carry a transmission mechanism, a discovery lead must
never be the sole support for a conclusion, a proxy must never be labelled a
quotation, and a High or Critical conclusion must never reach the Dashboard
without a human-review record.

Runs entirely offline.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.assessments import (  # noqa: E402
    DOMAINS,
    validate_preparedness_option,
    validate_scenario_outlook,
)
from analysis.contracts import load_json, schema_errors  # noqa: E402
from analysis.events import (  # noqa: E402
    event_qualifies_for_current_publication,
    is_active_at,
    validate_event,
)
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    LIVE_FRESHNESS_STATUSES,
    PUBLISH_DERIVED_VALUE,
    SYNTHETIC_SOURCE_ID,
    dataset_of,
    is_fixture,
    provenance_problems,
    publication_use_problems,
    qualifies_for_current_publication,
    record_intended_source_id,
    record_origin,
    record_source_id,
)
from analysis.reference import (  # noqa: E402
    chokepoint_index,
    country_index,
    geography_index,
    node_index,
)

#: Sources whose governance is settled by a prior Work Order and which WO-010
#: is prohibited from modifying. They are exempt from the qualification-record
#: requirement, and the exemption is named here rather than left implicit.
_PRE_EXISTING_SOURCES = {"TMD_CAP", "GDACS"}

_IMPACT_AREAS = {
    "warehouse",
    "logistics",
    "transport",
    "import_export",
    "inventory",
    "cost",
    "capacity",
    "service",
    "business_continuity",
}

#: Domains whose direction comes from recorded events or source health rather
#: than from a numeric threshold rule, and which therefore legitimately carry
#: no threshold_rule_id.
_NON_THRESHOLD_DOMAINS = {
    "operational_event_status",
    "capacity_evidence",
    "transit_time_or_service_evidence",
    "source_freshness_and_coverage",
}


def validate_item(item: Any, schema_name: str, label: str) -> bool:
    errors = schema_errors(item, schema_name)
    if errors:
        print(f"[FAIL] {label}")
        for error in errors:
            print(f"  - {error}")
        return False
    print(f"[PASS] {label}")
    return True


def report(label: str, problems: list[str]) -> bool:
    if not problems:
        print(f"[PASS] {label}")
        return True
    print(f"[FAIL] {label}")
    for problem in problems:
        print(f"  - {problem}")
    return False


# --------------------------------------------------------------------------
# Legacy WO-002 contracts, retained unchanged
# --------------------------------------------------------------------------


def semantic_checks(event: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    impacts = event.get("impact_assessments", [])
    areas = [impact.get("area") for impact in impacts]
    if set(areas) != _IMPACT_AREAS or len(areas) != 9:
        problems.append("impact_assessments must contain each of the nine areas exactly once")

    evidence_ids = {evidence["evidence_id"] for evidence in event.get("evidence", [])}
    for evidence in event.get("evidence", []):
        if len(evidence.get("content_sha256", "")) != 64:
            problems.append(f"{evidence.get('evidence_id')}: invalid content hash")
        if not evidence.get("retrieved_at"):
            problems.append(f"{evidence.get('evidence_id')}: missing retrieval timestamp")
        if not evidence.get("parser_version"):
            problems.append(f"{evidence.get('evidence_id')}: missing parser version")

    for impact in impacts:
        unknown = set(impact.get("evidence_ids", [])) - evidence_ids
        if unknown:
            problems.append(f"{impact.get('area')}: unknown evidence IDs {sorted(unknown)}")
        if impact.get("severity") in {"high", "critical"} and impact.get(
            "evidence_strength"
        ) not in {"A", "B"}:
            problems.append(
                f"{impact.get('area')}: high/critical impact lacks primary-grade evidence"
            )
        if (
            impact.get("status") in {"observed", "potential"}
            and impact.get("severity") != "none"
            and not impact.get("transmission_mechanism")
        ):
            problems.append(f"{impact.get('area')}: missing transmission mechanism")

    if event.get("publication_status") == "No material impact detected" and not event.get(
        "negative_operational_evidence"
    ):
        problems.append("no-material-impact status requires negative operational evidence")
    return problems


def source_publication_use_checks(registry: dict[str, Any]) -> list[str]:
    """Every source's publication_use must be compatible with its own terms.

    WO-010-R2. ``reuse_status`` answered "may we read this"; the platform was
    acting on "may we republish this", which is a different permission. The
    disposition is checked for every source, disabled or not, so an
    incompatible pairing is caught long before somebody flips ``enabled``.

    TMD_CAP and GDACS are governed by their own prior records and are
    deliberately left untouched, as they were under R1.
    """
    problems: list[str] = []
    for source in registry.get("sources", []):
        if source.get("id") in _PRE_EXISTING_SOURCES:
            continue
        problems.extend(publication_use_problems(source))
    return problems


def source_contract_checks(registry: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    source_ids = [source.get("id") for source in registry.get("sources", [])]
    if len(source_ids) != len(set(source_ids)):
        problems.append("source IDs must be unique")
    for source in registry.get("sources", []):
        source_id = source.get("id")
        if source.get("enabled"):
            if source.get("machine_readable_status") != "verified":
                problems.append(f"{source_id}: enabled source is not machine-readable verified")
            if source.get("licence_status") != "reviewed":
                problems.append(f"{source_id}: enabled source licence has not been reviewed")
            if not source.get("endpoint"):
                problems.append(f"{source_id}: enabled source has no endpoint")

        qualification = source.get("qualification")
        enablement = source.get("enablement")
        if source_id in _PRE_EXISTING_SOURCES:
            continue
        if qualification is None or enablement is None:
            problems.append(
                f"{source_id}: every WO-010 source must carry a qualification and an "
                "enablement record"
            )
            continue

        if qualification.get("access_cost") == "paid":
            problems.append(
                f"{source_id}: a paid source is not eligible under the free-only policy "
                "(Paid-source dependency = 0)"
            )
        if source.get("enabled"):
            # WO-010-R1: every qualification and reuse gate, not just the
            # structural ones. A future enablement cannot slip through on an
            # unreviewed licence or an unobserved freshness.
            if qualification.get("access_cost") not in {"free", "free_with_registration"}:
                problems.append(
                    f"{source_id}: an enabled source must be free or free-with-registration, "
                    f"not {qualification.get('access_cost')!r}"
                )
            if qualification.get("paywall_status") == "full":
                problems.append(f"{source_id}: a fully paywalled source cannot be enabled")
            if qualification.get("reuse_status") in {None, "unknown", "restricted"}:
                problems.append(
                    f"{source_id}: an enabled source requires a reviewed reuse position, "
                    f"not {qualification.get('reuse_status')!r}"
                )
            if qualification.get("redistribution_status") in {None, "unknown", "prohibited"}:
                problems.append(
                    f"{source_id}: an enabled source requires a resolved redistribution "
                    f"position, not {qualification.get('redistribution_status')!r}"
                )
            if qualification.get("prototype_eligibility") != "eligible":
                problems.append(
                    f"{source_id}: an enabled source must be prototype_eligibility "
                    f"'eligible', not {qualification.get('prototype_eligibility')!r}"
                )
            if not qualification.get("observed_freshness"):
                problems.append(
                    f"{source_id}: an enabled source must record an independently observed "
                    "freshness, not a claimed cadence alone"
                )
            if not qualification.get("publication_cadence"):
                problems.append(f"{source_id}: an enabled source must record its cadence")
            if source.get("access_method") != "manual" and (
                enablement.get("live_validation_status") == "not_required"
            ):
                problems.append(
                    f"{source_id}: live validation may only be 'not_required' for a genuinely "
                    "manual, non-network contract"
                )
            if enablement.get("live_validation_status") == "completed" and not enablement.get(
                "live_validation_reference"
            ):
                problems.append(
                    f"{source_id}: a completed live validation must cite its evidence reference"
                )
            if not enablement.get("fixture_test_reference"):
                problems.append(
                    f"{source_id}: an enabled source must cite its fixture test reference"
                )
            if enablement.get("blockers"):
                problems.append(
                    f"{source_id}: an enabled source cannot have unresolved enablement "
                    f"blockers: {enablement['blockers']}"
                )
            if not enablement.get("fixture_test_exists"):
                problems.append(f"{source_id}: an enabled source requires a fixture test")
            if enablement.get("live_validation_status") not in {"completed", "not_required"}:
                problems.append(
                    f"{source_id}: an enabled source requires a completed, or explicitly "
                    "unnecessary, controlled live validation"
                )
            if not enablement.get("parser_fails_closed"):
                problems.append(f"{source_id}: an enabled source requires a fail-closed parser")
            if not enablement.get("response_bounded"):
                problems.append(f"{source_id}: an enabled source requires a bounded response")
            if not enablement.get("schedule_justified"):
                problems.append(
                    f"{source_id}: an enabled source requires a justified collection schedule"
                )
            if not enablement.get("public_repository_safe"):
                problems.append(
                    f"{source_id}: an enabled source must be safe for the public repository"
                )
    return problems


_LIVE_SOURCE_STATUSES = {"fresh", "stale"}


def source_status_checks(source_status: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    sources = source_status.get("sources", [])

    no_data_like = {"no_data", "error", "disabled"}
    for source in sources:
        if source.get("status") in no_data_like and source.get("item_count") == 0:
            problems.append(
                f"{source.get('source_id')}: a gap must never be represented as zero items"
            )

    # A required source that is anything other than fresh/stale is a
    # publication gap, matching collectors/source_health.py's
    # _required_source_gap precedence (checked ahead of "is anything live").
    required_gap_sources = [
        source.get("source_id")
        for source in sources
        if source.get("required_for_publication")
        and source.get("status") not in _LIVE_SOURCE_STATUSES
    ]
    if required_gap_sources and source_status.get("overall_status") != "insufficient":
        problems.append(
            "required source gap must force overall_status to insufficient, not "
            f"{source_status.get('overall_status')!r} (degraded required sources: "
            f"{sorted(required_gap_sources)})"
        )

    status_by_id = {source.get("source_id"): source.get("status") for source in sources}
    required_by_id = {
        source.get("source_id"): bool(source.get("required_for_publication")) for source in sources
    }
    for capability in source_status.get("capabilities", []):
        capability_name = capability.get("capability")
        supporting = capability.get("supporting_sources", [])
        has_live_source = any(status_by_id.get(sid) in _LIVE_SOURCE_STATUSES for sid in supporting)
        degraded_required = [
            sid
            for sid in supporting
            if required_by_id.get(sid) and status_by_id.get(sid) not in _LIVE_SOURCE_STATUSES
        ]

        if capability.get("status") == "sufficient":
            if not has_live_source:
                problems.append(
                    f"{capability_name}: sufficient coverage requires a fresh or stale "
                    "supporting source"
                )
            if degraded_required:
                problems.append(
                    f"{capability_name}: sufficient coverage cannot include a degraded "
                    f"required supporting source {sorted(degraded_required)}"
                )
        elif degraded_required and capability.get("status") != "insufficient":
            problems.append(
                f"{capability_name}: a degraded required supporting source "
                f"{sorted(degraded_required)} must make coverage insufficient, "
                f"not {capability.get('status')!r}"
            )

        if not supporting:
            problems.append(f"{capability_name}: capability has no supporting sources")

    return problems


# --------------------------------------------------------------------------
# WO-010 contracts
# --------------------------------------------------------------------------


def observation_checks(records: list[dict[str, Any]], family: str) -> list[str]:
    """The missing-is-not-zero rule, plus provenance and reference integrity."""
    problems: list[str] = []
    geographies = geography_index()
    countries = country_index()
    nodes = node_index()
    seen: set[str] = set()

    for record in records:
        provenance = record["provenance"]
        measurement = record["measurement"]
        placement = record["placement"]
        record_id = provenance["record_id"]

        available = measurement["value_status"] == "available"
        if available and measurement["value"] is None:
            problems.append(f"{record_id}: value_status is 'available' but the value is null")
        if not available and measurement["value"] is not None:
            problems.append(
                f"{record_id}: value_status is {measurement['value_status']!r} but a value is "
                "present; missing data must never be converted to a number"
            )
        if available and not measurement["unit"]:
            problems.append(f"{record_id}: an available value must record its unit")

        if (
            provenance["period_start"]
            and provenance["period_end"]
            and provenance["period_start"] > provenance["period_end"]
        ):
            problems.append(f"{record_id}: period_start is after period_end")

        geography_id = placement.get("geography_id")
        if geography_id and geography_id not in geographies:
            problems.append(f"{record_id}: unknown geography {geography_id}")
        country_id = placement.get("country_id")
        if country_id and country_id not in countries:
            problems.append(f"{record_id}: unknown country {country_id}")
        node_id = placement.get("node_id")
        if node_id and node_id not in nodes:
            problems.append(f"{record_id}: unknown logistics node {node_id}")

        if record_id in seen:
            problems.append(
                f"{record_id}: duplicate record ID in {family}; re-collection must update a "
                "record rather than duplicate it"
            )
        seen.add(record_id)

        if family == "cost_observations" and (
            record["benchmark_class"] != "actual_quotation"
            and record["quotation_claim"] != "not_a_quotation"
        ):
            problems.append(
                f"{record_id}: benchmark_class {record['benchmark_class']!r} must record "
                "quotation_claim 'not_a_quotation'"
            )
        if (
            family == "port_observations"
            and record["metric"] in {"container_throughput", "cargo_throughput", "vessel_calls"}
            and record["operational_interpretation"] != "volume_only"
        ):
            problems.append(
                f"{record_id}: {record['metric']!r} is a volume metric and must be recorded as "
                "'volume_only'; it cannot support a congestion claim"
            )
    return problems


def lane_checks(lanes: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    geographies = geography_index()
    countries = country_index()
    nodes = node_index()
    chokepoints = chokepoint_index()
    seen: set[str] = set()

    for lane in lanes:
        lane_id = lane["lane_id"]
        if lane_id in seen:
            problems.append(f"{lane_id}: duplicate lane ID")
        seen.add(lane_id)

        for scope in ("origin_scope", "destination_scope"):
            for geography_id in lane[scope]["geography_ids"]:
                if geography_id not in geographies:
                    problems.append(f"{lane_id}/{scope}: unknown geography {geography_id}")
        for country_id in lane["country_ids"]:
            if country_id not in countries:
                problems.append(f"{lane_id}: unknown country {country_id}")
        for node_id in lane.get("node_ids", []):
            if node_id not in nodes:
                problems.append(f"{lane_id}: unknown logistics node {node_id}")
        for chokepoint_id in lane.get("chokepoint_ids", []):
            if chokepoint_id not in chokepoints:
                problems.append(f"{lane_id}: unknown chokepoint {chokepoint_id}")

        for evidence in lane["selection_evidence"]:
            if evidence["source_reference"] is None and evidence["evidence_class"] not in {
                "analytical_inference",
                "insufficient_evidence",
            }:
                problems.append(
                    f"{lane_id}: selection evidence classified {evidence['evidence_class']!r} "
                    "must cite a source reference"
                )
        if lane["data_period_used"] is None and not any(
            "not retrieved" in limitation.lower() or "no quantitative" in limitation.lower()
            for limitation in lane["known_limitations"]
        ):
            problems.append(
                f"{lane_id}: a lane with no data period must state that limitation explicitly"
            )
    return problems


def lane_assessment_checks(
    assessments: list[dict[str, Any]],
    lane_ids: set[str],
    event_ids: set[str],
) -> list[str]:
    problems: list[str] = []
    for assessment in assessments:
        assessment_id = assessment["assessment_id"]
        if assessment["lane_id"] not in lane_ids:
            problems.append(f"{assessment_id}: unknown lane {assessment['lane_id']}")

        domains = [item["domain"] for item in assessment["domain_assessments"]]
        if sorted(domains) != sorted(DOMAINS):
            problems.append(
                f"{assessment_id}: must assess all nine domains exactly once; got {domains}"
            )
        for item in assessment["domain_assessments"]:
            if item["direction"] == "insufficient_evidence" and item["threshold_rule_id"]:
                problems.append(
                    f"{assessment_id}/{item['domain']}: cites threshold rule "
                    f"{item['threshold_rule_id']!r} while reporting insufficient evidence"
                )
            if (
                item["direction"] != "insufficient_evidence"
                and not item["threshold_rule_id"]
                and item["domain"] not in _NON_THRESHOLD_DOMAINS
            ):
                problems.append(
                    f"{assessment_id}/{item['domain']}: an indicator-derived direction must "
                    "cite the threshold rule that produced it"
                )

        unknown_events = (
            set(assessment["active_event_ids"]) | set(assessment["external_driver_event_ids"])
        ) - event_ids
        if unknown_events:
            problems.append(f"{assessment_id}: references unknown events {sorted(unknown_events)}")

        if assessment.get("scenarios"):
            problems.extend(validate_scenario_outlook(assessment["scenarios"]))
        for option in assessment.get("preparedness_options", []):
            problems.extend(validate_preparedness_option(option))
    return problems


# --------------------------------------------------------------------------
# WO-010-R1: provenance truthfulness and the current-publication boundary
# --------------------------------------------------------------------------


def provenance_checks(
    records: list[dict[str, Any]],
    label: str,
    registry_ids: set[str],
) -> list[str]:
    """Every record's origin, retrieval status and source identity must be true."""
    problems: list[str] = []
    for record in records:
        provenance = record.get("provenance", record)
        identifier = provenance.get("record_id") or record.get("evidence_id") or "<unknown>"
        problems.extend(provenance_problems(record, label=f"{label}/{identifier}"))

        source_id = record_source_id(record)
        if source_id and source_id != SYNTHETIC_SOURCE_ID and source_id not in registry_ids:
            problems.append(
                f"{label}/{identifier}: source_id {source_id!r} is not in the source registry"
            )
        intended = record_intended_source_id(record)
        if intended and intended not in registry_ids:
            problems.append(
                f"{label}/{identifier}: intended_source_id {intended!r} is not in the source "
                "registry"
            )
    return problems


def series_source_compatibility(
    records: list[dict[str, Any]],
    label: str,
    registry: dict[str, Any],
) -> list[str]:
    """A series must be compatible with the logistics role of its source.

    This is the check that would have caught WO-010's freight benchmark being
    attributed to a retail fuel publisher: the series' family and the source's
    declared logistics role simply do not overlap.
    """
    problems: list[str] = []
    roles_by_source = {
        source["id"]: set((source.get("qualification") or {}).get("logistics_role", []))
        for source in registry["sources"]
    }
    required_roles = {
        "trade_observations": {"thailand_trade_flow"},
        "port_observations": {"thailand_port_or_maritime_activity"},
        "cost_observations": {
            "domestic_fuel_or_energy_cost",
            "freight_market_benchmark_or_proxy",
            "fx_context",
        },
        "indicator_observations": {
            "fx_context",
            "global_supply_chain_baseline",
            "thailand_port_or_maritime_activity",
            "external_driver_context",
        },
    }
    needed = required_roles.get(label)
    if not needed:
        return problems

    by_series: dict[str, str] = {}
    for record in records:
        series_id = record.get("series_id") or record.get("indicator_id")
        source = record_intended_source_id(record) or record_source_id(record)
        if not series_id or not source:
            continue
        previous = by_series.setdefault(series_id, source)
        if previous != source:
            problems.append(
                f"{label}/{series_id}: conflicting source mappings {previous!r} and "
                f"{source!r}; one series cannot come from two sources"
            )
        roles = roles_by_source.get(source, set())
        if roles and not (roles & needed):
            problems.append(
                f"{label}/{series_id}: source {source!r} declares logistics role(s) "
                f"{sorted(roles)}, which is incompatible with a {label.replace('_', ' ')} "
                f"series (expected one of {sorted(needed)})"
            )
    return problems


def current_publication_checks(
    thailand: dict[str, Any],
    lane_assessments: list[dict[str, Any]],
    events: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
    registry: dict[str, Any],
) -> list[str]:
    """The current view must never rest on a fixture.

    With no qualified evidence, every current reading must be
    ``insufficient_evidence``, no lane may be raised above routine, no event
    may be active and no chokepoint may carry a notice. This is the check the
    Work Order asks for: it fails whenever a current-publication payload
    references a synthetic or historical-validation record as current evidence.
    """
    problems: list[str] = []

    qualified_observations = [
        record
        for records in observations.values()
        for record in records
        if qualifies_for_current_publication(
            record, registry=registry, publication_use=PUBLISH_DERIVED_VALUE
        )
    ]
    # An event carries no origin of its own; it qualifies through its dataset
    # and the evidence behind it. Reading `record_origin` on an event would
    # always return None and quietly classify every event as non-fixture.
    qualified_events = [
        event
        for event in events
        if event_qualifies_for_current_publication(event, evidence_by_id, registry=registry)
    ]
    has_qualified_evidence = bool(qualified_observations) or bool(qualified_events)

    if dataset_of(thailand) != CURRENT_PUBLICATION:
        problems.append(
            f"thailand_assessment: dataset is {dataset_of(thailand)!r}, but this file is the "
            "current-publication view"
        )

    fixture_event_ids = {
        event["event_id"]
        for event in events
        if not event_qualifies_for_current_publication(event, evidence_by_id, registry=registry)
    }
    fixture_evidence_ids = {
        item["evidence_id"] for item in evidence_by_id.values() if is_fixture(record_origin(item))
    }

    referenced = set(thailand.get("active_verified_events", []))
    referenced |= set(thailand.get("admitted_external_drivers", []))
    referenced |= set(thailand.get("contextual_external_drivers", []))
    referenced |= set(thailand.get("discovery_leads", []))
    leaked = referenced & fixture_event_ids
    if leaked:
        problems.append(
            f"thailand_assessment: references fixture events {sorted(leaked)} as current evidence"
        )

    for assessment in lane_assessments:
        assessment_id = assessment["assessment_id"]
        if dataset_of(assessment) != CURRENT_PUBLICATION:
            problems.append(
                f"{assessment_id}: dataset is {dataset_of(assessment)!r} in the "
                "current-publication file"
            )
        lane_events = set(assessment["active_event_ids"]) | set(
            assessment["external_driver_event_ids"]
        )
        lane_leaked = lane_events & fixture_event_ids
        if lane_leaked:
            problems.append(
                f"{assessment_id}: references fixture events {sorted(lane_leaked)} as current "
                "evidence"
            )
        for domain in assessment["domain_assessments"]:
            leaked_evidence = set(domain.get("evidence_ids", [])) & fixture_evidence_ids
            if leaked_evidence:
                problems.append(
                    f"{assessment_id}/{domain['domain']}: cites fixture evidence "
                    f"{sorted(leaked_evidence)} as current evidence"
                )
            status = domain["freshness"]["status"]
            if status in LIVE_FRESHNESS_STATUSES - {"no_data"} and not has_qualified_evidence:
                problems.append(
                    f"{assessment_id}/{domain['domain']}: reports real-world freshness "
                    f"{status!r} with no qualified evidence behind it"
                )

    if not has_qualified_evidence:
        if thailand.get("overall_direction") != "insufficient_evidence":
            problems.append(
                "thailand_assessment: overall_direction is "
                f"{thailand.get('overall_direction')!r} with zero qualified evidence; it must "
                "be 'insufficient_evidence'"
            )
        if thailand.get("active_verified_events"):
            problems.append(
                "thailand_assessment: reports active verified events with zero qualified evidence"
            )
        if thailand.get("lanes_requiring_attention"):
            problems.append(
                "thailand_assessment: raises lanes to attention with zero qualified evidence"
            )
        for assessment in lane_assessments:
            if assessment["attention_level"] in {"watch", "elevated"}:
                problems.append(
                    f"{assessment['assessment_id']}: attention level "
                    f"{assessment['attention_level']!r} with zero qualified evidence"
                )
            if assessment["overall_direction"] != "insufficient_evidence":
                problems.append(
                    f"{assessment['assessment_id']}: overall_direction "
                    f"{assessment['overall_direction']!r} with zero qualified evidence"
                )
            for exposure in assessment.get("chokepoint_exposure", []):
                if exposure["status"] == "official_notice_active":
                    problems.append(
                        f"{assessment['assessment_id']}/{exposure['chokepoint_id']}: reports an "
                        "active official notice with zero qualified evidence"
                    )

    return problems


def event_dataset_checks(
    events: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    cutoff: datetime,
    registry: dict[str, Any],
) -> list[str]:
    """No fixture-backed event may be publishable as currently active."""
    problems: list[str] = []
    for event in events:
        decision = is_active_at(event, evidence_by_id, cutoff=cutoff, registry=registry)
        if decision.is_active and not event_qualifies_for_current_publication(
            event, evidence_by_id, registry=registry
        ):
            problems.append(
                f"{event['event_id']}: a fixture-origin event was judged currently active"
            )
        if event.get("active_as_of") and not event.get("active_basis"):
            problems.append(f"{event['event_id']}: active_as_of recorded with no active_basis")
    return problems


def main() -> int:
    ok = True

    # ---- Legacy WO-002 records -------------------------------------------
    candidates = load_json(ROOT / "data/candidates/latest.json")
    for index, item in enumerate(candidates.get("candidates", [])):
        ok &= validate_item(item, "candidate_event.schema.json", f"candidate[{index}]")

    reviewed = load_json(ROOT / "data/reviewed/current_events.json")
    for index, item in enumerate(reviewed.get("events", [])):
        item_ok = validate_item(item, "reviewed_event.schema.json", f"reviewed_event[{index}]")
        for problem in semantic_checks(item):
            print(f"[FAIL] reviewed_event[{index}] semantic: {problem}")
            item_ok = False
        ok &= item_ok

    # ---- Source registry --------------------------------------------------
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    ok &= validate_item(registry, "source_contract.schema.json", "source_contract_registry")
    ok &= report("source_contract_registry semantics", source_contract_checks(registry))
    ok &= report("source publication use", source_publication_use_checks(registry))

    source_status = load_json(ROOT / "data/source_status/latest.json")
    ok &= validate_item(source_status, "source_status.schema.json", "source_status")
    ok &= report("source_status semantics", source_status_checks(source_status))

    # ---- Reference dimensions and lanes -----------------------------------
    dimensions = load_json(ROOT / "data/reference/dimensions.json")
    ok &= validate_item(dimensions, "reference_dimensions.schema.json", "reference_dimensions")

    lanes = load_json(ROOT / "data/reference/lanes.json")["lanes"]
    lanes_ok = True
    for lane in lanes:
        if schema_errors(lane, "lane.schema.json"):
            lanes_ok = validate_item(lane, "lane.schema.json", f"lane[{lane['lane_id']}]")
    if lanes_ok:
        print(f"[PASS] lanes ({len(lanes)} records)")
    ok &= lanes_ok
    ok &= report("lane semantics", lane_checks(lanes))

    # ---- Observations -----------------------------------------------------
    observation_schemas = {
        "indicator_observations": "indicator_observation.schema.json",
        "trade_observations": "trade_observation.schema.json",
        "port_observations": "port_transport_observation.schema.json",
        "cost_observations": "cost_observation.schema.json",
    }
    registry_ids = {source["id"] for source in registry["sources"]}
    all_observations: dict[str, list[dict[str, Any]]] = {}
    for family, schema_name in observation_schemas.items():
        records = load_json(ROOT / f"data/observations/{family}.json")["records"]
        all_observations[family] = records
        family_ok = True
        for record in records:
            errors = schema_errors(record, schema_name)
            if errors:
                print(f"[FAIL] {family}/{record['provenance']['record_id']}")
                for error in errors:
                    print(f"  - {error}")
                family_ok = False
        if family_ok:
            print(f"[PASS] {family} ({len(records)} records)")
        ok &= family_ok
        ok &= report(f"{family} semantics", observation_checks(records, family))
        ok &= report(f"{family} provenance", provenance_checks(records, family, registry_ids))
        ok &= report(
            f"{family} source compatibility",
            series_source_compatibility(records, family, registry),
        )

    # ---- Events and evidence ---------------------------------------------
    events = load_json(ROOT / "data/events/events.json")["events"]
    evidence = load_json(ROOT / "data/events/event_evidence.json")["evidence"]
    evidence_by_id = {item["evidence_id"]: item for item in evidence}

    evidence_ok = True
    for item in evidence:
        errors = schema_errors(item, "event_evidence.schema.json")
        if errors:
            print(f"[FAIL] event_evidence/{item['evidence_id']}")
            for error in errors:
                print(f"  - {error}")
            evidence_ok = False
    if evidence_ok:
        print(f"[PASS] event_evidence ({len(evidence)} records)")
    ok &= evidence_ok
    ok &= report(
        "event_evidence provenance", provenance_checks(evidence, "event_evidence", registry_ids)
    )
    ok &= report(
        "event dataset semantics",
        event_dataset_checks(events, evidence_by_id, datetime(2026, 7, 24, tzinfo=UTC), registry),
    )

    events_ok = True
    event_problems: list[str] = []
    for event in events:
        errors = schema_errors(event, "logistics_event.schema.json")
        if errors:
            print(f"[FAIL] event/{event['event_id']}")
            for error in errors:
                print(f"  - {error}")
            events_ok = False
        event_problems.extend(validate_event(event, evidence_by_id))
    if events_ok:
        print(f"[PASS] events ({len(events)} records)")
    ok &= events_ok
    ok &= report("event semantics", event_problems)

    # ---- Assessments ------------------------------------------------------
    assessments = load_json(ROOT / "data/assessments/lane_assessments.json")["assessments"]
    assessments_ok = True
    for assessment in assessments:
        # preparedness_options is an additive field the Dashboard consumes; the
        # lane assessment contract itself stays focused on the assessment.
        payload = {key: value for key, value in assessment.items() if key != "preparedness_options"}
        errors = schema_errors(payload, "lane_assessment.schema.json")
        if errors:
            print(f"[FAIL] lane_assessment/{assessment['assessment_id']}")
            for error in errors:
                print(f"  - {error}")
            assessments_ok = False
    if assessments_ok:
        print(f"[PASS] lane_assessments ({len(assessments)} records)")
    ok &= assessments_ok
    ok &= report(
        "lane assessment semantics",
        lane_assessment_checks(
            assessments,
            {lane["lane_id"] for lane in lanes},
            {event["event_id"] for event in events},
        ),
    )

    thailand = load_json(ROOT / "data/assessments/thailand_assessment.json")
    ok &= report(
        "current publication boundary",
        current_publication_checks(
            thailand, assessments, events, evidence_by_id, all_observations, registry
        ),
    )

    demo_path = ROOT / "data/assessments/demo_lane_assessments.json"
    if demo_path.exists():
        demo = load_json(demo_path)["assessments"]
        demo_ok = True
        for assessment in demo:
            payload = {
                key: value for key, value in assessment.items() if key != "preparedness_options"
            }
            errors = schema_errors(payload, "lane_assessment.schema.json")
            if errors:
                print(f"[FAIL] demo_lane_assessment/{assessment['assessment_id']}")
                for error in errors:
                    print(f"  - {error}")
                demo_ok = False
        if demo_ok:
            print(f"[PASS] demo_lane_assessments ({len(demo)} records)")
        ok &= demo_ok
        ok &= report(
            "demo lane assessment semantics",
            lane_assessment_checks(
                demo,
                {lane["lane_id"] for lane in lanes},
                {event["event_id"] for event in events},
            ),
        )

    history = load_json(ROOT / "data/assessments/assessment_history.json")
    ok &= validate_item(history, "assessment_history.schema.json", "assessment_history")

    # ---- Review packages, when any exist ----------------------------------
    for package_path in sorted((ROOT / "data/review/packages").glob("*.json")):
        ok &= validate_item(
            load_json(package_path),
            "review_package_input.schema.json",
            f"review_package_input[{package_path.stem}]",
        )

    print("\nValidation successful." if ok else "\nValidation failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
