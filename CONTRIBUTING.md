# Contributing

This repository is built through a Work Order process: one bounded change, one GitHub Issue,
one branch, one pull request, with independent review before merge. This document describes
that process for a human contributor. If you are an automated agent, also read
[`AGENTS.md`](AGENTS.md), which defines allowed/prohibited write paths and mandatory behavior
for automated changes — it is stricter than this document, not looser.

## The Work Order process

1. **Open an Issue** describing the origin (what surfaced the need), the problem, the scope
   (what is and is not touched), the planned changes, and acceptance criteria. See any closed
   Work Order issue (e.g. #18, #20, #22) for the structure this repository uses. The
   `.github/ISSUE_TEMPLATE/work_order.md` template captures the same fields.
2. **Create one branch per Work Order**, named for the Work Order (e.g.
   `wo-011-source-qualification-consistency`). Keep the change bounded — if a Work Order grows
   past a few days of focused work, split it rather than widen the branch.
3. **Implement with tests and docs together**, not as a follow-up. A change to behavior
   without a regression test that would have caught its absence is not complete.
4. **Run local validation** before opening the pull request (see below).
5. **Open one pull request per Work Order**, referencing its Issue. Review fixes stay on that
   PR — do not open a second PR to fix review findings on the first.
6. **Get an independent review** before merge. In this repository's current practice that
   review is a fresh, context-isolated pass (human or a separately-invoked reviewer) that did
   not write the change — the implementer does not approve their own work. The review should
   independently re-run validation, not just read the diff.
7. **Merge only a reviewed, green head.** CI must pass, the PR must be mergeable, and any
   review findings must be resolved (blocking) or explicitly accepted as documented
   limitations (non-blocking).

## Local validation

Mirrors what `.github/workflows/validate-pr.yml` runs in CI. From a virtual environment with
`requirements.lock` and `requirements-dev.txt` installed:

```bash
ruff check analysis collectors scripts tests
ruff format --check analysis collectors scripts tests

python scripts/validate.py
python scripts/collect.py --dry-run

# Every generated artefact must still match the inputs it claims to be derived from.
python scripts/ingest_fixtures.py --check
python scripts/build_events_from_cases.py --check
python scripts/build_analysis.py --check

python scripts/run_historical_validation.py
python scripts/build_warehouse.py
python scripts/build_dashboard.py

# The build must not have altered any committed artefact.
git status --porcelain data dashboard/public

pytest
```

## What this repository will not accept

These are structural rules, not style preferences — see `AGENTS.md` and
`docs/security_and_privacy_boundary.md` for the full reasoning:

- **No source is enabled without a separately authorized Work Order.** Every entry in
  `config/sources.yaml` is `enabled: false`; enabling one requires a controlled live
  validation, a licensing review, and clearing its recorded `enablement.blockers` — not a
  drive-by change alongside unrelated work.
- **No credential of any kind committed to the repository.** None exists today and none is
  introduced casually; see `SECURITY.md`.
- **No fixture, demo, or historical-validation data presented as current intelligence.**
  `evidence_origin` and `dataset` fields are structural, not cosmetic, and are enforced by
  `scripts/validate.py`.
- **No missing value represented as zero.** A value exists only when its `value_status` is
  `available`; every other status carries a null value.
- **No organization-specific claim** ("your fleet", "your shipment") in anything published —
  enforced by `analysis/assessments.py` and covered by tests.
- **No private, paid, or restricted-license data**, and no addition that would make
  `docs/security_and_privacy_boundary.md` or the source-qualification records inaccurate.

## Style

- Python: `ruff check` (rules `E`, `F`, `I`, `B`, `UP`, `S`) and `ruff format`, both enforced
  in CI with no local override.
- Prefer editing an existing file over adding a new one; prefer the smallest change that makes
  the Work Order's acceptance criteria true.
- Comments explain a non-obvious *why* (a hidden constraint, a workaround, a subtlety a reader
  would otherwise miss) — not what the code already says by being well-named.
