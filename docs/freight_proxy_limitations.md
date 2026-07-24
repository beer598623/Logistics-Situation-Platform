# Freight proxy limitations

**Work Order:** WO-010 Gate F · **Status:** implemented and enforced

## 1. The rule

A public freight index or benchmark is labelled, everywhere it appears, as one of:

- **market benchmark** — a published market-wide index;
- **route proxy** — a benchmark for a route that is not the lane being discussed;
- **directional indicator** — the direction only, not the level.

It is **never** a Thailand shipment quotation.

## 2. How the rule is enforced rather than merely stated

| Layer | Enforcement |
|---|---|
| Contract | `schemas/cost_observation.schema.json` requires `benchmark_class` **and** `quotation_claim` on every cost record |
| Validator | `scripts/validate.py::observation_checks` rejects any record whose `benchmark_class` is not `actual_quotation` but whose `quotation_claim` is not `not_a_quotation` |
| Threshold rule | `FREIGHT-BENCHMARK-MOM-V1`'s own description states the output is directional and never a Thailand quotation; a test asserts that wording is present |
| AI gate | `analysis/review_package.py` rejects a returned assessment containing quotation phrasing such as "average Thailand freight rate", "quoted rate" or "spot rate from Thailand" |
| Dashboard | Each cost series prints its `benchmark_class`, its `quotation_claim`, its route scope and its Thailand applicability; a test asserts no quotation claim reaches the payloads |

`actual_quotation` exists in the enum but is used by **no source in this registry**. It is
reserved for a qualified dataset that genuinely quotes shipments, and none has been
qualified.

## 3. What the platform does not publish

- **No Thailand freight average.** No qualified dataset covering Thailand-origin freight
  rates exists in the registry, so no average is computed, displayed or implied anywhere.
  `tests/test_dashboard_build.py::test_no_thailand_freight_average_is_published` asserts it.
- **No point forecast** for any freight level. `analysis/assessments.py::find_point_forecasts`
  scans every scenario narrative for a forward-looking verb combined with a numeric
  quantity and rejects the outlook if one is found.
- **No derived Thailand rate from a third-route benchmark.** A benchmark's route scope is
  carried with it precisely so it cannot be silently reassigned to a Thailand lane.

## 4. The series currently registered

| Series | Class | Route scope | Thailand applicability |
|---|---|---|---|
| `container_freight_benchmark` | `route_proxy` | Composite east-west mainlane benchmark, **not a Thailand route** | `directional_context_only` |
| `brent_crude_price` | `market_benchmark` | not route specific | `directional_context_only` |
| `thailand_diesel_retail_price` | `published_official_price` | not route specific | `measured` |

All three are currently derived from labelled synthetic fixtures.

## 5. Why crude is not a freight cost

Pass-through runs crude → refined bunker fuel → carrier cost → freight rate. Each step has
its own timing, its own margin and its own contractual structure. The platform records the
chain as a **transmission mechanism** producing *potential* cost pressure, and never as a
computed cost effect. Historical validation case HVC-005 exists specifically to check that
an energy-cost driver produces potential pressure rather than a quantified number.

## 6. Why retail diesel is not bunker fuel

`thailand_diesel_retail_price` is a domestic pump price. It is genuine cost context for
inland drayage between Thailand ports and the hinterland. It is **not** the fuel any vessel
burns, and it must not be presented as an ocean freight input. The series carries that
limitation on every record.

## 7. Surcharges and fees

No surcharge or fee series is published. No registry source publishing carrier surcharges
has been qualified, so the platform records that as a coverage gap on the Cost section
rather than estimating one.
