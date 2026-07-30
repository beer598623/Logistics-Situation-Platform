# Future Air and Land extension points

**Work Order:** WO-010 · **Status of Air and Land modules:** planned, not implemented

WO-010 delivers the Ocean module only. What it also delivers is a shared foundation that
accepts Air, Road, Rail and Border without a schema change — and the claim is checkable,
not merely asserted. Every item below is covered by a test in
`tests/test_reference_and_lanes.py`.

## 1. What already accepts a non-Ocean record

| Shared entity | Mode neutrality |
|---|---|
| `observation_common.schema.json` | `transportMode` permits `sea`, `air`, `road`, `rail`, `border`, `inland_waterway`, `multimodal`, `not_applicable` |
| `dim_transport_mode` | All eight modes registered; Air, Road, Rail, Border and inland waterway carry `module_status: planned` |
| `dim_logistics_node` | `node_type` includes `airport`, `border_crossing`, `inland_terminal`, `rail_terminal`, `warehouse_hub`. **An airport (`NODE-THBKKAIR`) and a border crossing (`NODE-THSDK`) are already registered** |
| `dim_chokepoint` | `chokepoint_type` includes `border_corridor`, `airspace`, `rail_gauge_break`. **A road/border corridor (`CHK-THSDK-BKH`) is already registered** |
| `dim_lane` | Mode is carried as data. Adding an Air lane is a new record, not a schema change |
| `port_transport_observation.schema.json` | Named for transport, not ports. Metric enum already includes `aircraft_movements`, `border_crossings`, `rail_movements` |
| `logistics_event.schema.json` | `modes` is an array of the shared mode enum; event types are mode-agnostic |
| `indicator`, `trade`, `cost` observations | All carry the shared placement block with its mode field |

The three pre-registered non-Ocean records carry no data. They exist so that "the shared
entities are mode-neutral" is a testable statement rather than an intention.

## 2. What a future Air module would add

- **Lanes:** `LANE-AIR-TH-*` records with `mode: air`, origin and destination airport
  groups, and airspace chokepoints where relevant.
- **Nodes:** cargo terminals beyond `NODE-THBKKAIR`.
- **Observations:** air cargo tonnage and capacity via `port_transport_observation` with
  `metric: aircraft_movements` or `capacity_deployed`; air freight rate benchmarks via
  `cost_observation` with an appropriate `benchmark_class`.
- **Events:** airport or cargo-terminal interruption, airspace closure, capacity withdrawal
  — all already expressible in the existing event type enum or a small additive extension.
- **Threshold rules:** new IDs in `analysis/thresholds.py`, documented alongside in
  `docs/indicator_definitions.md`. The rule engine itself needs no change.

## 3. What a future Land, Rail and Border module would add

- **Lanes:** `LANE-ROAD-TH-*`, `LANE-RAIL-TH-*`, `LANE-BORDER-TH-*` with corridor
  resolution.
- **Nodes:** border crossings beyond `NODE-THSDK`, inland terminals, rail terminals.
- **Chokepoints:** border corridors beyond `CHK-THSDK-BKH`, plus rail gauge breaks.
- **Observations:** border crossing counts, rail movements, road transit times.
- **Events:** road, rail or border closure, customs system outage — already in the event
  type enum.

## 4. What must not change

These are the constraints that keep the foundation shared rather than Ocean-shaped:

1. **No Ocean-only assumption may enter a shared entity.** If an Air module needs a field
   that only makes sense for Air, it belongs on an Air-specific record, not on
   `observation_common`.
2. **The missing-is-not-zero rule applies identically** to every mode.
3. **The transmission chain and evidence lifecycle are mode-agnostic** and must stay so.
4. **The nine impact areas are fixed** and apply to every mode.
5. **Free-only and no-private-data apply identically.**
6. **`insufficient_evidence` remains a first-class answer** in every module.

## 5. Cross-modal work deliberately deferred

The roadmap's later "Cross-modal News and AI hardening" bundle covers what WO-010 does not:
clustering an event that affects Ocean and Air simultaneously, comparing scenarios across
modes, and a Thailand assessment that rolls up more than one mode. The current Thailand
assessment is explicitly `subject: thailand_ocean` rather than `thailand_overall`, so
adding a second mode extends the roll-up rather than reinterpreting the existing one.

`scenario_outlook.schema.json` already permits `subject_type: thailand_overall` for that
future roll-up.
