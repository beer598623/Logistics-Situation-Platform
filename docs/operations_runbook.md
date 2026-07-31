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

Three generators accept `--check`, which regenerates in memory and exits non-zero if the
committed output no longer matches its inputs: `ingest_fixtures.py`,
`build_events_from_cases.py`, `build_analysis.py`. CI runs all three
(`.github/workflows/validate-pr.yml`, "Verify generated data is reproducible"). The other
generators accept no CLI arguments at all — an unrecognized flag such as `--check` now fails
fast (exit 2) rather than being silently ignored. Their reproducibility is enforced
differently: `build_dashboard.py`'s by CI's own "Confirm the build produced no uncommitted
change" step, which runs the real build and then requires
`git status --porcelain data dashboard/public` to be empty; `generate_synthetic_fixtures.py`'s
by `tests/test_derived_outputs.py::test_regenerating_the_fixtures_is_a_no_op`, which
byte-compares its output before and after a fresh run. `build_warehouse.py` and
`run_historical_validation.py` accept unrelated flags (`--path`, `--write-report`) and also
reject `--check`.

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

None of these makes a network request. One command in this runbook is the exception, and it
is run separately rather than folded into the block above:

```bash
pip-audit -r requirements.lock
```

`pip-audit` (WO-013, §4 below) queries PyPI's advisory feed about the pinned versions
themselves — ordinary CI dependency tooling, not contact with any registered logistics
source.

## 3. Workflows

| Workflow | Trigger | Network |
|---|---|---|
| `validate-pr.yml` | pull request, push to main, manual | package install and dependency-vulnerability lookup only |
| `dependency-audit.yml` | weekly, manual | package install and dependency-vulnerability lookup only |
| `collect.yml` | manual only | **none** — contract dry run |
| `deploy-pages.yml` | push to main, manual | none beyond Pages upload |
| `health-check.yml` | **daily**, manual | fetches the *published Dashboard URL itself* (liveness check, WO-014) and the GitHub Issues API (to record/clear a failure); neither is a registered logistics source |
| `manual-live-source-test.yml` | **manual only** | the one place a live fetch of a *registered source* may occur |

`dependency-audit.yml` and the "Audit locked dependencies" step in `validate-pr.yml` both call
`pip-audit`, which queries a public vulnerability database (PyPI's advisory feed) about the
*pinned dependency versions themselves* — this is ordinary CI dependency tooling, the same
class of network access `pip install` already makes, not contact with any registered
logistics data source in `config/sources.yaml`.

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

### The dependency vulnerability audit fails
`pip-audit -r requirements.lock` (WO-013) found a known vulnerability in a pinned package —
either on a pull request (`validate-pr.yml`'s "Audit locked dependencies" step) or on the
standing weekly `dependency-audit.yml` run against whatever is already on `main`. The failing
job's log, or the `pip-audit-report` artifact on a PR run, names the package, the installed
version, the advisory ID, and the fix version(s) if one exists.

**Triage:**
1. Read the advisory (search its ID — a `PYSEC-...` or `GHSA-...` identifier — for the full
   description) and assess whether this repository's actual usage of the package is affected;
   not every advisory applies to every usage pattern (see the `duckdb`/`PYSEC-2025-112` entry
   in `CHANGELOG.md` for a worked example: the advisory concerned a database-encryption
   feature this repository never uses, and the fix was still applied as a zero-risk bump).
2. If a fix version exists and there is no known compatibility break, bump the pin in all
   three places it is recorded (`requirements.txt`, `requirements.lock`, `pyproject.toml`),
   re-run the full local validation sequence (§2), and confirm `pip-audit -r requirements.lock`
   is clean.
3. If no fix version exists yet, or bumping would require a wider compatibility change, this
   is a judgment call outside what an automated Work Order should decide alone — treat it as a
   blocker requiring human review, note the advisory ID and why it isn't yet fixed, and do not
   silently downgrade the audit's severity to work around it.

This in-tree scan is distinct from **Dependabot security updates** and **secret scanning**,
which are GitHub repository settings, not files in this repository, and are not configured by
any Work Order to date — `.github/dependabot.yml` currently configures only routine *version*
updates.

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

### Rolling back the published Dashboard (WO-014)

`deploy-pages.yml` is redeploy-from-source, not serve-a-branch: it checks out a commit, runs
`scripts/build_dashboard.py`, and uploads that fresh build as the Pages artifact. There is no
`gh-pages` branch holding old builds to check out directly (`docs/deployment_verification.md`
§1). To roll the *published site* back to a prior known-good state:

1. Identify the last commit on `main` known to have built and validated correctly (e.g. the
   commit an earlier successful `deploy-pages.yml` run deployed).
2. Re-run `deploy-pages.yml` `workflow_dispatch` against that commit's SHA — either by
   dispatching the workflow with that ref, or by pushing a revert commit to `main` that
   restores the prior tree and letting the normal `push`-triggered deploy handle it. A revert
   commit is preferred: it keeps `main`, the build inputs, and the published site consistent
   with each other, rather than leaving `main` ahead of what is actually live.
3. Confirm the rollback with `docs/deployment_verification.md`'s liveness check (or wait for
   the next daily `health-check.yml` run) against the published URL.

Because `deploy-pages.yml`'s `build` job fails closed (§4, "A generator fails"), a bad commit
that fails validation never reaches the artifact-upload step in the first place — the site
already stays on its last good deploy without any rollback action. Rollback is only needed
when a commit *passed* validation but is discovered to be wrong after the fact (a data-quality
issue caught later, a licensing concern about already-published content, and similar).

## 7. Before enabling any source

1. Complete a controlled live validation through `manual-live-source-test.yml`.
2. Record the observed freshness, the data period and the response envelope.
3. Read the publisher's terms and record `reuse_status` and `redistribution_status`.
4. Set `machine_readable_status: verified` and `licence_status: reviewed` only if the
   evidence actually supports it.
5. Clear `enablement.blockers`.
6. Justify a collection schedule that does not exceed the source's cadence.
7. Re-run `python scripts/validate.py` — it will refuse an enabled source with a blocker.

## 8. Backup and disaster recovery (WO-014)

There is exactly one stateful, non-derivable system: **this git repository**. Every published
fact, every schema, every reviewed assessment, and every source contract is a committed file.
GitHub's own repository redundancy is the backup for that state; there is no separate database,
object store, or credential vault to back up, because none exists (`docs/security_and_privacy_boundary.md`
§5-6).

Everything else is derived and disposable:

- **The DuckDB warehouse** (`warehouse/logistics.duckdb`) is gitignored and rebuilt from
  committed data by `scripts/build_warehouse.py`. Losing it costs one command, not data.
- **The published Dashboard** (`dashboard/public/`) is committed (so it is itself
  git-recoverable) *and* independently rebuildable from `data/` by `scripts/build_dashboard.py`.
- **GitHub Pages' serving infrastructure** is not this project's to back up; recovery from a
  Pages-side outage is "wait, or redeploy" (§6 above), not a restore-from-backup operation.

**Recovery time objective:** a full rebuild from a clean clone (`git clone` → install locked
dependencies → `scripts/build_warehouse.py` → `scripts/build_dashboard.py`) completes in
minutes on ordinary CI hardware — see `validate-pr.yml`'s `timeout-minutes: 15` for the
outer bound actually observed in practice, which covers far more than just the rebuild.

**Recovery point objective:** whatever was last committed to `main`. There is no window of
uncommitted, unrecoverable state by design — `AGENTS.md` and this runbook's own review cycle
(§5) require every published change to go through a pull request, not a direct write to a
running system.

## 9. Incident response (WO-014)

This is a public-data research repository with no on-call rotation and no paid incident
tooling. "Incident response" here means: notice, triage, act, record — using the mechanisms
already in this repository rather than inventing new ones.

**Severity levels:**

| Severity | Meaning | Example |
|---|---|---|
| **Info** | No user-facing effect | A single `health-check.yml` run fails transiently (e.g. a GitHub Pages CDN blip) and the next scheduled run passes |
| **Degraded** | The published Dashboard is stale, incomplete, or shows a data-quality problem, but is reachable | A generator's `--check` step would fail if re-run today (caught before the next deploy by `validate-pr.yml`, so this should never reach production) |
| **Down** | The published URL is unreachable or not serving the expected content | `health-check.yml`'s liveness step fails on two or more consecutive scheduled runs |
| **Integrity** | Something published violates a structural guarantee this platform claims (fixture data presented as current, a missing value shown as zero, an organization-specific claim, licensing content beyond what a source permits) | Caught by `scripts/validate.py`'s fail-closed checks before publication; if one is discovered *after* publication despite that, treat as Integrity regardless of how it reached production |

**Detection:**
- **Down** — the automated `[Automated] Repository health check failed` issue from
  `health-check.yml` (§3 of `docs/deployment_verification.md`). Do not wait for a human to
  notice a red workflow run; the issue is the notification.
- **Degraded / Integrity** — a `validate-pr.yml` failure on a pull request (should block merge
  before publication), a `dependency-audit.yml` finding (§4 above), or a report from anyone
  reading the published Dashboard.

**Response:**
1. **Triage severity** using the table above. An Info-level single transient failure needs no
   action beyond confirming the next scheduled run passed.
2. **Down** — follow §6's Pages rollback/redeploy procedure once the cause is understood
   (Pages-service-side vs. a bad deploy). If the cause is unknown, redeploying the last known
   good commit is a safe first action; it cannot make things worse, since the artifact
   pipeline always redeploys from a validated build.
3. **Degraded / Integrity discovered after publication** — this is the one case where a
   rollback is not automatically safe on its own: check *what* was wrong before just reverting,
   because reverting to an earlier commit could reintroduce a different, already-fixed problem.
   Prefer a forward fix (a new, reviewed Work Order correcting the specific defect) unless the
   published content needs to come down immediately, in which case roll back first and open the
   corrective Work Order afterward.
4. **Record it.** The automated health-check issue covers Down. For Degraded/Integrity, open
   an Issue describing what was found, its severity, and the corrective Work Order — the same
   Issue → branch → PR → independent review → merge cycle this repository already uses for
   every other change (`CONTRIBUTING.md`), not a separate incident process.
5. **Close it** only once the corrective change is merged and verified live (or, for the
   automated Down issue, once `health-check.yml` closes it on the next successful run).

**Escalation:** there is no on-call rotation or paging system. "Escalation" means the automated
issue (or a manually opened one per step 4) is the durable record that something needs human
judgment — the same pattern this repository already uses for any blocker requiring credentials,
legal/licensing judgment, or another human-only decision.
