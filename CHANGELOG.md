# Changelog

All notable changes to this repository are recorded here, backfilled from git history in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style. This project has not yet cut
a tagged release; `pyproject.toml`'s `version = "0.3.0"` reflects the state delivered by
WO-010 and is not bumped by every Work Order.

## [Unreleased]

### Fixed

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
