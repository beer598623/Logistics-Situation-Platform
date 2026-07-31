# MPA Singapore statistics (data.gov.sg) — qualification record

**Work Order:** WO-026, extended by WO-027 · **Status:** offline engineering reconciled;
controlled live validation authorized but not yet executed (environment network-access
blocker, see §7)
**Source ID:** `MPA_SG_STATISTICS` · **Registry:** `config/sources.yaml`

This document records what was actually verified about this candidate, as opposed to what is
merely assumed pending confirmation — the same discipline `docs/deployment_verification.md`
and `docs/source_qualification_report.md` apply elsewhere in this repository.

## 0. Why this document exists, and its central limitation

The Ocean Minimum Live Core research (recorded on Issue #54) found that `WebFetch` is blocked
for every external host in this environment: `data.go.th`, `gdcatalog.go.th`,
`portwatch.imf.org`, `newyorkfed.org`, and `data.gov.sg` itself all returned HTTP 403. WO-026's
parser and fixtures were therefore built against the *documented convention* data.gov.sg's own
developer pages name ("Datastore Search"), not a captured response — and, as WO-027 found, two
of WO-026's field-name assumptions were wrong.

**What WO-026 changed:** a human read the primary `data.gov.sg` licence pages directly and
recorded the findings in §1 below. That is the only reason this source carries
`licence_status: reviewed` rather than `pending_review` — the first source in this registry to
reach that status through direct primary-text verification rather than being pre-existing
(`GDACS`) or a bounded intake mechanism (`MANUAL_NOTICE_INTAKE`).

**What WO-027 changed:** a human independently reconciled the primary dataset pages a second
time — this time reading the actual field schemas, not just the licence terms — and corrected
two wrong field names (§2), confirmed the endpoint (§2), and authorized a bounded controlled
live validation (§5) that this environment cannot yet execute (§7) because outbound network
access to `data.gov.sg` from this session's `Bash` tool is denied by the auto-mode permission
classifier, and `WebFetch` cannot satisfy the validation's raw-bytes/header/hash retention
requirements even where it is reachable. §7 records this precisely.

Everything **not** explicitly attributed to a human primary-source reading in §1 or §2 remains
either an engineering assumption (flagged as such) or a still-open question (§6), not fact.

## 1. Human-verified licence findings (WO-026, Issue #54 human decision)

Recorded verbatim from the human decision, not re-derived:

1. The Singapore Open Data Licence v1.0 grants a worldwide, perpetual, royalty-free,
   non-exclusive right to access, download, copy, distribute, modify and adapt covered
   datasets and derived analyses, commercially or non-commercially.
2. Attribution is required. The implementation must acknowledge the dataset name, access
   date, MPA/data.gov.sg as the source, and the Singapore Open Data Licence v1.0. It must not
   imply government endorsement.
3. The licence does not grant rights over personal data, third-party rights, patents,
   trademarks or design rights. The selected MPA statistical datasets must be confirmed to
   contain no such fields before publication — **not yet done**, since no live response has
   been read (see §6, §7).
4. The official MPA dataset pages label the following as free forever for personal or
   commercial use under the Open Data Licence: Container Throughput (Monthly), Registered
   Vessels and Shipping Tonnage (Monthly), and monthly cargo-throughput total/breakdown
   datasets.
5. Official data.gov.sg developer documentation states that public read APIs (Datastore
   Search) can be accessed without an API key. Anonymous access has lower rate limits,
   including 4 Datastore Search calls per 10 seconds and 2 dataset-download calls per 10
   seconds. An API key is recommended for higher production limits but is not required for
   initial low-frequency access.

## 2. Confirmed dataset schema (WO-027, Issue #56 human decision)

Recorded verbatim from the human decision, not re-derived. This **corrects** WO-026's assumed
field names, which were wrong:

| Dataset | Resource ID | Confirmed fields | `port_transport_observation.metric` |
|---|---|---|---|
| Container Throughput, Monthly | `d_da030f7028200d19ffcbe4a2d71af39c` | `month`, `container_throughput` | `container_throughput` |
| Vessel Arrivals (>75 GT) Total, Monthly | `d_d48c5a038904f6da3c603cd854b6c191` | `month`, `number_of_vessels`, `gross_tonnage` | `vessel_calls` |

- **Endpoint confirmed:** `https://data.gov.sg/api/action/datastore_search`.
- **WO-026's two assumed value-field names were wrong** and have been fully retired from
  `collectors/adapters/data_gov_sg.py` and the test fixtures in favour of the confirmed names
  in the table above.
  `tests/test_data_gov_sg_adapter.py::test_retired_field_names_are_absent_from_the_adapter_module`
  and its sibling test grep the adapter module and the fixtures to make sure neither retired
  name reappears in code.
- **`gross_tonnage` is confirmed to exist** on the vessel-arrivals dataset but is **not**
  wired into any parsed capability. Per the human decision, it must be assessed separately
  and implemented only if it adds a clearly defined capability — it is not added merely
  because it is available. The test suite's `VESSEL_SPEC` (§3: no production spec is
  instantiated anywhere outside the tests) does not reference it;
  `tests/test_data_gov_sg_adapter.py::test_gross_tonnage_is_present_in_the_fixture_but_not_parsed`
  pins this.
- The dataset (resource) identifiers are unchanged from WO-026 and are now human-confirmed
  rather than search-snippet-derived.

**Capability mapping (unchanged from WO-026).** Neither dataset measures Thailand directly.
Per `docs/air_land_extension_points.md`'s and `docs/known_data_gaps.md`'s established
discipline of stating a mechanism rather than asserting relevance, both are registered with
`logistics_role: [external_driver_context]`, not `thailand_port_or_maritime_activity` — that
enum value is reserved for a genuine Thailand measurement. `docs/ocean_lane_selection.md`
already documents Singapore's role for `LANE-OCEAN-TH-ASEAN-SG`: "Singapore hub condition is a
real Thailand input... through the transshipment mechanism," and the pre-registered reference
node `NODE-SGSIN` (Port of Singapore, `thailand_relationship: transit_or_chokepoint`) already
exists for exactly this reason.

`operational_interpretation: volume_only` on both metrics (already a valid enum value — no
schema change was needed): a throughput or vessel-call count can never on its own establish
congestion, waiting time or berth delay, the same rule `PAT_STATISTICS` and `IMF_PORTWATCH`
already carry.

## 3. Open unit issue — container throughput (WO-027, must not be resolved by assumption)

The `container_throughput` field's raw numeric scale does not obviously match individual TEUs
against official MPA annual statements the human decision cited: **41.12 million TEUs for
2024, 44.66 million TEUs for 2025.** Neither figure has yet been reconciled against a real
returned value (§7 blocks that).

Per the human decision: **do not assign `unit: teu` to a published value, and do not apply a
×1,000 (or any other) scale conversion, until the scale is independently reconciled against
real evidence.** Missing or ambiguous unit metadata must fail publication rather than risk
producing a value that is roughly 1,000× wrong.

**This is enforced in code, not only in documentation.** No `collect()` or production
collector wiring exists yet for this source (§4) — the only place a `DatastoreSeriesSpec` is
currently instantiated at all is this repository's own test suite. What matters for safety is
what happens when one *is* eventually instantiated, including by a future author who has not
read this document: `collectors/adapters/data_gov_sg.py`'s `DatastoreSeriesSpec.unit_verified`
field defaults to **`False`** — fail-closed, per a finding from independent review that the
original WO-027 draft had this backwards (defaulting to `True`, which let an omitted argument
silently parse `container_throughput` with a guessed unit — exactly the outcome this section
exists to prevent). A spec must *affirmatively* set `unit_verified=True` before
`parse_datastore_search_response` will touch it; omitting the argument entirely, not just
setting it to `False`, refuses to parse. `parse_datastore_search_response` checks this flag
**before opening the payload at all** and raises `UnverifiedUnitError` (a
`DatastoreContractError` subclass) — a policy refusal, not a payload defect.
`tests/test_data_gov_sg_adapter.py::test_omitting_unit_verified_defaults_to_false_and_refuses_to_parse`
pins the fail-closed default directly; `::test_unit_unverified_series_refuses_to_parse` and
`::test_unit_unverified_refusal_happens_before_the_payload_is_even_opened` pin the refusal
mechanism itself (the latter passes deliberately-invalid bytes as the payload and confirms the
unit error surfaces first, proving the check runs before any parsing attempt).

Vessel arrivals (`number_of_vessels`) carries no equivalent ambiguity — it is a literal count,
not a scaled aggregate — and is not unit-blocked.

**Verified fact vs. analytical inference vs. remaining uncertainty**, kept separate per the
human decision:

- **Verified fact:** the field is named `container_throughput` (§2, human-confirmed). Its
  publisher-documented unit label (if any) has not yet been read by this repository.
- **Analytical inference (not yet made):** whether the raw number is individual TEUs,
  thousand-TEU units, or another scale. This requires the bounded returned values from §5/§7
  plus the two official annual figures above — Part C of WO-027, not performed until §7's
  blocker clears.
- **Remaining uncertainty:** everything about this field's scale, until Part C completes.

## 4. What this Work Order pairing implemented

**WO-026:**
- `config/sources.yaml`: the `MPA_SG_STATISTICS` contract, `licence_status: reviewed`,
  `enabled: false`.
- `collectors/adapters/data_gov_sg.py`: a fixture-first, bounded, fail-closed JSON parser for
  the standard CKAN Datastore Search response envelope
  (`{"success", "result": {"resource_id", "fields", "records", "total"}}`), producing
  `port_transport_observation` records via the shared `build_observation` helper. Deliberately
  **does not** include a `SourceAdapter.collect()` HTTP-fetching class: writing a
  request-construction method against a guessed URL would have misrepresented an assumption as
  engineering-complete. Still true after WO-027 — the endpoint is now confirmed (§2), but no
  live request has actually been made (§7), so `collect()` remains deferred to the live
  validation itself.
- `tests/fixtures/data_gov_sg/`: two fixtures, exercising both missing-value representations
  (`""` and JSON `null`).
- `docs/source_qualification_report.md`, `docs/source_enablement_decisions.md`,
  `docs/bundle1_architecture.md`: registry-source-count and candidate-register updates.

**WO-027:**
- Retired WO-026's two wrong value-field-name guesses; replaced with the confirmed
  `container_throughput`/`number_of_vessels` throughout the adapter and fixtures (§2).
- Added the `gross_tonnage` field to the vessel-arrivals fixture (matching the confirmed real
  shape) without wiring it into a parsed capability (§2).
- Added `DatastoreSeriesSpec.unit_verified` and the `UnverifiedUnitError` fail-closed gate
  (§3).
- Regression tests preventing the two retired field names from reappearing in the adapter
  module or the fixtures, plus tests for the new unit-refusal behaviour.
- This document: corrected §2's field names, added §3 (unit issue) and §7 (Part B execution
  status).

## 5. Controlled live-validation package — authorized, execution status in §7

Unlike WO-026's draft, this package is **human-authorized exactly as specified** (Issue #56).
It is not a draft awaiting approval; it awaits only the environment blocker in §7 clearing.

**Exactly two sequential GET requests, no more:**

```
GET https://data.gov.sg/api/action/datastore_search?resource_id=d_da030f7028200d19ffcbe4a2d71af39c&limit=5&sort=month%20desc&fields=month,container_throughput

GET https://data.gov.sg/api/action/datastore_search?resource_id=d_d48c5a038904f6da3c603cd854b6c191&limit=5&sort=month%20desc&fields=month,number_of_vessels,gross_tonnage
```

**Bounds:** exactly 2 requests; sequential, not parallel; no retry unless separately approved;
30-second timeout per request; maximum 5,000,000 response bytes; `application/json` only; no
redirects to another host; no API key or account; no recurring schedule.

**Retain in the controlled-validation artifact:** request URL without credentials, retrieval
timestamp, HTTP status, content type, response byte count and SHA-256, `resource_id`,
`result.total`, returned field names, exactly the five bounded returned records, ETag and
Last-Modified when present, parser outcome and structured error when applicable.

**Do not retain or publish:** unrelated response fields, account or request identifiers,
credentials, unrestricted raw dumps, Dashboard current data, scheduled output.

## 6. Explicit open questions

Most of WO-026's open questions are now resolved by §1/§2. What remains:

1. **Container-throughput unit/scale** (§3) — the central open question, blocking §5's
   execution outcome from being usable for anything beyond confirming the schema.
2. **Personal data / third-party rights / patents / trademarks / design rights** (§1 item 3).
   Not yet confirmed against a real response; requires §5's execution.
3. **Response envelope shape.** The parser assumes the standard CKAN Datastore Search envelope
   (`{"success", "result": {...}}`); this has not yet been directly observed for these two
   specific resources.
4. **Observed freshness and rate-limit behaviour.** `qualification.observed_freshness` stays
   `null` until a real response is read.

## 7. Part B execution status: blocked in this environment

The controlled live validation authorized in §5 has **not been executed**. Two independent
attempts to reach `data.gov.sg` from this session failed for different reasons, both recorded
here rather than silently retried around:

1. A direct `curl` request via the `Bash` tool was **denied by the session's auto-mode
   permission classifier** ("Blocked by classifier"), before any request left the container.
2. `WebFetch` (the tool `docs/mpa_sg_statistics_qualification.md` §0 already documented as
   403'd for every external host in the WO-026 research pass) would not satisfy §5's
   evidentiary requirements even if permitted: it summarizes fetched content through a
   secondary model rather than returning raw bytes, and cannot produce an exact HTTP status,
   content-type header, byte count, or SHA-256 of the actual response — all explicitly
   required by §5's artifact-retention list.

**This is a genuine environment/tooling blocker, not a scope or authorization gap.** The
human decision fully authorizes exactly the two requests in §5; nothing about §5 is
outstanding except a mechanism capable of executing it and preserving the required evidence.
Resolving it requires either explicit tool permission for this specific bounded action in this
session, or the requests being performed outside this session (by the human, or by a
tool/environment with outbound access) with the raw responses (including headers) then handed
back for processing into the validation artifact and Part C's unit reconciliation.

Parts C (unit reconciliation) and D (post-validation gate) of WO-027 cannot proceed until this
resolves. `MPA_SG_STATISTICS` remains `enabled: false`; no schedule; no live/current
publication.
