# Air Lane selection methodology and selected lanes

**Work Order:** WO-039 Bundle 2 Option A · **Review date:** 2026-08-06 · **Lane count:** 5
**Machine-readable:** `data/reference/lanes.json` · **Contract:** `schemas/lane.schema.json`

## 1. The evidence limitation, stated first

**No quantitative Thailand air cargo ranking was retrieved or used under WO-039.** This is a
stronger limitation than Ocean's, not a weaker one, for three independent reasons:

- The one Thai air-cargo candidate identified to date, `air-freight-pass` on
  `datagov.mot.go.th`, stays unregistered: its licence names nothing real
  (`license_id: "Open Data Common"`, `license_url: null`, `isopen: false`) and its schema
  carries no unit column at all, so its `Value` figures could never be read as a verified
  quantity regardless of which rows are read. See `docs/known_data_gaps.md` §8.
- The other candidate investigated, AEROTHAI's Bangkok FIR flight-volume series, was closed
  **NOT QUALIFIED** on substance: its "type of operation" field carries no cargo dimension
  (`Schedule`/`General`/`Others`/`Military`/`Non-Schedule` only) and it carries no aerodrome
  field, so it can never resolve to `NODE-THBKKAIR` even in principle.
- No free Thailand-scoped air freight rate benchmark exists. `FBX_PUBLIC` covers named
  east-west **container** routes only and cannot stand in for an air reading.

**No figure from any of those three was used to select, rank, order or size any lane.**

Every lane therefore records `data_period_used: null`, states that limitation explicitly in
`known_limitations`, and classifies each selection statement with its own evidence class.
Where a statement rests on general structural reasoning rather than on a retrieved figure, it
is classified `analytical_inference` with a null source reference — never dressed up as a
measurement. Where a criterion could not be supported at all, it is classified
`insufficient_evidence` rather than left silent. `scripts/validate.py::lane_checks` enforces
that a statement classified as anything stronger must cite a source.

Lanes are `status: provisional` for exactly this reason. Re-selection against measured air
cargo data is the first thing that should happen once a qualified Air source is enabled.

## 2. Selection criteria

The lane contract permits seven criteria. Which were actually usable for Air:

| Criterion | Used? | Notes |
|---|---|---|
| Recent Thailand air cargo value or volume | **No** | No source retrieved or usable. Recorded as `insufficient_evidence` on every lane |
| Data availability | Yes, as `insufficient_evidence` | Recorded to name that nothing covers any Air lane, rather than left blank |
| Strategic trade relevance | Yes, as `analytical_inference` | Well-established corridor relationships, not a measured ranking |
| Chokepoint exposure | Yes, as **`analytical_inference`** | Deliberately weaker than Ocean's `verified_fact`: a ship's transit of a strait is geography, an aircraft's routing is a filed flight plan this platform does not observe |
| Geographic coverage | Yes, as `analytical_inference` | So the set is not composed only of long-haul groupings |
| Operational distinctiveness | Yes, as `analytical_inference` | Lanes that would behave differently under the same event are kept separate |
| Ability to support source-backed analysis | **No** | Not used at all: no registered notice channel covers any Air lane, so no lane could claim it. Ocean's `official_publication` class appears nowhere in the Air set |

No lane was selected on an assumption about any specific company or carrier. The platform
holds no company data at all.

## 3. The five lanes

| Lane ID | Name | Resolution | Chokepoints |
|---|---|---|---|
| `LANE-AIR-TH-EASIA` | Thailand ↔ East Asia air cargo | regional | — |
| `LANE-AIR-TH-ASEAN` | Thailand ↔ ASEAN and Singapore air cargo | regional | — |
| `LANE-AIR-TH-EUR` | Thailand ↔ Europe air cargo | regional | South Asian overflight corridor |
| `LANE-AIR-TH-NAM` | Thailand ↔ North America air cargo | regional | — |
| `LANE-AIR-TH-DOMESTIC` | Thailand air cargo gateway and domestic connection | corridor | — |

### Why these groupings

Ocean has eleven lanes; Air has five. The reduction is not arbitrary — each Ocean grouping
decision rests on at least one structural fact Air does not have:

- **China, Hong Kong, Japan and Korea are one East Asia lane**, not split as Ocean splits
  them, because the platform holds no air network or schedule reference data that would
  justify separating them. East Asia carries Thailand's manufacturing component flows in both
  directions, and time-sensitive electronics and component movements are the category most
  commonly carried by air rather than sea, giving the grouping continuity relevance distinct
  from its ocean counterpart.
- **ASEAN and Singapore kept as one lane**, mirroring Ocean's reasoning exactly: it carries
  short-haul regional flows and the intra-ASEAN transfer leg a Thailand long-haul air shipment
  may use, so a disruption here can propagate into the long-haul lanes as well as affecting
  the lane itself. It is also included so the set is not composed only of long-haul groupings.
- **Northern Europe and the Mediterranean grouped into one lane**, unlike Ocean's separate
  lanes. Ocean's split rests on Mediterranean ports being the first discharge after Suez; no
  air routing analogue to that sequencing exists, so splitting here would assert a distinction
  this platform cannot support. This is the only lane in the set with a stated corridor
  exposure — a Thailand–Europe air routing crosses South Asian airspace — recorded as
  `analytical_inference`, not `verified_fact` (see the note below).
- **North America grouped as one lane**, unlike Ocean's West Coast / East and Gulf Coast
  split. Ocean's split rests on a genuine Panama-versus-Suez routing choice; no equivalent
  competing air routing is registered, so splitting here would be an invented distinction. It
  is kept in the set so the effect of a corridor event on the Europe lane can be read against
  a long-haul lane that does not share that corridor.
- **A domestic lane**, mirroring Ocean's reasoning: every international Air lane in this set
  terminates at the same single registered Thailand airport node, so gateway condition is a
  shared dependency assessed once here rather than duplicated into each lane.

**Note the deliberate downgrade.** Ocean records `chokepoint_exposure` as `verified_fact`
because a ship's transit of a strait is fixed by geography. An aircraft's routing is not — it
is a filed flight plan this platform does not observe — so the Europe lane's chokepoint
exposure is recorded as `analytical_inference` throughout, enforced by
`test_air_chokepoint_exposure_is_inference_not_verified_fact`.

### What was deliberately not included

South Asia, the Middle East and Gulf, Oceania, Africa and Latin America are each a plausible
Air corridor grouping, but WO-039 has no structural fact that distinguishes any of them from
the long-haul groups already present — only a volume ranking could, and no usable ranking
source exists. Adding them would be padding, and padding a lane set under `analytical_inference`
is exactly the failure mode §1 above exists to prevent. They are named again in §6's review
triggers rather than added speculatively.

Oceania in particular is not included as a second chokepoint-free long-haul baseline, because
the North America lane already supplies one; a second would be redundant.

## 4. Resolution honesty

**No lane claims airport-pair resolution**, because the platform holds no Thailand
airport-pair statistics — and the lane contract has **no `airport_pair` value at all**: the
`resolution` enum in `schemas/lane.schema.json` permits only `port_pair`, `port_group`,
`country`, `regional` and `corridor`, and WO-039 deliberately did not add one.
`test_no_air_lane_claims_a_resolution_it_does_not_have` enforces both halves of that claim.

The four international Air lanes have exactly one registered node between them
(`NODE-THBKKAIR`, the Thailand end). No destination airport node is registered for any of
them, so an event at a foreign airport cannot resolve to an Air lane by node —
`test_every_air_lane_anchors_only_on_registered_air_nodes` locks this in.

`CHK-SASIA-AIRSPACE` reuses the existing `GEO-RGN-SASIA` geography record rather than minting
a new one, because the geography `level` enum in `schemas/reference_dimensions.schema.json`
has no `airspace` value. Inventing one would have been a schema change this Work Order does
not need; §5 of `docs/bundle2_air_cargo_scope.md`'s acceptance gates does not require it
either.

## 5. Mode neutrality

Every lane here is `mode: air`, and the lane contract carries mode as data — no schema change
was needed to add any of them, exactly as `docs/ocean_lane_selection.md` §5 asserts for
Ocean. `test_the_lane_contract_is_mode_tagged_rather_than_ocean_hardcoded` covers both modes
in one assertion.

**Mode-respecting, not just mode-neutral.** `analysis.reference.resolve_lane_relevance` now
accepts a `modes` parameter: a lane whose mode is not among an event's stated `modes` is never
matched, however many countries or nodes they share. Before this change, an Ocean event
tagged `country_ids: ["TH"]` would have resolved every Air lane too, purely because every Air
lane also lists `TH` — the same "geography leakage" failure mode
`scripts/run_historical_validation.py` already measures for. The rule uses strict set
membership with no `multimodal` wildcard: an event tagged `modes: ["sea", "road",
"multimodal"]` still resolves no Air lane, because "multimodal" names the modes an event
actually lists, not "every mode there is." A caller that passes no `modes` at all keeps the
old mode-blind behaviour, which is why every previously committed Ocean historical-validation
case still passes unchanged. `test_lane_relevance_respects_the_event_modes` covers all four
cases.

The Ocean analysis pipeline (`scripts/build_analysis.py`, `scripts/build_dashboard.py`) is
explicitly scoped to `mode == "sea"` lanes wherever it produces a lane assessment, indicator
roll-up or scenario outlook. The Thailand roll-up therefore remains `subject: thailand_ocean`
— Air is not silently folded into it, and a future Air extension of that roll-up is a decision
for whichever Work Order actually has Air observation data to roll up.

## 6. Review triggers

This lane set should be re-reviewed when any of the following occurs:

- an air cargo volume or route-significance source is enabled, making evidence-based ranking
  possible for the first time;
- the `air-freight-pass` licence question (`"Open Data Common"` / `isopen: false`) is resolved
  by a human determination;
- a Thailand airport-level source is enabled, making airport-group resolution possible;
- an airport or airspace notice channel is registered, at which point `CHK-SASIA-AIRSPACE`
  gains an `authority_notice_source_ids` entry and the `source_backed_analysis_support`
  criterion becomes usable for the first time;
- a second Thai airport node is registered;
- any of the deliberately omitted corridors named in §3 — South Asia, the Middle East and
  Gulf, Oceania, Africa, Latin America — acquires a structural or measured basis;
- the Land module is built, at which point the domestic lane's landside leg gains its own
  road record rather than continuing to be described only as a known limitation of this one.
