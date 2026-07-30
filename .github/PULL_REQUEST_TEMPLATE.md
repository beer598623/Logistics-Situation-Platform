Closes #<!-- issue number -->

## What changed

<!-- One or two sentences: what this Work Order changed and why. -->

## Scope

<!-- What this PR explicitly does NOT touch, especially: config/sources.yaml, any source's
     enabled/licence_status/reuse_status/redistribution_status, data/, dashboard/public/. -->

## Validation run

<!-- Paste actual command output/status, not just "passed". Mirrors
     .github/workflows/validate-pr.yml: -->

```
ruff check analysis collectors scripts tests
ruff format --check analysis collectors scripts tests
python scripts/validate.py
python scripts/collect.py --dry-run
python scripts/ingest_fixtures.py --check
python scripts/build_events_from_cases.py --check
python scripts/build_analysis.py --check
python scripts/run_historical_validation.py
python scripts/build_warehouse.py
python scripts/build_dashboard.py
git status --porcelain data dashboard/public
pytest
```

## Review

<!-- Independent-review outcome once available: ACCEPT / ACCEPT WITH NON-BLOCKING
     LIMITATIONS / REWORK REQUIRED, and how any findings were resolved. -->
