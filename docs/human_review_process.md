# Human Review process

**Work Order:** WO-010 Gate I · **Status:** implemented

## 1. What requires human review

| Trigger | Requirement |
|---|---|
| Any AI assessment claiming `high` or `critical` severity | Explicit human-review record before publication. Never autonomous |
| Any event whose worst impact severity is `high` or `critical` | `human_review.required` must be true; publication to the main dashboard requires `human_review.status: approved` |
| Any AI assessment at all | An explicit approve or reject decision, recorded with a named reviewer |
| Enabling a source | A controlled live validation through the human-triggered workflow, plus a licence review |

The first two are enforced by `analysis/events.py::validate_event` and
`analysis/review_package.py::requires_human_review`; a `high`-severity event marked
`Main dashboard` without an approved review fails validation.

## 2. The reviewer's decision

```bash
python scripts/review_decision.py --package-id PKG-YYYYMMDD-NNN \
    --decision approve|reject --reviewer '<name or accountable record>' --note '...'
```

`--reviewer` is required. The decision is recorded against a named human, not against a
process.

The script:

1. **Re-runs the import gates.** An approve decision is blocked outright if the assessment
   fails validation — the rejection reasons are printed and nothing is written.
2. **Archives what it supersedes.** Any currently approved assessment for the package is
   moved to `data/assessments/archive/` with a timestamped filename before the new one is
   written. A prior view is preserved, never silently rewritten.
3. **Appends to the assessment history** with the action, the content hash, the reviewer
   record and the archive path.
4. **Writes the approved assessment** only on an approve decision.

A rejection is recorded just as durably as an approval. What was rejected, and why, is part
of the audit trail.

## 3. What a reviewer should actually check

The mechanical rules catch the failure modes that can be caught mechanically. They cannot
tell whether an assessment is *right*. A reviewer should check:

- **Does each material conclusion's transmission chain describe a mechanism that plausibly
  operates?** A complete chain can still be a bad chain.
- **Is the Thailand relevance real, or is it geographic coincidence?** The platform resolves
  lane relevance structurally; whether that structure matters for this event is judgement.
- **Is `observed` genuinely observed, or is it `potential` promoted?** Observed requires
  evidence of the impact, not evidence of the event.
- **Do the scenarios' triggers point at something actually monitorable by this platform?**
- **Are the preparedness options useful without being instructions?**
- **Does the assessment say what it does not know?** An assessment with no data gaps listed,
  against a source registry with insufficient coverage, is wrong by omission.

## 4. Assessment history

`data/assessments/assessment_history.json` is append-only. Each entry records the subject,
revision number, timestamp, action (`created`, `revised`, `approved`, `rejected`,
`archived`, `superseded`, `closed`), content hash, the entry it supersedes, a summary, the
reviewer record and the archive path.

This is what makes a later change of view visible as a change, rather than as the way things
always were.

## 5. Approve and reject are asymmetric (WO-010-R1)

A rejection is a statement about the **inbound** assessment. It says nothing about the
assessment already approved.

| | Reject | Approve |
|---|---|---|
| Re-runs every gate | Records the outcome | **Blocks on failure** |
| Approved assessment file | **Untouched, byte for byte** | Replaced atomically |
| Archive | Nothing archived | Previous version archived, but only after the new one passes |
| History | Rejection recorded | Approval recorded with a revision number and the entry it supersedes |

Under WO-010 a rejection archived the currently approved assessment: declining a bad
submission silently withdrew the good one that was live, and the Dashboard lost its AI
Outlook because someone said "no" to something else. `scripts/review_decision.py` now
archives only on the approve path.

Both paths are transactional. Every file the script may touch — the history, the approved
assessment and the archive destination — is captured before any change and restored if
anything raises, so a failure part-way through leaves the repository exactly as it was
rather than with an archived old version and no new one. Archive destinations are also
de-duplicated: two approvals of the same package within the same second used to produce the
same filename, and the second move overwrote the first archived version.

Regression coverage is in `tests/test_review_decision_transactions.py`.

## 5b. What a reviewer cannot approve (WO-010-R2)

Approval is bound to the exact package the assessment was produced from. Typing
`--decision approve` is not sufficient, and the following are refused before any
file is touched:

- a package that is not `current_publication`, or whose dataset and purpose
  disagree;
- a package containing fixture or historical-validation evidence;
- an output citing evidence that is not current evidence in that package;
- a package edited after it was generated — its recorded `package_sha256` no
  longer matches its contents;
- an output produced against a different version of the package;
- a data cutoff differing from the package's without an explicit supersession;
- an output making current claims when the package holds no evidence eligible to
  support one.

The approved record retains the package ID, its SHA-256, its dataset and
purpose, both cutoffs, the evidence IDs, an evidence-origin summary, the
validation status, the supersession flag, the approval time, the reviewer and
the output hash.

Publication re-checks every one of those **independently**, from the files on
disk. An approved assessment that is not bound to a current package, cites no
package hash, did not pass validation, has been superseded, or rests on
fixture-origin evidence is withheld and listed on the Dashboard rather than
published.

## 6. Boundaries a reviewer cannot waive

- No paid source may be enabled or required for publication.
- No private company data may enter the public repository.
- No credential may be committed.
- `TMD_CAP` and `GDACS` remain governed by their own records; this process does not cover
  them.
- Missing data may not be published as zero.
- No AI output may be published without passing through this process.
- No assessment produced from a demonstration or historical package may be approved into
  the current AI Outlook, whatever a reviewer decides.

## 7. Current state

No assessment has been submitted for review, so no review record exists. The process,
its scripts and its gates are implemented and tested.
