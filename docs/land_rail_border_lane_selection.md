# Land, Rail and Border Lane selection methodology and selected lanes

**Work Order:** WO-041 Bundle 3 (structural-foundation-first) · **Review date:** 2026-08-06 · **Lane count:** 8
**Machine-readable:** `data/reference/lanes.json` · **Contract:** `schemas/lane.schema.json`

## 1. The evidence limitation, stated first

**No quantitative Thailand road, rail or border freight ranking was retrieved or used under
WO-041.** This is a stronger limitation than Air's, not a weaker one, for two independent
reasons:

- Four Thai candidates were identified for Road and Rail — `freight-import-export` and
  `freight-dom` (MOT-ICT, mode-split national trade volume) and `stat_freight_rail`
  (Department of Rail Transport, monthly and province-resolved) — and every one is blocked
  before qualification by the identical `license_id: "Open Data Common"`, `license_url:
  null`, `isopen: false` non-licence string that already blocks the Air and Ocean candidates.
  This is no longer an isolated per-dataset finding: it is a cross-cutting Thai open-data
  licensing question that now blocks three modules at once. See `docs/known_data_gaps.md`
  §9. `stat_freight_rail` is additionally reachable only through a harvest mirror, not its
  primary catalogue.
- **No border-crossing dataset of any kind exists** in the Ministry of Transport's open-data
  catalogue. This is a documented negative research result — two independent Thai-language
  catalogue searches returned zero hits — not an incomplete search or a candidate that failed
  qualification.

**No figure from any of these was used to select, rank, order or size any lane.** No row of
`freight-import-export`, `freight-dom`, `stat_freight_rail` or the examined-and-refused
truck-GPS analytics candidate (`gps-freight-transport-analytics`) was ever read.

Every lane therefore records `data_period_used: null`, states that limitation explicitly in
`known_limitations`, and classifies each selection statement with its own evidence class.
Where a statement rests on general structural reasoning rather than on a retrieved figure, it
is classified `analytical_inference` with a null source reference — never dressed up as a
measurement. Where a statement rests on a fact already recorded elsewhere in this platform's
own registry (for example, an existing country record's `known_limitations`), it cites that
record as its `source_reference` — a citable in-repo structural basis, not an external
measurement. `scripts/validate.py::lane_checks` enforces that a statement classified as
anything stronger must cite a source.

Lanes are `status: provisional` for exactly this reason. Re-selection against measured road,
rail or border data is the first thing that should happen once a qualified source is enabled.

## 2. Selection criteria

The lane contract permits seven criteria. Which were actually usable for Land:

| Criterion | Used? | Notes |
|---|---|---|
| Recent Thailand road, rail or border freight value or volume | **No** | No source qualified. Recorded as `insufficient_evidence` on every lane |
| Data availability | Yes, as `insufficient_evidence` | Recorded to name the specific blocker per mode — a blocked licence for Road and Rail, a total absence of a dataset for Border. These are different facts and are stated differently, not flattened into one sentence |
| Strategic trade relevance | Yes, as `analytical_inference`, citing this platform's own registry | The three land-neighbour road lanes (Lao PDR, Cambodia, Myanmar) each close a limitation this platform's own country records already state |
| Chokepoint exposure | Yes, as `analytical_inference` | The Sadao–Bukit Kayu Hitam corridor (already registered under WO-010) and the Nong Khai–Thanaleng rail gauge break |
| Geographic coverage | Yes, as `analytical_inference` | Thailand has exactly four land neighbours; the four cross-border road lanes are a complete partition, not a selection |
| Operational distinctiveness | Yes, as `analytical_inference` | Lanes that would behave differently under the same event, or that carry a genuinely distinct analytical subject, are kept separate |
| Ability to support source-backed analysis | **No** | Not used at all: no registered notice channel covers any Land lane, so no lane may claim it |

No lane was selected on an assumption about any specific company, carrier or haulier. The
platform holds no company data at all.

## 3. The eight lanes

| Lane ID | Name | Mode | Resolution | Chokepoints |
|---|---|---|---|---|
| `LANE-ROAD-TH-MY` | Thailand ↔ Malaysia cross-border road freight | road | corridor | Sadao–Bukit Kayu Hitam |
| `LANE-ROAD-TH-LA` | Thailand ↔ Lao PDR cross-border road freight | road | corridor | — |
| `LANE-ROAD-TH-KH` | Thailand ↔ Cambodia cross-border road freight | road | corridor | — |
| `LANE-ROAD-TH-MM` | Thailand ↔ Myanmar cross-border road freight | road | corridor | — |
| `LANE-ROAD-TH-DOMESTIC` | Thailand domestic road freight and gateway drayage | road | corridor | — |
| `LANE-RAIL-TH-LA` | Thailand ↔ Lao PDR international rail freight | rail | corridor | Nong Khai–Thanaleng gauge break |
| `LANE-RAIL-TH-DOMESTIC` | Thailand domestic rail freight and port connection | rail | corridor | — |
| `LANE-BORDER-TH-CROSSINGS` | Thailand land border crossing operations | border | corridor | Sadao–Bukit Kayu Hitam, Nong Khai–Thanaleng |

### Why these groupings

- **One road lane per land neighbour.** Thailand has exactly four land neighbours — Malaysia,
  Lao PDR, Cambodia and Myanmar — and the four road lanes are a **complete partition** of
  them, not a selection. Omitting any one would be arbitrary in a way this platform's other
  omissions are not. Three of the four close a limitation this platform's own country
  records already state: Lao PDR is recorded as "a landlocked neighbour dependent on
  Thailand ports for ocean access" with land and rail transit named as "a Land-module
  concern"; Cambodia and Myanmar both carry "Cross-border road flows are a Land-module
  concern and are not assessed by the Ocean module."
- **Malaysia kept structurally distinct within the four.** It is the only Thai land corridor
  with a chokepoint already registered in this platform (`CHK-THSDK-BKH`, registered under
  WO-010), and its destination country also hosts major container ports — an ocean
  alternative the other three land-neighbour lanes lack.
- **A domestic road lane** closes two limitations already recorded in this repository:
  `LANE-AIR-TH-DOMESTIC`'s landside road drayage leg, explicitly deferred to "a separate road
  lane record when the Land module is built," and the Ocean module's own inland-drayage gap
  on the seaport leg.
- **International rail kept to one lane.** Thailand's rail network has exactly one physically
  continuous international connection, and it crosses a gauge break: Thailand's metre-gauge
  network meets standard gauge at the Lao side of the Nong Khai crossing, so a through
  container must be transhipped. This is fixed infrastructure, not an inferred fact — but the
  lane's chokepoint-exposure evidence is still classified `analytical_inference`, not
  `verified_fact`, because this platform holds no rail network reference data and observes no
  train.
- **A domestic rail lane** because the port-to-inland-container-depot rail leg is a shared
  dependency of Thai rail freight, assessed once here rather than duplicated.
- **A single Border lane covering all four crossings**, rather than one Border lane per
  crossing. Its subject is the crossing process itself — customs, immigration, inspection,
  opening hours — not any particular vehicle movement or country pair. A customs-system
  outage or a bilateral closure acts on that process at every registered crossing at once and
  is not attributable to one country pair, so it is assessed once here rather than duplicated
  into the four road lanes. This gives `mode: border` a distinct analytical subject rather
  than a duplicate of the road lanes, mirroring how the Ocean and Air domestic lanes use the
  same shared-dependency reasoning.

### What was deliberately not included

A separate lane per border crossing (rather than the single `LANE-BORDER-TH-CROSSINGS`), and
a domestic road lane covering every Thai road movement rather than only the gateway-connected
leg this platform has a node for, would both be padding: neither closes a recorded limitation
or rests on a structural fact this platform holds. They are named here so a future reviewer
does not re-propose them without new evidence.

## 4. Resolution honesty

**No lane claims a resolution it does not have.** The lane contract's `resolution` enum
permits only `port_pair`, `port_group`, `country`, `regional` and `corridor` — there is **no
border-pair or crossing-specific value**, and WO-041 deliberately did not add one, mirroring
WO-039's refusal to invent `airport_pair` for Air. `corridor` is the honest value for every
lane in this set.

The four cross-border road lanes and the international rail lane each have exactly one
registered node on the Thailand side. No foreign crossing node is registered for any of them,
so an event on the far side of a crossing cannot resolve to a Land lane by node —
`test_every_land_lane_anchors_only_on_registered_land_nodes` locks this in.

`CHK-THNKI-TNL` is the first chokepoint of type `rail_gauge_break` this platform registers.
No new geography level was needed for it, or for any of the three new country geographies
(`GEO-CTY-KH`, `GEO-CTY-LA`, `GEO-CTY-MM`) this Work Order added — the `country` level already
existed.

## 5. Mode neutrality

Every lane here carries `mode: road`, `mode: rail` or `mode: border`, and the lane contract
carries mode as data — no schema change was needed to add any of them, exactly as
`docs/air_lane_selection.md` §5 asserts for Air.

**Mode-respecting, inherited rather than rebuilt.** `analysis.reference.resolve_lane_relevance`'s
`modes` parameter (added under WO-039) already required both call sites to pass an event's
stated modes before this Work Order began, so no code change was needed to prevent a Land
event leaking into an Ocean or Air lane, or vice versa — this Work Order only had to prove
the guard actually holds for a real Land event, which `HVC-010` does.

The Land payload's node and chokepoint filters use an explicit **allowlist**
(`{road, rail, border}`), not a denylist of "not sea and not air." A denylist would sweep
`NODE-THBKK`'s `inland_waterway` mode into the Land payload; the allowlist cannot.

The Ocean analysis pipeline (`scripts/build_analysis.py::_ocean_lanes()`) is unchanged by this
Work Order — it already filtered strictly to `mode == "sea"`, so adding Land lanes to the
shared registry required no widening and introduced no risk of a Land lane picking up a
fabricated Ocean assessment. The Thailand roll-up remains `subject: thailand_ocean`.

## 6. Review triggers

This lane set should be re-reviewed when any of the following occurs:

- the cross-cutting Thai open-data licence question (`"Open Data Common"` / `isopen: false`)
  is resolved by a human determination, which would potentially unblock `freight-import-export`,
  `freight-dom` and `stat_freight_rail` simultaneously;
- `stat_freight_rail`'s primary catalogue (`drt.gdcatalog.go.th`, not the `datagov.mot.go.th`
  harvest mirror this platform can currently reach) becomes reachable;
- a border-crossing or customs-operational dataset is identified — none exists in the
  Ministry of Transport's catalogue as of this review, but a different Thai publisher (for
  example, the Ministry of Commerce's border-trade reporting) may carry one;
- an airport or land-border notice channel is registered, at which point `CHK-THSDK-BKH` or
  `CHK-THNKI-TNL` gains an `authority_notice_source_ids` entry and the
  `source_backed_analysis_support` criterion becomes usable for the first time;
- a second Thai land-border node beyond the four registered here is needed;
- a mode-neutral event-type value for a road, rail or border *restriction* (as distinct from
  a full closure) is added — `docs/known_data_gaps.md` §9 records this as a documented,
  deliberately unclosed schema gap.
