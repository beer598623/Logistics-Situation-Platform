# Bundle 2 — Air Cargo Intelligence: scope and architecture

**Work Order:** WO-017 · **Status:** scoping document only — no Air data, lane, node, or
source contract is delivered by this Work Order.

This is the Bundle 2 equivalent of what
`docs/thailand_multimodal_logistics_intelligence_scope.md` and
`docs/source_priority_framework.md` were for Bundle 1: a scoping document written before
implementation, not a record of what has been built. `docs/thailand_multimodal_logistics_mvp_roadmap.md`
already names "Air Cargo Intelligence" as Phase 3 / the next approved delivery bundle; this
document is what that name expands into.

## 1. What already exists (verified against the actual schema and data, not asserted)

`docs/air_land_extension_points.md` claims WO-010 built a mode-neutral foundation that
accepts Air without a schema change. Re-verified here against the committed files rather than
taken on that document's word:

| Claim | Verified against |
|---|---|
| `observation_common.schema.json`'s `transportMode` permits `air` | `schemas/observation_common.schema.json` |
| `dim_transport_mode` registers `air` at `module_status: planned` | `data/reference/dimensions.json` → `transport_modes` |
| An airport node is already registered | `data/reference/dimensions.json` → `logistics_nodes`: `NODE-THBKKAIR`, "Suvarnabhumi Airport cargo terminal", `node_type: airport`, `modes: [air]`, `known_limitations: ["No Air observations, lanes or events are delivered by WO-010; this node carries no data yet."]` |
| `port_transport_observation.schema.json`'s metric enum already accepts Air-relevant metrics | `schemas/port_transport_observation.schema.json` → `metric` enum includes `aircraft_movements` and `capacity_deployed` (both present; confirmed by direct read, not by cross-reference alone) |
| `cost_observation.schema.json` needs no change for an air freight benchmark | `schemas/cost_observation.schema.json` → `benchmark_class` enum (`market_benchmark`, `route_proxy`, `directional_indicator`, `published_official_price`, `actual_quotation`) is transport-mode-agnostic already |
| `dim_lane` needs no schema change to carry an Air lane | Mode is a data field on the lane record, not a schema branch |

**Closed by WO-035, ahead of any Bundle 2 implementation.** This section originally documented
a real gap: `schemas/logistics_event.schema.json`'s `event_type` enum included
`capacity_withdrawal`, `service_suspension`, `carrier_rerouting`, and `customs_or_system_outage`
— all genuinely mode-agnostic and directly usable for Air — but `port_or_terminal_closure` and
`canal_restriction` were Ocean-worded, with no exact-fit value for an airport/cargo-terminal
closure or an airspace closure. WO-035 added two purely additive enum values —
`airspace_closure` and `terminal_or_facility_closure` — with no existing value renamed or
removed, so no committed event record needed migration. A future Bundle 2 implementation WO
can use these directly; no schema change remains outstanding for event typing.

## 2. What Bundle 2 would add

- **Lanes:** `LANE-AIR-TH-*` records, `mode: air`, origin/destination airport groups, and
  airspace chokepoints where relevant to a lane's routing.
- **Nodes:** cargo terminals beyond `NODE-THBKKAIR` (e.g. Don Mueang, U-Tapao if in scope for
  the selected lanes).
- **Chokepoints:** airspace or airport-capacity chokepoints, using the existing `airspace`
  `chokepoint_type` (`dim_chokepoint`'s type enum already includes it — see
  `docs/air_land_extension_points.md` §1).
- **Observations:** air cargo tonnage/movements and capacity via
  `port_transport_observation` (`metric: aircraft_movements` or `capacity_deployed`); air
  freight rate benchmarks via `cost_observation` with an appropriate `benchmark_class`
  (almost certainly `market_benchmark` or `route_proxy` — an actual-quotation air freight
  source is exceptionally unlikely to be free-and-public, per the qualification framework
  §3).
- **Events:** the `airspace_closure`/`terminal_or_facility_closure` values added by §1's WO-035
  extension, plus reuse of the already-generic types.
- **Threshold rules:** new IDs in `analysis/thresholds.py`, documented in
  `docs/indicator_definitions.md` alongside the existing ones. The rule engine itself needs
  no change (`docs/air_land_extension_points.md` §2 confirms this and it holds on inspection
  of `analysis/thresholds.py`'s structure — rules are data, not mode-specific code paths).

## 3. Air lane-selection criteria — the open question this WO does not resolve

`docs/ocean_lane_selection.md` §1 states plainly: **"No quantitative Thailand trade ranking
was retrieved under WO-010."** Every Ocean lane's selection rests on structural reasoning
(named port pairs, known trade corridors), not a ranked volume source, and the lane records
say so explicitly (`data_period_used: null`, the limitation stated in `known_limitations`).

A Bundle 2 implementation WO faces the identical choice WO-010 already made once for Ocean,
and this document deliberately does not make it in advance:

- **Option A — structural reasoning again.** Select initial Air lanes by named
  airport-pair significance (e.g. Suvarnabhumi as Thailand's primary cargo gateway, paired
  with its most obviously significant international counterparts), exactly as Ocean did.
  This repeats a documented limitation rather than closing it, and the implementation WO
  should say so as plainly as `docs/ocean_lane_selection.md` does, not less plainly.
- **Option B — wait for or seek a qualified ranking source.** Do not select Air lanes until
  an air cargo volume/route significance source is qualified per §4 below. This delays
  Bundle 2's start but avoids compounding the same limitation a second time.

**Evidence update (WO-034/WO-036, see `docs/known_data_gaps.md` §8):** a candidate for
Option B was found and bounded-live-validated — `air-freight-pass` on `datagov.mot.go.th`,
CAAT-sourced, airport-disaggregated, annual, DataStore-backed. It is not yet usable for
either option: its licence names nothing real (`"Open Data Common"`, `isopen: false`), and
its cargo-specific rows were never observed in the bounded read (only passenger rows
returned), so neither its unit/scale nor its exact cargo field value is confirmed. This
narrows, but does not close, the question — a future implementation WO still chooses between
A and B, now with a concrete, partially-verified Option B candidate on record rather than a
purely hypothetical one.

Neither option is authorized by this WO. The choice belongs to whichever future WO actually
implements Bundle 2, made explicitly and reviewed, not defaulted into.

## 4. Source-capability gaps Air introduces

None of the following exist in `config/sources.yaml` today (verified: zero entries with
`logistics_role` or `purposes` referencing air/aviation/cargo-terminal activity). A Bundle 2
implementation WO needs at least one of each, run through the same Gate C qualification
process `docs/source_qualification_report.md` used for Bundle 1's 18 candidates:

| Gap | What it would support | Bundle 1 analogue | Status after WO-034/036 |
|---|---|---|---|
| Air cargo volume/route significance source | Lane selection (§3 Option B), `aircraft_movements` observations | `IMF_PORTWATCH`, `PAT_STATISTICS` (Ocean port activity) | **Candidate found and bounded-live-validated: `air-freight-pass` on `datagov.mot.go.th`.** Field contract verified; blocked on an unresolved licence (`"Open Data Common"`, `isopen: false`) and on the cargo-specific rows never having been observed (only passenger rows were returned). See `docs/known_data_gaps.md` §8. |
| Air freight rate benchmark | `cost_observation` records, distinct route scope from `FBX_PUBLIC` — `config/sources.yaml`'s own `known_limitations` for that contract state it covers "named east-west **container** routes" only and "No route in this index is a Thailand-origin route", so it cannot stand in for an air freight reading | `FBX_PUBLIC` | **No free official Thailand-scoped source found (WO-034).** Every commercial candidate investigated (IATA, ACI, TAC Index, Baltic Exchange, and Freightos' free tier) is *reported* paid, membership-gated, or a regional (not Thailand) aggregate — all their hosts were blocked in that environment, so this is secondary evidence, not a direct read (see `docs/known_data_gaps.md` §8). Documented as an unclosed gap, not manufactured around. |
| Airport/airspace operational-notice source | Event evidence for closures, capacity withdrawals, airspace restrictions | `PAT_NOTICE` (Ocean port notices) | **AEROTHAI's NOTAM office identified as the correct primary source (WO-034), but blocked on reachability, likely PDF format, and unknown terms — not on merit.** `MANUAL_NOTICE_INTAKE` (already implemented, zero-egress) is the honest interim path, matching Ocean's four notice channels. |
| Airport authority statistics (Thailand-specific) | A Thailand-scoped alternative or complement to a global aviation-volume source | `PAT_STATISTICS` | **Substantially the same candidate as the row above** (`air-freight-pass` is CAAT-sourced; `[INFERENCE]` from its CAAT lineage — the national aviation regulator's own statistics, not just AOT's six airports — that it covers all Thai public airports; the airport list was not read exhaustively, but the five values observed at `limit=5` already include non-AOT regional airports (Buriram, Chiang Rai)). AOT's, the Department of Airports' and CAAT's own direct catalogue entries (`aot_traffic`, `airports-dataset`, `domestic-air-freight`) were separately checked (WO-036) and found stale, empty, or file-only — not usable regardless of this gap's disposition. AEROTHAI's Bangkok FIR flight-volume series was bounded-live-validated and found **NOT QUALIFIED**: no cargo dimension, no aerodrome resolution. |

Qualifying any of these means reading the publisher's actual terms and recording
`reuse_status`/`redistribution_status` — the same standing requirement `docs/source_enablement_decisions.md`
applies to every current source, none of which is waived for a new mode.

## 5. Acceptance gates for a Bundle 2 implementation Work Order

Mirroring what Bundle 1 actually delivered and was reviewed against — not a new invented
bar:

1. **Gate B/C equivalent** — a data-model and source-qualification pass for every new Air
   source candidate, following `docs/source_priority_framework.md`'s existing framework
   rather than a Bundle-2-specific one.
2. **No source enabled by default** — every new Air source contract ships `enabled: false`,
   exactly like all 17 current entries.
3. **Fixture/current separation preserved** — any Air fixture data is `evidence_origin`-tagged
   and dataset-scoped identically to Ocean's, never entering `current_publication` without a
   genuine live source.
4. **Publication-use enforcement extended, not bypassed** — the same `scripts/validate.py`
   checks that guard Ocean records (missing-as-zero, organization-neutral, benchmark/proxy
   labelling) must hold for every new Air record with no mode-specific carve-out.
5. **At least one historical validation case** — mirroring the 8 Ocean cases
   `docs/known_data_gaps.md` and the validation suite already rely on, demonstrating the Air
   event/impact/scenario chain end-to-end before any live data is claimed.
6. **Dashboard integration** — an Air section (or extension of an existing section) that
   states its coverage honestly, the same way the current Dashboard states
   `live_coverage: insufficient` rather than implying completeness.
7. **All existing tests continue to pass**, plus new tests for every new schema field,
   adapter, and validation rule — no reduction in `tests/test_reference_and_lanes.py`'s
   existing mode-neutrality assertions.
8. **Independent review**, following this repository's standing process
   (`CONTRIBUTING.md`): the implementer does not approve their own Bundle 2 work.

## 6. What this document explicitly does not do

- It does not add, modify, or enable any source in `config/sources.yaml`.
- It does not add an Air lane, node, chokepoint, observation, or event record.
- It does not itself change any schema — the event-type enum gap this document (WO-017)
  identified in §1 was fixed separately, by WO-035, which also updated this section.
- It does not decide between §3's Option A and Option B.
- It does not authorize contacting any publisher or beginning a live validation for any
  candidate source named in §4.
