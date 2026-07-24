# WO-007A: candidate evidence contract hardening & Gate readiness (Implementation v0.2.3)

Publication date of this note: **2026-07-24**.

This is a narrowly-scoped follow-up to
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
(Implementation v0.2.2, WO-006, Issue #11), written for WO-007 (Issue #13)
after that issue's Gate 1 review returned a **CONDITIONAL** disposition.
It changes only the *reporting* boundary of the existing
`candidate_cap_validation` operation -- what a dry-run or live report
retains about the candidate a workflow run was asked to validate. It does
not change candidate reference grammar, the pinned transport, envelope
classification, the strict CAP 1.2 parser, the error taxonomy, or the
manual workflow's wiring; see Section 5 below for the exact unchanged
list.

**This document and its code do not authorize a live candidate fetch, and
this increment does not re-run WO-007 Issue #13 Gate 1.** No live
candidate fetch was performed to write it; every example and test uses
synthetic fixtures only, exactly as under WO-006. A live fetch still
requires explicit human approval, distinct from and in addition to this
increment's own code-level review, per
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 10 (unchanged by this increment).

## 1. Gate 1 finding and how this increment resolves it

WO-007 Issue #13 Gate 1 reviewed the WO-006 dry-run artifact -- the
sanitized `report.json` a `candidate_cap_validation` workflow run with
`dry_run: true` produces -- and returned CONDITIONAL. The report recorded
`language` and the derived `request_url`, but not the exact
`candidate_filename`, `candidate_evidence_run_id`, or
`candidate_evidence_item_index` a reviewer had submitted as workflow
inputs. Since those inputs are not otherwise part of the uploaded
artifact, an independent reviewer working from the artifact alone could
not confirm which candidate, traceable to which WO-005-style discovery
evidence, a given report actually described.

This increment closes that finding, and only that finding: every
`candidate_cap_validation` report -- dry-run or live, whether the
candidate reference was accepted or rejected -- now carries a bounded,
sanitized `candidate_reference` object (Section 2) and, when the
environment provides them, `workflow_run_id` alongside the existing
`workflow_sha` (Section 3).

## 2. The `candidate_reference` object

Present at `report["candidate_reference"]` on every
`candidate_cap_validation` report, in both `dry_run` and `live` modes,
regardless of whether the candidate reference passed structural
validation:

| Field | Content |
| --- | --- |
| `language` | the language selector submitted (`"primary"` or `"thai_language_cap"`) |
| `candidate_filename` | the candidate filename submitted |
| `candidate_evidence_run_id` | the WO-005-style discovery workflow run ID submitted |
| `candidate_evidence_item_index` | the discovery item index submitted |
| `request_url` | the request URL derived from the four fields above by fixed policy, or `null` if the reference was rejected before a URL could be derived |

Two behaviors depend on whether `build_candidate_reference()` accepted
the submitted values:

- **Accepted:** every field echoes the already-validated
  `CandidateReference` (`reference.language`,
  `reference.candidate_filename`, ...), not the raw argument -- what is
  retained is exactly what was validated and (for `dry_run: false`) what
  was fetched.
- **Rejected:** every field echoes the raw, unvalidated caller input
  instead, and `request_url` is `null`. This is deliberate: the whole
  point of the Gate 1 finding is that a reviewer needs to see *what was
  rejected and why*, not only what a successful run validated.

Every field is bounded independently at this boundary to 64 characters
(`scripts/manual_live_source_test.py::_bound_provenance_field`, mirroring
`collectors/adapters/tmd_cap.py::_bounded_field`'s existing bound) --
a second, independent bound in addition to the whole-report
`_sanitize_report` pass (300 characters) that already runs unconditionally
over the entire report. This matters specifically for the *rejected*
case: an overlong or malicious `candidate_filename` input has, by
definition, not passed `validate_candidate_filename()`'s own length check
by the time it reaches this object, so nothing upstream has bounded it
yet.

On the live path, the same values are also retained directly on
`CandidateValidationOutcome` (`collectors/adapters/tmd_cap.py`) as
`candidate_filename`, `evidence_run_id`, and `evidence_item_index` --
`candidate_filename` is new in this increment; the other two already
existed under WO-006. See
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 5 (amended) for the full retained-field list.

## 3. `workflow_run_id` and `workflow_sha`

Both are retained at the top level of every `candidate_cap_validation`
report -- `report["workflow_run_id"]`, `report["workflow_sha"]` -- read
once from the `GITHUB_RUN_ID` / `GITHUB_SHA` environment variables that
GitHub Actions populates for every workflow run. Outside a GitHub Actions
run (e.g. running the script or the test suite locally) both are `None`;
this code never fabricates a placeholder value for either. `workflow_sha`
already existed on `CollectionRun` (WO-002), `RssDiscoveryOutcome`
(WO-004), and `CandidateValidationOutcome` (WO-006); `workflow_run_id` is
new in this increment, added to `CandidateValidationOutcome` and to the
top-level report for both `dry_run` and `live` modes -- a dry run is
still a workflow run whose provenance a reviewer may want to trace back to
its exact Actions run.

## 4. Zero DNS / zero network in dry run: unchanged

`run_tmd_candidate_cap_validation()`'s `dry_run` branch still only calls
`build_candidate_reference()` and `derive_candidate_request()` --
pure functions with no `socket`/`ssl` import anywhere in
`collectors/adapters/tmd_candidate.py`
([`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 3). Adding `candidate_reference`, `workflow_run_id`, and
`workflow_sha` to the report changes nothing about that: every one of
those values is derived from data already in memory (the validated
reference, or the raw CLI arguments on rejection) or from the process
environment, never from a network call or a DNS lookup.
`tests/test_manual_workflow.py::test_run_tmd_candidate_cap_validation_dry_run_derives_url_with_zero_network`
(WO-006, unmodified) and this increment's own dry-run provenance tests
(Section 6 below) both continue to hold.

## 5. Fail-closed behavior for invalid provenance: unchanged, now covered live too

`build_candidate_reference()` remains the single choke point every
candidate reference passes through before any DNS or network activity, in
*both* modes (unchanged from WO-006,
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 3). An invalid or missing `candidate_filename`,
`evidence_run_id`, or `evidence_item_index` raises
`CandidateReferenceError` before `derive_candidate_request()`,
`resolve_pinned_address()`, or `get_pinned_candidate()` are ever reached.
WO-006 already had dry-run-mode test coverage of this boundary; this
increment adds explicit **live-mode** coverage proving a rejected
candidate reference never reaches the pinned transport there either
(`tests/test_manual_workflow.py::test_main_candidate_cap_validation_live_invalid_provenance_fails_before_dns_or_network`
and
`::test_main_candidate_cap_validation_live_missing_item_index_fails_before_dns_or_network`,
each with a `resolve_pinned` spy that would raise if DNS resolution were
ever attempted).

## 6. What this increment does **not** change

Everything in
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Sections 2-4 and 6-11 (candidate reference grammar and rejections; the
DNS-pinned transport; envelope classification and the strict CAP 1.2
parser, both fully unmodified; the error taxonomy; the manual workflow
operation) is unchanged. In particular, this increment does not touch:

- DNS/IP pinning, TLS/SNI/hostname verification, the one-request limit,
  or redirect/retry/fallback policy (`collectors/http_client.py`)
- the strict CAP 1.2 parser (`collectors/adapters/cap.py`)
- `TMD_CAP.enabled`, `machine_readable_status`, or `licence_status`
  (`config/sources.yaml`) -- all remain exactly as WO-006 left them
- `required_for_publication`, scheduling, staging, or dashboard
  publication
- `.github/workflows/manual-live-source-test.yml` -- no new input, no new
  step; `GITHUB_RUN_ID`/`GITHUB_SHA` are already implicitly available to
  every step's environment, so no workflow YAML change was needed to
  retain them

No live candidate fetch is performed or authorized by this increment.

## 7. Test coverage added (network-free)

All new tests run with zero DNS resolution and zero network I/O, using
the same `FakeHttpClient` / `fake_resolve_pinned` fixtures
(`tests/conftest.py`) already used throughout `tests/test_tmd_cap_adapter.py`
and `tests/test_manual_workflow.py`.

`tests/test_manual_workflow.py`:

- exact English and Thai `candidate_reference` provenance in dry-run
  reports (`test_run_tmd_candidate_cap_validation_dry_run_retains_exact_english_provenance`,
  `..._retains_exact_thai_provenance`)
- provenance retained on a rejected dry-run reference, with a null
  `request_url` (`..._retains_provenance_on_rejection`)
- a missing evidence run ID and an out-of-bound item index each fail
  before DNS/network in dry-run mode
  (`test_run_tmd_candidate_dry_run_missing_run_id_fails_before_dns_or_network`,
  `test_run_tmd_candidate_dry_run_invalid_item_index_fails_before_dns_or_network`)
- an overlong, invalid `candidate_filename` canary is bounded, never
  retained verbatim, in the dry-run report
  (`..._dry_run_bounds_an_overlong_filename_canary`)
- `workflow_run_id`/`workflow_sha` are retained when present and `None`
  outside CI, in dry-run mode (`..._retains_workflow_run_id_and_sha`,
  `..._workflow_ids_are_none_outside_ci`)
- the live report's `candidate_reference` matches the dry-run shape
  exactly, for both English and Thai
  (`test_main_candidate_cap_validation_live_report_retains_matching_candidate_reference`,
  `..._retains_exact_thai_provenance`)
- `workflow_run_id` is retained end-to-end in a live report, on both the
  top-level report and `candidate_validation`
  (`..._live_report_retains_workflow_run_id`)
- an invalid candidate reference and a missing item index each fail
  before DNS/network in **live** mode, proven with a `resolve_pinned` spy
  that raises if ever called
  (`..._live_invalid_provenance_fails_before_dns_or_network`,
  `..._live_missing_item_index_fails_before_dns_or_network`)
- the evidence-contract additions do not reopen any WO-006 leak: no raw
  XML, no Content-Type parameter canary, no credential-shaped text, in
  the final live `report.json`
  (`..._report_never_contains_raw_xml_or_content_type_params`)

`tests/test_tmd_cap_adapter.py`:

- `validate_candidate()` retains `candidate_filename` alongside
  `evidence_run_id`/`evidence_item_index`, and `workflow_run_id`
  alongside `workflow_sha`, when the environment provides them
  (`test_validate_candidate_retains_candidate_filename_and_workflow_run_id`)
- both are `None` outside a workflow run
  (`test_validate_candidate_workflow_run_id_is_none_outside_a_workflow_run`)
- a rejected candidate filename is still retained (bounded) on the
  outcome, and the pinned transport is never reached
  (`test_validate_candidate_retains_the_raw_rejected_filename_before_any_network`)
- an overlong rejected filename canary is bounded, never retained
  verbatim, on the outcome
  (`test_validate_candidate_bounds_an_overlong_rejected_filename_canary`)

The full existing suite -- including every GDACS, direct-CAP,
RSS-discovery, and WO-006 candidate-validation regression test -- remains
green and unmodified; this increment only adds tests and the two small,
additive code changes described above.

## 8. WO-007 Gate review requirements for this increment

Before a WO-007 Gate re-reviews the dry-run artifact this increment
produces, or considers any subsequent step toward a live candidate fetch,
it should confirm, in writing and before any further action:

- the sanitized dry-run `report.json` for a specific candidate now
  carries `candidate_reference.candidate_filename`,
  `candidate_reference.candidate_evidence_run_id`, and
  `candidate_reference.candidate_evidence_item_index` matching the exact
  values a reviewer submitted, resolving the Gate 1 CONDITIONAL finding
- `candidate_reference.request_url` on a successful dry run matches the
  URL `derive_candidate_request()` would produce from fixed policy plus
  those three fields, independently re-derivable by the reviewer
- `workflow_run_id`/`workflow_sha`, when present, identify the exact
  Actions run and commit that produced the artifact under review
- none of `docs/tmd_candidate_cap_validation.md` Sections 10-11's
  pre-existing criteria for a live run have been altered or weakened by
  this increment -- they have not; this increment changes only the
  reporting boundary described above
- this increment's own PR is reviewed and approved by a human (and, per
  standing project practice, by ChatGPT review) before merge; this
  document alone does not constitute that approval
