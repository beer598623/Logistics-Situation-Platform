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

### Added

- `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, `CHANGELOG.md`,
  `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/work_order.md` and `config.yml`,
  `tests/test_oss_governance_files.py` (WO-012).
- `pip-audit` dependency-vulnerability scanning: a fail-closed step in
  `.github/workflows/validate-pr.yml` (report uploaded as an artifact) and a new weekly
  `.github/workflows/dependency-audit.yml` (`schedule` + `workflow_dispatch` only), plus
  `tests/test_dependency_audit_workflow.py` (WO-013).

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
