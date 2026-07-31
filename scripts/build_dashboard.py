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

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.build_context import parse_timestamp  # noqa: E402
from analysis.events import active_events, event_qualifies_for_current_publication  # noqa: E402
from analysis.indicators import derive_series  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    DERIVED_VALUES_ONLY,
    HISTORICAL_VALIDATION,
    PUBLISH_BOUNDED_CLAIM,
    PUBLISH_DERIVED_VALUE,
    PUBLISH_RAW_VALUE,
    RAW_VALUES_PERMITTED,
    TECHNICAL_DEMO,
    dataset_of,
    is_fixture,
    qualified_records,
    qualifies_for_current_publication,
    record_origin,
    series_homogeneity_problems,
)
from scripts.build_analysis import GLOBAL_OR_PROXY_SERIES  # noqa: E402

PUBLIC = ROOT / "dashboard/public"
DATA = PUBLIC / "data"

#: The pinned as-of time technical-demo and historical-validation panels use.
#: WO-010-R4 §6 keeps these fixed on purpose; only the current-publication
#: panels advance, driven by the shared Build Context (see
#: ``_current_as_of`` below) build_analysis.py wrote.
DATA_CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)
DATA_CUTOFF_ISO = DATA_CUTOFF.isoformat().replace("+00:00", "Z")


def _current_as_of() -> tuple[datetime, str]:
    """The current build's as-of time, read from the shared Build Context.

    ``scripts/build_analysis.py`` is the only writer of this file
    (WO-010-R4 §6): reading it here, rather than resolving an independent
    ``--as-of`` of its own, is what guarantees the Dashboard's current
    panels and Source Health both describe the same moment as the analysis
    build that produced ``data/assessments/thailand_assessment.json`` and
    ``data/source_status/latest.json`` -- there is exactly one place that
    decides what "now" means for a current build, and everything else reads
    it from there.

    Reads ``ROOT`` fresh on every call (a module global, not a constant
    captured at import time) so a test that points ``ROOT`` at a temporary
    copy of the data tree is honoured here too, the same way every other
    path in this module already is.
    """
    context_path = ROOT / "data" / "build_context" / "current.json"
    if not context_path.exists():
        raise SystemExit(
            f"No Build Context found at {context_path.relative_to(ROOT)}. Run "
            "python scripts/build_analysis.py first -- it is the only writer of the "
            "current build's as-of time."
        )
    context = json.loads(context_path.read_text(encoding="utf-8"))
    as_of = parse_timestamp(context["as_of_time"])
    return as_of, context["as_of_time"]


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


_CURRENT_SERIES = (
    "thailand_port_calls",
    "laem_chabang_container_throughput",
    "bangkok_port_container_throughput",
    "thailand_diesel_retail_price",
    "brent_crude_price",
    "container_freight_benchmark",
    "usd_thb_reference_rate",
)


def _contract_bounds(registry: dict[str, Any], source_id: str | None) -> tuple[int, int | None]:
    for source in registry.get("sources", []):
        if source["id"] == source_id:
            return int(source["max_stale_minutes"]), source.get("expected_cadence_minutes")
    return 52560, None


#: Payload fields that describe a raw magnitude -- the current reading itself
#: or a chartable point -- rather than a derived reading. A source qualified
#: only for :data:`PUBLISH_DERIVED_VALUE` may not have any of these published
#: (WO-010-R3 §5): its terms permit a percentage change, an indexed
#: direction, a rolling value or a threshold result, never the raw series a
#: chart would render from.
_RAW_ONLY_SERIES_FIELDS = ("current_value", "previous_period_change", "deviation_from_baseline")


def _current_series_payload(
    series_id: str,
    records: list[dict[str, Any]],
    registry: dict[str, Any],
    *,
    raw_record_ids: frozenset[str] = frozenset(),
    now: datetime | None = None,
    mixed_series_gaps: list[str] | None = None,
) -> dict[str, Any] | None:
    """A current-publication series payload, or ``None`` when nothing qualifies.

    The demonstration panels and the current panels never share a derivation:
    each is built from its own set of records, so a fixture cannot contribute
    a period, a freshness label or a direction to a current reading.

    ``raw_record_ids`` is the set of record IDs whose own source qualifies
    for :data:`PUBLISH_RAW_VALUE` -- the narrower of the two publication-use
    surfaces. When the record backing this series is not in that set, the
    source's terms permit only a derived reading: ``current_value`` and the
    raw chart ``points`` are suppressed rather than published, whatever the
    derivation was able to compute them as.

    ``now`` is the current build's as-of time (WO-010-R4 §6); it defaults to
    the pinned ``DATA_CUTOFF`` so every existing direct call is unaffected.

    WO-010-R4 §5: raw-publication permission is never read from ``records[0]``
    alone. Every record here must first agree on source, unit, geography,
    lane and publication-use disposition (``series_homogeneity_problems``); a
    mixed series -- which cannot occur today, since every current record
    still comes from exactly one source, but must never silently derive a
    reading from an inconsistent set if it ever does -- is excluded rather
    than combined under whichever record happened to be first.
    """
    if not records:
        return None
    homogeneity_problems = series_homogeneity_problems(records, registry=registry)
    if homogeneity_problems:
        # WO-010-R5 §4: a mixed series is a data gap, not a silent omission
        # -- recorded when the caller gives somewhere to record it, so it
        # can reach thailand_situation.json's major_data_gaps rather than
        # simply not appearing in the chart with no trace of why.
        if mixed_series_gaps is not None:
            mixed_series_gaps.append(
                f"Series {series_id!r} was excluded: its qualified records disagree on "
                "source, unit, geography, lane or publication-use disposition and cannot be "
                "safely combined into one reading (" + "; ".join(homogeneity_problems) + ")."
            )
        return None
    source_id = records[0]["provenance"]["source_id"]
    max_stale, cadence = _contract_bounds(registry, source_id)
    derivation = derive_series(
        series_id,
        records,
        max_stale_minutes=max_stale,
        expected_cadence_minutes=cadence,
        now=now or DATA_CUTOFF,
        origin=record_origin(records[0]),
    )
    record_id = records[0]["provenance"]["record_id"]
    raw_permitted = record_id in raw_record_ids
    payload = {
        **derivation.to_dict(),
        "dataset": CURRENT_PUBLICATION,
        "source_id": source_id,
        "evidence_origin": record_origin(records[0]),
        "source_limitations": list(records[0]["provenance"]["known_limitations"]),
        "geographic_scope": (
            "global_or_proxy" if series_id in GLOBAL_OR_PROXY_SERIES else "thailand"
        ),
        "points": _series_points(records) if raw_permitted else [],
        "publication_use_applied": RAW_VALUES_PERMITTED if raw_permitted else DERIVED_VALUES_ONLY,
    }
    if not raw_permitted:
        for field_name in _RAW_ONLY_SERIES_FIELDS:
            payload[field_name] = None
    # WO-010-R4 §5: a second, independent check over the final payload
    # itself, not only over the pre-publication filter that built it -- a
    # derived-only payload must never actually carry a raw field or a raw
    # chart point.
    if payload["publication_use_applied"] == DERIVED_VALUES_ONLY and (
        payload["points"]
        or any(payload.get(field_name) is not None for field_name in _RAW_ONLY_SERIES_FIELDS)
    ):
        raise RuntimeError(f"derived-only series payload {series_id!r} leaked a raw field or point")
    return payload


def publishable_assessment_problems(record: dict[str, Any]) -> list[str]:
    """Whether an approved assessment may actually be published.

    Deliberately independent of the approval script. Approval is a decision
    recorded at one moment by one person; publication happens later, from
    files on disk, and must not assume that whatever is sitting in the
    approved directory earned its place. Each condition is re-checked here.
    """
    problems: list[str] = []
    if record.get("input_dataset") != CURRENT_PUBLICATION:
        problems.append(
            f"bound to a {record.get('input_dataset')!r} package, not a current-publication one"
        )
    if not record.get("input_package_sha256"):
        problems.append("records no input package hash, so it is bound to nothing")
    if record.get("validation_status") != "passed":
        problems.append(f"validation_status is {record.get('validation_status')!r}, not 'passed'")
    if record.get("superseded"):
        problems.append("has been superseded by a later approval")
    fixture_origins = {
        origin
        for origin in (record.get("input_evidence_origin_summary") or {})
        if is_fixture(origin)
    }
    if fixture_origins:
        problems.append("rests on evidence of fixture origin " + ", ".join(sorted(fixture_origins)))
    return problems


# ---------------------------------------------------------------------------
# WO-010-R3 §7: current-view messages, computed from the actual payload
# rather than written as a fixed statement that was only ever true while
# every source was disabled.
# ---------------------------------------------------------------------------


def _live_coverage_statement(
    evidence_coverage: str,
    qualified_observation_count: int,
    current_indicator_count: int,
    qualified_event_count: int,
) -> str:
    if evidence_coverage == "insufficient":
        return (
            "Live coverage is INSUFFICIENT. No source in the registry is enabled and none "
            "has completed a controlled live validation, so the platform holds no "
            "live-retrieved or human-reviewed evidence at all. Every current reading below "
            "is therefore 'insufficient evidence' -- which is a coverage gap, not a finding "
            "that conditions are normal. Synthetic and historical-validation fixtures are "
            "shown only in the separately labelled Technical demonstration panels and never "
            "contribute to a current reading."
        )
    if evidence_coverage == "limited":
        return (
            f"Live coverage is PARTIAL. {qualified_observation_count} qualified observation(s), "
            f"{current_indicator_count} current indicator(s) and {qualified_event_count} "
            "qualified event(s) are in scope at this cutoff, but at least one required "
            "capability still lacks sufficient source coverage. Every current reading not "
            "backed by one of these remains 'insufficient evidence' -- a coverage gap, not a "
            "finding that conditions are normal there. Synthetic and historical-validation "
            "fixtures remain confined to the separately labelled Technical demonstration "
            "panels and never contribute to a current reading."
        )
    return (
        f"Live coverage is SUFFICIENT. {qualified_observation_count} qualified observation(s), "
        f"{current_indicator_count} current indicator(s) and {qualified_event_count} qualified "
        "event(s) are in scope at this cutoff, across every required capability. Synthetic and "
        "historical-validation fixtures remain confined to the separately labelled Technical "
        "demonstration panels and never contribute to a current reading."
    )


def _current_notice_statement(
    current_dataset_notices: list[dict[str, Any]],
    qualified_notices: list[dict[str, Any]],
    current_notice_evidence: list[dict[str, Any]],
) -> str:
    """WO-010-R4 §9: four distinct notice states, not a binary empty/non-empty
    check. ``current_dataset_notices`` is every official-notice evidence item
    tagged for the current-publication dataset, whether or not it qualifies;
    ``qualified_notices`` narrows that to items that individually qualify for
    current publication; ``current_notice_evidence`` narrows further still to
    notices tied to an event that is itself currently active. Each stage can
    be non-empty while the next is empty, and each of those states needs its
    own sentence."""
    if not current_dataset_notices:
        return (
            "No current notice record exists. No notice channel is monitored live and no "
            "human-reviewed notice has been entered, so this is an absence of records rather "
            "than evidence that no notice was published."
        )
    if not qualified_notices:
        return (
            f"{len(current_dataset_notices)} notice record(s) are held for the current "
            "dataset, but none qualifies for current publication -- each fails licence, "
            "retrieval, or reviewer confirmation. No qualified operational notice is "
            "published below."
        )
    if not current_notice_evidence:
        return (
            f"{len(qualified_notices)} qualified notice(s) exist, but the event(s) they "
            "reference are not currently active, so no qualified notice is published against "
            "an active event below."
        )
    return (
        f"{len(current_notice_evidence)} qualified operational notice(s) are recorded below, "
        "each either retrieved live from its publisher or transcribed by a named human "
        "reviewer, against a currently active event. An active event not covered by one of "
        "these still has no qualified notice behind it."
    )


def _trade_current_statement(current_trade_lanes: list[dict[str, Any]]) -> str:
    if not current_trade_lanes:
        return (
            "No qualified Thailand trade observation exists, so no current trade reading is "
            "published."
        )
    return (
        f"{len(current_trade_lanes)} lane(s) below carry at least one qualified Thailand trade "
        "flow reading. A lane not listed here still has no qualified trade observation."
    )


def _cost_current_statement(current_cost_series: list[dict[str, Any]]) -> str:
    if not current_cost_series:
        return (
            "No qualified cost observation exists, so no current cost or freight pressure "
            "reading is published."
        )
    return (
        f"{len(current_cost_series)} qualified cost/FX series below carry a current reading. "
        "A series not listed here still has no qualified observation."
    )


def _events_current_statement(
    current_dataset_events: list[dict[str, Any]],
    qualified_current_events: list[dict[str, Any]],
    current_active: list[dict[str, Any]],
) -> str:
    """WO-010-R4 §9: six distinct event-lifecycle states.

    ``current_dataset_events`` is every event tagged for the current-publication
    dataset, whether or not it individually qualifies. ``qualified_current_events``
    narrows that to events that qualify for current publication (regardless of
    whether they are still active). ``current_active`` narrows further still to
    events confirmed active at this build's cutoff. A qualified-but-inactive
    event (closed, superseded, or a discovery lead that structurally can never
    confirm activity) must never be folded into "every stored event is
    historical" -- that phrasing is reserved for the case where no current-
    dataset event exists at all.
    """
    if not current_dataset_events:
        return (
            "No current event records exist. Every event the platform holds is a historical "
            "validation fixture with an assessment cutoff in the past; none is evidence of a "
            "current condition, and none appears above."
        )
    if not qualified_current_events:
        return (
            f"{len(current_dataset_events)} current-dataset event record(s) exist, but none "
            "qualifies for current publication -- none is backed by qualified current "
            "evidence. No event is published above on that basis."
        )
    if not current_active:
        if all(event["event_class"] == "discovery_lead" for event in qualified_current_events):
            return (
                f"{len(qualified_current_events)} qualified discovery lead(s) exist without "
                "confirmation. A discovery lead may surface an item but can never itself "
                "confirm an active condition, so none is published as active above."
            )
        return (
            f"{len(qualified_current_events)} qualified current event(s) exist, but none is "
            "confirmed active at this cutoff -- each lacks a current active-as-of "
            "confirmation, or its confirmed activity window has closed. None is published as "
            "active above."
        )
    if any(event["event_class"] == "direct_operational_event" for event in current_active):
        return (
            f"{len(current_active)} qualified, currently active event(s) are recorded above, "
            "including at least one direct operational event, each re-confirmed as of its own "
            "active_as_of date. An event not listed here is either not qualified for current "
            "publication or is no longer active."
        )
    return (
        f"{len(current_active)} currently active event(s) are recorded above, but only "
        "contextual external drivers -- no direct operational event is currently active. An "
        "external driver alone does not establish a direct operational impact."
    )


def build_payloads() -> dict[str, Any]:
    current_as_of, current_as_of_iso = _current_as_of()
    # WO-010-R5 §4: every series this build excludes for being a mixed
    # record set is recorded here and folded into thailand_situation.json's
    # major_data_gaps, rather than simply not appearing in a chart.
    mixed_series_gaps: list[str] = []
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

    # ---- Current events, derived once and reused ---------------------------
    # Both the Ocean and the Events payloads read these. Deriving them here
    # keeps one filter in charge of what "current" means across the page.
    current_active = active_events(events, evidence_by_id, cutoff=current_as_of, registry=registry)
    current_active_ids = {event["event_id"] for event in current_active}
    # WO-010-R4 §9: the three progressively narrower event stages the
    # lifecycle-message state matrix distinguishes -- every current-dataset
    # event record, the subset that individually qualifies for current
    # publication, and the subset of those confirmed active at this cutoff.
    current_dataset_events = [event for event in events if dataset_of(event) == CURRENT_PUBLICATION]
    qualified_current_events = [
        event
        for event in current_dataset_events
        if event_qualifies_for_current_publication(event, evidence_by_id, registry=registry)
    ]
    current_dataset_notices = [
        item
        for item in evidence
        if item.get("claim_type") == "official_notice" and dataset_of(item) == CURRENT_PUBLICATION
    ]
    qualified_notices = [
        item
        for item in current_dataset_notices
        if qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
    ]
    current_notice_evidence = [
        item for item in qualified_notices if item["event_id"] in current_active_ids
    ]
    qualified_observations = {
        family: qualified_records(records, registry=registry, publication_use=PUBLISH_DERIVED_VALUE)
        for family, records in observations.items()
    }
    # WO-010-R3 §5: the narrower publish_raw_value surface. Only a record
    # whose own ID appears here may have its raw current reading or raw
    # chart points published; everything else in qualified_observations may
    # still drive a derived reading.
    raw_publishable_records = {
        family: qualified_records(records, registry=registry, publication_use=PUBLISH_RAW_VALUE)
        for family, records in observations.items()
    }
    raw_record_ids = frozenset(
        record["provenance"]["record_id"]
        for records in raw_publishable_records.values()
        for record in records
    )
    current_series = [
        payload
        for series_id in _CURRENT_SERIES
        if (
            payload := _current_series_payload(
                series_id,
                _records_for(qualified_observations, series_id=series_id),
                registry,
                raw_record_ids=raw_record_ids,
                now=current_as_of,
                mixed_series_gaps=mixed_series_gaps,
            )
        )
        is not None
    ]
    current_series_by_id = {item["series_id"]: item for item in current_series}

    # ---- Thailand Logistics Situation ------------------------------------
    situation = {
        "dataset": CURRENT_PUBLICATION,
        "generated_at": current_as_of_iso,
        "data_cutoff_at": thailand["data_cutoff_at"],
        "methodology_version": METHODOLOGY_VERSION,
        "overall_direction": thailand["overall_direction"],
        "evidence_coverage": thailand["evidence_coverage"],
        "coverage_message": thailand["coverage_message"],
        "live_coverage_statement": _live_coverage_statement(
            thailand["evidence_coverage"],
            thailand["qualified_observation_count"],
            thailand["current_indicator_count"],
            thailand["qualified_event_count"],
        ),
        # Every count is carried through from the analysis build, which computes
        # it from the filtered records. None of them is a literal.
        "qualified_observation_count": thailand["qualified_observation_count"],
        "current_indicator_count": thailand["current_indicator_count"],
        "qualified_event_count": thailand["qualified_event_count"],
        "current_lane_coverage": thailand["current_lane_coverage"],
        "current_capability_coverage": thailand["current_capability_coverage"],
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
        "current_cost_pressure": [
            {
                "dataset": CURRENT_PUBLICATION,
                "series_id": item["series_id"],
                "source_id": item["source_id"],
                "evidence_origin": item["evidence_origin"],
                "geographic_scope": item["geographic_scope"],
                "publication_use_applied": item["publication_use_applied"],
                "current_value": item["current_value"],
                "current_period": item["current_period"],
                "unit": item["unit"],
                "month_over_month_pct": item["month_over_month_pct"],
                "freshness": item["freshness"],
            }
            for key, item in sorted(current_series_by_id.items())
            if key
            in {
                "thailand_diesel_retail_price",
                "usd_thb_reference_rate",
                "container_freight_benchmark",
            }
        ],
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
        "generated_at": current_as_of_iso,
        "current_port_series": [
            item
            for key, item in sorted(current_series_by_id.items())
            if key
            in {
                "thailand_port_calls",
                "laem_chabang_container_throughput",
                "bangkok_port_container_throughput",
            }
        ],
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
        # Derived by filtering, not written as an empty list. A qualified
        # notice on a currently active event appears here the moment one
        # exists; today the filter matches nothing.
        "current_operational_notices": [
            {
                "dataset": CURRENT_PUBLICATION,
                "evidence_id": item["evidence_id"],
                "evidence_origin": item["evidence_origin"],
                "retrieval_status": item["retrieval_status"],
                "event_id": item["event_id"],
                "source_id": item["source_id"],
                "source_name": item["source_name"],
                "source_class": item["source_class"],
                "source_url": item.get("source_url"),
                "underlying_publisher": item.get("underlying_publisher"),
                "claim": item["claim"],
                "publication_date": item.get("publication_date"),
                "retrieved_at": item.get("retrieved_at"),
                "licence_status": item["licence_status"],
                "known_limitations": item["known_limitations"],
            }
            for item in current_notice_evidence
        ],
        "current_notice_statement": _current_notice_statement(
            current_dataset_notices, qualified_notices, current_notice_evidence
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
        # Same rule: populated only from qualified impacts on currently active
        # events. Zero qualified evidence produces an empty list through the
        # filter rather than through a literal.
        "current_capacity_and_service_evidence": [
            {
                "dataset": CURRENT_PUBLICATION,
                "event_id": event["event_id"],
                "title": event["title"],
                "area": impact["area"],
                "status": impact["status"],
                "severity": impact["severity"],
                "evidence_strength": impact["evidence_strength"],
                "confidence": impact["confidence"],
                "active_as_of": event.get("active_as_of"),
                "known_limitations": impact["known_limitations"],
            }
            for event in current_active
            for impact in event["impact_assessments"]
            if impact["area"] in {"capacity", "service"}
            and impact["status"] in {"observed", "potential"}
            and impact["severity"] != "none"
            and any(
                qualifies_for_current_publication(
                    evidence_by_id[eid],
                    registry=registry,
                    publication_use=PUBLISH_BOUNDED_CLAIM,
                )
                for eid in impact.get("evidence_ids", [])
                if eid in evidence_by_id
            )
        ],
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

    current_trade_lanes = []
    for lane in lanes:
        slug = _LANE_SLUGS[lane["lane_id"]]
        flows = []
        for direction in ("export", "import"):
            series_id = f"th_{direction}_value_{slug}"
            payload = _current_series_payload(
                series_id,
                _records_for(qualified_observations, series_id=series_id, lane_id=lane["lane_id"]),
                registry,
                raw_record_ids=raw_record_ids,
                now=current_as_of,
                mixed_series_gaps=mixed_series_gaps,
            )
            if payload is not None:
                flows.append({**payload, "flow_direction": direction})
        if flows:
            current_trade_lanes.append(
                {"lane_id": lane["lane_id"], "name": lane["name"], "flows": flows}
            )

    trade = {
        "dataset": TECHNICAL_DEMO,
        "demo_label": (
            "Technical demonstration — every series below is a synthetic fixture standing in "
            "for a production candidate. No Thailand trade statistic has been retrieved."
        ),
        "generated_at": DATA_CUTOFF_ISO,
        "current_statement": _trade_current_statement(current_trade_lanes),
        "current_lane_flows": current_trade_lanes,
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

    current_cost_series = [
        item
        for key, item in sorted(current_series_by_id.items())
        if key
        in {
            "thailand_diesel_retail_price",
            "brent_crude_price",
            "container_freight_benchmark",
            "usd_thb_reference_rate",
        }
    ]

    cost = {
        "dataset": TECHNICAL_DEMO,
        "demo_label": (
            "Technical demonstration — every series below is a synthetic fixture standing in "
            "for a production candidate. No fuel, FX or freight figure has been retrieved."
        ),
        "generated_at": DATA_CUTOFF_ISO,
        "current_statement": _cost_current_statement(current_cost_series),
        "current_cost_series": current_cost_series,
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

    event_payload = {
        "dataset": CURRENT_PUBLICATION,
        "generated_at": current_as_of_iso,
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
        "current_statement": _events_current_statement(
            current_dataset_events, qualified_current_events, current_active
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
    all_approved = [_load(path) for path in sorted(approved_dir.glob("*.json"))]
    approved: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for record in all_approved:
        reasons = publishable_assessment_problems(record)
        if reasons:
            withheld.append(
                {
                    "package_id": record.get("package_id"),
                    "input_dataset": record.get("input_dataset"),
                    "reasons": reasons,
                }
            )
        else:
            approved.append(record)
    ai_outlook = {
        "generated_at": current_as_of_iso,
        "approved_assessments": approved,
        "withheld_assessments": withheld,
        "publication_gate_note": (
            "Publication re-checks every approved assessment independently of the approval "
            "step: it must be bound to a current-publication package, cite that package's "
            "hash, record that it passed validation, not be superseded, and make no current "
            "claim resting on fixture-origin evidence. An assessment failing any of those is "
            "withheld and listed rather than published."
        ),
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
        "package_boundary_note": (
            "The review package a human hands to ChatGPT is built from the current view only. "
            "Synthetic observations, technical-demonstration indicators and lane assessments, "
            "historical-validation events and their evidence are filtered out and counted, and "
            "every approval is bound to the exact package it was produced from by that "
            "package's SHA-256. A demonstration package can be generated for exercising the "
            "workflow, but it records its own purpose and can never be approved into this "
            "section."
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
        "generated_at": current_as_of_iso,
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

    # WO-010-R5 §4: folded in only now, after every _current_series_payload
    # call site (both the situation-panel series above and the trade/cost
    # series built below) has had the chance to append to it.
    situation["major_data_gaps"] = situation["major_data_gaps"] + mixed_series_gaps

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
        "build_status.json": {
            "built_at": current_as_of_iso,
            "fixture_generated_at": DATA_CUTOFF_ISO,
            # WO-010-R4 §9: computed from the same counts the situation panel
            # reports, not a literal -- this must never disagree with
            # situation.qualified_observation_count / .qualified_event_count.
            "qualified_evidence": bool(
                thailand.get("qualified_observation_count") or thailand.get("qualified_event_count")
            ),
            "methodology_version": METHODOLOGY_VERSION,
            "data_cutoff_at": current_as_of_iso,
            "live_coverage": source_status["overall_status"],
            "paid_source_dependency": 0,
            "ai_api_used": False,
        },
    }


def main() -> int:
    # No CLI arguments accepted: unlike ingest_fixtures/build_events_from_cases/
    # build_analysis, this script has no --check mode. An unrecognized flag
    # (e.g. --check) must fail loudly rather than being silently ignored while
    # still writing files -- see docs/operations_runbook.md §1.
    argparse.ArgumentParser().parse_args()

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
