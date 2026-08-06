# Production-readiness roadmap — third audit

<!-- registry-source-count: 18 -->

**Audit date:** 2026-07-31
**Baseline audited:** `main` @ `1bd1d9a` (WO-023 merge, PR #49)
**Previous audit baselines:** `main` @ `49bb9c4` (second audit, WO-016 merge, PR #31); `main` @
`af8e52f` (first audit, WO-010 Bundle 1 merge, PR #19)

This is the **third** production-readiness audit. The first two rounds (WO-011 through WO-021)
are summarized in "Recently closed" below rather than re-narrated here; the full implementation
history for each is on its own closed Issue/PR. This audit re-verified all ten gates against
real evidence — file contents, test names, live GitHub state — rather than carrying forward the
second audit's citations, several of which had already gone stale (see WO-024 in "Recently
closed").

The second audit's own List A (A1-A3: WO-019, WO-020, WO-021) is now fully closed. This audit's
own independent re-derivation of the gate table (not an assumption that "List A empty" implies
"nothing to find") turned up three more real, autonomously-fixable defects — WO-022, WO-023 and
this document's own currency pass (WO-024) — all closed by the time this text reached `main`. As
of this baseline, **List A is empty**: every autonomously-executable item any audit has found to
date is closed.

## What changed since audit 2

- All four of audit 2's List A items closed: WO-018 (Dashboard heading-skip fix, closing Issue
  #32), WO-019 (nine-domains vocabulary reconciliation), WO-020 (health-check content-marker
  binding), WO-021 (health-check issue-dedupe hardening).
- This audit found and closed three more: WO-022 (two unlabelled, uncovered payloads reached the
  published Dashboard data directory — one of them, `current_events.json`, contained a real
  legacy event record that contradicted `events.json`'s correctly-derived "zero current events"
  on the same site), WO-023 (`docs/air_land_extension_points.md` and `README.md` contradicted a
  finding WO-017 had already verified, about a real gap in the event-type schema enum), and
  WO-024 (this document, plus `CHANGELOG.md` and `docs/deployment_verification.md`, had gone
  stale after the volume of merges above).
- **Nothing touched `config/sources.yaml`, any schema, or any data file** across any of the seven
  Work Orders above. All 18 registered sources remain `enabled: false`; 15 of 18 remain
  `licence_status: pending_review`. Live coverage is still "insufficient" by design.
- No List B item became actionable. Issue #15 (TMD_CAP governance HOLD) is still open, unchanged
  since 2026-07-24.

## 10-gate snapshot

| # | Gate | Status | Current reason |
|---|------|--------|----------------|
| 1 | Multimodal foundation | PARTIAL | Reference entities are mode-neutral and already accept Air (`data/reference/dimensions.json` — `air` mode at `module_status: planned`; `NODE-THBKKAIR`, explicitly carrying no data). Only Ocean (Bundle 1) is delivered; `docs/bundle2_air_cargo_scope.md` (WO-017) is a scope document, not an implementation. Unchanged since audit 1, other than WO-023's documentation correction (below) about a real gap that a Bundle 2 implementation will still need to close. |
| 2 | Verified-source provenance | PARTIAL | Provenance machinery is complete and tested — acquisition binding (`tests/test_acquisition_binding.py`), collection manifests (`tests/test_r7_manifest_contract.py`), content hashes, retrieval-time fail-closed. Exercised only against fixtures, because no source is enabled. Unchanged since audit 1. |
| 3 | Fixture/current separation | **PASS (regression found and fixed this audit)** | Enforced by `tests/test_current_publication_boundary.py`, `tests/test_review_package_isolation.py`, `tests/test_current_positive_path.py`, and now also `tests/test_dashboard_build.py::test_no_orphaned_json_file_sits_in_the_published_data_directory`. This audit found a real violation — `current_events.json`, an unlabelled legacy record, was reaching the published site outside every one of these boundary tests — and closed it as WO-022. |
| 4 | Acquisition/review binding | PASS | `tests/test_review_decision_transactions.py` and the WO-010-R5/R6/R7 record-level acquisition proof and approval-hash closure. Unchanged. |
| 5 | Licensing/enablement review | PARTIAL (human-blocked) | 15 of 18 contracts are `licence_status: pending_review`; `docs/source_enablement_decisions.md` registers all 18 with a decision record. Blocked on List B items 1 and 3. Unchanged. |
| 6 | Controlled live validation, offline-default CI | PASS | `collect.yml` and `manual-live-source-test.yml` are `workflow_dispatch:`-only with no `schedule:`/`push:`/`pull_request:` trigger, enforced by `tests/test_workflow_consistency.py::test_collect_workflow_has_no_schedule_or_push_trigger` and `tests/test_manual_workflow.py`. Unchanged since audit 2. |
| 7 | Deterministic / auditable / fail-closed pipelines | PASS | `scripts/validate.py` semantic checks, a real `--check` mode on the three generators that have one (`ingest_fixtures`, `build_events_from_cases`, `build_analysis`) plus an equivalent CI/byte-comparison reproducibility check on the other two (`build_dashboard`, `generate_synthetic_fixtures` — WO-025), cross-version determinism fix, warehouse rebuild tests. |
| 8 | Dashboard accurate / accessible / organization-neutral | **PASS (regression found and fixed this audit)** | `tests/test_dashboard_accessibility.py` covers heading structure, `lang`, skip-link target, landmark names, WCAG AA contrast computed from the real CSS, and payload budgets; WO-018 closed the runtime `<h2>`→`<h4>` heading-skip (Issue #32) with a mutation-verified regression test. Organization-neutrality is enforced by `analysis/assessments.py`'s `validate_preparedness_option`/`_MANDATORY_PHRASES`/`_ORGANIZATION_SPECIFIC`. This audit found the same publication-boundary gap as gate 3 above (an unlabelled legacy record on the published site, contradicting the properly-derived Dashboard content) and closed it as WO-022. Known residual gap, unchanged from audit 2: the accessibility regression test's regex doesn't resolve the `events-*` containers (a different, array-driven render pattern); manually verified correct, but a regression there wouldn't be caught by this suite. |
| 9 | Operational deployment / monitoring / backup / runbooks | **PASS** | `health-check.yml` runs daily (`17 3 * * *`) with automated issue open-on-failure/close-on-recovery, binding its content marker to the real committed `index.html` (WO-020) and excluding pull requests from its issue-dedupe lookup (WO-021); `docs/deployment_verification.md` and runbook §6/§8/§9. WO-013 added weekly `pip-audit`. **Operational-proof gap closed:** the post-WO-014 form of the workflow (daily liveness fetch + issue automation, merged `bb73501` 2026-07-30) has now fired 5 consecutive successful scheduled runs (`run_number` 3–7, 2026-08-01 through 2026-08-05), all against the current head `9bc1942` — the empirical production proof this gate previously lacked. |
| 10 | No unresolved Critical/High blocker | PASS | Two open issues as of this baseline: #15 (deliberate TMD_CAP governance HOLD, by design) and #52 (this WO-025, open until this PR merges — self-counting, the same convention prior roadmap refreshes used for their own tracking issue). Every other issue this and the prior audits opened (#32, #33, #35, #38, #40, #42, #44, #46, #48, #50) is closed. None was, or is, Critical or High. |

---

## List A — autonomously executable now

**Empty as of this baseline.** Every item any of the three audits has found — WO-018 through
WO-024 below — is closed. The historical implementation plans are left in place rather than
deleted, the same in-place-correction convention used throughout this document's revisions; a
future audit adds new sections here rather than reopening these.

### ~~WO-018~~ — fix the Trade/Cost/Outlook heading-level skip (Issue #32) — DONE

Merged as PR #37 (`5f78897`), closing Issue #32. Gate 8 moved to PASS. Left in place below,
unmodified, as the historical implementation plan the merged fix actually followed — it was
independently re-verified line-by-line against the real files before implementation and matched.

**The defect.** `dashboard/public/index.html:105-113` (Trade) contains an `<h2>` and *no* `<h3>` at
all; `dashboard/public/index.html:115-122` (Cost) has its first `<h3>` only at line 123, after two
injection points; `dashboard/public/index.html:151-158` (Outlook) has its first `<h3>` only at line
159, after two more injection points. Into those six containers, `app.js` writes `<h4>`:

| Container (index.html) | Written by | Heading emitted |
|---|---|---|
| `#current-trade-lanes` (line 109) | `renderTrade`, `app.js:512-521` | `<h4>` lane name (`app.js:514`) + `<h4>` per flow via `seriesBlock` (`app.js:219`) |
| `#trade-lanes` (line 112) | `renderTrade`, `app.js:523-534` | `<h4>` lane name (`app.js:531`) + `<h4>` per flow |
| `#current-cost-series` (line 119) | `renderCost`, `app.js:539-543` | `<h4>` per series via `seriesBlock` |
| `#cost-series` (line 122) | `renderCost`, `app.js:547-555` | `<h4>` per series via `seriesBlock` |
| `#withheld-assessments` (line 157) | `app.js:727-735` | `<h4>` per withheld package (`app.js:731`) |
| `#approved-assessments` (line 158) | `app.js:737-743` | `<h4>` per approved package (`app.js:739`) |

Result at runtime: `h2 → h4`, a level skip in **three** of seven sections (Trade, Cost, Outlook).
The Outlook instance is latent today — `dashboard/public/data/ai_outlook.json` currently has
`withheld_assessments: []` and `approved_assessments: []`, so both containers render `''` — but it
is the fail-closed publication-gate path and is expected to populate. It must be fixed in the same
Work Order as Trade/Cost, not deferred: the regression test in step 4 below is data-independent and
would fail on it immediately if step 1 omitted it.

**Prescribed fix — static `<h3>` headings in `index.html`, mirroring the pattern the Ocean section
already uses.** Do *not* change `seriesBlock`'s heading level. Its only callers are in the Ocean
section (`app.js:396`, `:438`) and the Trade/Cost containers this WO is already fixing
(`app.js:516`, `:525`, `:541`, `:548`, `:556`). The two Ocean call sites already sit under an
existing `<h3>` today (`index.html:72` `<h3 class="demo-heading">Thailand port and maritime
indicators…</h3>` → `#port-series`, and `index.html:123` `<h3>FX context</h3>` → `#fx-series`); the
Trade/Cost call sites will too, once step 1 below adds the missing `<h3>`s — that is the defect
this WO closes, so `seriesBlock` itself does not need to change either way. The Outlook, Events, and Sources sections'
`<h4>`s are emitted by their own inline literals, not `seriesBlock` — a distinction that matters
because it means fixing Outlook (below) does not touch `seriesBlock` or its other callers either.
Concretely:

1. In `index.html`, insert an `<h3>` immediately before each of the following, following the
   existing "current vs demonstration" labelling convention already used at `index.html:84-89`
   (which pairs a `<h3>… <span class="pill pill-note">current</span></h3>` with a current panel):
   - before `#current-trade-lanes`: `<h3>Current trade flows <span class="pill pill-note">current</span></h3>`
   - before `#trade-lanes`: `<h3 class="demo-heading">Trade flows by lane <span class="pill pill-demo">technical demonstration</span></h3>`
   - before `#current-cost-series`: `<h3>Current cost readings <span class="pill pill-note">current</span></h3>`
   - before `#cost-series`: `<h3 class="demo-heading">Cost and freight benchmarks <span class="pill pill-demo">technical demonstration</span></h3>`
   - before `#withheld-assessments` (one heading covers both it and the immediately following
     `#approved-assessments` — they are adjacent siblings with no content between them):
     `<h3>Assessment status <span class="pill pill-note">current</span></h3>`
   Place each new `<h3>` *after* its section's existing banner paragraph(s) so the banner ordering
   in `renderTrade`/`renderCost`/the Outlook render function is unaffected.
2. In `app.js`, replace the two empty-string fallbacks — `app.js:521` (`: ''` for
   `#current-trade-lanes`) and `app.js:543` (`: ''` for `#current-cost-series`) — with an
   `<p class="empty-state">…</p>` message, so the new static `<h3>` never heads a visibly empty
   region. Match the wording style of the existing empty state at `app.js:493-494` ("…this is an
   absence of records rather than evidence that…"). `#approved-assessments`'s empty fallback
   (`app.js:743`) should get the same treatment for consistency, even though `#withheld-assessments`
   already renders a banner when non-empty and `''` (silently, appropriately) when empty — withheld
   assessments being absent is good news, not a gap, so it alone does not need an empty-state
   message. No other `app.js` change is required.
3. `dashboard/public/assets/styles.css` needs **no** change: `section h3` (line 101),
   `.demo-heading`, and `.series h4` (line 175) already style both levels; verify visually only.
4. **Regression test.** Extend `tests/test_dashboard_accessibility.py` with a source-level check
   that does not need a browser: for each container id that `app.js` assigns `innerHTML` containing
   an `<hN>` literal, assert the nearest *preceding* heading in `index.html` is exactly level
   `N-1`. Implement by regexing `app.js` for `el('<id>').innerHTML` blocks and the `<hN>` literals
   they reach (including via `seriesBlock`), and by reusing the existing `_DashboardHtmlParser` to
   record heading level and element ids in document order. This is deliberately data-independent —
   it must catch the Outlook containers even though they render empty with today's fixture data —
   and catches the whole class of defect, not just today's six instances.
5. Update `docs/dashboard_user_guide.md:172-177`, which currently documents this exact skip as a
   known gap and cites Issue #32 — replace with a statement of what is now enforced.

**Acceptance criteria.** `ruff check` / `ruff format --check`, `scripts/validate.py`, the three
real `--check` generators, `python scripts/build_dashboard.py` (with the rebuilt output checked
for drift via `git status --porcelain`, since this script has no `--check` mode of its own —
see WO-025), and `pytest` pass;
`git status --porcelain data dashboard/public/data` is empty (only `index.html`, `app.js` and the
two doc/test files change); `config/sources.yaml`, all schemas and all data files unchanged; the
payload-budget tests (`tests/test_dashboard_accessibility.py:429`, `:437` — line numbers as of
WO-025; they were at `:288`/`:296` when WO-018 itself merged, before later edits shifted them)
still pass — the added markup is well under 1 KB against a budget with megabytes of headroom.
Close Issue #32 on merge.

### ~~WO-019~~ — reconcile the two "nine domains" vocabularies — DONE

Merged as PR #41 (`a3a9c32`), closing Issue #40. Added a reconciliation table to
`docs/known_data_gaps.md` §5 between `analysis/assessments.py`'s nine *measurement* domains
(`DOMAINS`) and `schemas/impact_assessment.schema.json`'s nine *business-impact* areas (`area`
enum) — two disjoint vocabularies enforced with near-identical wording in `scripts/validate.py`,
which invites the assumption they correspond. Documentation only; no rename (a rename touches
committed data under `data/assessments/`/`data/events/` and remains List B item 8).

### ~~WO-020~~ — bind the health-check content marker to the actual page — DONE

Merged as PR #43 (`79b2ba1`), closing Issue #42. `tests/test_deployment_health_workflow.py` only
checked that its content-marker constant appeared in `health-check.yml`'s own grep command, never
that it actually appeared on the page the workflow greps. Added
`test_content_marker_is_actually_present_on_the_committed_page`, asserting the marker is present
in the committed `dashboard/public/index.html`. Test-only.

### ~~WO-021~~ — harden the health-check issue dedupe — DONE

Merged as PR #45 (`122d9fe`), closing Issue #44. `health-check.yml`'s two issue-dedupe lookups
matched by title alone against `GET /issues`, which also returns pull requests; added
`select(.pull_request == null)` to both jq filters so a same-titled PR can't be mistaken for the
tracked issue. The `per_page=100` pagination cap was deliberately left unfixed and is now
documented in a workflow comment and in `docs/deployment_verification.md` §4 (WO-024) as a real,
currently-latent limit.

### ~~WO-022~~ — stop publishing two unlabelled, uncovered payloads — DONE

Merged as PR #47 (`160d272`), closing Issue #46. Found by this audit: `scripts/build_dashboard.py`
published `data/reviewed/current_events.json` and `innovation/solution_register.json` to
`dashboard/public/data/` since WO-010 Gate K, unlabelled (no `dataset` field), untested, and
unconsumed by `assets/app.js`. The first carried a real legacy WO-002 event record that
contradicted the properly-derived `events.json` on the same site, which correctly reports zero
current events. Stopped publishing both; the underlying source file and its own validation
(`scripts/validate.py`, `tests/test_data_contracts.py`) are unaffected. Also found and fixed in
the same WO: `build_dashboard.py`'s build step never removed a file a prior build wrote once a
later change stopped generating it — exactly how the two files went unnoticed for eight WO-010
revisions and two prior audits. Added
`tests/test_dashboard_build.py::test_no_orphaned_json_file_sits_in_the_published_data_directory`,
which checks the real directory contents rather than only the declared payload dict, and
tightened the existing payload-set assertion from a subset check to an exact-set check.

### ~~WO-023~~ — reconcile air_land_extension_points.md with WO-017's finding — DONE

Merged as PR #49 (`1bd1d9a`), closing Issue #48. Found by this audit: WO-017 had already verified
that `logistics_event.schema.json`'s `event_type` enum has two Ocean-worded values
(`port_or_terminal_closure`, `canal_restriction`) with no exact fit for a non-Ocean closure event
— a real, small schema change a future Bundle 2 implementation WO must still make. A separate,
older document, `docs/air_land_extension_points.md` (plus `README.md`), was never corrected and
still claimed, unqualified, that the whole shared foundation needs no schema change. Qualified
both documents to match WO-017's verified position; corrected a stale test-coverage claim.
Documentation only.

### ~~WO-024~~ — currency pass on roadmap, CHANGELOG and deployment-verification docs — DONE

This Work Order. Found by this audit: this document itself, plus `CHANGELOG.md` and
`docs/deployment_verification.md`, had gone stale after the volume of merges above — three
items presented as pending "next Work Order"s that were already merged, several stale
line-number self-citations (WO-019's own docstring insertion shifted the line numbers this
document cited for it — the same defect class two independent reviews already caught elsewhere
in this repository's history), a `CHANGELOG.md` `[Unreleased]` section that stopped at WO-013,
and a deployment-verification doc describing the pre-WO-021 dedupe behaviour. This is that
correction — the document you are reading.

### ~~WO-025~~ — reconcile "`--check` on every generator" claims with the real code — DONE

Found by a fourth audit, run after this document's WO-024 rewrite. `docs/operations_runbook.md`,
`docs/bundle1_architecture.md`, `docs/data_model_and_persistence.md` and
`tests/test_derived_outputs.py`'s own docstring all claimed, unqualified, that every generator
has a `--check` mode. Independently re-verified against the real code: only three do
(`ingest_fixtures.py`, `build_events_from_cases.py`, `build_analysis.py`).
`build_dashboard.py` and `generate_synthetic_fixtures.py` silently ignored an unrecognized
`--check` flag, wrote files anyway, and exited 0 — a maintainer following the documented
"verify without writing" instruction for either got a false-clean result while mutating the
working tree. Corrected the four false-claim locations and this document's own gate-7 wording
and stale WO-018 acceptance-criteria prescription (now at `:137-140` post-fix; folded in this
document's own stale `tests/test_dashboard_accessibility.py` line citation, now at `:143-144`,
which had drifted from `:288`/`:296` to `:429`/`:437` since WO-018 merged — the same
self-citation-drift defect class WO-019 and WO-024 already hit — line numbers throughout this
paragraph are as of this WO-025 merge, not the pre-fix state they describe). Also folded in a
stale `README.md` claim that WO-010 was still "pending
independent review." Made both silently-ignored flags loud: `build_dashboard.py` and
`generate_synthetic_fixtures.py`'s `main()` functions now reject an unrecognized argument with
exit 2, matching `build_warehouse.py`'s and `run_historical_validation.py`'s existing behaviour.
Added a binding test in `tests/test_derived_outputs.py` that parses `scripts/*.py` for real
`--check` support and asserts it against what the docs claim, so this defect class cannot recur
silently.

---

## List B — blocked on human decision

All items re-verified against the current tree; **none has become actionable**.

1. **Enabling any source.** All 17 remain `enabled: false` (`tests/test_documentation_registry_coverage.py::test_no_source_became_enabled` locks this). Enablement is a licensing and operational-commitment decision, not an engineering one.
2. **Dispatching a controlled live validation run.** `manual-live-source-test.yml` is `workflow_dispatch`-only by design and requires a human to trigger and review each run.
3. **Licence review for 15 `pending_review` contracts.** Only `GDACS` and `MANUAL_NOTICE_INTAKE` are `reviewed`. Each remaining one needs a human reading actual terms.
4. **TMD_CAP governance sequence (Issue #15, still open).** WO-008B (send the permission inquiry), WO-008C (cadence observation), WO-008D (contract-architecture choice among Options A–D), WO-008E/F. Nothing in this backlog advances it; the HOLD disposition stands.
5. **`BOT_FX` API credential.** `config/sources.yaml:380` and `:420` record that the developer portal requires account registration and an API key, and that no credential-handling mechanism exists in this repository. Needs a human to register **and** a secrets-handling decision.
6. **Dependabot security-alert and branch-protection settings.** `.github/dependabot.yml` covers `pip` and `github-actions` on a monthly cadence, but security alerts, secret scanning and required-status-check branch protection are repository *settings*, not files — only a repo admin can set them.
7. **XLSX / PDF parser dependency decision.** `WB_COMMODITY` is `format: xlsx` (`config/sources.yaml:433`) and several qualification/terms references are PDFs. Parsing either adds a runtime dependency to a repository that currently has a deliberately minimal lockfile. Needs an explicit accept/reject.
8. **Destructive data migration.** Any rename of the impact-area or measurement-domain vocabularies (see WO-019's reconciliation table in `docs/known_data_gaps.md` §5) rewrites committed data under `data/assessments/` and `data/events/`. Requires human sign-off before it is attempted.
9. **Air cargo lane-selection source (new, from the WO-017 scope work).** Selecting Bundle 2 Air lanes needs either a qualified air-cargo volume/route source — none is registered — or an explicit reviewed decision to repeat WO-010's structural-reasoning-only approach, which `docs/known_data_gaps.md` §3 already records as a limitation for Ocean. That is a scope decision, not an implementation task.

Audit-1 List B items not repeated above were either folded into items 1–8 or were resolved by
WO-012 / WO-013 / WO-014 (governance files, vulnerability scanning, deployment monitoring).

---

## Recently closed

| Work Order | Issue / PR | Merged | What it delivered |
|---|---|---|---|
| WO-011 | #20 / #21 | 2026-07-30 | Closed doc/registry drift — `docs/source_qualification_report.md` named only 15 of 17 registered sources; added `tests/test_documentation_registry_coverage.py`. |
| WO-012 | #22 / #23 | 2026-07-30 | OSS governance baseline: `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, issue/PR templates, `CHANGELOG.md`. |
| WO-013 | #24 / #25 | 2026-07-30 | `dependency-audit.yml` (weekly `pip-audit` + on-PR); found and fixed a real low-severity CVE in the pinned `duckdb`. |
| — | Dependabot #2 | 2026-07-30 | `actions/upload-artifact` v4 → v7 across two workflows. |
| WO-014 | #26 / #27 | 2026-07-30 | Daily liveness check of the published Pages URL with automated issue open/close; `docs/deployment_verification.md`; runbook §6 rollback, §8 backup/DR, §9 incident response. |
| WO-015 | #28 / #29 | 2026-07-30 | `tests/test_workflow_consistency.py` — cross-workflow action-pin consistency and `collect.yml` trigger safety. |
| WO-016 | #30 / #31 | 2026-07-30 | `tests/test_dashboard_accessibility.py` (heading levels, skip-link target, landmark names, WCAG AA contrast from the real CSS) and payload-budget tests. Discovered Issue #32. |
| WO-017 | #33 / #34 | 2026-07-30 (`99ecfc4`, shortly after audit 2 was written) | `docs/bundle2_air_cargo_scope.md` + `tests/test_bundle2_scope_doc_claims.py`. Was in review when audit 2 was written; that audit's affected passages were corrected in place rather than left stale. |
| — | Roadmap refresh #2 | 2026-07-30 (`72f3e0a`) | Audit 2's own document, `docs/production_readiness_roadmap.md`, Issue #35 / PR #36. |
| WO-018 | #32 / #37 | 2026-07-31 (`5f78897`) | Fixed the Trade/Cost/Outlook `h2→h4` heading-level skip (5 new static `<h3>`s) and added `test_dynamically_injected_headings_never_skip_a_level`, a data-independent regression test mutation-verified to catch the defect class. Closed gate 8's last open blocker. |
| — | Roadmap follow-up | 2026-07-31 (`c81770e`) | Corrected audit 2's own document after WO-018 merged (gate 8, gate 10, List A renumbering), Issue #38 / PR #39. |
| WO-019 | #40 / #41 | 2026-07-31 (`a3a9c32`) | `docs/known_data_gaps.md` §5 — reconciliation table between the nine measurement domains and the nine business-impact areas, built from the real `event_domain_direction` call sites rather than asserted. |
| WO-020 | #42 / #43 | 2026-07-31 (`79b2ba1`) | Bound the health-check content-marker test to the real committed `index.html`, not just the workflow file's own grep text. |
| WO-021 | #44 / #45 | 2026-07-31 (`122d9fe`) | Excluded pull requests from `health-check.yml`'s two issue-dedupe lookups (`select(.pull_request == null)`). |
| WO-022 | #46 / #47 | 2026-07-31 (`160d272`) | Stopped publishing two unlabelled, uncovered Dashboard payloads, one of which contradicted the properly-derived `events.json` on the same site; added a directory-level orphan-file test. |
| WO-023 | #48 / #49 | 2026-07-31 (`1bd1d9a`) | Reconciled `docs/air_land_extension_points.md` and `README.md` with WO-017's already-verified event-type-enum finding. |
| — | Roadmap third audit | 2026-07-31 (`6b39f3b`) | This document's own full rewrite (WO-024), Issue #50 / PR #51. |
| WO-025 | #52 / this PR | 2026-07-31 | Corrected four documents' and one test docstring's false claim that every generator has a `--check` mode (only three do); made `build_dashboard.py` and `generate_synthetic_fixtures.py` reject an unrecognized `--check` flag instead of silently writing files; added a binding test cross-checking the docs' claims against the real scripts. |
