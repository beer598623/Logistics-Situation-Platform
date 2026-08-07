# Future Air and Land extension points

**Work Order:** WO-010 · **Status of Air and Land modules:** planned, not implemented

WO-010 delivers the Ocean module only. What it also delivers is a shared foundation that
accepts Air, Road, Rail and Border without a schema change — and the claim is checkable, not
merely asserted. `logistics_event.schema.json`'s `event_type` enum (§1, table row 7; §2-3
below) originally had one exception: two of its 18 values were Ocean-worded, with no
exact-fit value for a non-Ocean closure event — see `docs/bundle2_air_cargo_scope.md` §1,
which verified this against the real schema during WO-017. **WO-035 closed that exception**
with a purely additive extension (`airspace_closure`, `terminal_or_facility_closure`), so the
whole shared foundation now accepts a non-Ocean record without a schema change. Every item
below is covered by a test in `tests/test_reference_and_lanes.py`; the event-type row's claim
is covered by
`tests/test_bundle2_scope_doc_claims.py::test_event_type_enum_covers_the_mode_agnostic_types_the_doc_cites`
and `test_event_type_enum_covers_non_ocean_closure_events`.

## 1. What already accepts a non-Ocean record

| Shared entity | Mode neutrality |
|---|---|
| `observation_common.schema.json` | `transportMode` permits `sea`, `air`, `road`, `rail`, `border`, `inland_waterway`, `multimodal`, `not_applicable` |
| `dim_transport_mode` | All eight modes registered; Air, Road, Rail, Border and inland waterway carry `module_status: planned` |
| `dim_logistics_node` | `node_type` includes `airport`, `border_crossing`, `inland_terminal`, `rail_terminal`, `warehouse_hub`. **An airport (`NODE-THBKKAIR`) and a border crossing (`NODE-THSDK`) are already registered** |
| `dim_chokepoint` | `chokepoint_type` includes `border_corridor`, `airspace`, `rail_gauge_break`. **A road/border corridor (`CHK-THSDK-BKH`) is already registered** |
| `dim_lane` | Mode is carried as data. Adding an Air lane is a new record, not a schema change |
| `port_transport_observation.schema.json` | Named for transport, not ports. Metric enum already includes `aircraft_movements`, `border_crossings`, `rail_movements` |
| `logistics_event.schema.json` | `modes` is an array of the shared mode enum. `event_type` is mode-agnostic (`carrier_rerouting`, `service_suspension`, `capacity_withdrawal`, `strike`, `customs_or_system_outage`, and more); **`port_or_terminal_closure` and `canal_restriction` stay Ocean-worded, and WO-035 added `airspace_closure`/`terminal_or_facility_closure`** so a non-Ocean closure event now has an exact-fit value too — see §2-3 |
| `indicator`, `trade`, `cost` observations | All carry the shared placement block with its mode field |

The three pre-registered non-Ocean records carry no data. They exist so that "the shared
entities are mode-neutral" is a testable statement rather than an intention.

## 2. What a future Air module would add

**WO-039 delivered the first three items** (lanes, the airspace chokepoint, and the event
types this section names) as the Air foundation under Bundle 2 Option A — see
`docs/air_lane_selection.md`. Observations and threshold rules remain undelivered because no
Air source is enabled.

- **Lanes:** `LANE-AIR-TH-*` records with `mode: air`, origin and destination airport
  groups, and airspace chokepoints where relevant.
- **Nodes:** cargo terminals beyond `NODE-THBKKAIR`.
- **Observations:** air cargo tonnage and capacity via `port_transport_observation` with
  `metric: aircraft_movements` or `capacity_deployed`; air freight rate benchmarks via
  `cost_observation` with an appropriate `benchmark_class`.
- **Events:** capacity withdrawal is already expressible. An airport/cargo-terminal
  interruption uses `terminal_or_facility_closure`; an airspace closure uses
  `airspace_closure` — both added by WO-035, no further schema change needed.
- **Threshold rules:** new IDs in `analysis/thresholds.py`, documented alongside in
  `docs/indicator_definitions.md`. The rule engine itself needs no change.

## 3. What a future Land, Rail and Border module would add

**WO-041 delivered the lanes, nodes, chokepoints and closure event typing** as the Land
foundation under Bundle 3, structural-foundation-first — see
`docs/land_rail_border_lane_selection.md`. Observations remain undelivered because no Road,
Rail or Border source is enabled; a mode-neutral *restriction* event type (as distinct from a
closure) also remains undelivered — see `docs/known_data_gaps.md` §9 for why that gap was
left open on purpose.

- **Lanes:** `LANE-ROAD-TH-*`, `LANE-RAIL-TH-*`, `LANE-BORDER-TH-*` with corridor
  resolution. **Delivered:** eight lanes — four cross-border road lanes (one per Thai land
  neighbour), one domestic road lane, one international rail lane, one domestic rail lane,
  and one border-crossing-operations lane covering all four registered crossings.
- **Nodes:** border crossings beyond `NODE-THSDK`, inland terminals, rail terminals.
  **Delivered:** `NODE-THNKI` (Nong Khai, the only registered crossing carrying both road and
  rail), `NODE-THARY` (Aranyaprathet), `NODE-THMST` (Mae Sot), and `NODE-THLKB` (Lat Krabang
  Inland Container Depot, the first `inland_terminal` this platform registers).
- **Chokepoints:** border corridors beyond `CHK-THSDK-BKH`, plus rail gauge breaks.
  **Delivered:** `CHK-THNKI-TNL`, the Nong Khai–Thanaleng rail gauge break — the first
  `rail_gauge_break` this platform registers.
- **Observations:** border crossing counts, rail movements, road transit times. **Still
  undelivered.** No qualified source exists for any of them; every Thai road and rail
  candidate identified is blocked by an unresolved open-data licence question, and no
  border-crossing dataset was found at all. See `docs/known_data_gaps.md` §9.
- **Events:** customs system outage is already in the event type enum. A road, rail or
  border closure uses `terminal_or_facility_closure` — the same WO-035 value §2 uses for
  Air, not a separate one. **Delivered:** one historical validation case, `HVC-010`, uses
  exactly this value for a real border closure.

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
