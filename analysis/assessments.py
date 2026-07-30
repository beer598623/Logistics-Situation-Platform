"""Lane assessment, scenario and preparedness-option logic.

The assessment produced here is a *transparent roll-up*, not a score. Each of
the nine domains keeps its own direction, its own threshold rule ID, its own
indicators and its own limitations, and the lane-level direction is derived
from those by a rule a reader can apply by hand.

Two guards live here because they are analytical rather than structural:

* Scenario narratives may not contain point forecasts. A scenario says what
  could happen and what to watch; it does not predict a number.
* Preparedness options must stay organization-neutral and conditional. The
  public core may say "an organization exposed to X may consider Y if Z"; it
  may never issue a mandatory instruction to a specific company.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .indicators import SeriesDerivation, change_for_basis
from .thresholds import Direction, combine_directions, rule

#: The nine assessment domains, in publication order. Every lane assessment
#: carries all nine, because a domain that was not assessed must be visible
#: as ``insufficient_evidence`` rather than absent.
DOMAINS = (
    "thailand_trade_flow",
    "port_maritime_activity",
    "freight_benchmark_direction",
    "fuel_pressure",
    "fx_pressure",
    "operational_event_status",
    "capacity_evidence",
    "transit_time_or_service_evidence",
    "source_freshness_and_coverage",
)

#: Forward-looking verbs that turn a numeric quantity in a scenario narrative
#: into a point forecast.
_FORECAST_VERBS = re.compile(
    r"\b(will|shall|expect(?:ed|s)?|forecast(?:ed|s)?|project(?:ed|s)?|predict(?:ed|s)?)\b",
    re.IGNORECASE,
)

#: A numeric quantity: a bare number, a percentage, a currency amount, or a
#: duration. Used only in combination with a forecast verb.
_QUANTITY = re.compile(
    r"(?:[$€£]\s?\d|\d+(?:\.\d+)?\s*(?:%|percent|usd|thb|eur|teu|days?|weeks?|months?)\b|\b\d+(?:\.\d+)?\b)",
    re.IGNORECASE,
)

#: Mandatory-instruction phrasing that is not permitted in a public,
#: organization-neutral preparedness option.
_MANDATORY_PHRASES = (
    "you must",
    "you should",
    "your company must",
    "your company should",
    "companies must",
    "organizations must",
    "organisations must",
    "is required to",
    "are required to",
    "shall immediately",
    "must immediately",
    "we recommend that you",
)

#: Second-person and possessive framing that makes an option organization-
#: specific rather than conditional and general.
_ORGANIZATION_SPECIFIC = ("your fleet", "your warehouse", "your shipment", "our customer")


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def find_point_forecasts(narrative: str) -> list[str]:
    """Return the sentences that read as a numeric point forecast.

    A sentence is flagged only when it contains both a forward-looking verb
    and a numeric quantity. Trigger conditions are deliberately not passed
    through this function: "if the benchmark rises more than 20 percent" is a
    monitorable threshold, not a prediction.
    """
    return [
        sentence
        for sentence in _split_sentences(narrative)
        if _FORECAST_VERBS.search(sentence) and _QUANTITY.search(sentence)
    ]


def validate_scenario_outlook(outlook: Mapping[str, Any]) -> list[str]:
    """Check scenario completeness and prohibited point forecasts."""
    problems: list[str] = []
    outlook_id = outlook.get("outlook_id", "<unknown>")
    for case_name in ("base_case", "deterioration_case", "improvement_case"):
        case = outlook.get(case_name)
        if not case:
            problems.append(f"{outlook_id}: missing {case_name}")
            continue
        if not case.get("trigger_conditions"):
            problems.append(f"{outlook_id}/{case_name}: no trigger conditions recorded")
        for sentence in find_point_forecasts(str(case.get("narrative", ""))):
            problems.append(
                f"{outlook_id}/{case_name}: narrative contains an unsupported point "
                f"forecast: {sentence!r}"
            )
    return problems


def validate_preparedness_option(option: Mapping[str, Any]) -> list[str]:
    """Check that a preparedness option stays conditional and neutral."""
    problems: list[str] = []
    description = str(option.get("description", ""))
    lowered = description.lower()
    label = option.get("option_type", "<unknown>")

    for phrase in _MANDATORY_PHRASES:
        if phrase in lowered:
            problems.append(
                f"preparedness option '{label}': mandatory instruction phrasing "
                f"{phrase!r} is not permitted in the organization-neutral public core"
            )
    for phrase in _ORGANIZATION_SPECIFIC:
        if phrase in lowered:
            problems.append(
                f"preparedness option '{label}': organization-specific phrasing "
                f"{phrase!r} is not permitted in the public core"
            )
    if not option.get("trigger_condition"):
        problems.append(
            f"preparedness option '{label}': an option with no trigger condition is an "
            "instruction, not a conditional option"
        )
    if not option.get("exit_condition"):
        problems.append(f"preparedness option '{label}': no exit condition recorded")
    if not option.get("limitations"):
        problems.append(f"preparedness option '{label}': no limitations recorded")
    return problems


def direction_for_derivation(
    derivation: SeriesDerivation,
    rule_id: str,
) -> tuple[Direction, float | None]:
    """Apply one documented threshold rule to one derived series."""
    threshold = rule(rule_id)
    change, observations_used = change_for_basis(derivation, threshold.basis)
    return threshold.evaluate(change, observations_used=observations_used), change


def build_domain_assessment(
    domain: str,
    *,
    direction: Direction,
    basis: str,
    threshold_rule_id: str | None = None,
    indicator_ids: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
    data_period: str | None = None,
    freshness: Mapping[str, Any] | None = None,
    revision_status: str = "unknown",
    known_limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble one domain assessment record.

    ``threshold_rule_id`` is forced to ``None`` when the direction is
    ``insufficient_evidence``: citing a rule that could not actually be
    applied would misrepresent how the answer was reached.
    """
    if domain not in DOMAINS:
        raise ValueError(f"Unknown assessment domain: {domain}")
    return {
        "domain": domain,
        "direction": direction,
        "basis": basis,
        "threshold_rule_id": None if direction == "insufficient_evidence" else threshold_rule_id,
        "indicator_ids": list(indicator_ids),
        "evidence_ids": list(evidence_ids),
        "data_period": data_period,
        "freshness": dict(freshness)
        if freshness
        else {"status": "no_data", "as_of": None, "age_days": None},
        "revision_status": revision_status,
        "known_limitations": list(known_limitations),
    }


def attention_level(
    domain_assessments: Sequence[Mapping[str, Any]],
    *,
    active_operational_event_ids: Sequence[str],
) -> str:
    """Deterministic attention level for a lane.

    Order matters. A lane whose evidence is entirely missing is
    ``insufficient_evidence`` and is never reported as ``routine``: absence of
    a signal is not an all-clear.
    """
    directions = [assessment["direction"] for assessment in domain_assessments]
    if all(direction == "insufficient_evidence" for direction in directions):
        return "insufficient_evidence"
    deteriorating = "deteriorating" in directions
    if deteriorating and active_operational_event_ids:
        return "elevated"
    if deteriorating or active_operational_event_ids:
        return "watch"
    return "routine"


def build_lane_assessment(
    lane: Mapping[str, Any],
    *,
    assessment_id: str,
    generated_at: str,
    data_cutoff_at: str | None,
    domain_assessments: Sequence[Mapping[str, Any]],
    active_event_ids: Sequence[str] = (),
    external_driver_event_ids: Sequence[str] = (),
    chokepoint_exposure: Sequence[Mapping[str, Any]] = (),
    scenarios: Mapping[str, Any] | None = None,
    data_gaps: Sequence[str] = (),
    known_limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble one lane assessment from already-computed domain readings."""
    recorded = {assessment["domain"] for assessment in domain_assessments}
    missing_domains = [domain for domain in DOMAINS if domain not in recorded]
    if missing_domains:
        raise ValueError(
            "Lane assessment must carry all nine domains; missing: " + ", ".join(missing_domains)
        )

    ordered = sorted(domain_assessments, key=lambda item: DOMAINS.index(item["domain"]))
    overall = combine_directions([item["direction"] for item in ordered])

    return {
        "assessment_id": assessment_id,
        "lane_id": lane["lane_id"],
        "generated_at": generated_at,
        "data_cutoff_at": data_cutoff_at,
        "overall_direction": overall,
        "attention_level": attention_level(
            ordered, active_operational_event_ids=list(active_event_ids)
        ),
        "domain_assessments": ordered,
        "active_event_ids": list(active_event_ids),
        "external_driver_event_ids": list(external_driver_event_ids),
        "chokepoint_exposure": [dict(item) for item in chokepoint_exposure],
        "scenarios": dict(scenarios) if scenarios else None,
        "data_gaps": list(data_gaps),
        "known_limitations": list(known_limitations),
        "methodology_version": "0.8",
    }
