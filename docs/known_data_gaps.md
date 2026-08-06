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
| **Thailand trade flow** | No live source. Published customs figures are all-mode totals, so even once enabled they cannot be attributed to ocean freight without a mode dimension the source does not provide. WO-029 identified `ctm_06_18`/`ctm_06_17` on `catalog.customs.go.th` as the only candidate that plausibly satisfies the sea-mode requirement at its source; that host is allowlisted in some environments but has never delivered a byte (see §7) |
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
  event exists for any of them. Air Cargo's research-pass record is at §8.
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
  ENVIRONMENT ACCESS BLOCKER. The authorized nine-request package (§A4) spans three hosts —
  `catalog.customs.go.th` (requests 1–7), `data.go.th` (request 8), `uncomtrade.org`
  (request 9). **0 of 9 completed.** Request 1, against `catalog.customs.go.th`, failed at
  the transport layer (connection reset before ServerHello) and, per the no-retry rule,
  requests 2–7 against that same host were never attempted. Requests 8 and 9 *were* later
  issued, verbatim, in a separate authorized pass, and did respond: request 8
  (`https://data.go.th/en/pages/dga-open-government-license`, the actual DGA licence-page
  URL, not a root-path probe) returned an HTTP 403 access-denial body from Cloudflare — a
  finding about an access control in front of `data.go.th`, and about nothing else; zero
  words of licence text were obtained. Request 9
  (`https://uncomtrade.org/docs/data-availability/`) returned HTTP 200 and was read in full,
  establishing that the page is documentation about *how* to check data availability and
  contains no per-reporter table and zero mentions of Thailand — a genuine correction to the
  candidate register, but not a mode-of-transport answer. Neither reception counts toward
  completing the nine-request package or qualifies the customs dataset.
  Identified `ctm_06_18`/`ctm_06_17` on `catalog.customs.go.th` as the only candidate found
  that plausibly satisfies the sea-mode requirement at its source (published customs
  statistics are otherwise all-mode totals); `datagov.mot.go.th`'s `freight-import-export`
  dataset also carries a publisher-declared mode-of-transport dimension but is a
  complementary cross-check, not a substitute, with its own unread licence.
- **WO-031 — Port Authority of Thailand statistics, research phase (Issue #63, closed).**
  RESEARCH INCOMPLETE — ENVIRONMENT ACCESS BLOCKER. Zero primary text read; that
  environment could not reach `catalog.port.co.th` at all. On the evidence available,
  assessed PAT's own CKAN catalogue as "the best candidate found in either of the first two
  Ocean sequence items… It fails on verification, not on substance."
- **WO-032 — Port Authority of Thailand statistics, bounded live validation (Issue #65,
  closed).** A later session's environment allowlisted `catalog.port.co.th` and
  `datagov.mot.go.th`; the human-authorized six-request primary package plus two-request
  mirror fallback (Issue #63 §5.1/§5.2) was attempted — 4 of the 6 primary requests were
  issuable (requests 3–4 required a resource id read from request 1's response, which never
  arrived, so they were correctly abandoned rather than substituted). RESEARCH INCOMPLETE —
  ENVIRONMENT OR EVIDENCE BLOCKER. `catalog.port.co.th`'s CONNECT tunnel is accepted but its
  TLS session resets after ~12s on all four issued attempts (zero publisher bytes ever
  received — an upstream transport problem, not a policy denial). The `datagov.mot.go.th`
  mirror fallback
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

## 8. Air Cargo (Bundle 2) research passes — what WO-034/035/036 established

Ocean Minimum Live Core was accepted before Air Cargo research began (see the acceptance
record on Issue #68). `docs/bundle2_air_cargo_scope.md` (WO-017) is the standing Bundle 2
scope document; this section records what the three Work Orders that followed it actually
found, so this inventory doesn't drift from the record the way §7 corrected for Ocean.

- **WO-034 — Air Cargo primary-source research (Issue #69, closed).** Found
  `datagov.mot.go.th` (Thailand's Ministry of Transport CKAN catalogue) reachable in this
  environment and containing real primary-source pages for two promising candidates, neither
  of which had its field-level data read at that stage — only catalogue metadata. Every
  publisher host for a commercial air-freight-rate or volume candidate (`iata.org`,
  `aci.aero`, `tacindex.com`, `balticexchange.com`, `freightos.com`, and ICAO's data hosts)
  was blocked in that environment, so Issue #69 labels these findings `[REPORTED]` —
  secondary evidence, not a primary read. On that secondary evidence, every commercial
  candidate investigated (IATA CargoIS/WATS, ACI's World Airport Traffic Dataset, TAC Index,
  the Baltic Air Freight Index) is reported paid or membership-gated, ICAO's data products
  are reported either paid or a credential-gated trial tier, and Freightos' free tier is
  reported to be a regional aggregate that does not isolate a Thailand rate — excluded by the
  zero-cost or Thailand-scope constraints if the reports hold. No free official
  Thailand-scoped air-freight-rate series was found; that gap does not close
  (mirrors the same finding already recorded for ocean freight rates).
- **WO-035 — additive `event_type` enum extension (Issue #70, PR #71, merged).** Closed the
  one schema gap `docs/bundle2_air_cargo_scope.md` §1 had documented — `port_or_terminal_closure`/
  `canal_restriction` are Ocean-worded — by adding `airspace_closure` and
  `terminal_or_facility_closure`, purely additive, no existing value renamed or removed. No
  schema change remains outstanding for event typing in any future Bundle 2 implementation.
- **WO-036 — bounded live validation, MOT Data Catalog (Issue #72, closed).** Human-authorized
  8-request package (Issue #69 Part 4 §5.1/§5.2), executed in full — every slot returned HTTP
  200, nothing abandoned. Two candidates, two different outcomes:
  - **`air-freight-pass` (CAAT-sourced, via MOT-ICT): VERIFIED DATA SHAPE, BUT
    LICENCE/PUBLICATION GATE REMAINS.** A live, DataStore-backed, 2,592-row CKAN resource. Its
    field contract is now known exactly: a long/tidy layout (`Detail`, `Airport`, `Month`,
    `Type`, `Value`), airport identity as free-text English names with no code (joining to
    `NODE-THBKKAIR` needs a hand-confirmed name mapping), `Month` as an English month name
    with **no year field anywhere in the data**. `license_id: "Open Data Common"` (the same
    non-licence string WO-032 found on `catalog.port.co.th`), `license_url: null`, and CKAN's
    own `isopen: false` — names no real licence, and blocks publication regardless of data
    quality. Separately: **the schema has no unit column at all** — `Value` is a bare number
    whose meaning depends entirely on which `Detail` the row carries, so unit and scale may
    never be verifiable from data alone, regardless of which `Detail` rows are read. On top
    of that structural gap, **every one of the 5 returned records was a passenger row; no
    cargo row was ever observed**, so the cargo measure's literal `Detail` value stays
    unverified too. Both stay fail-closed. All three sibling MOT air datasets checked in the
    same pass are unusable for unrelated reasons: `airports-dataset` (Department of Airports)
    is file-only (XLSX, no DataStore) and last updated 2021; `aot_traffic` (AOT) is an empty
    catalogue placeholder with no resource content at all; `domestic-air-freight` (CAAT) is
    DataStore-backed but abandoned since 2020 with an empty licence field.
  - **AEROTHAI Bangkok FIR monthly flight volumes: NOT QUALIFIED — DOCUMENTED COVERAGE
    GAP.** The highest-value open question WO-034 identified — whether the "type of
    operation" cut separates cargo from passenger flights — has a decisive negative answer
    read directly from the data: the field is a scheduled/non-scheduled/general-aviation/
    military classification, with the five observed values (`Schedule`, `General`, `Others`,
    `Military`, `Non-Schedule`) carrying **no cargo dimension of any kind**. A sixth row
    exists in the resource's 6-row total and was not returned at the bounded `limit=5`, so
    its value was never observed. The resource also carries **no aerodrome or location
    field** — it is Bangkok FIR-wide only and can never attach to `NODE-THBKKAIR`.
    Flight counts are not cargo weight in any case. This closes the candidate on substance,
    not on access — transport and DataStore both worked. (Also confirmed, as a secondary
    finding: `bangkok-june-2569` and `bangkok-june-25691` are duplicate catalogue records of
    the same month with no supersession marker between them — a real identity hazard for any
    future collector, moot now that the candidate itself is closed.)

**What remains open for `air-freight-pass`, not executed by any Work Order to date:** two
independent next steps, each requiring its own separate human authorization — (a) a human
licence determination on `"Open Data Common"`/`isopen: false`, since that question is not
API-decidable, or (b) one additional bounded `datastore_search` request with a `Detail`
filter to observe the actual cargo rows before any adapter or contract is written. Writing a
field contract for the cargo measure without that read would repeat the exact failure mode
WO-026's wrong field-name guesses represented, which WO-027 had to correct — this repository
does not repeat that shape a second time.

- **WO-039 — Air Cargo foundation, Bundle 2 Option A (Issue #76).** Built the Air structural
  scaffolding under Option A: five provisional `LANE-AIR-TH-*` lanes, one `airspace`
  chokepoint (`CHK-SASIA-AIRSPACE`), zero new nodes, and one historical validation case
  (`HVC-009`, the 27 February 2019 Pakistan airspace closure and the resulting
  Thailand–Europe air service cancellations). **No source was registered, enabled, scheduled
  or published, and no figure from `air-freight-pass`, from AEROTHAI, or from any
  passenger-traffic series was used to select, rank or size any lane** — the selection rests
  entirely on the recorded structural criteria, every lane carries `data_period_used: null`,
  and every gap in this section stays open. `air-freight-pass` remains unregistered pending a
  human licence determination on `"Open Data Common"`/`isopen: false`. The four
  source-capability gaps in `docs/bundle2_air_cargo_scope.md` §4 are unchanged by this Work
  Order and are now also stated on the Dashboard's Air Cargo section. See
  `docs/air_lane_selection.md` for the full selection methodology.

WO-039 is now the one implementation Work Order landed for Air Cargo; every gap this section
records for `air-freight-pass`, the air freight rate benchmark, and the airport/airspace
notice channel remains open regardless.
