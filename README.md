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

Implementation v0.1.1: source contracts, collection provenance, source-health gates, adapter interfaces, locked runtime dependencies, and quality checks. Live collectors remain disabled until source-specific integration tests pass.

## Data contracts

- `config/sources.yaml` is the source contract registry.
- `schemas/collection_run.schema.json` records collection-run lineage.
- `schemas/source_status.schema.json` prevents a source outage from appearing as an all-clear.
- Evidence records retain retrieval time, content hash, parser version, reuse status, and source revision.
- Live collection is disabled unless the source endpoint and machine-readable status are verified and the reuse position is reviewed.
