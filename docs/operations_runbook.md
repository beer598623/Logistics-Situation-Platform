# Operations and recovery runbook

**Work Order:** WO-010 · **Status:** implemented

## 1. Full rebuild, in order

```bash
python scripts/generate_synthetic_fixtures.py    # no-op on a clean tree
python scripts/ingest_fixtures.py                # fixtures  → observations
python scripts/build_events_from_cases.py        # cases     → events + evidence
python scripts/build_analysis.py                 # → indicators, lane and Thailand assessments
python scripts/run_historical_validation.py --write-report
python scripts/build_warehouse.py                # derived DuckDB (gitignored)
python scripts/build_dashboard.py                # static payloads
python scripts/validate.py                       # contracts + semantics
```

Every generator also accepts `--check`, which regenerates in memory and exits non-zero if
the committed output no longer matches its inputs. CI runs all of them.

## 2. Verification commands

```bash
ruff check analysis collectors scripts tests
ruff format --check analysis collectors scripts tests
python scripts/validate.py
python scripts/collect.py --dry-run
python scripts/build_dashboard.py
pytest
```

Plus the commands WO-010 introduces:

```bash
python scripts/build_warehouse.py
python scripts/run_historical_validation.py
python scripts/ingest_fixtures.py --check
python scripts/build_events_from_cases.py --check
python scripts/build_analysis.py --check
```

None of these makes a network request.

## 3. Workflows

| Workflow | Trigger | Network |
|---|---|---|
| `validate-pr.yml` | pull request, push to main, manual | **none** |
| `collect.yml` | manual only | **none** — contract dry run |
| `deploy-pages.yml` | push to main, manual | none beyond Pages upload |
| `health-check.yml` | weekly, manual | none |
| `manual-live-source-test.yml` | **manual only** | the one place a live fetch may occur |

`manual-live-source-test.yml` must never gain a `schedule:`, `push:` or `pull_request:`
trigger. It is the sole authorized live-network path, it is human-triggered, it verifies
that no public dashboard or event data changed during the run, and it uploads only a
redacted report.

## 4. Failure handling

### A generator fails
Nothing downstream is written. `build_dashboard.py` in particular assembles every payload in
memory before touching `dashboard/public/data`, so a failure leaves the previously published
Dashboard exactly as it was. `tests/test_dashboard_build.py::test_a_failed_build_leaves_the_published_directory_untouched`
asserts this.

**Recovery:** fix the input, re-run the chain. The last reviewed Dashboard stays live in the
meantime.

### Validation fails
`scripts/validate.py` prints the failing record and the specific rule. Common causes:

| Message | Cause |
|---|---|
| `value_status is 'missing' but a value is present` | An adapter emitted a number for an unpublished period |
| `benchmark_class ... must record quotation_claim 'not_a_quotation'` | A proxy was marked as a quotation |
| `is a volume metric and must be recorded as 'volume_only'` | A throughput series was given an operational interpretation |
| `cites threshold rule ... while reporting insufficient evidence` | A rule was cited that could not have been applied |
| `an enabled source cannot have unresolved enablement blockers` | A source was flipped to enabled prematurely |
| `records are out of date` | A committed artefact no longer matches its inputs — re-run the generator |

### The warehouse is corrupt or stale
Delete and rebuild. It is derived and gitignored; nothing is lost.

```bash
rm -f warehouse/logistics.duckdb && python scripts/build_warehouse.py
```

### A source starts failing (once any is enabled)
A failed collection becomes an explicit intelligence gap: the source's health status becomes
`error` or `no_data`, its capability coverage degrades, and the Dashboard shows the gap. It
never becomes zero items and never becomes an all-clear. The previously reviewed Dashboard
remains published.

## 5. The review cycle

```bash
python scripts/build_review_package.py --package-id PKG-YYYYMMDD-NNN
# [human] run through ChatGPT, save reply to data/review/inbound/<id>.json
python scripts/import_review.py --package-id PKG-YYYYMMDD-NNN
python scripts/review_decision.py --package-id PKG-YYYYMMDD-NNN \
    --decision approve --reviewer '<name>'
python scripts/build_dashboard.py
```

See `docs/chatgpt_review_workflow.md` and `docs/human_review_process.md`.

## 6. Rollback

Every WO-010 change is additive on one branch. To roll back:

- **Data only:** `git checkout <ref> -- data/ dashboard/public/data/` and rebuild.
- **Everything:** revert the branch. The pre-existing collectors, schemas, workflows and
  WO-002…WO-009 evidence are unmodified except for additive fields, so reverting leaves the
  prior platform intact.
- **The warehouse** needs no rollback; delete and rebuild.

## 7. Before enabling any source

1. Complete a controlled live validation through `manual-live-source-test.yml`.
2. Record the observed freshness, the data period and the response envelope.
3. Read the publisher's terms and record `reuse_status` and `redistribution_status`.
4. Set `machine_readable_status: verified` and `licence_status: reviewed` only if the
   evidence actually supports it.
5. Clear `enablement.blockers`.
6. Justify a collection schedule that does not exceed the source's cadence.
7. Re-run `python scripts/validate.py` — it will refuse an enabled source with a blocker.
