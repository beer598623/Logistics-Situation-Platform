# Indicator definitions and threshold rules

**Work Order:** WO-010 (Bundle 1)
**Status:** implemented
**Machine-readable counterpart:** `analysis/thresholds.py`

This document and `analysis/thresholds.py` are two views of the same rule set.
`tests/test_analysis_indicators.py` asserts that every rule ID in code appears here and
that every rule ID mentioned here exists in code, so the two cannot drift apart.

## 1. What the platform publishes, and what it refuses to publish

The platform publishes a **direction** per domain, drawn from exactly five values:

| Direction | Meaning |
|---|---|
| `improving` | The domain's documented rule fired in the favourable direction. |
| `stable` | The rule was applied and the change fell inside its band. |
| `deteriorating` | The rule fired in the adverse direction. |
| `mixed` | Sub-readings disagree. |
| `insufficient_evidence` | The rule's inputs were missing, unavailable, or too few. |

It deliberately does **not** publish:

- a single composite "logistics score" — every direction keeps its own rule, inputs and
  limitations, and the lane roll-up is a transparent combination, not a weighting;
- a numeric point forecast for freight, transit time, inventory or cost;
- a deviation from an unstated baseline;
- a percentage change against a zero basis (that is undefined, and is reported as
  undefined rather than as a very large number).

## 2. Missing is never zero

This is the single rule that governs every derivation.

- An observation with `value_status` other than `available` carries `value: null`. The
  contract in `schemas/observation_common.schema.json` and the builder in
  `collectors/observations.py` both refuse to construct a record that violates this.
- A derivation that needs a missing period returns `None` and records why.
- A rule whose input is `None`, or whose available-period count is below its declared
  minimum, returns `insufficient_evidence` — never `stable`.
- Every derivation reports `periods_total`, `periods_available`, `periods_missing` and
  the list of missing periods, so a reader can see how thin the evidence is.

## 3. Derived readings

For each series the platform computes, where the data permits:

| Reading | Definition | Withheld when |
|---|---|---|
| Current value | Latest period with `value_status: available`. | No usable period exists. |
| Previous-period change | Current minus the previous **available** period, absolute and percentage. | Fewer than two usable periods; percentage also withheld when the basis is zero. |
| Month-over-month | Change against the calendar month immediately preceding the current period. | That exact month has no usable value. A nearby period is never substituted. |
| Year-over-year | Change against the same calendar month twelve months earlier. | That exact month has no usable value. |
| Rolling average | Mean of the last three usable periods. | Fewer than three usable periods exist. |
| Deviation from baseline | Current value minus an explicitly stated baseline. | `baseline_definition` is null. |
| Freshness | Age of the latest usable period's publication time against the source contract's `expected_cadence_minutes` (or half of `max_stale_minutes` when cadence is unknown). | No usable period exists — reported as `no_data`, never as a zero-day age. |
| Revision status | `revised` when the current period carries a revision marker, otherwise `original`. | No usable period exists — reported as `unknown`. |

## 4. The threshold rules

Each rule declares whether a rise is adverse. Nothing infers the sign from the metric name.

### TH-TRADE-YOY-V1 — Thailand trade flow

- **Metric:** published Thailand trade value for a lane group.
- **Basis:** year-over-year percentage change.
- **Direction:** higher is better. Deteriorating at −7.5%, improving at +7.5%.
- **Minimum observations:** 13.
- **Why year-over-year:** monthly customs series carry strong seasonality that a
  month-over-month reading would report as a trend.
- **Limitation:** published trade value is an all-mode total. It is not ocean freight
  volume and must never be displayed as one.

### TH-TRADE-MOM-V1 — short-horizon Thailand trade movement

- **Basis:** month-over-month percentage change. Deteriorating at −5%, improving at +5%.
- **Minimum observations:** 2.
- **Use:** reported alongside, never instead of, the year-over-year rule. One month of an
  unadjusted series is not a trend.

### PORT-VOLUME-YOY-V1 — port and maritime activity

- **Metric:** port throughput or port-call count.
- **Basis:** year-over-year percentage change. Deteriorating at −7.5%, improving at +7.5%.
- **Minimum observations:** 13.
- **This rule measures VOLUME ONLY.** A rising direction means more cargo moved. It is not
  congestion, and a falling direction is not improved fluidity. Congestion requires
  operational evidence and is never produced by this rule. See
  `docs/port_pressure_interpretation.md`.

### FUEL-MOM-V1 — fuel cost pressure

- **Metric:** published retail or bunker fuel price.
- **Basis:** month-over-month percentage change. Deteriorating at +3%, improving at −3%.
- **Direction:** higher is worse. The indicator measures cost pressure on logistics
  operations, not the health of the energy market.
- **Limitation:** a retail pump price is domestic cost context, not a bunker price.

### FX-MOM-V1 — FX cost pressure

- **Metric:** USD/THB reference rate.
- **Basis:** month-over-month percentage change. Deteriorating at +2%, improving at −2%.
- **Direction:** higher is worse, because a rising USD/THB rate raises the baht cost of
  USD-denominated freight, bunker and imported inputs.
- **Explicit scope limit:** this is a **cost-pressure** reading only. It is deliberately
  *not* a statement about Thailand export competitiveness, which moves the opposite way
  and is out of scope for this module.

### FREIGHT-BENCHMARK-MOM-V1 — freight benchmark direction

- **Metric:** a public container freight benchmark.
- **Basis:** month-over-month percentage change. Deteriorating at +5%, improving at −5%.
- **Output is a directional reading of a market benchmark or route proxy.** It is never a
  Thailand shipment quotation, and the benchmark's own route scope is displayed with it.
  See `docs/freight_proxy_limitations.md`.

### GSCPI-DEVIATION-V1 — global supply-chain baseline

- **Metric:** the global supply-chain pressure index.
- **Basis:** absolute deviation from the publisher's own stated baseline of zero, which the
  publisher defines as the series average in standard-deviation units.
- **Direction:** higher is worse. Deteriorating at +0.5, improving at −0.5.
- **Why deviation is permitted here:** the baseline is explicit and published. No deviation
  is published for any series whose `baseline_definition` is null.
- **Limitation:** a global index cannot establish a Thailand-specific or lane-specific
  conclusion on its own.

## 5. Lane roll-up

`analysis.thresholds.combine_directions` combines the nine domain directions:

1. No directions at all, or only `insufficient_evidence` → `insufficient_evidence`.
2. Any `mixed`, or both `improving` and `deteriorating` present → `mixed`.
3. Otherwise the single non-stable direction present, or `stable`.

`insufficient_evidence` entries are ignored when at least one real direction exists, but
they are never converted to `stable`, and they remain visible in the domain breakdown.

## 6. Attention level

`analysis.assessments.attention_level` is deterministic and applies in this order:

1. Every domain `insufficient_evidence` → `insufficient_evidence`. A lane whose evidence is
   entirely missing is never reported as `routine`: absence of a signal is not an all-clear.
2. A deteriorating domain **and** an open operational event → `elevated`.
3. Either one alone → `watch`.
4. Otherwise → `routine`.

## 7. Domains without a threshold rule

Four domains derive their direction from recorded events or source health rather than from
a numeric rule, and they legitimately carry no `threshold_rule_id`:

- `operational_event_status`
- `capacity_evidence`
- `transit_time_or_service_evidence`
- `source_freshness_and_coverage`

A lane with only discovery-class leads recorded against it gets `insufficient_evidence` for
the event-derived domains, never `stable` — a lead is not an observation of calm.

`scripts/validate.py` enforces the converse too: a domain reporting
`insufficient_evidence` may not cite a threshold rule, because citing a rule that could not
be applied misrepresents how the answer was reached.

## 8. Current data status

Every series in this bundle is derived from a **labelled synthetic test fixture**
(`evidence_class: synthetic_test_fixture`). No source is enabled and none has completed a
controlled live validation. The rules above are implemented and tested; the numbers they
are currently applied to describe the platform's behaviour, not the real world. See
`docs/source_qualification_report.md` and `docs/known_data_gaps.md`.
