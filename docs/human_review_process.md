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

## 5. Boundaries a reviewer cannot waive

- No paid source may be enabled or required for publication.
- No private company data may enter the public repository.
- No credential may be committed.
- `TMD_CAP` and `GDACS` remain governed by their own records; this process does not cover
  them.
- Missing data may not be published as zero.
- No AI output may be published without passing through this process.

## 6. Current state

No assessment has been submitted for review, so no review record exists. The process,
its scripts and its gates are implemented and tested.
