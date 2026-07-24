# Known data gaps

**Work Order:** WO-010 · **As of:** 2026-07-24

This is the honest inventory. Where the platform cannot say something, this document says
why, rather than the platform saying it anyway.

## 1. The governing gap: no live source coverage

**No source in the registry is enabled. None has completed a controlled live validation.**

Outbound network access was blocked by policy in the WO-010 execution environment, and this
repository's governance requires live source contact to run through the human-triggered
workflow rather than from an automated executor.

Consequences, all stated on the Dashboard's face:

- Every numeric series is a **labelled synthetic test fixture**, not a published statistic.
- All event evidence is a **historical validation fixture** whose content was not retrieved.
- Overall evidence coverage is **insufficient**, and every capability reports the same.
- Every lane assessment carries the coverage limitation in its own limitations list.

## 2. Gaps by capability

| Capability | Gap |
|---|---|
| **Thailand trade flow** | No live source. Published customs figures are all-mode totals, so even once enabled they cannot be attributed to ocean freight without a mode dimension the source does not provide |
| **Thailand port activity** | No live source. The best candidate publishes model-derived estimates from vessel tracking, not port-authority reported throughput |
| **Port operational condition** | **No source of any kind is registered.** No waiting time, berth occupancy or yard measure exists, which is why no congestion statement is made anywhere |
| **Transit time and schedule reliability** | No qualified source. Service quality is assessed only through recorded events |
| **Deployed capacity** | No qualified source. Capacity effects are inferred from routing length and stated as potential |
| **Thailand freight rates** | **No qualified source at all.** No Thailand freight average is published anywhere in the platform |
| **Carrier surcharges and fees** | No qualified source. Recorded as a gap rather than estimated |
| **FX** | Candidate requires an API key; no credential mechanism exists |
| **Energy and commodity baseline** | Candidate publishes XLSX; no XLSX parser exists |
| **Official notices** | Four channels registered, none with a confirmed machine-readable feed. Cadence unknown for all four, so no schedule is justified |
| **News discovery** | Candidate registered but unvalidated. Discovery-only in any case, and skewed toward English-language syndicated outlets |
| **Carrier routing** | Which services actually transit a given chokepoint is carrier-specific and published by no qualified source. Chokepoint exposure is therefore **potential**, never confirmed, for any specific shipment |

## 3. Analytical gaps

- **Lane selection has no quantitative basis.** No trade ranking was retrieved, so lanes
  were selected on documented structural criteria. Every lane records
  `data_period_used: null` and is marked `provisional`.
- **No lane supports port-pair resolution.** The platform holds no Thailand port-pair
  statistics. Eight lanes are regional, two country-level, one corridor.
- **Deviation from baseline is published for exactly one series** (`gscpi_index`), because
  it is the only one with an explicit published baseline.
- **No previous assessment exists**, so "key changes" reports that there is nothing to
  compare against rather than inventing a change.
- **No AI assessment has been produced or approved.** The AI Outlook section is empty and
  says so.
- **Transshipment attribution is impossible.** Thailand cargo relayed through Singapore
  cannot be separated from any qualified public source, so the ASEAN/Singapore lane is
  regional and its Thailand-side effects are potential rather than measured.

## 4. Structural gaps by design

These are out of WO-010's scope, not oversights:

- Air Cargo, and Land/Rail/Border — the shared entities accept them, but no data, lane or
  event exists for any of them.
- Inland drayage on the domestic lane — the Ocean module covers only the seaport leg.
- The Private Decision Overlay — company-specific exposure, capacity and inventory remain
  local-only and outside the public core.
- Innovation Radar — deferred outside the MVP.

## 5. What would close the largest gaps, in order

1. **A controlled live validation of one Thailand trade source** — turns lane selection from
   structural reasoning into evidence, and gives the trade domain a real reading.
2. **Any operational-condition source** — currently the single largest analytical hole. It
   is what stands between "volume pressure" and a supportable congestion statement.
3. **A confirmed machine-readable official notice feed** — or a commitment to the manual
   intake path, which exists and is tested but has recorded nothing.
4. **A transit-time or schedule-reliability source** — would let the service domain be
   measured rather than inferred from events.
