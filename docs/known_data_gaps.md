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
| **Thailand trade flow** | No live source. Published customs figures are all-mode totals, so even once enabled they cannot be attributed to ocean freight without a mode dimension the source does not provide. WO-029 identified `ctm_06_18`/`ctm_06_17` on `catalog.customs.go.th` as the only located candidates carrying an explicit mode dimension; that host is allowlisted but has never delivered a byte (see §7) |
| **Thailand port activity** | No live source. `PAT_STATISTICS` — Port Authority of Thailand's own CKAN catalogue — is the strongest candidate found, not the vessel-tracking estimate: WO-032's mirror evidence shows monthly per-port vessel/cargo/container data through June 2026, but the primary host has never delivered a byte, and two publisher-side findings (a self-contradicting container unit, an unnamed licence) block it regardless of reachability (see §7). `IMF_PORTWATCH`'s model-derived vessel-tracking estimate remains a fallback candidate only |
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

## 5. Two "nine domains" vocabularies, reconciled

The repository has two disjoint nine-item vocabularies, both enforced with near-identical wording
in `scripts/validate.py` ("must assess/contain all nine ... exactly once"), which invites the
assumption that they line up one-to-one. They don't.

- **Measurement domains** — `analysis/assessments.py:39-49`'s `DOMAINS`. What each lane
  assessment actually measures: `thailand_trade_flow`, `port_maritime_activity`,
  `freight_benchmark_direction`, `fuel_pressure`, `fx_pressure`, `operational_event_status`,
  `capacity_evidence`, `transit_time_or_service_evidence`, `source_freshness_and_coverage`.
  Enforced at `scripts/validate.py:479-481`.
- **Business impact areas** — `schemas/impact_assessment.schema.json`'s `area` enum. What an
  *event's* impact assessment is scored against: `warehouse`, `logistics`, `transport`,
  `import_export`, `inventory`, `cost`, `capacity`, `service`, `business_continuity`. Enforced at
  `scripts/validate.py:115-116` and described at `schemas/logistics_event.schema.json:335`.

The table below records the actual relationship, read from the code that computes each domain
(`scripts/build_analysis.py`, `analysis/events.py::event_domain_direction`) rather than asserted
from either vocabulary's name:

| Measurement domain | How it's derived | Impact area(s) |
|---|---|---|
| `operational_event_status` | Event-derived: `event_domain_direction(lane_id, events, areas)` | **Code-enforced**: `transport`, `logistics`, `import_export` |
| `capacity_evidence` | Event-derived: same function | **Code-enforced**: `capacity` |
| `transit_time_or_service_evidence` | Event-derived: same function | **Code-enforced**: `service`, `transport` |
| `thailand_trade_flow` | Indicator-derived: a trade-value series and a threshold rule | No code link. Conceptually closest to `import_export` |
| `port_maritime_activity` | Indicator-derived: `thailand_port_calls` series | No code link. Conceptually closest to `transport` |
| `freight_benchmark_direction` | Indicator-derived: `container_freight_benchmark` series | No code link. Conceptually closest to `cost` |
| `fuel_pressure` | Indicator-derived: `thailand_diesel_retail_price` series | No code link. Conceptually closest to `cost` |
| `fx_pressure` | Indicator-derived: `usd_thb_reference_rate` series | No code link. Conceptually closest to `cost` |
| `source_freshness_and_coverage` | Meta-domain: overall source-coverage status, not a lane condition | No correspondence, conceptual or otherwise — it is not about business impact at all |

"Code-enforced" means `analysis/events.py::event_domain_direction` literally filters
`impact_assessments` on `impact["area"] in areas` for that domain — a `deteriorating` reading
requires an event whose recorded impact area matches. The five indicator-derived domains never
read an event's `area` field at all; the "conceptually closest" column is this document's own
informal reading for a person comparing the two vocabularies, not something any code path checks.

**Three impact areas have no domain evidencing them, even conceptually: `warehouse`, `inventory`,
`business_continuity`.** No measurement domain is derived from, or informally maps to, any of the
three. An event can still carry an impact assessment scored against them (the schema requires all
nine areas on every event, per `scripts/validate.py:115-116`), but nothing rolls that scoring up
into a lane-level domain reading the way the three event-derived domains above do for their areas.

This is a documentation reconciliation only. Neither vocabulary is renamed here — a rename would
touch `schemas/impact_assessment.schema.json`, `analysis/assessments.py`, and every record already
committed under `data/assessments/` and `data/events/`, which is a separate, human-blocked decision
(see the production-readiness roadmap's List B).

## 6. What would close the largest gaps, in order

1. **A controlled live validation of one Thailand trade source** — turns lane selection from
   structural reasoning into evidence, and gives the trade domain a real reading. WO-029
   identified a mode-bearing candidate (`ctm_06_18`/`ctm_06_17` on `catalog.customs.go.th`)
   but has not yet reached it — see §7.
2. **Any operational-condition source** — currently the single largest analytical hole. It
   is what stands between "volume pressure" and a supportable congestion statement.
3. **A confirmed machine-readable official notice feed** — or a commitment to the manual
   intake path, which exists and is tested but has recorded nothing.
4. **A transit-time or schedule-reliability source** — would let the service domain be
   measured rather than inferred from events.
5. **A successful read of PAT's own port-statistics catalogue** — the strongest port-activity
   candidate found; blocked on transport reachability and two publisher-side findings, not
   on merit — see §7.

## 7. Ocean-sequence research passes — what three research Work Orders established

WO-029 (Issue #60), WO-031 (Issue #63) and WO-032 (Issue #65) — plus the consolidated
egress-allowlist plan, Issue #64 — probed the Ocean sequence's two most promising
Thailand-official candidates under successive rounds of human-authorized live access.
Recorded here so this document's inventory doesn't drift from what those passes actually
found.

- **WO-029 — Thai Customs transport-mode data (Issue #60, closed).** RESEARCH INCOMPLETE —
  ENVIRONMENT ACCESS BLOCKER. 0 of 9 authorized requests completed; every candidate host
  either rejected the CONNECT tunnel or reset the TLS session before any response.
  Identified `ctm_06_18`/`ctm_06_17` on `catalog.customs.go.th` as the only located
  candidates carrying an explicit transport-mode dimension (published customs statistics
  are otherwise all-mode totals).
- **WO-031 — Port Authority of Thailand statistics, research phase (Issue #63, closed).**
  RESEARCH INCOMPLETE — ENVIRONMENT ACCESS BLOCKER. Zero primary text read; that
  environment could not reach `catalog.port.co.th` at all. On the evidence available,
  assessed PAT's own CKAN catalogue as "the best candidate found in either of the first two
  Ocean sequence items… It fails on verification, not on substance."
- **WO-032 — Port Authority of Thailand statistics, bounded live validation (Issue #65,
  closed).** A later session's environment allowlisted `catalog.port.co.th` and
  `datagov.mot.go.th`; the human-authorized six-request primary package plus two-request
  mirror fallback (Issue #63 §5.1/§5.2) was executed. RESEARCH INCOMPLETE — ENVIRONMENT OR
  EVIDENCE BLOCKER. `catalog.port.co.th`'s CONNECT tunnel is accepted but its TLS session
  resets after ~12s on all four attempts (zero publisher bytes ever received — an upstream
  transport problem, not a policy denial). The `datagov.mot.go.th` mirror fallback
  succeeded (2/2 requests) and shows the underlying candidate is genuinely promising:
  monthly per-port vessel/cargo/container data, harvested from `catalog.port.co.th` itself,
  spanning 01/2018–06/2026, `last_updated_date: 2026-07-27`. Mirror evidence can disqualify
  but never qualify the primary. Two publisher-side findings survive any future fix to
  reachability: the container-unit field self-contradicts (Bangkok's `unit_of_measure`
  states TEU; Laem Chabang's states boxes while its own `unit_of_multiplier_other` field
  separately says "1 TEU"), with the authoritative data dictionary published as a JPEG
  image rather than machine-readable text; and the licence field names no real licence
  (`license_id: "Open Data Common"`, `license_url: null`, `isopen: false`).

None of these three passes found either candidate unqualified on substance — in every case,
the underlying data was never actually read. **It is a factual error to describe either
candidate as low-value, rejected, or ruled out on data quality.** The correct framing,
carried forward from Issue #64 §0, is that both remain the strongest candidates the Ocean
sequence has found, blocked on transport reachability (and, for PAT, two additional
publisher-side findings) rather than on merit.
