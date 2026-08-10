"""mode_situation computation (WO-049 / Issue #92 item 5; design part 2
Section 3).

"What is happening now, according to source-backed Developments." Computed
deterministically from already-approved ``logistics_event``/``claim``/
``document`` records -- never authored directly by AI or a human. Consumes
the existing nine-area ``impact_assessment`` machinery; does not recompute
it.

Gate 0 reuses ``analysis/events.py::is_active_at`` verbatim (conditions 1-5)
plus three new predicates (conditions 6-8, design part 2 Section 3.4). The
five statuses are evaluated in order, first match wins -- no averaging, no
weighting, no count-based dilution, the same shape as
``analysis/thresholds.py::combine_directions``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from analysis.claim_evidence_adapter import freshness_state
from analysis.events import ACTIVE_LIFECYCLE_STATUSES, is_active_at  # noqa: F401  (re-exported)
from analysis.grading import compute_evidence_grade, eligible_claims, independent_group_count
from analysis.reference import lane_by_id, lanes_for_chokepoint, lanes_for_node

#: Gate 0 condition 6: situation_state values that admit an event to
#: mode_situation contribution outright. UNCERTAIN is admitted separately,
#: and only when the event carries an unresolved existence/status_change
#: contradiction (design part 2 Section 3.8's T2 resolution) -- an event
#: UNCERTAIN merely from staleness is excluded anyway by condition 7.
_SITUATION_STATE_ELIGIBLE = frozenset({"EMERGING", "ACTIVE", "DEVELOPING", "STABLE", "EASING"})

#: Gate 0 condition 7: freshness states that keep an event eligible.
_FRESHNESS_ELIGIBLE = frozenset({"fresh", "ageing"})

_SEVERITY_ORDER = ("none", "low", "moderate", "high", "critical")
_MATERIAL_SEVERITIES = frozenset({"moderate", "high", "critical"})

_CONFIDENCE_LEVELS = ("low", "medium", "high")

#: contradiction_type values that make an UNCERTAIN event still eligible
#: (Gate 0 condition 6's UNCERTAIN carve-out) and that feed rule 2.
_CAPPING_CONTRADICTION_TYPES = frozenset({"existence", "status_change"})


def _has_capping_contradiction(event: Mapping[str, Any]) -> bool:
    for entry in event.get("conflicting_evidence", []) or []:
        if (
            entry.get("resolution_status") == "unresolved"
            and entry.get("contradiction_type") in _CAPPING_CONTRADICTION_TYPES
        ):
            return True
    return False


def _situation_state_eligible(event: Mapping[str, Any]) -> tuple[bool, str]:
    state = event.get("situation_state")
    if state in _SITUATION_STATE_ELIGIBLE:
        return True, f"situation_state {state!r} is eligible."
    if state == "UNCERTAIN" and _has_capping_contradiction(event):
        return True, (
            "situation_state 'UNCERTAIN' with an unresolved existence/status_change "
            "contradiction is eligible (contributes to rule 2 only)."
        )
    return False, (
        f"situation_state {state!r} is not eligible for mode_situation contribution "
        f"(eligible: {sorted(_SITUATION_STATE_ELIGIBLE)}, or 'UNCERTAIN' with an unresolved "
        "existence/status_change contradiction)"
    )


def _event_freshness_state(
    event: Mapping[str, Any],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    now: datetime,
) -> str:
    """The worst (most stale) freshness state among the event's Q(E) claims.

    An event with no eligible claims is treated as ``unknown`` -- Gate 0
    condition 7 then excludes it, which is correct: nothing establishes
    that any evidence behind this event is still current.
    """
    order = ("fresh", "ageing", "stale", "expired", "unknown")
    claims = eligible_claims(event, claims_by_id, documents_by_id, registry)
    if not claims:
        return "unknown"
    worst = "fresh"
    for claim in claims:
        document = documents_by_id.get(claim.get("document_id")) or {}
        state = freshness_state(document, registry, now=now)
        if order.index(state) > order.index(worst):
            worst = state
    return worst


def _has_thailand_link(event: Mapping[str, Any], *, country_code: str) -> bool:
    """Gate 0 condition 8: a geography link to the situation's country.

    ``TH`` in ``country_ids``, or a node/chokepoint on a Lane whose
    ``country_ids`` include the country, or a ``lane_relevance`` entry
    naming such a Lane. Reuses ``analysis/reference.py``'s existing Lane
    index; no new field.
    """
    if country_code in (event.get("country_ids") or []):
        return True
    for node_id in event.get("node_ids") or []:
        for lane_id in lanes_for_node(node_id):
            if country_code in lane_by_id(lane_id).get("country_ids", []):
                return True
    for chokepoint_id in event.get("chokepoint_ids") or []:
        for lane_id in lanes_for_chokepoint(chokepoint_id):
            if country_code in lane_by_id(lane_id).get("country_ids", []):
                return True
    for entry in event.get("lane_relevance") or []:
        try:
            lane = lane_by_id(entry.get("lane_id"))
        except KeyError:
            continue
        if country_code in lane.get("country_ids", []):
            return True
    return False


def _gate0(
    event: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    cutoff: datetime,
    country_code: str,
) -> tuple[bool, str, str]:
    """Gate 0, all eight conditions. Returns ``(passes, reason, freshness_state)``."""
    activity = is_active_at(event, evidence_by_id, cutoff=cutoff, registry=registry)
    if not activity.is_active:
        return False, activity.reason, "unknown"

    state_ok, state_reason = _situation_state_eligible(event)
    if not state_ok:
        return False, state_reason, "unknown"

    freshness = _event_freshness_state(event, claims_by_id, documents_by_id, registry, now=cutoff)
    if freshness not in _FRESHNESS_ELIGIBLE:
        return (
            False,
            (
                f"freshness_state {freshness!r} is not among the eligible set "
                f"{sorted(_FRESHNESS_ELIGIBLE)} (Gate 0 condition 7)"
            ),
            freshness,
        )

    if not _has_thailand_link(event, country_code=country_code):
        return (
            False,
            ("regional scope, no Thailand link established (Gate 0 condition 8)"),
            freshness,
        )

    return True, "Passes all eight Gate 0 conditions.", freshness


def _step_confidence(level: str, delta: int) -> str:
    index = _CONFIDENCE_LEVELS.index(level)
    index = max(0, min(len(_CONFIDENCE_LEVELS) - 1, index + delta))
    return _CONFIDENCE_LEVELS[index]


def _worst_impact_status_severity(
    event: Mapping[str, Any], statuses: frozenset[str]
) -> tuple[str | None, str]:
    """The highest-severity impact_assessment whose status is in ``statuses``."""
    best_area = None
    best_severity = "none"
    for impact in event.get("impact_assessments", []) or []:
        if impact.get("status") not in statuses:
            continue
        severity = impact.get("severity", "none")
        if _SEVERITY_ORDER.index(severity) > _SEVERITY_ORDER.index(best_severity):
            best_severity = severity
            best_area = impact.get("area")
    return best_area, best_severity


def _coverage_basis(
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    geography_id: str,
    country_code: str,
    now: datetime,
) -> dict[str, Any]:
    candidate_source_ids = {
        source["id"]
        for source in (registry or {}).get("sources", [])
        if (source.get("governance") or {}).get("enabled_for_public_claims")
        and (source.get("governance") or {}).get("evidence_layer") == "current_evidence"
    }
    qualifying_documents = [
        document
        for document in documents_by_id.values()
        if document.get("source_id") in candidate_source_ids
        and document.get("dataset") == "current_publication"
        and freshness_state(document, registry, now=now) in _FRESHNESS_ELIGIBLE
        and (
            geography_id in (document.get("geographies") or [])
            or country_code in (document.get("geographies") or [])
        )
    ]
    sources_with_public_claims = sorted(
        {document.get("source_id") for document in qualifying_documents}
    )
    window_minutes = None
    if sources_with_public_claims:
        windows = [
            source.get("max_stale_minutes")
            for source in (registry or {}).get("sources", [])
            if source.get("id") in sources_with_public_claims and source.get("max_stale_minutes")
        ]
        window_minutes = min(windows) if windows else None
    return {
        "sources_with_public_claims": sources_with_public_claims,
        "qualifying_document_count": len(qualifying_documents),
        "window_minutes": window_minutes,
    }


def compute_mode_situation(
    *,
    mode: str,
    geography_id: str,
    country_code: str,
    events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Compute one ``mode_situation.schema.json``-conformant record.

    Pure and deterministic given its inputs: nothing here is timestamped at
    call time except ``as_of`` itself, which the caller supplies (never the
    wall clock, matching ``scripts/build_analysis.py``'s ``current_as_of``
    discipline).
    """
    excluded_event_ids: list[dict[str, str]] = []
    eligible: list[tuple[dict[str, Any], str | None, list[str], str]] = []

    for event in events:
        passes, reason, freshness = _gate0(
            event,
            evidence_by_id,
            claims_by_id,
            documents_by_id,
            registry,
            cutoff=as_of,
            country_code=country_code,
        )
        if not passes:
            excluded_event_ids.append({"event_id": event["event_id"], "exclusion_reason": reason})
            continue
        grade, _grade_basis = compute_evidence_grade(
            event, claims_by_id, documents_by_id, registry, now=as_of
        )
        eligible.append((dict(event), grade, [], freshness))

    contributing_event_ids: list[str] = []
    watch_event_ids: list[str] = []
    status_basis: list[dict[str, Any]] = []
    status = "insufficient_current_evidence"

    # --- Rule 1: confirmed_disruption --------------------------------------
    rule1_hits = []
    for event, grade, _basis, freshness in eligible:
        if grade != "CONFIRMED":
            continue
        area, severity = _worst_impact_status_severity(event, frozenset({"observed"}))
        if area is None or severity not in _MATERIAL_SEVERITIES:
            continue
        if freshness != "fresh":
            continue
        if _has_capping_contradiction(event):
            continue
        rule1_hits.append((event, area, severity))
    if rule1_hits:
        status = "confirmed_disruption"
        for event, area, severity in rule1_hits:
            contributing_event_ids.append(event["event_id"])
            status_basis.append(
                {
                    "event_id": event["event_id"],
                    "rule_id": "R1",
                    "contribution": (
                        f"CONFIRMED development with observed {severity} impact in {area!r}, "
                        "fresh, uncontradicted."
                    ),
                }
            )

    # --- Rule 2: mixed_evidence ---------------------------------------------
    if status == "insufficient_current_evidence":
        rule2_hits = [
            (event, grade)
            for event, grade, _basis, _fresh in eligible
            if _has_capping_contradiction(event)
        ]
        if rule2_hits:
            status = "mixed_evidence"
            for event, _grade in rule2_hits:
                contributing_event_ids.append(event["event_id"])
                status_basis.append(
                    {
                        "event_id": event["event_id"],
                        "rule_id": "R2",
                        "contribution": (
                            "Unresolved existence/status_change contradiction on this "
                            "Development's core assertion."
                        ),
                    }
                )

    # --- Rule 3: elevated_watch ----------------------------------------------
    if status == "insufficient_current_evidence":
        rule3_hits = []
        for event, grade, _basis, freshness in eligible:
            if grade in {"CONFIRMED", "CORROBORATED", "REPORTED"}:
                area, severity = _worst_impact_status_severity(
                    event, frozenset({"potential", "elevated_watch"})
                )
                if area is not None and _SEVERITY_ORDER.index(severity) >= _SEVERITY_ORDER.index(
                    "moderate"
                ):
                    rule3_hits.append(
                        (event, f"grade {grade} with {area!r} at {severity} severity")
                    )
                    continue
            if grade == "CONFIRMED":
                impacts = event.get("impact_assessments", []) or []
                if impacts and all(
                    impact.get("status") == "insufficient_evidence" for impact in impacts
                ):
                    rule3_hits.append((event, "confirmed development, no impact area yet assessed"))
                    continue
                area, severity = _worst_impact_status_severity(event, frozenset({"observed"}))
                if area is not None and severity in _MATERIAL_SEVERITIES and freshness == "ageing":
                    rule3_hits.append(
                        (
                            event,
                            f"met rule 1 ({area!r} at {severity}) but has drifted to freshness "
                            "'ageing'",
                        )
                    )
                    continue
        if rule3_hits:
            status = "elevated_watch"
            for event, contribution in rule3_hits:
                contributing_event_ids.append(event["event_id"])
                status_basis.append(
                    {"event_id": event["event_id"], "rule_id": "R3", "contribution": contribution}
                )

    # --- Rule 4: no_material_impact_detected ---------------------------------
    coverage = _coverage_basis(
        documents_by_id, registry, geography_id=geography_id, country_code=country_code, now=as_of
    )
    if status == "insufficient_current_evidence":
        rule4_hits = []
        for event, _grade, _basis, _fresh in eligible:
            if not event.get("negative_operational_evidence"):
                continue
            for impact in event.get("impact_assessments", []) or []:
                if impact.get("status") == "no_material" and impact.get("no_material_basis"):
                    rule4_hits.append((event, impact.get("area")))
        if rule4_hits and coverage["qualifying_document_count"] >= 1:
            status = "no_material_impact_detected"
            for event, area in rule4_hits:
                contributing_event_ids.append(event["event_id"])
                status_basis.append(
                    {
                        "event_id": event["event_id"],
                        "rule_id": "R4",
                        "contribution": f"Explicit negative operational evidence in {area!r}.",
                    }
                )

    contributing_event_ids = sorted(set(contributing_event_ids))
    watch_event_ids = sorted(
        {event["event_id"] for event, *_ in eligible} - set(contributing_event_ids)
    )

    # --- confidence ------------------------------------------------------
    if status == "insufficient_current_evidence" and not eligible:
        confidence = "low"
        confidence_reductions = ["No eligible event; confidence reflects the empty evidence base."]
    else:
        if status == "confirmed_disruption":
            confidence = "high"
        elif status in {"elevated_watch", "no_material_impact_detected"}:
            confidence = "medium"
        else:
            confidence = "low"
        confidence_reductions = []
        contributing = [
            event for event, *_ in eligible if event["event_id"] in contributing_event_ids
        ]
        all_claims: list[dict[str, Any]] = []
        for event in contributing:
            all_claims.extend(eligible_claims(event, claims_by_id, documents_by_id, registry))
        if any(_has_capping_contradiction(event) for event in contributing):
            confidence = _step_confidence(confidence, -1)
            confidence_reductions.append("Unresolved contradiction among contributing evidence.")
        contributing_not_fresh = any(
            freshness != "fresh"
            for _event, _grade, _basis, freshness in eligible
            if _event["event_id"] in contributing_event_ids
        )
        if contributing_not_fresh:
            confidence = _step_confidence(confidence, -1)
            confidence_reductions.append("At least one contributing event is ageing, not fresh.")
        ig_count = independent_group_count(all_claims, documents_by_id)
        if ig_count <= 1:
            confidence = _step_confidence(confidence, -1)
            confidence_reductions.append("Single independent origin.")
        else:
            confidence = _step_confidence(confidence, 1)
            confidence_reductions.append(
                f"Raised: {ig_count} independent groups confirm the leading contributing event."
            )
        null_cadence_sources = {
            document.get("source_id")
            for claim in all_claims
            for document in [documents_by_id.get(claim.get("document_id")) or {}]
        }
        registry_by_id = {source["id"]: source for source in (registry or {}).get("sources", [])}
        if any(
            registry_by_id.get(source_id, {}).get("expected_cadence_minutes") is None
            for source_id in null_cadence_sources
            if source_id
        ):
            confidence_reductions.append(
                "Publisher cadence unknown for at least one contributing source "
                "(expected_cadence_minutes is null)."
            )

    # --- evidence_composition ---------------------------------------------
    by_grade = {"CONFIRMED": 0, "CORROBORATED": 0, "REPORTED": 0, "ANALYTICAL_INFERENCE": 0}
    for event, grade, _basis, _fresh in eligible:
        if event["event_id"] in contributing_event_ids and grade in by_grade:
            by_grade[grade] += 1
    contributing_claims: list[dict[str, Any]] = []
    for event, _grade, _basis, _fresh in eligible:
        if event["event_id"] in contributing_event_ids:
            contributing_claims.extend(
                eligible_claims(event, claims_by_id, documents_by_id, registry)
            )
    by_layer = {"l1": 0, "l2": 0, "l3": 0}
    layer_key = {"current_evidence": "l1", "context": "l2", "structural_research": "l3"}
    for claim in contributing_claims:
        key = layer_key.get(claim.get("evidence_layer"))
        if key:
            by_layer[key] += 1
    document_ids = {
        claim.get("document_id") for claim in contributing_claims if claim.get("document_id")
    }
    evidence_composition = {
        "by_grade": by_grade,
        "by_layer": by_layer,
        "document_count": len(document_ids),
        "claim_count": len(contributing_claims),
        "independent_group_count": independent_group_count(contributing_claims, documents_by_id),
    }

    # --- freshness ----------------------------------------------------------
    published_ats = [
        (documents_by_id.get(claim.get("document_id")) or {}).get("published_at")
        for claim in contributing_claims
    ]
    published_ats = sorted(value for value in published_ats if value)
    freshness_order = ("fresh", "ageing", "stale", "expired", "unknown")
    worst_state = "unknown"
    contributing_freshness = [
        freshness
        for event, _g, _b, freshness in eligible
        if event["event_id"] in contributing_event_ids
    ]
    if contributing_freshness:
        worst_state = "fresh"
        for state in contributing_freshness:
            if freshness_order.index(state) > freshness_order.index(worst_state):
                worst_state = state
    freshness_block = {
        "newest_verification_at": published_ats[-1] if published_ats else None,
        "oldest_contributing_verification_at": published_ats[0] if published_ats else None,
        "state": worst_state,
    }

    situation_id = (
        f"SIT-{mode.upper()}-{geography_id.replace('GEO-', '')}-{as_of.strftime('%Y%m%dT%H%M%SZ')}"
    )
    evidence_cutoff_at = (
        published_ats[-1] if published_ats else as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    return {
        "situation_id": situation_id,
        "mode": mode,
        "geography_id": geography_id,
        "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_cutoff_at": evidence_cutoff_at,
        "status": status,
        "status_basis": status_basis,
        "confidence": confidence,
        "confidence_reductions": confidence_reductions,
        "material_event_count": len(contributing_event_ids),
        "contributing_event_ids": contributing_event_ids,
        "watch_event_ids": watch_event_ids,
        "excluded_event_ids": excluded_event_ids,
        "evidence_composition": evidence_composition,
        "freshness": freshness_block,
        "gaps": [],
        "coverage_basis": coverage,
        "known_limitations": [
            "Development->Development relatedness (contradiction rule 2's second clause, "
            "opposed-predicate node/chokepoint overlap across two distinct events) is not "
            "computed by this Work Order; only a single event's own unresolved contradiction "
            "is checked. gaps[] is not computed (WO-045's #ocean-major-gaps derivation is a "
            "Dashboard-facing mechanism this Work Order does not touch).",
        ],
        "methodology_version": "0.8",
        "dataset": "current_publication",
    }
