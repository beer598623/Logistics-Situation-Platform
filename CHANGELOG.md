# Changelog

All notable changes to this repository are recorded here, backfilled from git history in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style. This project has not yet cut
a tagged release; `pyproject.toml`'s `version = "0.3.0"` reflects the state delivered by
WO-010 and is not bumped by every Work Order.

## [Unreleased]

### Changed

- WO-045: Ocean Dashboard Simplification (Issue #85) — evidence-first presentation redesign
  of the Ocean Operations view. No data, evidence semantics, schema or analysis threshold
  changed; this is presentation and information-hierarchy only. The view now opens with a
  static, unconditional statement ("Current Thailand Ocean conditions cannot be assessed
  reliably because no qualified live source is enabled. This is a coverage gap, not an
  all-clear."), followed by four evidence-status cards (current evidence status, latest
  available evidence date, verified current operational events, Thailand-relevant current
  capabilities), a four-to-six-item plain-language gap list derived from the source-capability
  registry (membership updates automatically as capabilities change) plus a "what would change
  this" sentence, and a simplified lane/chokepoint table using reader-friendly names and a
  single plain-language status cell — no lane is ranked, no internal ID or nine-domain
  assessment is shown before expansion. Every technical field the view rendered before this
  Work Order (internal IDs, mode, chokepoint IDs, all nine current domain assessments,
  selection evidence, known limitations) is preserved, unchanged, one level deeper behind a new
  collapsed "Technical details" disclosure, which — because it is current-publication material —
  sits before the historical/demonstration region in DOM order, not after (Issue #85 deviation
  D-1). The truck-turnaround/container-dwell gap is retained despite having the weakest
  evidence chain of the six, worded strictly as an absence-of-source statement (deviation D-2).
  Two new additive `data/ocean.json` fields (`evidence_summary`, `major_gaps`) are pure
  reshapings of values the build already computed — no new schema, no new source, no new
  current assessment. Also fixes a pre-existing defect where an empty current-notices panel
  silently rendered nothing (`''`) instead of stating the coverage gap like every other empty
  current panel, and a latent `revealAndFocus()` limitation that only opened the nearest
  ancestor `<details>` rather than every one, which the new nested technical-disclosure
  structure made reachable for current material. 15 new acceptance tests across
  `tests/test_current_publication_boundary.py`, `tests/test_dashboard_routing_and_regions.py`
  and `tests/test_dashboard_accessibility.py` enforce: no all-clear implication; no
  historical/demo value reaching the first screen; no missing value rendered as zero; no
  Singapore-scoped record entering Thailand evidence; internal IDs and domain detail hidden
  before expansion; every technical field remaining reachable; every pre-WO-045 anchor still
  resolving; native `<details>` disclosures with no hand-rolled substitute;
  `revealAndFocus()` opening every ancestor disclosure; every major gap traceable to a named
  `docs/known_data_gaps.md` §2 row; and the two ratified copy amendments' exact wording.

### Fixed

- WO-042: cross-modal documentation and display hygiene (Issue #81), found by the first
  independent readiness assessment to cover Ocean, Air and Land together. `ocean.json` had
  no mode filter on its `chokepoints`/`nodes` fields, unlike Air and Land — harmless while
  every registered chokepoint was `sea`, but once `CHK-SASIA-AIRSPACE`, `CHK-THSDK-BKH` and
  `CHK-THNKI-TNL` were registered it caused the published Ocean Chokepoints table to state
  "no lane exposed" for three chokepoints that do expose a lane. `scripts/build_dashboard.py`
  now scopes `ocean.json["chokepoints"]` to `sea`-mode records (mirroring the existing
  Air/Land filters) and drops the unused, unscoped `ocean.json["nodes"]` field entirely.
  `docs/historical_validation.md` still reported nine cases / 81 impact assessments after
  WO-041 added `HVC-010` as the tenth case; regenerated every count from
  `data/validation/validation_report.json` and added a machine-checked marker binding the
  doc to the report. `docs/dashboard_user_guide.md` omitted the `#/land` view entirely after
  WO-041 added it as the platform's ninth view; added its route-table row and a full Land,
  Rail & Border subsection mirroring the existing Air Cargo one, and added a test binding the
  guide's route table to `index.html`'s own routes. No source registered/enabled, no schema
  change, no new lane/node/chokepoint/geography record.

### Added

- WO-041: Land, Rail and Border foundation (Bundle 3, structural-foundation-first, Issue
  #79). Added eight provisional lanes to `data/reference/lanes.json`: four cross-border road
  lanes (`LANE-ROAD-TH-MY`, `-LA`, `-KH`, `-MM`, one per Thai land neighbour — a complete
  partition, not a selection), one domestic road lane, one international rail lane
  (`LANE-RAIL-TH-LA`), one domestic rail lane, and one border-crossing-operations lane
  (`LANE-BORDER-TH-CROSSINGS`) covering all four registered crossings at once because its
  subject is the crossing process itself, not any one country pair; see
  `docs/land_rail_border_lane_selection.md` for the full per-lane rationale. Added one new
  chokepoint, `CHK-THNKI-TNL` (the first `rail_gauge_break` this platform registers, at the
  Nong Khai–Thanaleng crossing where Thailand's metre-gauge network meets standard gauge),
  classified `analytical_inference` rather than `verified_fact` on the lane that transits it
  because this platform observes no train. Updated the existing WO-010 placeholder records
  `NODE-THSDK` and `CHK-THSDK-BKH` to anchor real lanes for the first time. Added four new
  nodes: `NODE-THNKI` (Nong Khai, the only registered crossing carrying both road and rail),
  `NODE-THARY` (Aranyaprathet), `NODE-THMST` (Mae Sot), and `NODE-THLKB` (Lat Krabang Inland
  Container Depot, the first `inland_terminal` this platform registers). Added three new
  country geographies (`GEO-CTY-KH`, `GEO-CTY-LA`, `GEO-CTY-MM`) required before any
  Thailand–Cambodia/Laos/Myanmar land lane could be written. Added one historical validation
  case, `HVC-010` (the 18 March 2020 Malaysian Movement Control Order closing the
  Thailand–Malaysia land border to general movement while goods traffic continued), chosen to
  prove two things at once: that a border closure is not read as a freight stoppage (goods
  movement was expressly exempted, so `import_export` stays `potential`, never `observed`),
  and that the mode-scoping guard WO-039 built for Air also holds for a genuine Land event —
  `HVC-010` shares `country_ids: ["TH","MY"]` with several Ocean lanes yet resolves no Ocean
  or Air lane at all. `analysis/reference.py::resolve_lane_relevance`'s `modes` parameter
  (added under WO-039) already required both call sites to pass an event's stated modes
  before this Work Order began, so no code change was required to prevent that leakage — this
  Work Order only had to prove the existing guard holds for Land. Added a new Dashboard
  payload, `land.json`, and a ninth routed view (`#/land`, "Land, Rail & Border") stating
  `live_coverage: insufficient` and a per-mode `module_status` map (`road`/`rail`/`border`,
  all `planned`) explicitly, with every lane's current assessment explicitly `null`. The Land
  node/chokepoint filters use an explicit allowlist (`{road, rail, border}`), not a denylist,
  so `NODE-THBKK`'s `inland_waterway` mode is never swept into the Land payload. New
  `docs/land_rail_border_lane_selection.md` documents the methodology; `docs/known_data_gaps.md`
  (new §9, plus a correction re-scoping the `"Open Data Common"`/`isopen: false` open-data
  licence question as a cross-cutting gap across Ocean, Air and Land rather than an
  Air-specific one — it now blocks a real, fresh, machine-readable Thai rail candidate too),
  `docs/air_land_extension_points.md`, and `README.md` were updated to match. **No schema
  file under `schemas/` changed** — every field needed (mode-tagged lanes, the
  `border_crossing`/`inland_terminal` node types, the `border_corridor`/`rail_gauge_break`
  chokepoint types, the `terminal_or_facility_closure` event type WO-035 already added) was
  already present. One schema gap is named and deliberately left open: there is no
  mode-neutral event-type value for a road/rail/border *restriction* as distinct from a full
  closure; `HVC-010` did not need one, and a future Work Order should add one additively only
  when a real restriction event needs recording. **No source was registered, enabled,
  scheduled or published** — `config/sources.yaml` was not touched, and no figure from any
  candidate examined during WO-040's research (Thai MOT road/rail trade statistics, DRT rail
  freight, truck-GPS analytics) was used to select, rank, order or size any lane, node or
  chokepoint. No live network request was made by this Work Order or by any test it added.
- WO-039: Air Cargo foundation (Bundle 2 Option A, Issue #76). Added five provisional
  `LANE-AIR-TH-*` lanes (East Asia, ASEAN and Singapore, Europe, North America, and a domestic
  gateway lane) to `data/reference/lanes.json`, selected by named structural reasoning exactly
  as WO-010 selected the eleven Ocean lanes — Air gets five instead of eleven because most of
  Ocean's splitting decisions (China/Hong Kong vs Japan/Korea, North Europe vs Mediterranean,
  US West Coast vs East/Gulf Coast) rest on structural facts (shared service strings, a
  post-Suez discharge order, a genuine Panama-vs-Suez routing choice) that have no Air
  analogue; see `docs/air_lane_selection.md` for the full reasoning and the corridors
  deliberately left out. Added one new chokepoint, `CHK-SASIA-AIRSPACE` (an `airspace`-type
  South Asian overflight corridor, reusing the existing `GEO-RGN-SASIA` geography rather than
  minting a new one), transited only by `LANE-AIR-TH-EUR`; its chokepoint-exposure evidence is
  deliberately classified `analytical_inference`, not `verified_fact` as Ocean's is, because an
  aircraft's routing is a filed flight plan this platform does not observe. Added zero new
  nodes — every Air lane anchors only on the already-registered `NODE-THBKKAIR`. Added one
  historical validation case, `HVC-009` (the 27 February 2019 Pakistan airspace closure and
  the resulting Thai Airways Bangkok–Europe cancellations), which resolves to `LANE-AIR-TH-EUR`
  through the new chokepoint and to no Ocean lane; its transport and service impacts are
  `observed` from the operator's own cancellation announcement, while capacity and cost stay
  `potential` with the measurement gap named explicitly. `analysis/reference.py::resolve_lane_relevance`
  gained a `modes` parameter so an event's stated modes gate lane matching by mode as well as
  by country/node/chokepoint — behaviour-preserving for every previously committed event,
  since all eight Ocean cases list `sea` and the parameter defaults to the old mode-blind
  behaviour when omitted, but now required to stop an Air event resolving an Ocean lane (or
  vice versa) purely because both happen to share Thailand as a country. `scripts/build_analysis.py`
  and `scripts/build_dashboard.py` scope their Ocean lane-assessment, indicator and outlook
  derivations to `mode == "sea"` lanes only, so no Air lane receives a fabricated current or
  demonstration assessment; the Thailand roll-up stays `subject: thailand_ocean`. Added a new
  Dashboard payload, `air.json`, and an eighth routed view (`#/air`, "Air Cargo") stating
  `live_coverage: insufficient` and `module_status: planned`, with every lane's current
  assessment explicitly `null` and labelled as a coverage gap rather than a neutral reading.
  New `docs/air_lane_selection.md` documents the methodology; `docs/bundle2_air_cargo_scope.md`,
  `docs/known_data_gaps.md`, `docs/production_readiness_roadmap.md`, `docs/historical_validation.md`,
  `docs/indicator_definitions.md`, `docs/dashboard_user_guide.md`, `docs/air_land_extension_points.md`
  and `README.md` were updated to match. **No schema file under `schemas/` changed** — the
  design review found every field WO-039 needed (mode-tagged lanes, the `airspace` chokepoint
  type, the `airspace_closure`/`terminal_or_facility_closure` event types WO-035 already added)
  already present. **No source was registered, enabled, scheduled or published** —
  `config/sources.yaml` was not touched, and no `air-freight-pass`, AEROTHAI or
  passenger-traffic figure was used to select, rank, order or size any lane, node or
  chokepoint. No live network request was made by this Work Order or by any test it added.

### Fixed

- WO-033: `docs/known_data_gaps.md` §2 named `IMF_PORTWATCH`'s model-derived vessel-tracking
  estimate as the best Thailand port-activity candidate; three research Work Orders
  (WO-029/Issue #60, WO-031/Issue #63, WO-032/Issue #65) had already established `PAT_STATISTICS`
  (Port Authority of Thailand's own CKAN catalogue) as the stronger candidate — monthly per-port
  data confirmed fresh through June 2026 via a corroborating mirror, blocked on transport
  reachability plus a self-contradicting container-unit field and an unnamed licence, not on
  substance. Corrected `known_data_gaps.md` (added §7 recording all three passes),
  `source_qualification_report.md`, `source_enablement_decisions.md` (`PAT_STATISTICS` and
  `TH_CUSTOMS` entries), `port_pressure_interpretation.md`, and `production_readiness_roadmap.md`
  (stale "17 registered sources" corrected to 18 at five occurrences across three locations,
  including one an initial pass of this same Work Order missed; the reviewed-sources list was
  also missing `MPA_SG_STATISTICS`; closed gate 9's health-check operational-proof gap — the
  post-WO-014 workflow has now fired 5 consecutive successful scheduled runs). A fresh
  independent review of the initial PR head also found two overstated claims carried over from
  WO-029's findings (Issue #60): "every candidate host" rejected or reset the connection, when
  two of three actually delivered a response (`data.go.th` 403, `uncomtrade.org` 200); and
  `catalog.customs.go.th` described as the "only" mode-bearing candidate, when
  `datagov.mot.go.th`'s `freight-import-export` dataset also carries a mode dimension (as a
  complementary cross-check, not a substitute) — both narrowed to match the source issue.
  Added a `registry-source-count` marker to `production_readiness_roadmap.md`, enforced by an
  extended `tests/test_documentation_registry_coverage.py`. Documentation and test only — no
  change to `config/sources.yaml`, no network request, no source enabled.
- WO-011: `docs/source_qualification_report.md` and `docs/bundle1_architecture.md` named only
  15 of the 17 registered source contracts, omitting the two WO-010-R1 additions
  (`PAT_STATISTICS`, `FBX_PUBLIC`). Both docs corrected, a machine-readable
  `registry-source-count` marker added to each, and `tests/test_documentation_registry_coverage.py`
  added to keep the two in sync going forward. Also corrected stale README text describing a
  scheduled/API-driven review cycle that predates the actual human-triggered, no-API flow.
- WO-013: `duckdb` bumped `1.4.1` → `1.4.2` in `requirements.txt`, `requirements.lock`, and
  `pyproject.toml`, clearing `PYSEC-2025-112` / `CVE-2025-64429` / `GHSA-vmp8-hg63-v2hp`
  (insecure RNG fallback and a GCM-downgrade issue in DuckDB's block-based database
  *encryption*, found by actually running `pip-audit -r requirements.lock` against `main`).
  This repository's only DuckDB usage (`analysis/warehouse.py`) never opens an encrypted
  database or uses `ATTACH`/`ENCRYPTION_KEY` — grepped, zero hits — so exploitability here is
  nil; the bump is applied anyway as a zero-risk clean-up, verified compatible by re-running
  `scripts/build_warehouse.py`.

- WO-022: `dashboard/public/data/current_events.json` and `solutions.json` were published,
  unlabelled and untested, since WO-010 Gate K. `current_events.json` carried a real legacy
  WO-002 event record that contradicted `events.json`'s correctly-derived "zero current
  events" on the same site. Stopped publishing both (neither was fetched by the frontend or
  documented); tightened `tests/test_dashboard_build.py`'s payload-set assertion from a
  subset check to an exact-set check, and added a directory-level orphan-file test so a
  future undeclared payload can't recur silently; corrected a false "every payload carries
  `dataset`" claim in `docs/evidence_provenance_and_datasets.md`.
- WO-023: `docs/air_land_extension_points.md` and `README.md` claimed, unqualified, that
  WO-010's shared foundation needs no schema change for Air/Land — including
  `logistics_event.schema.json`'s `event_type` enum, which WO-017 had already verified has
  two Ocean-worded values with no exact fit for a non-Ocean closure event. Qualified both
  documents to match WO-017's verified finding; corrected a stale test-coverage claim.
- WO-024: a currency pass on `docs/production_readiness_roadmap.md`, this file, and
  `docs/deployment_verification.md` after the volume of WO-018 through WO-023 merges; fixed a
  factual error a fresh independent review caught (a health-check run-count claim that had the
  workflow's post-WO-014 run count backwards).
- WO-025: `docs/operations_runbook.md`, `docs/bundle1_architecture.md`,
  `docs/data_model_and_persistence.md` and `tests/test_derived_outputs.py`'s own docstring
  claimed, unqualified, that every generator has a `--check` mode; only three do
  (`ingest_fixtures.py`, `build_events_from_cases.py`, `build_analysis.py`).
  `build_dashboard.py` and `generate_synthetic_fixtures.py` silently ignored an unrecognized
  `--check` flag and wrote files anyway. Corrected the claims; made both scripts reject an
  unrecognized flag with exit 2; added a binding test that AST-parses `scripts/*.py` for real
  `--check` support so the claim can't drift silently again.

### Added

- WO-037: `docs/known_data_gaps.md` §8 recording what WO-034 (Issue #69, Air Cargo
  primary-source research), WO-035 (Issue #70/PR #71, schema extension) and WO-036 (Issue #72,
  bounded live validation) actually established, so this document doesn't drift from the Air
  Cargo record the way §7 corrected for Ocean. `docs/bundle2_air_cargo_scope.md` §3 and §4
  updated with the same findings: `air-freight-pass` on `datagov.mot.go.th` is a real,
  DataStore-backed, field-contract-verified candidate blocked on an unresolved licence, on its
  schema carrying no unit column at all, and on its cargo-specific rows never having been
  observed; AEROTHAI Bangkok FIR is closed as NOT
  QUALIFIED (no cargo dimension, no aerodrome resolution); no free Thailand-scoped air freight
  rate source was found. Also corrected a stale "Bundle 1's 17 candidates" count in
  `bundle2_air_cargo_scope.md` §4 to 18. No `config/sources.yaml` change, no network request,
  no code — the licence determination and the one additional bounded request needed to observe
  `air-freight-pass`'s cargo rows both remain open, separately-authorizable next steps.
- WO-035: two purely additive `event_type` enum values in `schemas/logistics_event.schema.json`
  — `airspace_closure` and `terminal_or_facility_closure` — closing the one schema gap
  `docs/bundle2_air_cargo_scope.md` (WO-017) and `docs/air_land_extension_points.md` (WO-010)
  had documented: `port_or_terminal_closure`/`canal_restriction` are Ocean-worded and had no
  exact-fit value for a non-Ocean closure event. No existing value renamed or removed, so no
  committed event record needed migration. Updated both docs and `README.md` to record the
  gap as closed, and extended `tests/test_bundle2_scope_doc_claims.py` to lock it. No source
  registered, no Air data added, no config change — the first step of WO-034's recommended
  Bundle 2 sequencing (Issue #69).
- `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, `CHANGELOG.md`,
  `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/work_order.md` and `config.yml`,
  `tests/test_oss_governance_files.py` (WO-012).
- `pip-audit` dependency-vulnerability scanning: a fail-closed step in
  `.github/workflows/validate-pr.yml` (report uploaded as an artifact) and a new weekly
  `.github/workflows/dependency-audit.yml` (`schedule` + `workflow_dispatch` only), plus
  `tests/test_dependency_audit_workflow.py` (WO-013).
- `.github/workflows/health-check.yml` rewritten to run daily (was weekly) and fetch the real
  published Pages URL, requiring HTTP 200 and the page's own `<h1>` text as a content marker;
  opens/closes a tracked GitHub issue on failure/recovery. `docs/deployment_verification.md`
  new; `docs/operations_runbook.md` extended with rollback, backup/DR and incident-response
  sections (WO-014).
- `actions/upload-artifact` bumped v4 → v7 across `.github/workflows/manual-live-source-test.yml`
  and `validate-pr.yml` (Dependabot).
- `tests/test_workflow_consistency.py`: cross-workflow shared-action version-pin consistency,
  and a guard that `collect.yml` carries no `schedule`/`push`/`pull_request` trigger (WO-015).
- `tests/test_dashboard_accessibility.py`: single `<h1>`, no static heading-level skip, `lang`
  attribute, skip-link target, landmark accessible names, WCAG AA colour-contrast computed
  from the real `styles.css`, and payload-size budgets (WO-016). Found the Dashboard's runtime
  heading-level skip later fixed by WO-018 (tracked as Issue #32 at the time).
- `docs/bundle2_air_cargo_scope.md` and `tests/test_bundle2_scope_doc_claims.py`: Bundle 2
  (Air Cargo) scope and architecture, verified against the real schema/data rather than
  asserted — no Air lane, node, or source contract delivered (WO-017).
- Five new static `<h3>` headings in `dashboard/public/index.html` fixing a runtime
  `<h2>`→`<h4>` heading-level skip across the Trade, Cost and Outlook sections (Issue #32);
  `tests/test_dashboard_accessibility.py::test_dynamically_injected_headings_never_skip_a_level`,
  a data-independent regression test (WO-018).
- `docs/known_data_gaps.md`: a reconciliation table between the nine *measurement* domains
  (`analysis/assessments.py`'s `DOMAINS`) and the nine *business-impact* areas
  (`schemas/impact_assessment.schema.json`'s `area` enum) — two disjoint vocabularies that
  read as if they should correspond and don't (WO-019).
- `tests/test_deployment_health_workflow.py::test_content_marker_is_actually_present_on_the_committed_page`:
  binds the health-check workflow's content marker to the real committed `index.html`, closing
  a gap where the marker was only checked against the workflow file's own text (WO-020).
- `.github/workflows/health-check.yml`'s two issue-dedupe lookups now exclude pull requests
  (`select(.pull_request == null)`), which the underlying GitHub API returns alongside issues
  and could otherwise be mistaken for the tracked deployment-health issue (WO-021).
- `config/sources.yaml`'s `MPA_SG_STATISTICS` contract and `collectors/adapters/data_gov_sg.py`:
  the platform's first source with a human-verified `licence_status: reviewed` position
  (Singapore Open Data Licence v1.0, read directly by a human against the primary text since
  this environment's `WebFetch` is blocked for external hosts). Offline engineering only —
  fixture-first parser, tests, `docs/mpa_sg_statistics_qualification.md` and a draft
  controlled-live-validation package for a future human gate. `enabled: false`; no live
  request, account, API key, schedule, or Dashboard publication (WO-026, Issue #54).
- WO-027: corrected two wrong field-name guesses WO-026 made for `MPA_SG_STATISTICS`
  (`total_teus` → `container_throughput`, `total_vessels` → `number_of_vessels`) after a human
  independently reconciled the primary `data.gov.sg` dataset schemas and confirmed the
  Datastore Search endpoint. Added `DatastoreSeriesSpec.unit_verified` and a fail-closed
  `UnverifiedUnitError` gate in `collectors/adapters/data_gov_sg.py`: `container_throughput`'s
  raw numeric scale does not obviously match individual TEUs against official MPA annual
  statements (41.12M TEU for 2024, 44.66M TEU for 2025), so the parser now refuses to parse
  this series at all until its unit/scale is verified against real evidence, rather than
  guessing a conversion that could be off by roughly 1000×. A bounded 2-request controlled
  live validation is human-authorized (Issue #56) but not yet executed — outbound network
  access to `data.gov.sg` is denied by this environment's auto-mode permission classifier.
  `enabled: false` throughout.
- WO-027 Parts B-D: executed the human-authorized bounded live validation from a later
  session's environment that allowlists `data.gov.sg` (the prior denial was an
  environment-policy failure, not a `data.gov.sg` source response). `scripts/wo027_part_b_live_validation.py`
  ran exactly the two committed-specification requests, sequential, no retry; both succeeded
  (HTTP 200, `application/json`, matching the assumed CKAN envelope). Evidence — exactly the
  fields Issue #56 authorizes retaining — committed at
  `docs/evidence/wo027_part_b_live_validation.json`. Part C reconciled the live
  `container_throughput` values against official MPA annual totals by scale elimination: only
  a ×1,000 ("thousand TEU") scale is physically plausible, but this is analytical inference
  corroborated by magnitude elimination, not an independently-read primary-source unit label,
  so `DatastoreSeriesSpec.unit_verified` stays `False` and `UnverifiedUnitError` continues to
  refuse parsing this series — a deliberate, documented outcome, not an unfinished step.
  Confirmed none of the fields Part B actually requested/returned can carry personal or
  third-party-rights data; Part B's `fields=`-projected response cannot itself confirm either
  resource's *complete* schema, so that broader confirmation still rests on the earlier human
  primary-source reading (§1 item 4 of the qualification doc), not on Part B alone.
  `config/sources.yaml`: `machine_readable_status` raised to `verified` (does not affect
  `enabled`, which stays `false`); `observed_freshness`/`data_period` populated from the live
  evidence; `enablement.live_validation_status` set to `completed`. New regression tests
  exercise the real live-validated envelope shape end to end through the parser and the
  live-validation script's proxy/source failure-layer classification. `MPA_SG_STATISTICS`
  remains `enabled: false`; no schedule; no publication (WO-027, Issue #56).
- WO-030: restructured the Dashboard from one long scroll into seven hash-routed views
  (`#/overview`, `#/ocean`, `#/trade`, `#/cost`, `#/events`, `#/outlook`, `#/sources`), against
  a design-review specification finalised on Issue #59 (AC-1 through AC-47). Legacy anchors
  and `#/<route>/<id>`/bare-`#<id>` sub-anchors are supported; an unmatched hash falls back to
  Overview with a visible, announced notice rather than a silent redirect. Fixes carried in the
  same PR: technical-demonstration material no longer sits above the current material it
  modifies in Ocean (was C-1); the demonstration lane assessment is relocated out of the
  current lane row into its own demonstration-region block, leaving a value-free
  cross-reference in the current row (R-3, Issue #59 §22); no two headings in one view share
  leading text (was C-2); one function now drives both the persistent coverage chip and the
  Overview banner, with no exit from a load-failed state (was H-1, a dual-write race); wide
  tables no longer force horizontal page scroll at 1280×720/1440×900/1920×1080 (was H-4);
  every scrollable table container is independently keyboard-focusable (was H-5, a WCAG 2.1 SC
  2.1.1 failure); a no-JS load still renders all seven views in document order (was H-6); every
  table has a caption and a scoped `<thead>`, including the previously headerless source-detail
  table (was H-7); a source's or lane's blocker is reachable in one interaction via a new
  expandable-row table, replacing the card layout (was H-8). Also: a URL-scheme allowlist
  before any `href` is emitted (was M-1); the FX panel carries its own demonstration heading
  (was M-2); numeric table cells always carry `.num`, with no exception for a missing-value
  cell (was M-4); print now expands every collapsed region and row via a `beforeprint` handler,
  verified with a real print-to-PDF rather than assumed from the (documented-fallback-only)
  stylesheet rule (was M-5/M-6); sparkline distortion capped and given min/max/latest/
  period-range text annotations (was M-7); the global `table { min-width: 520px }` rule
  removed in favour of per-table rules (was M-8); a same-origin favicon added (was L-2); and a
  machine-readable payload list published on Sources & Methodology covering all ten files,
  including `indicators.json`/`source_status.json`, explicitly labelled as generated static
  artifacts and not a supported public API (was L-1, AC-37/AC-42/AC-43). `docs/dashboard_user_guide.md`
  §7 corrected: the previous claim that a print stylesheet alone expands collapsed panels
  described a CSS-only rule inert for a closed `<details>` element in current browser engines
  and had never been checked in a browser; it now names the `beforeprint` mechanism actually
  verified working. `tests/test_dashboard_accessibility.py`'s
  `test_dynamically_injected_headings_never_skip_a_level` anti-vacuity floor re-based (14 → 13)
  for the new heading-injection-site count, and its `cascaded_backgrounds` map updated for the
  new (actually-visible) zebra-stripe colour; `tests/test_dashboard_routing_and_regions.py`
  added, covering the new routing, region-ordering and table-structure invariants (WO-030,
  Issue #61).

## [0.3.0] — 2026-07-30 — WO-010: Bundle 1, Common Foundation + Ocean Logistics Intelligence MVP

Delivered after a scope reset (WO-009A, 2026-07-25) from an earlier, broader multimodal
ambition to a Thailand-centric MVP scoped to the Ocean mode only.

### Added

- 18 conceptual data-model entities and 14 JSON Schema contracts (Gate B/C).
- Source registry of 17 contracts, all `enabled: false` pending licensing/qualification
  review; two more fixture-first collector adapters (`csv_series`, `notice_feed` — GDACS and
  TMD_CAP were added earlier, in v0.2.0).
- 11-lane Ocean logistics model for Thailand; indicators; event lifecycle and clustering;
  9-domain impact-assessment engine; 3-case scenario outlooks with preparedness options.
- Human-triggered (no AI API) ChatGPT review workflow with a cryptographic
  approval-binding chain.
- 8 historical validation cases; a 7-section static Dashboard published via GitHub Pages.
- A DuckDB-derived analytical warehouse (gitignored, built from committed data).

Eight follow-up revisions (R1 through R7, then R7-R1) closed provenance,
acquisition-binding, publication-boundary, timestamp-semantics, and manifest-integrity gaps
found in independent review before final merge; all folded into this squashed release.

### Known limitations

Zero live sources enabled; the Dashboard states "insufficient" coverage on its face. Of the 17
registered sources, 15 carry a `qualification` block; on all but one of those, `reuse_status`
and `redistribution_status` remain `unknown` pending a terms review that requires outbound
access this environment does not have. The one exception is `MANUAL_NOTICE_INTAKE`, a
maintainer-operated intake path (not an external publisher) with a reviewed,
attribution-bounded reuse position. `NEWS_DISCOVERY` (owned by the GDELT Project) still
carries `reuse_status: unknown`; its `redistribution_status: link_only` is a self-imposed
ceiling on what this platform will consider publishing, not a permission GDELT has granted.
`GDACS` and `TMD_CAP` predate this qualification framework and carry only a `licence_status`
(`reviewed` and `pending_review` respectively), not a recorded reuse/redistribution position.

## [0.2.3] — 2026-07-24 — WO-007A: candidate evidence contract hardening

Hardened the candidate-evidence contract ahead of Bundle 1; four review rounds addressed on
the same PR before merge.

## [0.2.2] — 2026-07-24 — WO-006: controlled single-candidate TMD CAP validation

Added a controlled, manually-triggered, single-candidate CAP validation path
(`collectors/adapters/tmd_candidate.py`) that accepts only a bounded candidate reference,
resolves and pins DNS with fail-closed non-global-address rejection, and makes exactly one
physical HTTPS GET. Implementation only — no live candidate fetch was performed under this
Work Order.

## [0.2.1] — 2026-07-23 — TMD RSS envelope discovery and failure-path hardening

Added a controlled, discovery-only RSS-envelope path to classify and inspect TMD's feed
without weakening the strict CAP 1.2 parser; retains only bounded structural metadata, never
fetches a discovered item link.

## [0.2.0] — 2026-07-23 — GDACS + TMD CAP controlled integration pilot

First two collector adapters (GDACS, TMD CAP) and the fail-closed collector model: bounded
fetch, no-redirect discovery transport, DNS-pinned candidate transport, strict CAP 1.2
parsing that rejects rather than salvages malformed content.

## [0.1.2] — 2026-07-23 — Source health and event identity

Source-health scoring and canonical event-identity/deduplication (fingerprint + external-ID
matching, merge-status lifecycle).

## [0.1.1] — 2026-07-23 — Data contracts and provenance hardening

Provenance fields (content hash, parser version, retrieval time) made structural across the
initial data contracts.

## [0.1.0] — 2026-07-22 — Initial bootstrap

Repository bootstrap: initial data contracts, validation script, and project scaffolding.
