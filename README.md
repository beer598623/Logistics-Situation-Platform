# Logistics Situation Platform

Public research dashboard for global and Thailand logistics conditions, operational impacts, preparedness options, and innovation signals.

## Approved product direction (WO-009A)

The approved product direction is the **Thailand-Centric Multimodal Logistics Intelligence &
Outlook Dashboard**: Thailand-centric, multimodal (Sea, Air, Road, Rail, Border), Logistics-first,
externally informed, evidence-linked, scenario-based, and free-only. Ocean Logistics is the first
implementation module, not the permanent limit of the product. This supersedes the prior broad
hazard-oriented implementation priority as the platform's implementation priority; it does not
delete or invalidate prior technical evidence (WO-002 through WO-008).

See:

- [`docs/thailand_multimodal_logistics_intelligence_scope.md`](docs/thailand_multimodal_logistics_intelligence_scope.md) — approved product principles, Public Core/Private Overlay boundary, data-layer architecture, lane model, AI role and Human Review boundary, and Dashboard information architecture.
- [`docs/thailand_multimodal_logistics_mvp_roadmap.md`](docs/thailand_multimodal_logistics_mvp_roadmap.md) — implementation phases (Phase 0–7) and MVP acceptance criteria.
- [`docs/source_priority_framework.md`](docs/source_priority_framework.md) — source-priority matrix and free-only qualification framework.

WO-009A was architecture, governance, and documentation only. **WO-010 implements Bundle 1**
— the common data foundation plus the Ocean Logistics Intelligence MVP — pending independent
review. See [`docs/bundle1_architecture.md`](docs/bundle1_architecture.md).

## Project principles

- Public sources only.
- Organization-neutral analysis.
- Facts, reported claims, inference, forecasts, and preparedness options are separated.
- Missing data is never treated as zero.
- Impact is assessed independently across Warehouse, Logistics, Transport, Import–Export, Inventory, Cost, Capacity, Service, and Business Continuity.
- “No material impact detected” is used when evidence does not support a meaningful logistics impact.

## MVP workflow

1. GitHub prepares candidate data.
2. Scheduled ChatGPT researches and produces a Decision Package.
3. A human approves, revises, or rejects the package.
4. Codex updates approved data and opens a pull request.
5. GitHub Actions validates, builds, and deploys the static dashboard.

## Local validation

```bash
python -m pip install -r requirements.lock pytest==9.1.1 ruff==0.15.22
ruff check analysis collectors scripts tests
ruff format --check analysis collectors scripts tests
python scripts/validate.py
python scripts/collect.py --dry-run
python scripts/build_dashboard.py
pytest
```

Commands introduced by WO-010:

```bash
python scripts/ingest_fixtures.py --check          # observations match their fixtures
python scripts/build_events_from_cases.py --check  # events match the authored cases
python scripts/build_analysis.py --check           # derived assessments are current
python scripts/run_historical_validation.py        # replay the Gate J cases
python scripts/build_warehouse.py                  # derived DuckDB (gitignored)
```

None of these makes a network request. Open `dashboard/public/index.html` after building, or
serve the directory to avoid `file://` fetch restrictions:

```bash
python -m http.server 8000 --directory dashboard/public
```

## Deployment

GitHub Actions validates the repository and deploys `dashboard/public` to GitHub Pages.
The published site must retain the latest successful version when validation or collection fails.

## Current status

**Implementation v0.3.0 (WO-010, Bundle 1).** The common multimodal data foundation and the
Ocean Logistics Intelligence MVP are implemented: 18 conceptual entities, 11 Thailand-centred
Ocean lane groups, deterministic indicators with seven documented threshold rules, an event
model with lifecycle/clustering/transmission chains, nine-area impact assessment, scenario
outlooks with conditional preparedness options, a human-triggered ChatGPT review package with
its rejection rules and human-approval gate, eight historical validation cases, a derived
DuckDB warehouse, and a seven-section static Dashboard.

**Live coverage is insufficient and the Dashboard says so on its face.** No source in the
registry is enabled and none has completed a controlled live validation, so every numeric
series is a labelled synthetic test fixture and all event evidence is a historical validation
fixture whose content was not retrieved. `Paid-source dependency = 0`; no AI API is called.
See [`docs/source_qualification_report.md`](docs/source_qualification_report.md) and
[`docs/known_data_gaps.md`](docs/known_data_gaps.md).

Key WO-010 documents: [`bundle1_architecture`](docs/bundle1_architecture.md),
[`data_model_and_persistence`](docs/data_model_and_persistence.md),
[`ocean_lane_selection`](docs/ocean_lane_selection.md),
[`indicator_definitions`](docs/indicator_definitions.md),
[`event_lifecycle`](docs/event_lifecycle.md),
[`chatgpt_review_workflow`](docs/chatgpt_review_workflow.md),
[`historical_validation`](docs/historical_validation.md),
[`dashboard_user_guide`](docs/dashboard_user_guide.md),
[`operations_runbook`](docs/operations_runbook.md),
[`security_and_privacy_boundary`](docs/security_and_privacy_boundary.md).

### Prior implementation history

Implementation v0.2.1: TMD RSS envelope discovery and manual-workflow failure-path hardening (`collectors/adapters/xml_envelope.py`, `collectors/adapters/rss_discovery.py`, `TmdCapAdapter.discover_rss()`), following up WO-003 controlled live-validation evidence that both recorded TMD endpoints currently serve an RSS envelope rather than a direct CAP 1.2 alert. The strict CAP 1.2 parser is unchanged; RSS discovery is structural, redacted, and one-request-only, and never fetches a discovered item link or enclosure. This sits on top of Implementation v0.2 (a controlled, fixture-first GDACS adapter and a generic CAP 1.2 parser with a thin TMD CAP profile: `collectors/adapters/gdacs.py`, `collectors/adapters/cap.py`, `collectors/adapters/tmd_cap.py`), the v0.1.2 source-health/event-identity work, and the v0.1.1 provenance hardening. **No live source is enabled for production.** GDACS and TMD_CAP remain `enabled: false`; the only network-capable path is a `workflow_dispatch`-only manual workflow (`.github/workflows/manual-live-source-test.yml`) that never writes to public dashboard or candidate data and never uploads a raw TMD payload.

See [`docs/tmd_rss_discovery_hardening.md`](docs/tmd_rss_discovery_hardening.md) for the RSS-discovery design, WO-003 live evidence, and the SSRF/follow-link boundary; [`docs/gdacs_tmd_cap_pilot.md`](docs/gdacs_tmd_cap_pilot.md) for the v0.2 pilot's design, verified source facts, and the manual workflow's safety controls; and [`docs/source_health_and_event_identity.md`](docs/source_health_and_event_identity.md) for how source health, coverage, and event identity are computed.

## Data contracts

- `config/sources.yaml` is the source contract registry.
- `schemas/collection_run.schema.json` records collection-run lineage.
- `schemas/staging_record.schema.json` is the shared normalized-output contract for the GDACS and CAP/TMD adapters (Implementation v0.2) -- a candidate-level record with provenance, never an assigned `canonical_event_id` and never an operational-impact field.
- `schemas/source_status.schema.json` prevents a source outage from appearing as an all-clear, and breaks coverage down by purpose-aware capability.
- `collectors/source_health.py` evaluates each source's freshness deterministically from its contract and known collection runs.
- `collectors/event_identity.py` assigns a stable `canonical_event_id` from a source's external ID or a controlled-field fingerprint, never from title wording.
- Evidence records retain retrieval time, content hash, parser version, reuse status, and source revision.
- Live collection is disabled unless the source endpoint and machine-readable status are verified and the reuse position is reviewed; the only network-capable path is the `workflow_dispatch`-only manual workflow described in [`docs/gdacs_tmd_cap_pilot.md`](docs/gdacs_tmd_cap_pilot.md).
- `schemas/observation_common.schema.json` defines the shared provenance, placement and missing-value semantics for every observation family. A value exists **if and only if** `value_status` is `available`, enforced at construction, in the contract and again at validation.
- `schemas/lane.schema.json`, `schemas/logistics_event.schema.json`, `schemas/lane_assessment.schema.json` and `schemas/scenario_outlook.schema.json` carry the Ocean analytical model. All are mode-tagged rather than Ocean-hardcoded, so Air and Land extend them without a schema change.
- `schemas/review_package_input.schema.json` and `schemas/review_package_output.schema.json` define the human-triggered ChatGPT boundary.
- `config/sources.yaml` additionally carries per-source `qualification` and `enablement` records, including the exact unresolved blockers preventing enablement.
