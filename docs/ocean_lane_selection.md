# Ocean Lane selection methodology and selected lanes

**Work Order:** WO-010 Gate E · **Review date:** 2026-07-24 · **Lane count:** 11
**Machine-readable:** `data/reference/lanes.json` · **Contract:** `schemas/lane.schema.json`

## 1. The evidence limitation, stated first

**No quantitative Thailand trade ranking was retrieved under WO-010.** No source could be
live-validated in the execution environment (see `docs/source_qualification_report.md`), so
no lane was selected on measured trade value or volume.

Every lane therefore records `data_period_used: null`, states that limitation explicitly in
`known_limitations`, and classifies each selection statement with its own evidence class.
Where a statement rests on general structural reasoning rather than on a retrieved figure,
it is classified `analytical_inference` with a null source reference — never dressed up as a
measurement. `scripts/validate.py::lane_checks` enforces that a statement classified as
anything stronger must cite a source.

Lanes are `status: provisional` for exactly this reason. Re-selection against measured trade
data is the first thing that should happen once a trade source is enabled.

## 2. Selection criteria

The lane contract permits seven criteria. Which were actually usable:

| Criterion | Used? | Notes |
|---|---|---|
| Recent Thailand import/export value or volume | **No** | No data retrieved. Recorded as `insufficient_evidence` where it would have applied |
| Data availability | Yes | Which registered candidate would cover the lane once qualified |
| Strategic trade relevance | Yes, as `analytical_inference` | Well-established partner relationships, not a measured ranking |
| Chokepoint exposure | Yes, as `verified_fact` | Derived from the platform's own chokepoint reference data |
| Geographic coverage | Yes | So the set is not concentrated in one direction |
| Operational distinctiveness | Yes | Lanes that would behave differently under the same event are kept separate |
| Ability to support source-backed analysis | Yes, as `official_publication` | Whether a registered official notice channel covers the lane |

No lane was selected on an unrecorded assumption about any specific company. The platform
holds no company data at all.

## 3. The eleven lanes

| Lane ID | Name | Resolution | Chokepoints |
|---|---|---|---|
| `LANE-OCEAN-TH-EASIA-CN` | Thailand ↔ Mainland China and Hong Kong | country | — |
| `LANE-OCEAN-TH-JPKR` | Thailand ↔ Japan and Korea | country | — |
| `LANE-OCEAN-TH-ASEAN-SG` | Thailand ↔ ASEAN and Singapore transshipment | regional | Malacca, Singapore |
| `LANE-OCEAN-TH-SASIA` | Thailand ↔ South Asia | regional | Malacca |
| `LANE-OCEAN-TH-MEGULF` | Thailand ↔ Middle East and Gulf | regional | Malacca, Hormuz |
| `LANE-OCEAN-TH-NEUR` | Thailand ↔ Northern Europe | regional | Malacca, Bab el-Mandeb, Suez |
| `LANE-OCEAN-TH-MED` | Thailand ↔ Mediterranean | regional | Malacca, Bab el-Mandeb, Suez |
| `LANE-OCEAN-TH-USWC` | Thailand ↔ United States West Coast | regional | — |
| `LANE-OCEAN-TH-USEC` | Thailand ↔ United States East and Gulf Coast | regional | Panama, Malacca, Suez |
| `LANE-OCEAN-TH-OCEANIA` | Thailand ↔ Australia and New Zealand | regional | — |
| `LANE-OCEAN-TH-DOMESTIC` | Thailand domestic port and inland connection | corridor | — |

### Why these groupings

- **China and Hong Kong together, Japan and Korea together.** Both pairs are commonly served
  on shared service strings, so they behave as one operational group. The cost is that a
  disruption affecting only one country of a pair will be understated; each lane records
  that.
- **ASEAN and Singapore as one lane.** It carries both direct intra-ASEAN cargo and the
  transshipment leg of most Thailand long-haul services, so disruption here propagates into
  several other lanes. It is also the only lane with a registered notice channel covering
  its own chokepoint.
- **North Europe and Mediterranean kept separate** despite sharing a routing, because
  Mediterranean ports are the first discharge after Suez: a Suez event moves the two lanes
  by different amounts and at different times.
- **US West Coast and East/Gulf Coast kept separate** because the East/Gulf lane is the only
  one in the set with a genuine routing choice — eastbound via Panama or westbound via Suez
  — and therefore two competing chokepoint exposures.
- **Oceania included for geographic coverage.** Without it the set would have no lane south
  of the equator and no chokepoint-free long-haul comparison baseline.
- **A domestic lane** because every international lane terminates at a Thailand port, so
  domestic port condition is a shared dependency assessed once rather than duplicated
  eleven times.

## 4. Resolution honesty

**No lane claims port-pair resolution**, because the platform holds no Thailand port-pair
statistics. `tests/test_reference_and_lanes.py::test_no_lane_claims_port_pair_resolution_without_port_pair_data`
enforces that. The Dashboard prints each lane's actual resolution on its card, and the
Trade section repeats it per lane.

A regional lane is a genuine analytical object — it is just not a port-pair one, and the
difference is never blurred.

## 5. Mode neutrality

Every lane is `mode: sea`, but the lane contract carries mode as data. Adding an Air or Road
lane is a new record, not a schema change — asserted by
`test_the_lane_contract_is_mode_tagged_rather_than_ocean_hardcoded`.

The domestic lane is tagged `sea` because only its seaport leg is in scope. Its inland road
and rail drayage is a Land-module concern and is explicitly **not** assessed by WO-010; the
lane records that limitation rather than implying coverage it does not have.

## 6. Review triggers

This lane set should be re-reviewed when any of the following occurs:

- a Thailand trade source is enabled, making evidence-based ranking possible for the first
  time;
- a port-level Thailand source is enabled, making port-pair or port-group resolution
  possible;
- a lane's chokepoint exposure changes because a routing pattern changes;
- the Air or Land module is built, at which point lanes for those modes are added alongside
  rather than replacing these.
