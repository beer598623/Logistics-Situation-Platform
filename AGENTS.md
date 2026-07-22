# Codex operating contract

## Purpose
Apply only human-approved Daily Decision Packages to the logistics intelligence repository.

## Allowed write paths
- `data/reviewed/**`
- `data/archive/**`
- `briefs/**`
- `decisions/approved/**`
- `dashboard/data/**`
- `innovation/solution_register.json`

## Prohibited write paths
- `methodology/**`
- `schemas/**`
- `scripts/**`
- `.github/**`
- `AGENTS.md`
- `config/sources.yaml`

## Mandatory behavior
1. Confirm the methodology version in the approved package.
2. Preserve existing Event IDs across lifecycle updates.
3. Apply only explicitly approved events and edits.
4. Do not convert missing values into zero.
5. Keep verified facts separate from claims and inference.
6. Run `python scripts/validate.py`, `python scripts/build_dashboard.py`, and the test suite.
7. Create a pull request; do not push directly to `main`.
8. Include validation and build results in the pull-request description.
