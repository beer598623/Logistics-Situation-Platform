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

## The current package is a filtered artifact (WO-010-R2)

`scripts/build_review_package.py` defaults to `--surface current_publication`.

WO-010 built one combined package: every record the repository held, handed to
ChatGPT alongside a request for a current assessment. A synthetic freight series
and a 2021 canal closure travelled in the same payload as the question "what is
the situation now", and nothing on the way back could tell which was which.

**A current package contains only records that pass
`qualifies_for_current_publication`.** Excluded, and counted in
`provenance_summary.excluded_fixture_record_count`:

- synthetic observations and technical-demonstration indicators;
- technical-demonstration lane assessments;
- historical-validation events and their evidence;
- demonstration scenarios;
- historical expected evidence strength;
- validation fixtures.

With zero qualified evidence the package carries no indicators, no events, no
drivers and no evidence records; every lane reads `insufficient_evidence`; and
the data gaps lead with an explicit instruction that no current directional
conclusion can be produced, that an empty result is a coverage gap rather than a
finding of normality, and that substituting general knowledge for the missing
evidence will be rejected on import.

A demonstration package is available with `--surface technical_demo`. It records
`package_purpose: engine_demonstration` and **can never be approved into the
current AI Outlook** — the approval gate refuses it before any file is touched.

### What the package records

`dataset`, `package_purpose`, `source_cutoff`, a provenance summary of the
evidence and events it carries, the excluded-record count, and its own
`package_sha256`.

### What the validator now checks

`analysis/review_package.validate_output` inspects provenance, not only whether
an evidence ID exists. It rejects fixture or historical evidence in a current
package; evidence marked `not_retrieved` with no human review behind it being
used as a verified current fact; a severity claim unsupported by eligible
evidence; a current operational-condition claim resting only on demonstration
data; a citation of evidence excluded from the current package's citable set;
and a package whose dataset and purpose disagree.

`has_operational_condition_evidence()` requires the item to be eligible for
current publication, not merely to carry an official-looking `claim_type`. A
historical notice is still a notice; it is not a notice about now.

### Approval binding

An approved assessment retains the input package's ID, SHA-256, dataset,
purpose, data cutoff, source cutoff, evidence IDs, evidence-origin summary,
validation status, supersession flag, approval time, reviewer and output hash.

Approval is refused when the package is not `current_publication`, its dataset
and purpose disagree, it holds fixture or historical evidence, the output cites
evidence that is not current evidence in that package, the package has been
edited since generation, the output was produced against a different package
version, the cutoffs differ without explicit supersession, or the output makes
current claims while the package holds nothing eligible to support one.

Publication then re-checks all of it independently from the files on disk.
Approval is a decision made at one moment by one person; publication happens
later, and must not assume that whatever is in the approved directory earned its
place.
