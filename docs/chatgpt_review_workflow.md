# ChatGPT review-package workflow

**Work Order:** WO-010 Gate I · **Status:** implemented; no assessment produced or approved

## 1. No AI API is called

This repository contains no AI API client, no API key handling and no outbound AI call. The
workflow is deliberately human-triggered end to end: a package is generated, a human runs it
through ChatGPT themselves, and the returned assessment is imported and validated as
untrusted input.

`dashboard/public/data/build_status.json` records `ai_api_used: false`, and a test asserts
it.

## 2. The four commands

```bash
# 1. Build a bounded package
python scripts/build_review_package.py --package-id PKG-20260724-001

# 2. [Human] open data/review/packages/PKG-20260724-001.json, run it through ChatGPT with
#    the output instructions it contains, and save the structured reply to
#    data/review/inbound/PKG-20260724-001.json

# 3. Validate the reply against the schema and the rejection rules
python scripts/import_review.py --package-id PKG-20260724-001

# 4. Record an explicit human decision (archives whatever it supersedes)
python scripts/review_decision.py --package-id PKG-20260724-001 \
    --decision approve --reviewer 'A. Reviewer' --note '...'

# 5. Publish
python scripts/build_dashboard.py
```

## 3. What the input package contains

Per `schemas/review_package_input.schema.json`: package ID, methodology version, generated
time, data cutoff, source-health summary, key indicators, lane status, active operational
events, external drivers, evidence records, conflicting evidence, previous assessments, data
gaps, required output instructions, and the exclusions that were applied. The package also
carries its own SHA-256.

Events arrive already split into operational events and drivers, so the distinction survives
the hand-off. Discovery leads travel inside `external_drivers` with their class intact and
are never promoted.

## 4. What is excluded, and recorded as excluded

`exclusions_applied` is a required field so a reviewer can see the boundary was applied:

- **Secrets and credentials** — none exist in this repository and none are exported.
- **Private company information** — the public core holds none; the Private Decision Overlay
  is out of scope for WO-010.
- **Raw licensed content** — only bounded claims and source links, never a full article or a
  stored raw response.
- **Unbounded news text** — claims are capped at 600 characters by the evidence contract.
- **Unsupported claims** — only records that pass `scripts/validate.py` are exported.

## 5. The output contract

`schemas/review_package_output.schema.json` requires: current Thailand Ocean situation, key
changes from the previous assessment, lane-level assessments, verified facts, reported
claims, analytical inference, conflicting evidence, transmission chains, observed impacts,
potential impacts, base/deterioration/improvement scenarios with triggers and horizons,
evidence references, data gaps, conditional preparedness options, and the highest severity
claimed anywhere in the output.

## 6. The rejection rules

Schema validity is necessary but not sufficient. `analysis/review_package.py::validate_output`
additionally rejects an assessment that:

| Rule | Detection |
|---|---|
| References unknown evidence | Any `evidence_id` not present in the input package, in `evidence_references` or in any statement |
| Cites evidence it did not declare | An evidence ID used in a statement but absent from `evidence_references` |
| Omits a transmission mechanism for a material impact | Any impact with non-`none` severity and an empty mechanism |
| Treats missing data as zero | A numeric quantity stated for a series the package marked as having no available value |
| Presents a proxy as a quotation | Phrases such as "average Thailand freight rate", "quoted rate", "spot rate from Thailand" |
| Claims real-time congestion without evidence | Congestion or delay phrasing when the package contains no operational-condition evidence |
| Uses unsupported causation | A causal connective ("caused by", "due to", "led to", …) in a statement with no evidence reference |
| Returns a platform-only status | `no_material` is a platform assessment status recorded against negative operational evidence, and is not accepted from an AI reply |
| Produces an incomplete transmission chain | Any chain missing operational change, mechanism, indicator or outcome |
| Produces company-specific mandatory instructions | Mandatory or second-person phrasing in a preparedness option |
| Produces an incomplete scenario | Any of the three cases missing, or a case with no trigger, or a numeric point forecast in a narrative |
| Mismatches the package | An output `package_id` that does not match its input |

Every rule has a dedicated test in `tests/test_scenarios_and_review.py`.

## 7. The publication boundary

- Passing the rejection rules is **eligibility for human review, not approval**.
- `requires_human_review` returns true for any output claiming `high` or `critical`
  severity. Such an output can never be published without an explicit human-review record.
- The Dashboard's *AI Outlook* section reads **only** `data/assessments/approved/`. An
  unreviewed assessment has no path to it.
- `scripts/review_decision.py` re-runs the import gates before approving, so an assessment
  cannot be approved on the strength of a validation that happened before the file was last
  edited.

## 8. Current state

No AI assessment has been produced or approved. `data/review/inbound/` and
`data/assessments/approved/` are empty by design, and the Dashboard states that in words
rather than showing an empty panel.
