# Production-readiness roadmap — second audit

**Audit date:** 2026-07-30
**Baseline audited:** `main` @ `49bb9c4` (WO-016 merge, PR #31)
**Previous audit baseline:** `main` @ `af8e52f` (WO-010 Bundle 1 merge, PR #19)

This is the **second** production-readiness audit. The first ran against `af8e52f` and produced
8 autonomously-executable Work Orders (List A) and 12 human-blocked items (List B). Since then,
WO-011 through WO-016 have been implemented, independently reviewed, and merged, plus Dependabot
PR #2. **WO-017 was still in flight when this audit was written** — Issue #33 and PR #34 were open,
unmerged, at audit time, so the rest of this document (gate 1, gate 10, the closed-work table)
originally treated the Bundle 2 scope doc as *proposed*, not delivered. WO-017 merged shortly
afterward, as `99ecfc4`, and Issue #33 is closed; the affected passages below are corrected in
place rather than left stale, and are marked accordingly.

**Update (2026-07-31): this document's own A1 item, WO-018, has since been implemented and
merged** (PR #37, `5f78897`), closing Issue #32 and resolving gate 8's only open blocker. Rather
than rewrite the A1 section's implementation plan out of the historical record, it is left in
place below (marked done) and the gate table / List A / closed-work table are corrected to
reflect the new state, the same in-place-correction approach used above for WO-017.

## What changed since audit 1

- Six List A items closed (WO-011 … WO-016). All were CI / docs / test infrastructure.
- **Nothing touched `config/sources.yaml`, any schema, or any data file.** All 17 registered
  sources remain `enabled: false`; 15 of 17 remain `licence_status: pending_review` (only `GDACS`
  and `MANUAL_NOTICE_INTAKE` are `reviewed`). Live coverage is still "insufficient" by design.
- Two gates moved materially: **operational deployment/monitoring** (WO-014) and **Dashboard
  accessibility** (WO-016). One new open defect was discovered in the process, **Issue #32**;
  it has since been closed by WO-018 (PR #37, see the "Update" note above and gate 8 below).
- No List B item became actionable. Issue #15 (TMD_CAP governance HOLD) is still open, unchanged
  since 2026-07-24.

## 10-gate snapshot

| # | Gate | Status | Current reason |
|---|------|--------|----------------|
| 1 | Multimodal foundation | PARTIAL | Reference entities are mode-neutral and already accept Air (`data/reference/dimensions.json:87` — `air` mode at `module_status: planned`; `:100` — `NODE-THBKKAIR`, explicitly carrying no data). Only Ocean (Bundle 1) is delivered. Bundle 2 scope doc (`docs/bundle2_air_cargo_scope.md`) merged as WO-017 (`99ecfc4`, shortly after this audit was written) — documentation only, no Air lane/node/data added, so this gate's status is unchanged. |
| 2 | Verified-source provenance | PARTIAL | Provenance machinery is complete and tested — acquisition binding (`tests/test_acquisition_binding.py`), collection manifests (`tests/test_r7_manifest_contract.py`), content hashes, retrieval-time fail-closed. But it is exercised only against fixtures, because no source is enabled. Unchanged since audit 1. |
| 3 | Fixture/current separation | PASS | Enforced by `tests/test_current_publication_boundary.py`, `tests/test_review_package_isolation.py`, `tests/test_current_positive_path.py`; demo panels carry a distinct marker in the Dashboard. Unchanged. |
| 4 | Acquisition/review binding | PASS | `tests/test_review_decision_transactions.py` and the WO-010-R5/R6/R7 record-level acquisition proof and approval-hash closure. Unchanged. |
| 5 | Licensing/enablement review | PARTIAL (human-blocked) | 15 of 17 contracts are `licence_status: pending_review`; `docs/source_enablement_decisions.md` registers all 17 with a decision record. Blocked on List B items 1 and 3. Unchanged. |
| 6 | Controlled live validation, offline-default CI | **PASS (improved)** | `collect.yml` and `manual-live-source-test.yml` are `workflow_dispatch:`-only with no `schedule:`/`push:`/`pull_request:` trigger, and WO-015 now makes that a CI failure rather than a convention (`tests/test_workflow_consistency.py`). Was PARTIAL in audit 1 (correct but unenforced). |
| 7 | Deterministic / auditable / fail-closed pipelines | PASS | `scripts/validate.py` semantic checks, `--check` mode on every generator, cross-version determinism fix (`2171152`), warehouse rebuild tests. Unchanged. |
| 8 | Dashboard accurate / accessible / organization-neutral | **PASS (improved, WO-018)** | WO-016 added `tests/test_dashboard_accessibility.py` — single `<h1>`, no static heading skip, `lang`, skip-link target, landmark accessible names, WCAG AA contrast computed from `styles.css`, plus payload budgets. Organization-neutrality is enforced in `analysis/assessments.py:56-74`. **Issue #32 (the last blocker) closed by WO-018** (PR #37, `5f78897`): five new static `<h3>` headings fix the `h2→h4` skip in Trade/Cost/Outlook, with a new data-independent regression test (`test_dynamically_injected_headings_never_skip_a_level`) verified non-vacuous by mutation testing. One documented residual gap: that test's regex doesn't resolve the `events-*` containers (a different, array-driven render pattern); they were manually verified correct, but a regression there wouldn't be caught by this test suite. Was FAIL-equivalent (unverified claims) in audit 1. |
| 9 | Operational deployment / monitoring / backup / runbooks | **PASS (improved, minor robustness gap)** | WO-014 added a daily liveness check of the real Pages URL (`health-check.yml`, cron `17 3 * * *`) with automated issue open-on-failure / close-on-recovery, `docs/deployment_verification.md`, and runbook §6 rollback / §8 backup-DR / §9 incident response. WO-013 added weekly `pip-audit` (`dependency-audit.yml`). Minor gaps remain — see List A #2 and #3. Was FAIL in audit 1. |
| 10 | No unresolved Critical/High blocker | PASS | One open issue as of WO-018's merge: #15 (deliberate TMD_CAP governance HOLD, by design). #32, #33 and #35 all closed since this audit was written. None is Critical or High. |

---

## List A — autonomously executable now

### ~~WO-018 (was A1)~~ — fix the Trade/Cost/Outlook heading-level skip (Issue #32) — DONE

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

**Acceptance criteria.** `ruff check` / `ruff format --check`, `scripts/validate.py`, all `--check`
generators, `python scripts/build_dashboard.py --check`, and `pytest` pass;
`git status --porcelain data dashboard/public/data` is empty (only `index.html`, `app.js` and the
two doc/test files change); `config/sources.yaml`, all schemas and all data files unchanged; the
payload-budget tests (`tests/test_dashboard_accessibility.py:288`, `:296`) still pass — the added
markup is well under 1 KB against a budget with megabytes of headroom. Close Issue #32 on merge.

### A1 (next Work Order) — WO-019: reconcile the two "nine domains" vocabularies

Carried forward from audit 1 (was WO-018 there, then A2); **re-verified and still accurate**. Now
first in List A since WO-018 (the item that outranked it) is done.

The repository has two disjoint nine-item vocabularies, both described in prose as "the nine":

- `analysis/assessments.py:29-39` — `DOMAINS`, nine *measurement* domains (`thailand_trade_flow`,
  `port_maritime_activity`, `freight_benchmark_direction`, `fuel_pressure`, `fx_pressure`,
  `operational_event_status`, `capacity_evidence`, `transit_time_or_service_evidence`,
  `source_freshness_and_coverage`), enforced at `scripts/validate.py:479-483`
  ("must assess all nine domains exactly once").
- `schemas/impact_assessment.schema.json` `area` enum — nine *business impact* areas (`warehouse`,
  `logistics`, `transport`, `import_export`, `inventory`, `cost`, `capacity`, `service`,
  `business_continuity`), enforced at `scripts/validate.py:110-117` ("must contain each of the nine
  areas exactly once") and described at `schemas/logistics_event.schema.json:335`.

The two error strings are near-identical and the vocabularies do not map onto each other. Scope:
documentation only — add a mapping table (which measurement domain, if any, can evidence which
impact area) and state plainly that `warehouse`, `inventory`, `capacity` and `service` have **no**
measurement schema behind them today (`capacity_evidence` and `transit_time_or_service_evidence`
are event-derived, not indicator-derived). Land it in `docs/known_data_gaps.md` plus a clarifying
docstring at `analysis/assessments.py:26-28`. Do not rename either vocabulary — a rename touches
schemas and committed data and is out of scope.

### A2 — WO-020: bind the health-check content marker to the actual page

`tests/test_deployment_health_workflow.py:24` hardcodes
`EXPECTED_CONTENT_MARKER = "Thailand Ocean Logistics Intelligence"` and asserts (line 72) that it
appears **in the workflow file** — never that it appears in `dashboard/public/index.html:16`, where
the `<h1>` actually lives. Renaming that `<h1>` — likely at Bundle 2, when "Ocean" stops being the
whole scope — would silently break the daily liveness `grep` in `health-check.yml:72` and cause the
automated failure issue to open every day with no CI warning. Fix: add one assertion that the
marker is present in the committed `index.html`. Two-line change plus a comment.

### A3 — WO-021: harden the health-check issue dedupe

`health-check.yml:88-90` and `:108-110` look up the existing automated issue via
`GET /issues?state=open&per_page=100`. That endpoint returns pull requests as well as issues and is
capped at one page, so with enough open PRs/issues the dedupe silently misses and a fresh duplicate
issue is opened on every failing run. Fix: filter with `jq 'select(.pull_request | not)'`, or switch
to the search API scoped by title. Low priority — as of this correction (which is itself Issue #38
/ PR #39, following the same self-counting convention the prior roadmap refresh used for #35/#36),
the repository has 2 open issues (#15, #38) and 1 open PR (#39), so the failure mode is latent, not
active; this count will drift as soon as the next Work Order opens its own Issue/PR, same as any
other point-in-time count in this document. Add a matching assertion to
`tests/test_deployment_health_workflow.py`.

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
8. **Destructive data migration.** Any rename of the impact-area or measurement-domain vocabularies (see A1/WO-019) rewrites committed data under `data/assessments/` and `data/events/`. Requires human sign-off before it is attempted.
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
| WO-017 | #33 / #34 | 2026-07-30 (`99ecfc4`, shortly after this audit was written) | `docs/bundle2_air_cargo_scope.md` + `tests/test_bundle2_scope_doc_claims.py`. Was in review at audit time; corrected in place above rather than left stale. |
| — | Roadmap refresh #2 | 2026-07-30 (`72f3e0a`) | This document (`docs/production_readiness_roadmap.md`), Issue #35 / PR #36. |
| WO-018 | #32 / #37 | 2026-07-31 (`5f78897`) | Fixed the Trade/Cost/Outlook `h2→h4` heading-level skip (5 new static `<h3>`s) and added `test_dynamically_injected_headings_never_skip_a_level`, a data-independent regression test mutation-verified to catch the defect class. Closed gate 8's last open blocker. |
