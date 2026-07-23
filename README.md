# Logistics Situation Platform

Public research dashboard for global and Thailand logistics conditions, operational impacts, preparedness options, and innovation signals.

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
ruff check collectors scripts tests
ruff format --check collectors scripts tests
python scripts/validate.py
python scripts/collect.py --dry-run
python scripts/build_dashboard.py
pytest
```

Open `dashboard/public/index.html` after building.

## Deployment

GitHub Actions validates the repository and deploys `dashboard/public` to GitHub Pages.
The published site must retain the latest successful version when validation or collection fails.

## Current status

Implementation v0.2 pilot: a controlled, fixture-first GDACS adapter and a generic CAP 1.2 parser with a thin TMD CAP profile (`collectors/adapters/gdacs.py`, `collectors/adapters/cap.py`, `collectors/adapters/tmd_cap.py`), on top of the v0.1.2 source-health/event-identity work and the v0.1.1 provenance hardening. **No live source is enabled for production.** GDACS and TMD_CAP remain `enabled: false`; the only network-capable path is a `workflow_dispatch`-only manual workflow (`.github/workflows/manual-live-source-test.yml`) that never writes to public dashboard or candidate data and never uploads a raw TMD payload.

See [`docs/gdacs_tmd_cap_pilot.md`](docs/gdacs_tmd_cap_pilot.md) for the pilot's design, verified source facts, and the manual workflow's safety controls, and [`docs/source_health_and_event_identity.md`](docs/source_health_and_event_identity.md) for how source health, coverage, and event identity are computed.

## Data contracts

- `config/sources.yaml` is the source contract registry.
- `schemas/collection_run.schema.json` records collection-run lineage.
- `schemas/staging_record.schema.json` is the shared normalized-output contract for the GDACS and CAP/TMD adapters (Implementation v0.2) -- a candidate-level record with provenance, never an assigned `canonical_event_id` and never an operational-impact field.
- `schemas/source_status.schema.json` prevents a source outage from appearing as an all-clear, and breaks coverage down by purpose-aware capability.
- `collectors/source_health.py` evaluates each source's freshness deterministically from its contract and known collection runs.
- `collectors/event_identity.py` assigns a stable `canonical_event_id` from a source's external ID or a controlled-field fingerprint, never from title wording.
- Evidence records retain retrieval time, content hash, parser version, reuse status, and source revision.
- Live collection is disabled unless the source endpoint and machine-readable status are verified and the reuse position is reviewed; the only network-capable path is the `workflow_dispatch`-only manual workflow described in [`docs/gdacs_tmd_cap_pilot.md`](docs/gdacs_tmd_cap_pilot.md).
