"""Documented, deterministic threshold rules.

Every published direction must be attributable to exactly one rule ID in this
module. The rules are intentionally coarse: the platform publishes a
direction (improving / stable / deteriorating / mixed / insufficient
evidence), never a numeric forecast, and a coarse rule that a reviewer can
verify by hand is worth more than a finely tuned one that nobody can audit.

Two properties are enforced by tests rather than by convention:

* A rule never converts a missing observation into a zero change. If the
  inputs a rule needs are absent, the rule returns ``insufficient_evidence``.
* ``higher_is_worse`` is explicit per rule. Rising fuel cost is
  deteriorating; rising trade value is improving. Nothing infers the sign
  from the metric name.

The narrative definitions live in ``docs/indicator_definitions.md``; this
module is the machine-readable counterpart, and the two are checked against
each other by ``tests/test_thresholds.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["improving", "stable", "deteriorating", "mixed", "insufficient_evidence"]

#: Direction returned when a rule's inputs are not available. Named rather
#: than inlined so that no caller can accidentally substitute "stable".
INSUFFICIENT: Direction = "insufficient_evidence"


@dataclass(slots=True, frozen=True)
class ThresholdRule:
    """One documented direction rule.

    ``deteriorating_at`` and ``improving_at`` are expressed as percentage
    change against the comparison basis, except where ``basis`` is
    ``absolute_deviation`` in which case they are in the series' own units.
    """

    rule_id: str
    metric: str
    basis: Literal["previous_period", "month_over_month", "year_over_year", "absolute_deviation"]
    higher_is_worse: bool
    deteriorating_at: float
    improving_at: float
    min_observations: int
    description: str
    documented_in: str = "docs/indicator_definitions.md"

    def evaluate(self, change: float | None, *, observations_used: int) -> Direction:
        """Map a change value to a direction, or to insufficient evidence.

        ``change`` is ``None`` whenever the underlying observations were
        missing, unavailable, or too few to compute the comparison. That is
        never silently treated as no change.
        """
        if change is None or observations_used < self.min_observations:
            return INSUFFICIENT

        worse_side = (
            change >= self.deteriorating_at
            if self.higher_is_worse
            else change <= -abs(self.deteriorating_at)
        )
        better_side = (
            change <= -abs(self.improving_at)
            if self.higher_is_worse
            else change >= self.improving_at
        )

        if worse_side:
            return "deteriorating"
        if better_side:
            return "improving"
        return "stable"


#: The complete rule set. Adding a rule requires adding its narrative
#: definition to docs/indicator_definitions.md; a test asserts both sides
#: stay in step.
RULES: dict[str, ThresholdRule] = {
    "TH-TRADE-YOY-V1": ThresholdRule(
        rule_id="TH-TRADE-YOY-V1",
        metric="thailand_trade_value",
        basis="year_over_year",
        higher_is_worse=False,
        deteriorating_at=7.5,
        improving_at=7.5,
        min_observations=13,
        description=(
            "Thailand trade flow direction from year-over-year percentage change in "
            "published trade value. Year-over-year is used rather than month-over-month "
            "because monthly customs series carry strong seasonality that would otherwise "
            "be read as a trend."
        ),
    ),
    "TH-TRADE-MOM-V1": ThresholdRule(
        rule_id="TH-TRADE-MOM-V1",
        metric="thailand_trade_value",
        basis="month_over_month",
        higher_is_worse=False,
        deteriorating_at=5.0,
        improving_at=5.0,
        min_observations=2,
        description=(
            "Short-horizon Thailand trade movement from month-over-month percentage "
            "change. Reported alongside, never instead of, the year-over-year rule, "
            "because a single month of an unadjusted series is not a trend."
        ),
    ),
    "PORT-VOLUME-YOY-V1": ThresholdRule(
        rule_id="PORT-VOLUME-YOY-V1",
        metric="port_throughput_volume",
        basis="year_over_year",
        higher_is_worse=False,
        deteriorating_at=7.5,
        improving_at=7.5,
        min_observations=13,
        description=(
            "Port or maritime activity direction from year-over-year change in throughput "
            "or port calls. This rule measures VOLUME ONLY. A rising direction means more "
            "cargo moved, which is not congestion, and a falling direction means less cargo "
            "moved, which is not improved fluidity. Congestion requires operational evidence "
            "and is never produced by this rule."
        ),
    ),
    "FUEL-MOM-V1": ThresholdRule(
        rule_id="FUEL-MOM-V1",
        metric="retail_or_bunker_fuel_price",
        basis="month_over_month",
        higher_is_worse=True,
        deteriorating_at=3.0,
        improving_at=3.0,
        min_observations=2,
        description=(
            "Fuel cost pressure from month-over-month percentage change in a published "
            "fuel price. Rising price is deteriorating because the indicator measures cost "
            "pressure on logistics operations, not the health of the energy market."
        ),
    ),
    "FX-MOM-V1": ThresholdRule(
        rule_id="FX-MOM-V1",
        metric="usd_thb_rate",
        basis="month_over_month",
        higher_is_worse=True,
        deteriorating_at=2.0,
        improving_at=2.0,
        min_observations=2,
        description=(
            "FX pressure from month-over-month change in the USD/THB rate. A rising "
            "USD/THB rate is recorded as deteriorating because it raises the baht cost of "
            "USD-denominated freight, bunker and imported inputs. This is a cost-pressure "
            "reading only: it is deliberately NOT a statement about Thailand export "
            "competitiveness, which moves the opposite way and is out of scope."
        ),
    ),
    "FREIGHT-BENCHMARK-MOM-V1": ThresholdRule(
        rule_id="FREIGHT-BENCHMARK-MOM-V1",
        metric="container_freight_benchmark",
        basis="month_over_month",
        higher_is_worse=True,
        deteriorating_at=5.0,
        improving_at=5.0,
        min_observations=2,
        description=(
            "Direction of a public container freight benchmark. The output is a "
            "DIRECTIONAL reading of a market benchmark or route proxy. It is never a "
            "Thailand shipment quotation, and the benchmark's own route scope must be "
            "displayed with it."
        ),
    ),
    "GSCPI-DEVIATION-V1": ThresholdRule(
        rule_id="GSCPI-DEVIATION-V1",
        metric="global_supply_chain_pressure_index",
        basis="absolute_deviation",
        higher_is_worse=True,
        deteriorating_at=0.5,
        improving_at=0.5,
        min_observations=1,
        description=(
            "Global supply-chain baseline pressure from the index's deviation from its "
            "own published baseline of zero, which the publisher defines as the series "
            "average in standard-deviation units. Because the baseline is explicit and "
            "published, deviation is meaningful here; no deviation is published for any "
            "series whose baseline_definition is null."
        ),
    ),
}


def rule(rule_id: str) -> ThresholdRule:
    try:
        return RULES[rule_id]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Unknown threshold rule: {rule_id}") from exc


def combine_directions(directions: list[Direction]) -> Direction:
    """Roll several domain directions into one, transparently.

    This is deliberately not a weighted score. The rules are:

    * No directions at all, or only ``insufficient_evidence`` -> insufficient evidence.
    * Any disagreement between improving and deteriorating -> ``mixed``.
    * Otherwise the single non-stable direction present, or ``stable``.

    ``insufficient_evidence`` entries are ignored when at least one real
    direction exists, but they are never allowed to turn into ``stable``:
    the caller keeps them visible in the domain breakdown.
    """
    known = [direction for direction in directions if direction != INSUFFICIENT]
    if not known:
        return INSUFFICIENT
    if "mixed" in known:
        return "mixed"
    has_up = "improving" in known
    has_down = "deteriorating" in known
    if has_up and has_down:
        return "mixed"
    if has_down:
        return "deteriorating"
    if has_up:
        return "improving"
    return "stable"
