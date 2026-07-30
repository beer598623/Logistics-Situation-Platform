"""Deterministic scenario and preparedness generation.

These outlooks are an *analytical* product, not an AI product. They are
assembled from the lane's own domain directions, its active events and its
data gaps, by fixed rules — so a reader can trace every sentence back to a
threshold rule ID or an event ID. The separate AI Outlook section of the
Dashboard shows only human-approved ChatGPT assessments and never these.

Two constraints shape every narrative produced here:

* No numeric point forecast. Triggers carry the numbers, because a trigger is
  a monitorable threshold rather than a prediction, and
  ``analysis.assessments.find_point_forecasts`` is run over every narrative
  in the test suite to keep it that way.
* Preparedness options stay conditional and organization-neutral. They
  describe what an organization *exposed to a stated condition* may consider,
  never what any particular company must do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .thresholds import RULES

#: Domains whose deterioration is worth naming in a scenario narrative.
_NARRATIVE_DOMAINS = {
    "thailand_trade_flow": "Thailand trade flow",
    "port_maritime_activity": "port and maritime activity",
    "freight_benchmark_direction": "the freight benchmark",
    "fuel_pressure": "fuel cost pressure",
    "fx_pressure": "FX cost pressure",
    "capacity_evidence": "capacity evidence",
    "transit_time_or_service_evidence": "transit-time and service evidence",
}


def _domains_with(assessments: Sequence[Mapping[str, Any]], direction: str) -> list[str]:
    return [
        _NARRATIVE_DOMAINS[item["domain"]]
        for item in assessments
        if item["direction"] == direction and item["domain"] in _NARRATIVE_DOMAINS
    ]


def _join(items: Sequence[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _rule_triggers(
    assessments: Sequence[Mapping[str, Any]], direction: str
) -> list[dict[str, str]]:
    """Turn each domain's own threshold rule into a monitorable trigger."""
    triggers: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in assessments:
        rule_id = item.get("threshold_rule_id")
        if not rule_id or rule_id in seen or rule_id not in RULES:
            continue
        seen.add(rule_id)
        threshold = RULES[rule_id]
        if direction == "deteriorating":
            sign = "rises to or above" if threshold.higher_is_worse else "falls to or below"
            bound = (
                f"+{threshold.deteriorating_at}"
                if threshold.higher_is_worse
                else f"-{threshold.deteriorating_at}"
            )
        else:
            sign = "falls to or below" if threshold.higher_is_worse else "rises to or above"
            bound = (
                f"-{threshold.improving_at}"
                if threshold.higher_is_worse
                else f"+{threshold.improving_at}"
            )
        unit = "" if threshold.basis == "absolute_deviation" else " percent"
        triggers.append(
            {
                "condition": (
                    f"{threshold.metric} {threshold.basis.replace('_', ' ')} change {sign} "
                    f"{bound}{unit} (rule {rule_id})"
                ),
                "observable_via": f"the {threshold.metric} observation series in this platform",
            }
        )
    return triggers


def _event_triggers(event_ids: Sequence[str], *, escalation: bool) -> list[dict[str, str]]:
    if not event_ids:
        return []
    verb = (
        "publishes a further notice extending or widening the restriction"
        if escalation
        else "publishes a notice withdrawing or narrowing the restriction"
    )
    return [
        {
            "condition": f"the operating authority behind {event_id} {verb}",
            "observable_via": (
                "the official operational notice channel registered for that authority"
            ),
        }
        for event_id in event_ids
    ]


def build_lane_outlook(
    lane: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    generated_at: str,
    data_cutoff_at: str | None,
) -> dict[str, Any]:
    """Build the three-case outlook for one lane."""
    domains = assessment["domain_assessments"]
    active = list(assessment.get("active_event_ids", []))
    gaps = list(assessment.get("data_gaps", []))
    lane_name = lane["name"]

    deteriorating = _domains_with(domains, "deteriorating")
    improving = _domains_with(domains, "improving")
    insufficient = [item for item in domains if item["direction"] == "insufficient_evidence"]

    evidence_ids = sorted({eid for item in domains for eid in item.get("evidence_ids", [])})
    confidence = "low" if len(insufficient) >= 5 else "medium"

    if assessment["overall_direction"] == "insufficient_evidence":
        base_narrative = (
            f"No usable indicator reading is available for {lane_name}, so the current "
            "state of this lane is unknown rather than unchanged. Nothing in this outlook "
            "should be read as an all-clear."
        )
    else:
        parts = [
            f"{lane_name} currently reads as {assessment['overall_direction']} across the "
            "nine assessed domains"
        ]
        if deteriorating:
            parts.append(f"with {_join(deteriorating)} deteriorating")
        if improving:
            parts.append(f"and {_join(improving)} improving")
        base_narrative = ". ".join([", ".join(parts)])
        if active:
            base_narrative += (
                f" {len(active)} operational event(s) are open against this lane: "
                f"{', '.join(active)}."
            )
        else:
            base_narrative += " No operational event is currently open against this lane."
        if insufficient:
            base_narrative += (
                f" {len(insufficient)} of nine domains have insufficient evidence, so the "
                "reading is partial."
            )

    deterioration_narrative = (
        f"A deterioration case for {lane_name} would show the domains below crossing their "
        "documented thresholds in the adverse direction, or an operating authority extending "
        "a restriction that affects this lane. The triggers state what would have to be "
        "observed; no magnitude or date is asserted here."
    )
    improvement_narrative = (
        f"An improvement case for {lane_name} would show the same domains crossing their "
        "thresholds in the favourable direction, or an operating authority withdrawing a "
        "restriction. As with the deterioration case, the triggers are the monitorable part."
    )

    deterioration_triggers = _rule_triggers(domains, "deteriorating") + _event_triggers(
        active, escalation=True
    )
    improvement_triggers = _rule_triggers(domains, "improving") + _event_triggers(
        active, escalation=False
    )
    fallback_trigger = [
        {
            "condition": (
                "any source backing this lane changes freshness state, or a new official "
                "notice is recorded against a node or chokepoint the lane includes"
            ),
            "observable_via": "the source-health snapshot and the official notice channels",
        }
    ]

    return {
        "outlook_id": f"OUT-{lane['lane_id'].replace('LANE-', '')}",
        "subject_type": "lane",
        "subject_id": lane["lane_id"],
        "generated_at": generated_at,
        "data_cutoff_at": data_cutoff_at,
        "base_case": {
            "narrative": base_narrative,
            "time_horizon": "1-4_weeks",
            "trigger_conditions": fallback_trigger,
            "evidence_ids": evidence_ids,
            "confidence": confidence,
            "data_gaps": gaps,
            "point_forecast_disclaimer": (
                "No numeric forecast is given for freight, transit time, inventory or cost. "
                "No qualified dataset in this registry would support one."
            ),
        },
        "deterioration_case": {
            "narrative": deterioration_narrative,
            "time_horizon": "0-7_days" if active else "1-4_weeks",
            "trigger_conditions": deterioration_triggers or fallback_trigger,
            "evidence_ids": evidence_ids,
            "confidence": confidence,
            "data_gaps": gaps,
            "point_forecast_disclaimer": None,
        },
        "improvement_case": {
            "narrative": improvement_narrative,
            "time_horizon": "1-3_months",
            "trigger_conditions": improvement_triggers or fallback_trigger,
            "evidence_ids": evidence_ids,
            "confidence": confidence,
            "data_gaps": gaps,
            "point_forecast_disclaimer": None,
        },
        "known_limitations": [
            "Generated deterministically from this lane's domain directions, open events and "
            "data gaps. It is not an AI assessment and carries no judgement beyond the "
            "documented threshold rules it cites.",
            *(list(lane.get("known_limitations", []))),
        ],
    }


def build_preparedness_options(
    lane: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Conditional, organization-neutral options for one lane.

    Each option names the condition under which an organization might
    consider it and the condition under which it would stop being relevant.
    None of them instructs anyone to do anything.
    """
    options: list[dict[str, Any]] = []
    lane_name = lane["name"]
    evidence_ids = sorted(
        {eid for item in assessment["domain_assessments"] for eid in item.get("evidence_ids", [])}
    )
    attention = assessment["attention_level"]

    options.append(
        {
            "option_type": "monitor",
            "description": (
                f"Organizations with cargo moving on {lane_name} may wish to track the "
                "domain readings and official notices recorded for this lane, so that a "
                "change is noticed when it occurs rather than afterwards."
            ),
            "applicable_to": f"Organizations with exposure to {lane_name}",
            "trigger_condition": (
                "The lane is published with an attention level of watch or elevated, or any "
                "domain crosses its documented threshold."
            ),
            "possible_benefit": (
                "Earlier awareness of a change that is already observable in a public source."
            ),
            "tradeoffs": ["Requires ongoing attention to a lane that may not change."],
            "limitations": [
                "This platform holds no shipment, booking or capacity data, so it cannot "
                "state whether any particular organization is exposed to this lane."
            ],
            "exit_condition": (
                "The lane returns to a routine attention level and no official notice is "
                "open against its nodes or chokepoints."
            ),
            "evidence_basis": evidence_ids,
        }
    )

    if attention in {"watch", "elevated"}:
        options.append(
            {
                "option_type": "verify_exposure",
                "description": (
                    f"An organization may wish to establish, from its own records, whether "
                    f"its cargo actually routes through the nodes and chokepoints that "
                    f"{lane_name} includes, since public data cannot establish that."
                ),
                "applicable_to": f"Organizations that may have exposure to {lane_name}",
                "trigger_condition": (
                    "The lane is published at watch or elevated attention while the platform "
                    "records no confirmation of which services actually transit its "
                    "chokepoints."
                ),
                "possible_benefit": (
                    "Replaces an assumed exposure with a known one before any decision "
                    "depends on it."
                ),
                "tradeoffs": ["Requires internal information this public platform does not hold."],
                "limitations": [
                    "Routing information is carrier-specific and is not published by any "
                    "source qualified in this registry."
                ],
                "exit_condition": (
                    "Exposure has been established from the organization's own records."
                ),
                "evidence_basis": evidence_ids,
            }
        )

    if lane.get("chokepoint_ids"):
        options.append(
            {
                "option_type": "contingency",
                "description": (
                    "Where a lane transits a chokepoint with a registered notice channel, an "
                    "organization may wish to understand in advance what an alternative "
                    "routing would mean for its own transit-time assumptions."
                ),
                "applicable_to": (
                    f"Organizations whose planning assumptions depend on {lane_name} transit times"
                ),
                "trigger_condition": (
                    "An operating authority publishes a restriction affecting a chokepoint "
                    "this lane transits."
                ),
                "possible_benefit": (
                    "A planning assumption that is examined before it is tested rather than after."
                ),
                "tradeoffs": [
                    "Alternative routings usually carry their own cost or transit penalty."
                ],
                "limitations": [
                    "The platform does not model routings and publishes no transit-time "
                    "estimate for any alternative."
                ],
                "exit_condition": "The restriction is withdrawn or the lane's exposure is retired.",
                "evidence_basis": evidence_ids,
            }
        )

    if assessment["overall_direction"] == "insufficient_evidence":
        options.append(
            {
                "option_type": "no_action",
                "description": (
                    f"No source-backed action is indicated for {lane_name}, because the "
                    "platform currently has no usable reading for it. Absence of a reading "
                    "is a coverage gap and is not a basis for either action or reassurance."
                ),
                "applicable_to": "Any reader of this lane",
                "trigger_condition": "Every domain for this lane reports insufficient evidence.",
                "possible_benefit": (
                    "Avoids treating a coverage gap as though it were a finding of stability."
                ),
                "tradeoffs": ["A real change could be occurring unobserved."],
                "limitations": [
                    "This option exists because coverage is insufficient, not because the "
                    "lane was assessed and found quiet."
                ],
                "exit_condition": "At least one domain acquires a usable reading.",
                "evidence_basis": evidence_ids,
            }
        )

    return options
