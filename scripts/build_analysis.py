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
    build_domain_assessment,
    build_lane_assessment,
    direction_for_derivation,
)
from analysis.build_context import (  # noqa: E402
    build_context_record,
    context_problems,
    exclude_future_dated,
    latest_timestamp,
    parse_timestamp,
    resolve_current_as_of,
    to_iso,
)
from analysis.contracts import schema_errors  # noqa: E402
from analysis.events import (  # noqa: E402
    active_events,
    event_domain_direction,
    event_qualifies_for_current_publication,
)
from analysis.indicators import SeriesDerivation, derive_series  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    DERIVED_VALUES_ONLY,
    PUBLISH_BOUNDED_CLAIM,
    PUBLISH_DERIVED_VALUE,
    PUBLISH_RAW_VALUE,
    RAW_VALUES_PERMITTED,
    TECHNICAL_DEMO,
    SeriesHomogeneityError,
    acquisition_binding_problems,
    build_record_index,
    effective_source_id,
    qualified_records,
    qualifies_for_current_publication,
    record_origin,
    record_source_id,
    series_homogeneity_problems,
    source_health_publication_consistency_problems,
)
from analysis.reference import load_dimensions, load_lanes  # noqa: E402
from analysis.scenarios import build_lane_outlook, build_preparedness_options  # noqa: E402
from analysis.thresholds import combine_directions  # noqa: E402
from collectors.collection_runs import (  # noqa: E402
    load_collection_runs,
    load_manual_review_events,
)
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
CURRENT_INDICATOR_PATH = ROOT / "data" / "indicators" / "current.json"
SOURCE_STATUS_PATH = ROOT / "data" / "source_status" / "latest.json"

#: The current build's shared Build Context (WO-010-R4 §6). This is the only
#: script that writes it; scripts/build_dashboard.py and scripts/
#: build_review_package.py read it to guarantee they share the same as-of
#: time this build resolved, rather than each independently pinning one.
BUILD_CONTEXT_PATH = ROOT / "data" / "build_context" / "current.json"

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
# Current publication (WO-010-R1, positive path completed by WO-010-R2)
# ---------------------------------------------------------------------------

#: What a reader is told wherever the current view has nothing to report.
NO_QUALIFIED_EVIDENCE = (
    "No live-retrieved or human-reviewed evidence exists for this lane. Synthetic and "
    "historical-validation fixtures exercise the analysis engine but are excluded from "
    "the current view, so there is nothing to assess -- which is a coverage gap, not a "
    "finding that conditions are normal."
)

#: Which impact areas each event-derived domain reads.
_EVENT_DOMAIN_AREAS = {
    "operational_event_status": ("transport", "logistics", "import_export"),
    "capacity_evidence": ("capacity",),
    "transit_time_or_service_evidence": ("service", "transport"),
}


def qualified_series_records(
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    series_id: str,
    *,
    lane_id: str | None = None,
) -> list[dict[str, Any]]:
    """Qualified records for one series.

    Reads the already-filtered families, so a demonstration record cannot
    reach a current derivation even by sharing a series identifier with a
    qualified one. Current and demonstration records are never combined into
    one derivation: they are drawn from different collections entirely.
    """
    matched: list[dict[str, Any]] = []
    for records in qualified_observations.values():
        for record in records:
            identifier = record.get("series_id") or record.get("indicator_id")
            if identifier != series_id:
                continue
            if lane_id is not None and record["placement"].get("lane_id") != lane_id:
                continue
            matched.append(dict(record))
    return matched


def derive_current_series(
    records: Sequence[Mapping[str, Any]],
    series_id: str,
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> SeriesDerivation:
    """Derive one current series from qualified records.

    Source identity, and therefore the freshness contract applied, comes from
    the records' own provenance. Freshness ages against ``now`` -- the
    current build's as-of time (WO-010-R4 §6), defaulting to the pinned
    ``DATA_CUTOFF`` only when a caller supplies nothing, so every existing
    direct call keeps behaving exactly as before.

    WO-010-R5 §4: guards itself against a mixed record set rather than
    trusting every caller to pre-check. No current analytical path may call
    this on unchecked records any more, because there is no path into this
    function that skips the check -- raises :class:`SeriesHomogeneityError`
    (not a plain ``ValueError``) so a caller that wants to convert a mixed
    series into ``insufficient_evidence`` plus a recorded limitation, rather
    than letting the build fail, can catch exactly this and nothing broader.
    """
    homogeneity_problems = series_homogeneity_problems(records, registry=registry)
    if homogeneity_problems:
        raise SeriesHomogeneityError(
            f"series {series_id!r} cannot be derived from a mixed record set: "
            + "; ".join(homogeneity_problems)
        )
    source_id = record_source_id(records[0])
    max_stale, cadence = contract_freshness_bounds(registry, source_id or "")
    baseline_definition = records[0].get("baseline_definition")
    return derive_series(
        series_id,
        records,
        baseline_definition=baseline_definition,
        baseline_value=0.0 if baseline_definition else None,
        max_stale_minutes=max_stale,
        expected_cadence_minutes=cadence,
        now=now or DATA_CUTOFF,
        origin=record_origin(records[0]),
    )


def current_series_domain(
    domain: str,
    series_id: str,
    rule_id: str,
    records: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    absent_basis: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One series-driven current domain assessment.

    With no qualified records the domain is ``insufficient_evidence``. With
    qualified records it is the documented threshold rule applied to them --
    the same rule the demonstration engine applies, on a different set of
    records. A series with too few periods still comes out
    ``insufficient_evidence``, because the rule's ``min_observations`` is what
    decides that, not the presence of the series.

    A domain is only ever populated by the series that domain reads, so one
    qualified series cannot make an unrelated domain look sufficient.

    WO-010-R5 §4: a mixed record set is not a build failure here -- it is a
    coverage gap. ``derive_current_series`` raises ``SeriesHomogeneityError``
    rather than silently combining or silently dropping the records; this is
    the one place that converts that refusal into what a Lane-domain
    assessment must say: no direction, no indicator support ID, and the
    homogeneity problem recorded as an explicit limitation rather than
    disappearing.
    """
    if not records:
        return build_domain_assessment(
            domain,
            direction="insufficient_evidence",
            basis=absent_basis,
            known_limitations=[NO_QUALIFIED_EVIDENCE],
        )

    try:
        derivation = derive_current_series(records, series_id, registry, now=now)
    except SeriesHomogeneityError as error:
        return build_domain_assessment(
            domain,
            direction="insufficient_evidence",
            basis=(
                f"The qualified records for series {series_id} disagree on source, unit, "
                "geography, lane or publication-use disposition and cannot be safely combined "
                "into one reading."
            ),
            known_limitations=[str(error)],
        )
    direction, _ = direction_for_derivation(derivation, rule_id)
    source_id = record_source_id(records[0])
    return build_domain_assessment(
        domain,
        direction=direction,
        basis=(
            f"Applied threshold rule {rule_id} to {len(records)} qualified "
            f"observation(s) of series {series_id} from source {source_id}."
        ),
        threshold_rule_id=rule_id,
        indicator_ids=[series_id],
        data_period=derivation.current_period,
        freshness=derivation.freshness.to_dict(),
        revision_status=derivation.revision_status,
        # Scope limitations travel with the series. A global or proxy
        # indicator does not become Thailand-specific by being qualified.
        known_limitations=[
            *derivation.limitations,
            *records[0]["provenance"].get("known_limitations", []),
        ],
    )


def current_chokepoint_exposure(
    lane: Mapping[str, Any],
    active: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Chokepoint notice status derived from qualified active events.

    ``official_notice_active`` requires a qualified, currently active event
    carrying an official-notice evidence item for that chokepoint. Nothing is
    hard-coded to ``insufficient_evidence``: with no qualified events the
    search simply finds nothing.
    """
    exposure = []
    for chokepoint_id in lane.get("chokepoint_ids", []):
        noticing = [
            event
            for event in active
            if chokepoint_id in event.get("chokepoint_ids", [])
            and any(
                evidence_by_id[eid].get("claim_type") == "official_notice"
                and qualifies_for_current_publication(
                    evidence_by_id[eid],
                    registry=registry,
                    publication_use=PUBLISH_BOUNDED_CLAIM,
                )
                for eid in event.get("evidence_ids", [])
                if eid in evidence_by_id
            )
        ]
        if noticing:
            exposure.append(
                {
                    "chokepoint_id": chokepoint_id,
                    "status": "official_notice_active",
                    "basis": (
                        "A qualified official operational notice is recorded against this "
                        "chokepoint by "
                        + ", ".join(sorted(event["event_id"] for event in noticing))
                        + ", and the event is confirmed active at the data cutoff."
                    ),
                }
            )
        else:
            exposure.append(
                {
                    "chokepoint_id": chokepoint_id,
                    "status": "insufficient_evidence",
                    "basis": (
                        "No qualified notice is recorded for this chokepoint. Absence of a "
                        "record is not absence of a notice."
                    ),
                }
            )
    return exposure


def build_current_lane_assessments(
    lanes: Sequence[Mapping[str, Any]],
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    qualified_events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Lane assessments built from qualified evidence only.

    This is a real derivation path, not a zero-coverage special case. Feed it
    qualified observations and it applies the documented threshold rules; feed
    it none and every domain comes out ``insufficient_evidence``, no lane
    reaches watch or elevated, and no chokepoint carries a notice. Both
    behaviours fall out of the same code, which is what makes the empty result
    trustworthy rather than merely asserted.

    ``now`` is the current build's as-of time (WO-010-R4 §6); it defaults to
    the pinned ``DATA_CUTOFF`` so every existing direct call is unaffected.
    """
    moment = now or DATA_CUTOFF
    moment_iso = moment.isoformat().replace("+00:00", "Z")
    active = active_events(qualified_events, evidence_by_id, cutoff=moment, registry=registry)
    assessments: list[dict[str, Any]] = []
    total_qualified = sum(len(records) for records in qualified_observations.values())

    coverage_basis = (
        f"Derived from qualified (live-retrieved or human-reviewed) current-publication "
        f"records only. {total_qualified} such observation(s) and {len(qualified_events)} "
        f"such event(s) exist at this cutoff."
    )

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
                and event["transmission_chain"]["completeness"] == "complete"
                and any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
            }
        )

        domain_assessments: list[dict[str, Any]] = []

        trade_series = f"th_export_value_{_lane_slug(lane_id)}"
        domain_assessments.append(
            current_series_domain(
                "thailand_trade_flow",
                trade_series,
                "TH-TRADE-YOY-V1",
                qualified_series_records(qualified_observations, trade_series, lane_id=lane_id),
                registry,
                absent_basis=("No qualified Thailand trade observation is recorded for this lane."),
                now=moment,
            )
        )

        for domain, (series_id, rule_id) in _SHARED_DOMAIN_SERIES.items():
            domain_assessments.append(
                current_series_domain(
                    domain,
                    series_id,
                    rule_id,
                    qualified_series_records(qualified_observations, series_id),
                    registry,
                    absent_basis=f"No qualified observation exists for series {series_id}.",
                    now=moment,
                )
            )

        for domain, areas in _EVENT_DOMAIN_AREAS.items():
            direction, event_ids, evidence_ids, limitations = event_domain_direction(
                lane_id, qualified_events, areas
            )
            domain_assessments.append(
                build_domain_assessment(
                    domain,
                    direction=direction,
                    basis=(
                        "Derived from qualified events recorded against this lane: "
                        f"{', '.join(event_ids) if event_ids else 'none'}."
                    ),
                    evidence_ids=evidence_ids,
                    known_limitations=list(limitations),
                )
            )

        domain_assessments.append(
            build_domain_assessment(
                "source_freshness_and_coverage",
                direction=(
                    "insufficient_evidence"
                    if source_status["overall_status"] == "insufficient"
                    else "stable"
                ),
                basis=source_status["coverage_message"],
                known_limitations=[coverage_basis],
            )
        )

        data_gaps = sorted(
            {
                limitation
                for item in domain_assessments
                for limitation in item["known_limitations"]
                if "insufficient" in limitation.lower()
                or "no qualified" in limitation.lower()
                or "coverage gap" in limitation.lower()
            }
        ) or [NO_QUALIFIED_EVIDENCE]

        assessment = build_lane_assessment(
            lane,
            assessment_id=f"LAS-CUR-{lane_id.replace('LANE-', '')}-{moment:%Y%m%d}",
            generated_at=moment_iso,
            data_cutoff_at=moment_iso,
            domain_assessments=domain_assessments,
            active_event_ids=lane_active,
            external_driver_event_ids=lane_drivers,
            chokepoint_exposure=current_chokepoint_exposure(lane, active, evidence_by_id, registry),
            data_gaps=data_gaps,
            known_limitations=[NO_QUALIFIED_EVIDENCE, *lane["known_limitations"]]
            if not total_qualified
            else list(lane["known_limitations"]),
        )
        assessment["dataset"] = CURRENT_PUBLICATION
        assessment["scenarios"] = (
            build_coverage_only_outlook(lane, generated_at=moment_iso, data_cutoff_at=moment_iso)
            if assessment["attention_level"] == "insufficient_evidence"
            else build_lane_outlook(
                lane, assessment, generated_at=moment_iso, data_cutoff_at=moment_iso
            )
        )
        assessment["preparedness_options"] = build_preparedness_options(lane, assessment)
        assessments.append(assessment)

    return assessments


#: Series whose value describes a global or route-level benchmark rather than
#: Thailand-specific activity, read here as a fixed mapping rather than
#: inferred from a source's ``logistics_role`` at validation time -- a single
#: source can carry both kinds of series (UNCTAD_MARITIME publishes the
#: Thailand LSCI and also contributes to a global baseline), so the source
#: alone cannot answer what one specific series is scoped to. Producer-set
#: once, here, and carried through the package rather than re-guessed by
#: whoever reads it (WO-010-R3 §4).
GLOBAL_OR_PROXY_SERIES = frozenset(
    {
        "gscpi_index",
        "brent_crude_price",
        "container_freight_benchmark",
    }
)

#: Indicator-payload fields that describe a raw magnitude rather than a
#: derived reading. A source qualified only for :data:`PUBLISH_DERIVED_VALUE`
#: may not have any of these published -- its terms permit a percentage
#: change, a rolling value or a threshold result, never the raw current
#: reading (WO-010-R3 §5).
_RAW_ONLY_INDICATOR_FIELDS = ("current_value", "previous_period_change", "deviation_from_baseline")


def build_current_indicators(
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    registry: Mapping[str, Any],
    *,
    raw_publishable_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Indicator payloads for the current view, from qualified records only.

    ``qualified_observations`` is the broader, derived-publishable set -- a
    record whose source permits at least a derived value. Whether this
    payload may also carry ``current_value`` and the other raw-magnitude
    fields is a narrower question, answered by whether the record's own ID
    also appears in ``raw_publishable_records``: the source-qualified
    ``publish_raw_value`` set. A derived-only source drives a direction; it
    never leaks the raw reading that direction was computed from.
    """
    payloads: list[dict[str, Any]] = []
    series_ids = sorted(
        {
            record.get("series_id") or record.get("indicator_id")
            for records in qualified_observations.values()
            for record in records
        }
        - {None}
    )
    raw_record_ids = {
        record["provenance"]["record_id"]
        for records in (raw_publishable_records or {}).values()
        for record in records
    }
    for series_id in series_ids:
        records = qualified_series_records(qualified_observations, str(series_id))
        if not records:
            continue
        # WO-010-R4 §5: never derive from records[0] alone. Every record in
        # this series must agree on source, unit, geography, lane and
        # publication-use disposition before one derivation may honestly
        # speak for all of them; a mixed series is excluded rather than
        # silently combined under one record's terms.
        homogeneity_problems = series_homogeneity_problems(records, registry=registry)
        if homogeneity_problems:
            continue
        derivation = derive_current_series(records, str(series_id), registry, now=now)
        payload = derivation.to_dict()
        payload["dataset"] = CURRENT_PUBLICATION
        payload["source_id"] = record_source_id(records[0])
        payload["intended_source_id"] = None
        payload["evidence_origin"] = record_origin(records[0])
        payload["source_limitations"] = list(records[0]["provenance"]["known_limitations"])
        payload["geographic_scope"] = (
            "global_or_proxy" if str(series_id) in GLOBAL_OR_PROXY_SERIES else "thailand"
        )
        if records[0]["provenance"]["record_id"] in raw_record_ids:
            payload["publication_use_applied"] = RAW_VALUES_PERMITTED
        else:
            payload["publication_use_applied"] = DERIVED_VALUES_ONLY
            for field_name in _RAW_ONLY_INDICATOR_FIELDS:
                payload[field_name] = None
        # WO-010-R4 §5: a second, independent check over the final payload
        # itself, not only over the pre-publication filter that built it --
        # a derived-only payload must never actually carry a raw field.
        if payload["publication_use_applied"] == DERIVED_VALUES_ONLY and any(
            payload.get(field_name) is not None for field_name in _RAW_ONLY_INDICATOR_FIELDS
        ):
            raise RuntimeError(f"derived-only indicator payload {series_id!r} leaked a raw field")
        payloads.append(payload)
    return payloads


def current_capability_coverage(
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    qualified_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Which analytical capabilities have qualified current evidence behind them.

    Computed from the filtered records, so it reports zero today because there
    is nothing to count -- not because zero was written down.
    """
    families = {
        "thailand_trade_flow": len(qualified_observations.get("trade_observations", [])),
        "thailand_port_or_maritime_activity": len(
            qualified_observations.get("port_observations", [])
        ),
        "cost_and_freight_context": len(qualified_observations.get("cost_observations", [])),
        "global_baseline_context": len(qualified_observations.get("indicator_observations", [])),
        "operational_event_evidence": len(qualified_events),
    }
    return [
        {
            "capability": capability,
            "qualified_record_count": count,
            "status": "sufficient" if count else "insufficient",
            "gap_reason": None
            if count
            else "No qualified current-publication record supports this capability.",
        }
        for capability, count in sorted(families.items())
    ]


def _current_major_data_gaps(
    *,
    source_status: Mapping[str, Any],
    capability_coverage: Sequence[Mapping[str, Any]],
    current_lane_coverage: Mapping[str, Any],
    registry: Mapping[str, Any],
    qualified_events: Sequence[Mapping[str, Any]],
) -> list[str]:
    """The current view's own data gaps, computed from what is actually
    missing at this cutoff (WO-010-R3 §7).

    Each entry names one concrete, checkable absence -- an insufficient
    capability, Source Health's own overall status, an unqualified
    required-for-publication source, a lane with no qualified domain, or the
    absence of any qualified operational event. The list shrinks the moment
    real coverage exists rather than restating a fixed description of the
    day every source happened to be disabled.
    """
    gaps: list[str] = []

    overall_status = source_status.get("overall_status")
    if overall_status not in {"sufficient", "fresh"}:
        gaps.append(
            f"Source Health reports overall current-publication coverage "
            f"{overall_status!r}: {source_status.get('coverage_message', '')}"
        )

    for capability in capability_coverage:
        if capability["status"] != "sufficient":
            gaps.append(f"{capability['capability'].replace('_', ' ')}: {capability['gap_reason']}")

    required_not_enabled = sorted(
        source["id"]
        for source in registry.get("sources", [])
        if source.get("required_for_publication") and not source.get("enabled")
    )
    if required_not_enabled:
        gaps.append(
            "Required-for-publication source(s) not yet enabled: "
            + ", ".join(required_not_enabled)
            + "."
        )

    total_lanes = current_lane_coverage.get("lanes_total", 0)
    covered_lanes = current_lane_coverage.get("lanes_with_any_qualified_domain", 0)
    if covered_lanes < total_lanes:
        gaps.append(
            f"{total_lanes - covered_lanes} of {total_lanes} Ocean lane(s) have no qualified "
            "domain at all; every domain in that lane reads insufficient_evidence."
        )

    if not qualified_events:
        gaps.append(
            "No qualified operational event exists, so no congestion, waiting-time or "
            "berth-delay statement can be made anywhere in the platform."
        )

    return gaps


def build_current_thailand_assessment(
    lane_assessments: Sequence[Mapping[str, Any]],
    qualified_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    qualified_events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
    registry: Mapping[str, Any],
    current_indicators: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The Thailand Ocean view built from qualified evidence only.

    Every count below is computed from the filtered records. WO-010-R1 wrote
    ``qualified_observation_count: 0`` as a literal, which happened to be true
    and would have stayed "true" after the first source was enabled.

    ``now`` is the current build's as-of time (WO-010-R4 §6); it defaults to
    the pinned ``DATA_CUTOFF`` so every existing direct call is unaffected.
    """
    moment = now or DATA_CUTOFF
    moment_iso = moment.isoformat().replace("+00:00", "Z")
    active = active_events(qualified_events, evidence_by_id, cutoff=moment, registry=registry)
    attention = [
        assessment
        for assessment in lane_assessments
        if assessment["attention_level"] in {"watch", "elevated"}
    ]
    qualified_observation_count = sum(len(records) for records in qualified_observations.values())
    lanes_with_evidence = [
        assessment
        for assessment in lane_assessments
        if any(
            domain["direction"] != "insufficient_evidence"
            for domain in assessment["domain_assessments"]
        )
    ]
    admitted = [
        event["event_id"]
        for event in qualified_events
        if event["event_class"] == "external_driver"
        and event["transmission_chain"]["completeness"] == "complete"
    ]
    contextual = [
        event["event_id"]
        for event in qualified_events
        if event["event_class"] == "external_driver"
        and event["transmission_chain"]["completeness"] != "complete"
    ]
    leads = [
        event["event_id"] for event in qualified_events if event["event_class"] == "discovery_lead"
    ]
    capability_coverage = current_capability_coverage(qualified_observations, qualified_events)
    current_lane_coverage = {
        "lanes_total": len(lane_assessments),
        "lanes_with_any_qualified_domain": len(lanes_with_evidence),
        "lane_ids_with_any_qualified_domain": sorted(
            assessment["lane_id"] for assessment in lanes_with_evidence
        ),
    }

    return {
        "assessment_id": f"THA-CUR-OCEAN-{moment:%Y%m%d}",
        "dataset": CURRENT_PUBLICATION,
        "subject": "thailand_ocean",
        "generated_at": moment_iso,
        "data_cutoff_at": moment_iso,
        "overall_direction": combine_directions(
            [assessment["overall_direction"] for assessment in lane_assessments]
        ),
        "evidence_coverage": source_status["overall_status"],
        "coverage_message": source_status["coverage_message"],
        "qualified_observation_count": qualified_observation_count,
        "current_indicator_count": len(current_indicators),
        "qualified_event_count": len(qualified_events),
        "current_lane_coverage": current_lane_coverage,
        "current_capability_coverage": capability_coverage,
        "lanes_requiring_attention": [
            {
                "lane_id": assessment["lane_id"],
                "attention_level": assessment["attention_level"],
                "overall_direction": assessment["overall_direction"],
            }
            for assessment in attention
        ],
        "active_verified_events": [event["event_id"] for event in active],
        "admitted_external_drivers": admitted,
        "contextual_external_drivers": contextual,
        "discovery_leads": leads,
        "key_changes": (
            [
                "No current assessment can be produced: the platform holds no live-retrieved "
                "or human-reviewed evidence, so there is nothing to compare and nothing to "
                "report."
            ]
            if not qualified_observation_count and not qualified_events
            else [
                f"{qualified_observation_count} qualified observation(s) and "
                f"{len(qualified_events)} qualified event(s) are in scope at this cutoff."
            ]
        ),
        "major_data_gaps": _current_major_data_gaps(
            source_status=source_status,
            capability_coverage=capability_coverage,
            current_lane_coverage=current_lane_coverage,
            registry=registry,
            qualified_events=qualified_events,
        ),
        "methodology_version": "0.8",
    }


def build_coverage_only_outlook(
    lane: Mapping[str, Any],
    *,
    generated_at: str | None = None,
    data_cutoff_at: str | None = None,
) -> dict[str, Any]:
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
        "generated_at": generated_at or DATA_CUTOFF_ISO,
        "data_cutoff_at": data_cutoff_at or DATA_CUTOFF_ISO,
        "base_case": dict(case),
        "deterioration_case": dict(case),
        "improvement_case": dict(case),
        "known_limitations": [
            "This is a coverage statement, not an outlook. All three cases are identical "
            "because with no qualified evidence there is nothing to differentiate them.",
            *lane.get("known_limitations", []),
        ],
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
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or DATA_CUTOFF
    moment_iso = moment.isoformat().replace("+00:00", "Z")
    entries = []
    for index, assessment in enumerate(lane_assessments, start=1):
        digest = hashlib.sha256(json.dumps(assessment, sort_keys=True).encode("utf-8")).hexdigest()
        entries.append(
            {
                "history_id": f"HIST-{moment:%Y%m%d}-{index:03d}",
                "subject_type": "lane_assessment",
                "subject_id": assessment["lane_id"],
                "revision_number": 0,
                "recorded_at": moment_iso,
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
            "history_id": f"HIST-{moment:%Y%m%d}-900",
            "subject_type": "thailand_assessment",
            "subject_id": thailand["assessment_id"],
            "revision_number": 0,
            "recorded_at": moment_iso,
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
    return {"version": "0.8", "generated_at": moment_iso, "entries": entries}


def _observation_timestamp(record: Mapping[str, Any]) -> str | None:
    provenance = record.get("provenance") or {}
    return provenance.get("retrieved_at") or provenance.get("published_at")


def _event_timestamp(event: Mapping[str, Any]) -> str | None:
    return event.get("retrieval_date") or event.get("publication_date")


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify without writing.")
    parser.add_argument(
        "--as-of",
        default=None,
        help=(
            "ISO-8601 as-of time the current build treats as 'now' (WO-010-R4 §6). Defaults "
            "to the previously committed Build Context's own as-of time, or, if none exists "
            "yet, to a fixed committed default -- never the wall clock."
        ),
    )
    args = parser.parse_args()

    registry = load_registry()
    observations = load_observations()
    events = _load(EVENTS_PATH)["events"]
    evidence_records = _load(ROOT / "data/events/event_evidence.json")["evidence"]
    lanes = load_lanes()["lanes"]
    load_dimensions()

    previous_context = _load(BUILD_CONTEXT_PATH) if BUILD_CONTEXT_PATH.exists() else None
    current_as_of = resolve_current_as_of(args.as_of, previous_context=previous_context)
    current_as_of_iso = to_iso(current_as_of)

    # WO-010-R5 §2: every current observation and evidence record, indexed
    # once and handed to the manual-review loader below so it can check a
    # review event's related_record_ids against records that actually exist
    # -- reversing WO-010-R4's accepted behaviour of loading an event that
    # named a record nobody could find.
    record_index = build_record_index(observations=observations, evidence=evidence_records)

    # Loaded from persisted, schema-validated manifests -- never an empty
    # literal standing in for "we checked". No source has ever completed a
    # live run and no manual notice has ever been reviewed, so both loaders
    # return empty mappings today, which is the honest, checkable answer.
    #
    # Both loaders are given ``current_as_of``: WO-010-R4 §6 requires that a
    # collection run or manual review dated later than this build's as-of
    # time can never be treated as the latest one (collectors/source_health.py)
    # or even load at all (a future-dated manual event fails closed here).
    collection_runs = load_collection_runs()
    manual_events = load_manual_review_events(
        registry=registry, now=current_as_of, record_index=record_index
    )
    source_status = evaluate_registry_health(
        registry,
        collection_runs,
        now=current_as_of,
        manual_events_by_source=manual_events,
    )

    # WO-010-R5 §1/§3: an evidence item claiming a live_retrieved or
    # human_reviewed_manual origin must be bound to a persisted, verifiable
    # acquisition event before it may back any current conclusion --
    # filtered here, before evidence_by_id exists, so every downstream
    # consumer (event activity, notices, chokepoint exposure) inherits the
    # same guarantee rather than each having to re-check it.
    bound_evidence_records = [
        item
        for item in evidence_records
        if not acquisition_binding_problems(
            item,
            collection_runs_by_source=collection_runs,
            manual_events_by_source=manual_events,
            as_of=current_as_of,
        )
    ]
    evidence_by_id = {item["evidence_id"]: item for item in bound_evidence_records}

    # --- current publication: qualified evidence only ----------------------
    # The filter is the whole mechanism. Nothing downstream knows or cares that
    # the result is currently empty; it derives whatever it is handed.
    #
    # WO-010-R3 §5: two publication-use surfaces, not one. ``qualified_observations``
    # is the derived-publishable set (a source qualified for at least
    # PUBLISH_DERIVED_VALUE), which is what every direction and threshold rule
    # below is computed from. ``raw_publishable_records`` is the narrower
    # PUBLISH_RAW_VALUE set: only a record whose own source qualifies there may
    # have its raw current reading published, in build_current_indicators below.
    qualified_observations = {
        family: qualified_records(records, registry=registry, publication_use=PUBLISH_DERIVED_VALUE)
        for family, records in observations.items()
    }
    raw_publishable_records = {
        family: qualified_records(records, registry=registry, publication_use=PUBLISH_RAW_VALUE)
        for family, records in observations.items()
    }
    qualified_events = [
        event
        for event in events
        if event_qualifies_for_current_publication(event, evidence_by_id, registry=registry)
    ]

    # WO-010-R4 §6: a record later than the as-of time is excluded from the
    # current view -- it is not yet known "as of" this build, whatever its
    # eligibility otherwise. Zero committed observations or events are
    # future-dated today, so this is a no-op against the committed repository.
    qualified_observations = {
        family: exclude_future_dated(
            records, as_of=current_as_of, timestamp_of=_observation_timestamp
        )[0]
        for family, records in qualified_observations.items()
    }
    qualified_events, _ = exclude_future_dated(
        qualified_events, as_of=current_as_of, timestamp_of=_event_timestamp
    )

    # WO-010-R5 §1/§3: the same acquisition-binding requirement applied to
    # evidence above, applied to observations. A record with no matching
    # persisted collection run or manual review event does not qualify for
    # current publication, whatever its origin label claims -- excluded here
    # so build_current_indicators / build_current_lane_assessments never see
    # it, rather than trusting each derivation site to re-check it.
    def _acquisition_bound(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            record
            for record in records
            if not acquisition_binding_problems(
                record,
                collection_runs_by_source=collection_runs,
                manual_events_by_source=manual_events,
                as_of=current_as_of,
            )
        ]

    qualified_observations = {
        family: _acquisition_bound(records) for family, records in qualified_observations.items()
    }
    raw_publishable_records = {
        family: _acquisition_bound(records) for family, records in raw_publishable_records.items()
    }

    # WO-010-R5 §3: a second, independent check over the records actually
    # about to be published -- not only over the filters that built this
    # set -- that Source Health and current publication cannot disagree
    # about whether a source has any data.
    consistency_problems = source_health_publication_consistency_problems(
        source_status, [record for records in qualified_observations.values() for record in records]
    )
    consistency_problems += source_health_publication_consistency_problems(
        source_status, list(evidence_by_id.values())
    )
    if consistency_problems:
        raise RuntimeError(
            "Source Health and current publication disagree: " + "; ".join(consistency_problems)
        )

    current_lane_assessments = build_current_lane_assessments(
        lanes,
        qualified_observations,
        qualified_events,
        evidence_by_id,
        source_status,
        registry,
        now=current_as_of,
    )
    current_indicators = build_current_indicators(
        qualified_observations,
        registry,
        raw_publishable_records=raw_publishable_records,
        now=current_as_of,
    )
    current_thailand = build_current_thailand_assessment(
        current_lane_assessments,
        qualified_observations,
        qualified_events,
        evidence_by_id,
        source_status,
        registry,
        current_indicators,
        now=current_as_of,
    )

    # --- technical demonstration: the engine exercised on fixtures ---------
    # Permanently pinned to DATA_CUTOFF, never to current_as_of: WO-010-R4 §6
    # explicitly permits the technical-demo and historical-validation datasets
    # to keep a fixed context, and this platform's reproducibility tests rely
    # on them never advancing with the current build's as-of time.
    derivations, indicator_payloads = derive_all_series(observations, registry)
    demo_lane_assessments = build_lane_records(
        observations, events, registry, source_status, derivations, dataset=TECHNICAL_DEMO
    )
    demo_thailand = build_thailand_assessment(demo_lane_assessments, events, source_status)
    demo_thailand["dataset"] = TECHNICAL_DEMO
    demo_thailand["assessment_id"] = f"THA-DEMO-OCEAN-{DATA_CUTOFF:%Y%m%d}"

    history = build_history(current_lane_assessments, current_thailand, now=current_as_of)

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

    current_indicator_payload = {
        "generated_at": current_as_of_iso,
        "data_cutoff_at": current_as_of_iso,
        "dataset": CURRENT_PUBLICATION,
        "note": (
            "Current-publication indicators, derived from qualified (live-retrieved or "
            "human-reviewed) observations only. Empty because no source is enabled, not "
            "because the list is hard-coded: it is whatever the qualification filter "
            "returns."
        ),
        "indicator_count": len(current_indicators),
        "indicators": current_indicators,
    }

    # --- Build Context (WO-010-R4 §6, timestamp semantics corrected R5 §8) -
    # The single record scripts/build_dashboard.py and scripts/
    # build_review_package.py both read, so every current output in one
    # build shares exactly this as-of time -- never a separately pinned one.
    # WO-010-R5 §8: filtered to runs/events at or before current_as_of before
    # taking the latest -- a future-dated run must not leak into
    # latest_included_collection_run_at just because collectors/
    # source_health.py already (separately) excludes it from making a
    # source's health read as fresh.
    included_runs, _ = exclude_future_dated(
        [run for runs in collection_runs.values() for run in runs],
        as_of=current_as_of,
        timestamp_of=lambda run: run.get("completed_at"),
    )
    latest_run_at = latest_timestamp(
        included_runs, timestamp_of=lambda run: run.get("completed_at")
    )
    included_manual, _ = exclude_future_dated(
        [event for events_ in manual_events.values() for event in events_],
        as_of=current_as_of,
        timestamp_of=lambda event: event.get("reviewed_at"),
    )
    latest_manual_at = latest_timestamp(
        included_manual, timestamp_of=lambda event: event.get("reviewed_at")
    )
    input_hashes = {
        name: digest
        for name, path in (
            ("trade_observations", OBSERVATION_DIR / "trade_observations.json"),
            ("port_observations", OBSERVATION_DIR / "port_observations.json"),
            ("cost_observations", OBSERVATION_DIR / "cost_observations.json"),
            ("indicator_observations", OBSERVATION_DIR / "indicator_observations.json"),
            ("events", EVENTS_PATH),
            ("event_evidence", ROOT / "data/events/event_evidence.json"),
            ("sources_registry", ROOT / "config/sources.yaml"),
        )
        if (digest := _file_sha256(path)) is not None
    }

    # WO-010-R5 §8: source_cutoff is the latest timestamp this build actually
    # found among its included evidence -- never as_of_time, and never a
    # non-null value when nothing qualified. Drawn from qualified
    # observations, qualified events, the latest included collection run and
    # the latest included manual review, whichever is most recent.
    source_cutoff_candidates: list[datetime] = []
    for records in qualified_observations.values():
        observation_latest = latest_timestamp(records, timestamp_of=_observation_timestamp)
        if observation_latest is not None:
            source_cutoff_candidates.append(observation_latest)
    event_latest = latest_timestamp(qualified_events, timestamp_of=_event_timestamp)
    if event_latest is not None:
        source_cutoff_candidates.append(event_latest)
    if latest_run_at is not None:
        source_cutoff_candidates.append(latest_run_at)
    if latest_manual_at is not None:
        source_cutoff_candidates.append(latest_manual_at)
    source_cutoff = max(source_cutoff_candidates) if source_cutoff_candidates else None

    # WO-010-R5 §8: generated_at must be the true instant this record was
    # written, not as_of_time -- but a rebuild with the same build_context_id
    # and identical input_hashes is the same context, and must reuse the
    # originally persisted generated_at rather than overwrite it, which is
    # what keeps a bare rebuild byte-identical. Only a genuinely new context
    # (a different as-of time, or the same as-of time over changed inputs)
    # gets a freshly observed generated_at.
    prospective_id = f"BCTX-{CURRENT_PUBLICATION.upper()}-{current_as_of:%Y%m%dT%H%M%SZ}"
    if (
        previous_context is not None
        and previous_context.get("build_context_id") == prospective_id
        and previous_context.get("input_hashes") == input_hashes
    ):
        generated_at = parse_timestamp(previous_context["generated_at"])
    else:
        generated_at = datetime.now(UTC)

    build_context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=current_as_of,
        source_cutoff=source_cutoff,
        generated_at=generated_at,
        latest_collection_run_at=latest_run_at,
        latest_manual_review_at=latest_manual_at,
        input_hashes=input_hashes,
    )
    context_errors = [
        f"schema: {message}"
        for message in schema_errors(build_context, "build_context.schema.json")
    ]
    context_errors.extend(context_problems(build_context, previous_context=previous_context))
    if context_errors:
        print("[BLOCKED] The current Build Context fails validation:")
        for problem in context_errors:
            print(f"  - {problem}")
        return 1

    outputs = [
        (INDICATOR_PATH, indicators),
        (CURRENT_INDICATOR_PATH, current_indicator_payload),
        (SOURCE_STATUS_PATH, source_status),
        (BUILD_CONTEXT_PATH, build_context),
        (
            ASSESSMENT_DIR / "lane_assessments.json",
            {
                "version": "0.8",
                "dataset": CURRENT_PUBLICATION,
                "generated_at": current_as_of_iso,
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
