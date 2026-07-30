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
- `data/review/inbound/**` (WO-010: a returned ChatGPT assessment awaiting validation)
- `data/assessments/approved/**` (WO-010: written only by `scripts/review_decision.py --decision approve`)
- `data/assessments/archive/**` (WO-010: superseded assessments, written only by the same script)

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
9. Never write an AI assessment into `data/assessments/approved/**` by hand. It is written
   only by `scripts/review_decision.py`, which re-runs the import gates, requires a named
   reviewer, and archives whatever it supersedes.
10. A High or Critical conclusion requires an explicit human-review record before
    publication, in every module and every phase.

## Collector safety

- Do not enable a source unless `machine_readable_status` is `verified`, `licence_status` is `reviewed`, and an endpoint is recorded.
- Collector adapters may detect and normalize candidates; they must not infer or publish operational impact.
- Preserve retrieval timestamps, source record IDs, content hashes, parser versions, source revisions, and limitations.
- A failed or missing source must become an explicit intelligence gap, never a zero value or an all-clear conclusion.
- A value exists only when `value_status` is `available`. Any other status carries a null value; missing data must never be converted to a number, including zero.
- A volume metric (throughput, port calls) can never on its own support a congestion, delay or capacity-shortage conclusion.
- A market benchmark or route proxy must never be presented as a shipment quotation.
- A discovery source may detect a lead but may never be the sole evidence for a material impact conclusion.
