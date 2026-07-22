# Logistics Situation Platform

Public research dashboard for global and Thailand logistics conditions, operational impacts, preparedness options, and innovation signals.

Public-research dashboard for monitoring global and Thailand logistics conditions, assessing potential operational impacts, and tracking emerging logistics solutions.

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
python -m pip install -r requirements.txt
python scripts/validate.py
python scripts/build_dashboard.py
python -m unittest discover -s tests -v
```

Open `dashboard/public/index.html` after building.

## Initial setup

1. Create a public repository named `Logistics-Situation-Platform`.
2. Upload this bootstrap package to the repository root.
3. In **Settings → Pages**, select **GitHub Actions** as the source.
4. Run the `Validate repository` workflow.
5. Run the `Deploy GitHub Pages` workflow.

## Current status

Implementation v0.1: repository structure, schemas, validation, sample negative control, and static dashboard skeleton.
