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
manual workflow's wiring; see Section 6 below for the exact unchanged
list.

**This document and its code do not authorize a live candidate fetch, and
this increment does not re-run WO-007 Issue #13 Gate 1.** No live
candidate fetch was performed to write it; every example and test uses
synthetic fixtures only, exactly as under WO-006. A live fetch still
requires explicit human approval, distinct from and in addition to this
increment's own code-level review, per
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 10 (unchanged by this increment).

This document reflects the **round 2 review** revision of this increment
(see Sections 1a and 1b) -- the shape described below is what actually
ships, not an earlier draft a reviewer initially saw.

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
candidate reference was accepted or rejected -- now carries a
`candidate_reference` object (Section 2) and, when the environment
provides them, `workflow_run_id` alongside the existing `workflow_sha`
(Section 3).

### 1a. Round 1 review revision

The first draft of this increment (PR #14, initial head) retained a
rejected value's raw text verbatim in `candidate_reference` whenever it
was 64 characters or shorter, and silently dropped a non-numeric
`evidence_item_index` string to `null`. ChatGPT review round 1 on that PR
found both issues:

1. A short credential- or token-shaped string typed into `language`,
   `candidate_filename`, `candidate_evidence_run_id`, or a non-numeric
   `candidate_evidence_item_index` input would survive verbatim in a
   public report artifact if the candidate reference was rejected --
   contradicting both the "no credentials" guardrail and this document's
   own "sanitized" claim. The only prior protection (an overlong-value
   bound) only proved a *long* canary's full text was absent; it did not
   prove a *short* one was.
2. The live path additionally *lost* a non-integer `evidence_item_index`
   input to `null` on rejection, while the dry-run path still echoed it
   raw -- the two reject paths did not actually share the same evidence
   contract.

Both are fixed by replacing "retain the raw value, bounded" with "retain
a safe descriptor of the value until it is known to be safe" -- see
Section 2 below for the resulting shape. `GITHUB_RUN_ID`/`GITHUB_SHA` were
also hardened the same review round (Section 3) to be validated at origin
rather than copied blindly.

### 1b. Round 2 review revision

The round 1 fix still carved out one exception: an already-parsed
`evidence_item_index` **integer** (in-range or not) was retained as a
plain integer even when the candidate reference as a whole was rejected,
on the reasoning that an integer carries no free text. ChatGPT review
round 2 on PR #14 found this inconsistent with the stated policy itself
("every field holds the actual value after acceptance, or a descriptor
before/on rejection") -- an out-of-range or overlong numeric
`evidence_item_index` (e.g. `9999`, or a 20-digit token that parses as a
huge integer) is still unvalidated, operator-supplied input at the point
it is retained, and purely-numeric free text (a PIN, an OTP, a numeric
API key) is not inherently safer than alphanumeric text. The whole
premise of "not yet validated" is that `redact_candidate_provenance_value`
cannot itself tell a safe number from an unsafe one.

Fixed by removing the integer exception entirely:
`redact_candidate_provenance_value()` now descriptor-ifies every
non-`None` value, int or not, the same way. The only place a real integer
is ever retained is *after* `build_candidate_reference()` has accepted
the complete four-field reference -- exactly the same rule already
applied to the string fields, with no special case left for
`evidence_item_index`.

## 2. The `candidate_reference` object

Present at `report["candidate_reference"]` on every
`candidate_cap_validation` report, in both `dry_run` and `live` modes,
regardless of whether the candidate reference passed structural
validation:

| Field | Content |
| --- | --- |
| `language` | the language selector submitted |
| `candidate_filename` | the candidate filename submitted |
| `candidate_evidence_run_id` | the WO-005-style discovery workflow run ID submitted |
| `candidate_evidence_item_index` | the discovery item index submitted |
| `request_url` | the request URL derived from the four fields above by fixed policy, or `null` if the reference was rejected before a URL could be derived |

The top-level `report["language"]` field mirrors
`candidate_reference.language` exactly (same value, same accepted/rejected
rule below) -- it is not a second, independently-sourced copy.

**What each of the first four fields actually contains depends on whether
`build_candidate_reference()` accepted the submitted values as a whole**
(all four fields are validated together, atomically -- a failure on any
one means none of the other three are known-safe either, so all four get
the same treatment):

- **Accepted:** every field holds the actual validated value from the
  returned `CandidateReference` (`reference.language`,
  `reference.candidate_filename`, `reference.evidence_run_id` as a plain
  string; `reference.evidence_item_index` as a plain integer) -- never the
  raw argument. What is retained is exactly what was validated and (for
  `dry_run: false`) what was fetched.
- **Rejected:** every field holds a safe, non-reversible **descriptor**
  instead of any raw text --
  `collectors/adapters/tmd_cap.py::redact_candidate_provenance_value()`:

  ```json
  {"provided": true, "length": 19, "sha256": "<64 hex chars>"}
  ```

  or `null` if no value was supplied at all. `request_url` is `null`. This
  is deliberate and unconditional -- it applies even to a field whose
  submitted value would itself have been safe (e.g. `language: "primary"`
  when only `candidate_filename` was actually invalid), because
  `build_candidate_reference()` validates all four fields as one unit and
  only returns a validated reference if every one of them passes; there is
  no partial-success state to draw an accepted value from.

  `evidence_item_index` gets this exact same descriptor treatment as the
  three string fields, with **no exception for an already-parsed
  integer** -- an out-of-range numeric value (e.g. `9999`) or an
  overlong numeric canary is descriptor-ified exactly like a non-numeric
  string is (round 2 review, finding 1, Section 1b); a non-numeric
  string was already never dropped to `null` (round 1 review, finding 2,
  Section 1a).

  The whole point of the Gate 1 finding was that a reviewer needs to see
  *what was rejected and why*; the descriptor still serves that purpose --
  a reviewer can compare `length`/`sha256` across runs, or against a
  value they independently know, without the report ever carrying
  attacker- or operator-supplied free text it cannot itself validate.

On the live path, the same rule is applied on
`CandidateValidationOutcome` (`collectors/adapters/tmd_cap.py`) itself --
`language`, `candidate_filename`, and `evidence_run_id` are each typed
`str | dict[str, Any] | None`, and `evidence_item_index` is
`int | dict[str, Any] | None` -- and the script's `candidate_reference`
object for live mode is built directly from the outcome's fields, so dry
and live share one implementation of the accept/reject rule (via
`redact_candidate_provenance_value`, imported by
`scripts/manual_live_source_test.py` from
`collectors/adapters/tmd_cap.py`), not two independently-written copies
that could drift. `candidate_filename` is new on the outcome in this
increment; `evidence_run_id`/`evidence_item_index` already existed under
WO-006 but previously held the raw value unconditionally on rejection
(the exact issue Section 1a describes). See
[`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 5 (amended) for the full retained-field list.

## 3. `workflow_run_id` and `workflow_sha`

Both are retained at the top level of every `candidate_cap_validation`
report -- `report["workflow_run_id"]`, `report["workflow_sha"]` -- and on
`CandidateValidationOutcome` for the live path, read from the
`GITHUB_RUN_ID` / `GITHUB_SHA` environment variables that GitHub Actions
populates for every workflow run.

Both are **validated at origin** before being retained anywhere
(`collectors/adapters/tmd_cap.py::safe_workflow_run_id()` /
`safe_workflow_sha()`, round 1 review, finding 3) -- this code also runs
outside a real GitHub Actions job (locally, in tests, or on a
misconfigured self-hosted runner), so neither environment variable is
guaranteed to already be well-formed, and neither is copied blindly:

- `GITHUB_RUN_ID` must match GitHub's documented bounded-numeric run ID
  form (`^[0-9]{1,32}$`).
- `GITHUB_SHA` must match a 40-character hex commit SHA
  (`^[0-9a-fA-F]{40}$`).
- If the environment did not provide a value at all, the field is `None`.
- If the environment provided a value that does **not** match the
  expected form, the field is a short, static, human-authored marker
  string (`"<invalid: GITHUB_RUN_ID did not match the expected form>"` /
  the `GITHUB_SHA` equivalent) -- never the raw malformed value, and never
  collapsed to the same `None` a genuinely-absent value would produce, so
  the two cases stay distinguishable to a reviewer.

`workflow_sha` already existed on `CollectionRun` (WO-002),
`RssDiscoveryOutcome` (WO-004), and `CandidateValidationOutcome` (WO-006);
`workflow_run_id` is new in this increment. Both validators are scoped to
the `candidate_cap_validation` reporting paths this increment touches --
`collect()`/`discover_rss()`'s own pre-existing, unvalidated
`workflow_sha` reads are unchanged, out of this increment's scope.

## 4. Zero DNS / zero network in dry run: unchanged

`run_tmd_candidate_cap_validation()`'s `dry_run` branch still only calls
`build_candidate_reference()` and `derive_candidate_request()` --
pure functions with no `socket`/`ssl` import anywhere in
`collectors/adapters/tmd_candidate.py`
([`docs/tmd_candidate_cap_validation.md`](tmd_candidate_cap_validation.md)
Section 3). Adding `candidate_reference`, `workflow_run_id`, and
`workflow_sha` to the report changes nothing about that: every one of
those values is derived from data already in memory (the validated
reference, a `hashlib.sha256` digest of the raw CLI arguments on
rejection, or a regex match against them) or from the process
environment, never from a network call or a DNS lookup.
`tests/test_manual_workflow.py::test_run_tmd_candidate_cap_validation_dry_run_derives_url_with_zero_network`
(WO-006, unmodified) and this increment's own dry-run provenance tests
(Section 7 below) both continue to hold.

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
candidate reference never reaches the pinned transport there either, with
a `resolve_pinned` spy that would raise if DNS resolution were ever
attempted.

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

- exact English and Thai `candidate_reference` provenance in dry-run and
  live reports on acceptance (`..._retains_exact_english_provenance`,
  `..._retains_exact_thai_provenance`, and the live-mode equivalents)
- a rejected dry-run/live reference retains a safe descriptor -- never
  raw text -- for every field, with a null `request_url`
  (`..._retains_provenance_on_rejection`,
  `..._live_invalid_provenance_fails_before_dns_or_network`)
- a missing evidence run ID and an out-of-bound numeric item index each
  fail before DNS/network in dry-run mode, the latter now retaining a
  descriptor rather than the raw integer (round 2 review, finding 1)
  (`test_run_tmd_candidate_dry_run_missing_run_id_fails_before_dns_or_network`,
  `test_run_tmd_candidate_dry_run_invalid_item_index_fails_before_dns_or_network`)
- a non-numeric `evidence_item_index` string is represented as a
  descriptor, never lost to `null`, in both dry-run and live modes
  (`..._dry_run_invalid_item_index_string_is_not_lost`,
  `..._live_invalid_item_index_string_is_not_lost`)
- an out-of-range numeric item index, and a long purely-numeric item-index
  canary, never survive raw either, in both dry-run and live modes --
  the round 2 review, finding 1 regression tests
  (`..._dry_run_invalid_item_index_fails_before_dns_or_network`,
  `..._dry_run_long_numeric_item_index_canary_is_not_raw`,
  `..._live_out_of_range_item_index_is_not_raw`,
  `..._live_long_numeric_item_index_canary_is_not_raw`)
- an overlong, invalid `candidate_filename` canary never survives even as
  a truncated prefix (`..._dry_run_bounds_an_overlong_filename_canary`)
- a **short** credential/token-shaped canary in `language`,
  `candidate_filename`, or `candidate_evidence_run_id` never survives
  either -- the round 1 review, finding 1 regression test
  (`..._dry_run_short_credential_canary_in_every_field`)
- `workflow_run_id`/`workflow_sha` are retained when present and valid,
  `None` outside CI, and replaced with a static marker (never the raw
  value) when malformed, in both dry-run and live modes
  (`..._retains_workflow_run_id_and_sha`,
  `..._workflow_ids_are_none_outside_ci`,
  `..._workflow_ids_malformed_are_a_marker`,
  `..._live_report_retains_workflow_run_id`)
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
  alongside `workflow_sha`, when the environment provides valid values
  (`test_validate_candidate_retains_candidate_filename_and_workflow_run_id`)
- both are `None` outside a workflow run, and a marker (never the raw
  value) when malformed
  (`test_validate_candidate_workflow_run_id_is_none_outside_a_workflow_run`,
  `..._workflow_ids_malformed_are_a_marker_not_the_raw_value`)
- a rejected candidate filename is retained only as a safe descriptor,
  and the pinned transport is never reached
  (`test_validate_candidate_retains_a_safe_descriptor_for_a_rejected_filename`)
- a *short* credential-shaped canary in a rejected `candidate_filename` or
  `evidence_run_id` never survives verbatim
  (`test_validate_candidate_never_retains_a_short_credential_canary_from_a_rejected_field`)
- a non-integer `evidence_item_index` is represented as a descriptor,
  never lost to `None` (`test_validate_candidate_invalid_item_index_string_is_not_lost`)
- an out-of-range numeric `evidence_item_index`, and a long purely-numeric
  canary, are represented as a descriptor too -- never the raw integer --
  the round 2 review, finding 1 regression tests
  (`test_validate_candidate_rejected_numeric_item_index_is_not_raw`,
  `test_validate_candidate_long_numeric_item_index_canary_is_not_raw`)

The full existing suite -- including every GDACS, direct-CAP,
RSS-discovery, and WO-006 candidate-validation regression test -- remains
green and unmodified; this increment only adds tests and the additive
code changes described above.

## 8. WO-007 Gate review requirements for this increment

Before a WO-007 Gate re-reviews the dry-run artifact this increment
produces, or considers any subsequent step toward a live candidate fetch,
it should confirm, in writing and before any further action:

- the sanitized dry-run `report.json` for a specific candidate now
  carries `candidate_reference.candidate_filename`,
  `candidate_reference.candidate_evidence_run_id`, and
  `candidate_reference.candidate_evidence_item_index` matching the exact
  values a reviewer submitted (on acceptance), resolving the Gate 1
  CONDITIONAL finding
- `candidate_reference.request_url` on a successful dry run matches the
  URL `derive_candidate_request()` would produce from fixed policy plus
  those three fields, independently re-derivable by the reviewer
- a rejected candidate reference's `candidate_reference` object never
  carries raw, unvalidated text or a raw unvalidated number -- every
  field, including `candidate_evidence_item_index`, is either the
  `{"provided", "length", "sha256"}` descriptor shape or `null`; a plain
  integer appears there only once `build_candidate_reference()` has
  accepted the complete reference
- `workflow_run_id`/`workflow_sha`, when present and valid, identify the
  exact Actions run and commit that produced the artifact under review;
  a static invalid-form marker (rather than the value itself) means the
  environment provided something that did not match GitHub's own
  documented form for either
- none of `docs/tmd_candidate_cap_validation.md` Sections 10-11's
  pre-existing criteria for a live run have been altered or weakened by
  this increment -- they have not; this increment changes only the
  reporting boundary described above
- this increment's own PR is reviewed and approved by a human (and, per
  standing project practice, by ChatGPT) before merge; this document
  alone does not constitute that approval
