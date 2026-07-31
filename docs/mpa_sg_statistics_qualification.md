# MPA Singapore statistics (data.gov.sg) — qualification record

**Work Order:** WO-026, extended by WO-027 (Parts A-D) · **Status:** offline engineering
reconciled (Part A); bounded controlled live validation executed 2026-07-31 (Part B, §7);
`container_throughput` unit/scale remains **unverified and fail-closed** after reconciliation
against the live-validated values (Part C, §8) — this is a documented, deliberate outcome, not
an unfinished step. `MPA_SG_STATISTICS` remains `enabled: false`; enablement is a separate
human decision (Part D gate, §9).
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
live validation (§5). **Part A** (this offline reconciliation) landed first, in a session
whose environment denied outbound network access to `data.gov.sg` from the `Bash` tool and
whose `WebFetch` could not satisfy the validation's raw-bytes/header/hash retention
requirements even where reachable — §7 records that blocker as history. **A later session's
environment allowlisted `data.gov.sg`**, and Part B's exact two-request package was executed
from that environment on 2026-07-31; §7 now records the execution, and §8 records the Part C
unit reconciliation the live values made possible.

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
  status, at the time recording the environment blocker).

**WO-027 Parts B-D (this change):**
- `scripts/wo027_part_b_live_validation.py`: recreates and executes the exactly-two-request
  bounded live validation §5 authorizes, using `collectors.http_client.ResilientHttpClient
  .get_no_redirect` (single physical request, no redirect follow, no retry) for each request.
  Stops immediately and never attempts a second request if the first fails a transport bound,
  and attempts to distinguish a proxy/environment-layer failure from an actual data.gov.sg
  source response — narrowly: it recognizes only a rejected CONNECT tunnel, so an org-policy
  denial delivered as an ordinary HTTP error or an HTML block page would currently be
  misclassified as a source response. This is a diagnostic aid for human review, not something
  the script's stop-on-any-failure behavior depends on.
- `docs/evidence/wo027_part_b_live_validation.json`: the committed evidence artifact — exactly
  the fields §5 authorizes retaining, nothing else.
- This document: §5 updated to record execution; §6 items 2-4 resolved; §7 rewritten with the
  full execution record; §8 (new) records the Part C unit reconciliation and why
  `unit_verified` stays `False`; §9 (new) records the Part D per-field qualification status.
- `config/sources.yaml`: `MPA_SG_STATISTICS.machine_readable_status` raised to `verified`
  (the endpoint is now confirmed live-machine-readable — this does not enable the source, see
  `scripts/validate.py::source_contract_checks`, which only checks this field when `enabled`
  is `true`); `qualification.observed_freshness` and `qualification.data_period` populated
  from §7's evidence; `enablement.live_validation_status` set to `completed` with
  `live_validation_reference` citing the evidence artifact; `enablement.blockers` updated to
  drop the fully-resolved item (live validation performed), reword the personal-data item to
  attribute the confirmed-fields conclusion to the fields Part B actually requested rather than
  overclaiming a full-schema read, and keep the still-open ones (unit/scale; `gross_tonnage`
  capability assessment; rate-limit boundary only partially exercised; full-schema personal-data
  confirmation). `enabled: false` unchanged.
- `tests/test_data_gov_sg_adapter.py`: new tests exercising the live-validated response
  envelope shape end to end through the real parser (still refusing `container_throughput`
  via `UnverifiedUnitError`, still parsing `number_of_vessels` normally), plus tests for the
  live-validation script's failure-layer classification and the evidence artifact's
  retention-allowlist compliance.

## 5. Controlled live-validation package — authorized and executed (§7)

Unlike WO-026's draft, this package was **human-authorized exactly as specified** (Issue #56)
and has now been **executed exactly as specified**, in a later session whose environment
allowlisted `data.gov.sg`. This section is kept as the committed specification the execution
in §7 was run against — a reviewer can diff §7's actual requests against this section byte
for byte.

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

Most of WO-026's open questions were resolved by §1/§2; Part B's execution (§7) resolves all
but the first:

1. **Container-throughput unit/scale** (§3, §8) — **still open by deliberate fail-closed
   decision**, not for lack of evidence. §8 reconciles the live-validated values against the
   official MPA annual totals and finds a single physically plausible scale, but that is
   analytical inference corroborated by magnitude elimination, not an independently-read
   primary-source unit label (data.gov.sg's own field/dataset description was never fetched —
   doing so would have been a third request, outside the exactly-two-request authorization in
   §5). `unit_verified` stays `False`.
2. **Personal data / third-party rights / patents / trademarks / design rights** (§1 item 3) —
   **partially resolved; the full-schema confirmation still rests on §2's human primary-source
   reading, not on §7's live response.** Both Part B requests used a `fields=` projection
   (`month,container_throughput` and `month,number_of_vessels,gross_tonnage`) — a projected
   CKAN response can only echo the fields it was asked for and cannot enumerate a resource's
   *full* schema. This is independently visible in the evidence itself: every CKAN Datastore
   resource carries an internal `_id` field (present in `tests/fixtures/data_gov_sg/*.json`),
   yet no `_id` appears anywhere in §7's retained records, because it was never requested. So
   "no personal-data-capable field exists" is true of the fields actually requested and
   returned (`month`, `container_throughput`, `number_of_vessels`, `gross_tonnage` — plainly
   aggregate/numeric, none capable of carrying personal data), but §7's bounded, projected
   response cannot by itself prove the *entire* resource schema contains no such field. The
   original, broader confirmation this item describes still rests on §1 item 4's human reading
   of the primary MPA dataset pages (which describe these as aggregate monthly statistics
   datasets), not on Part B's response.
3. **Response envelope shape** — **resolved.** Both responses matched the standard CKAN
   Datastore Search envelope (`{"success": true, "result": {"resource_id", "records",
   "total", ...}}`) the parser already assumed; see §7.
4. **Observed freshness and rate-limit behaviour** — **partially resolved.** §7 records an
   observed ~2-month reporting lag (latest available month at retrieval time). Rate-limit
   behaviour remains only partially exercised: two sequential anonymous requests succeeded
   with no throttling response, well under the documented 4-calls/10s anonymous limit, but
   that is not an independent test of the limit itself.

## 7. Part B execution status: executed 2026-07-31

**Environment change.** The blocker originally recorded in this section (WO-027 Part A,
merged via PR #57) was environment-specific, not a scope or authorization gap: the session
that implemented Part A had `data.gov.sg` outbound access denied by its auto-mode permission
classifier, and `WebFetch` could not satisfy §5's raw-bytes/header/hash retention
requirements even where reachable. A later session's environment allowlists `data.gov.sg`.
Per the human's explicit instruction accompanying that change: *"Previous proxy-generated 403
responses were environment-policy failures, not data.gov.sg source responses"* — recorded here
verbatim because it is the human's characterization of the prior blocker, not this document's
own inference.

**Execution.** `scripts/wo027_part_b_live_validation.py` recreates the exact two-request
package from §5 (committed specification, not a prior-session `/tmp` script) and was run once,
end to end, on 2026-07-31T13:48:08Z. Both requests succeeded on the first attempt; per the
script's own no-retry design, a second attempt was never available regardless. Full retained
evidence (exactly the fields §5 authorizes retaining — nothing else) is committed at
`docs/evidence/wo027_part_b_live_validation.json`.

| | Request 1: container throughput | Request 2: vessel arrivals |
|---|---|---|
| `resource_id` | `d_da030f7028200d19ffcbe4a2d71af39c` (matched expected) | `d_d48c5a038904f6da3c603cd854b6c191` (matched expected) |
| HTTP status | 200 | 200 |
| Content-Type | `application/json` | `application/json` |
| Response bytes | 727 | 866 |
| SHA-256 | `053bbffb5d90dd5b224cd06ee412f31f6853663725546362c6f0bdae57cffd95` | `44853ed6f8938ef2b456587088603306797a6474290b31ff720a8a1f6fd25383` |
| `result.total` | 377 | 377 |
| Retained records | 5 (2026-01 through 2026-05) | 5 (2026-01 through 2026-05) |
| Last-Modified | `Fri, 31 Jul 2026 13:48:10 GMT` | `Fri, 31 Jul 2026 13:48:12 GMT` |
| ETag | not present | not present |
| Parser envelope check | `envelope_parsed_ok` | `envelope_parsed_ok` |

Retrieved `container_throughput` values (raw, as returned, most recent first): 3942.74
(2026-05), 3760.27 (2026-04), 3897.28 (2026-03), 3421.08 (2026-02), 3892.37 (2026-01).
Retrieved `number_of_vessels` / `gross_tonnage` pairs (most recent first): 11729 / 278622.13
(2026-05), 10873 / 261031.68 (2026-04), 11591 / 275916.11 (2026-03), 10886 / 257055.9
(2026-02), 12031 / 293346.24 (2026-01).

**Known limitation of this evidence artifact.** `returned_field_names` in the retained
evidence reflects the confirmed field *set* present in each retained record, not an
independently-observed wire order: the first run of the report-writing step serialized the
artifact with alphabetically-sorted JSON keys, losing the response's original field byte
order. This was a report-formatting defect, not a re-request — corrected by reprocessing the
already-retained records (no additional network call; the two-request bound was not exceeded)
and fixed in the script for future runs. It affects only the *order* claim; resource_id
matching, record content, byte counts, hashes, and HTTP status/header evidence were all
captured directly from the live response and are unaffected.

**Bounds compliance.** Exactly two requests, sequential, no retry; both completed well under
the 30-second timeout; both response bodies (727 and 866 bytes) are far under the 5,000,000-byte
cap; both required `application/json` and got it; neither response was a redirect; no API key,
account, or credential was sent or required; no schedule was created. Nothing outside the
retained-fields allowlist was written to the committed evidence artifact.

Parts C (§8) and D (§9) of WO-027 follow from this execution. `MPA_SG_STATISTICS` remains
`enabled: false`; no schedule; no live/current publication.

## 8. Unit reconciliation (Part C)

**Verified fact.** The five retrieved `container_throughput` values (§7) are: 3942.74,
3760.27, 3897.28, 3421.08, 3892.37 (2026-01 through 2026-05). Their sum is 18,913.74 and their
mean is 3,782.75, in whatever unit the raw field uses — this much is a direct reading of the
live response, not inference.

**Analytical inference.** The human decision's own anchors are MPA's official annual totals:
41.12 million TEU for 2024, 44.66 million TEU for 2025. Three candidate scales for the raw
field were tested against those anchors by simple order-of-magnitude elimination, extrapolating
the five observed months to a full year (mean × 12) as a rough annualization:

| Candidate scale | Extrapolated annual value | Plausible against 41.12M (2024) / 44.66M (2025) TEU? |
|---|---|---|
| raw = TEU (×1) | ≈45,393 TEU/year | No — roughly three orders of magnitude too small for the world's second-busiest container port |
| raw = thousand TEU (×1,000) | ≈45.39 million TEU/year | Yes — within ~2% of 2025's actual 44.66M and consistent with continued year-over-year growth from 2024's 41.12M |
| raw = million TEU (×1,000,000) | ≈45.39 billion TEU/year | No — roughly three orders of magnitude too large; exceeds plausible global container volumes, let alone one port |

This is genuine evidence-based reconciliation, not a guess: it uses the returned data and the
official MPA annual totals exactly as Part C instructs. But it has two logically separate
parts that carry different evidentiary weight:

1. **Elimination** rules out ×1 and ×1,000,000 outright — both land many orders of magnitude
   outside any plausible port-throughput figure. This part is close to conclusive on its own.
2. **The ~2% quantitative match** to 2025's actual annual figure is what actually discriminates
   ×1,000 as the *specific* right answer, not merely "not obviously wrong" — a materially
   different scale would not coincidentally land this close to two independent official annual
   totals across two different years.

Elimination alone would not rule out every plausible alternative: it tests only decade-spaced
scales (×1, ×1,000, ×1,000,000) and says nothing about a different *metric* definition at a
similar magnitude — for example, if the field counted "thousand containers (boxes)" rather
than "thousand TEU", a mixed 20/40-foot fleet could plausibly shift the true value by roughly
1.0-1.6× (a 40-foot box counts as 2 TEU but 1 container), which elimination by decade cannot
distinguish and the ~2% match does not itself rule out either, since a ~1.6x error would still
often land inside noisy year-over-year growth ranges depending on the true 2026 trend. This is
named here as a residual, not-fully-closed risk, not resolved by this reconciliation.

**Remaining uncertainty, and why `unit_verified` stays `False`.** This reconciliation has two
gaps the human decision's "must not be resolved by assumption" standard is read strictly
against:

1. It is **corroboration by elimination against a different source's aggregate**, not a
   **primary-source unit label** read directly from data.gov.sg's own field or dataset
   description. That page was never fetched — doing so was outside the exactly-two-request
   authorization in §5, and fetching it now would itself be a new, separately-authorizable
   live request, not part of this Work Order.
2. The extrapolation (5 observed months × 12/5) assumes no material seasonality across the
   other 7 months of the year; container throughput is not necessarily flat across a
   calendar year, and this arithmetic cannot rule that out.

Per the Part B-D acceptance checklist (independent architect review): *"If reconciliation is
inconclusive, `unit_verified` stays `False` — inconclusive is a valid, documented outcome, not
a reason to guess."* This reconciliation is strong corroborating evidence for a ×1,000
("thousand TEU") scale, but does not clear the bar of independently-confirmed primary-source
unit metadata that a fail-closed gate protecting against a ~1,000×-wrong published value
should require. **No code change accompanies this section: `DatastoreSeriesSpec.unit_verified`
keeps its `False` default, and no production spec sets it to `True` for `container_throughput`.
`UnverifiedUnitError` continues to refuse parsing this series unconditionally.** A future,
separately-authorized live read of data.gov.sg's own field/dataset unit documentation is the
concrete next step that could close this gap; it is out of scope for WO-027.

**`gross_tonnage`, assessed separately (per the human decision).** The raw `gross_tonnage` /
`number_of_vessels` quotient across the five observed months (§7) is consistently close to 24
(23.6-24.4). **This document deliberately does not interpret that number as "~24 GT per
vessel" or "~24,000 GT per vessel" or any other unit** — doing either would silently assume a
scale for `gross_tonnage` exactly the way §8 above refuses to do for `container_throughput`,
and `gross_tonnage`'s scale has had no reconciliation attempt of any kind in this Work Order.
The quotient is recorded only as a raw, unitless internal-consistency check (a materially
different quotient across months would have been a red flag; a stable one is not, on its own,
evidence of anything else) and does not by itself define a capability. Per the human decision,
`gross_tonnage` is **not** added as a parsed field or metric in this Work Order; it remains
present-but-unparsed, exactly as Part A left it, pending a separate assessment of what
capability it would serve and, if pursued, its own unit reconciliation.

**No operational inference drawn.** Neither the throughput values nor the vessel-arrival
counts are used here, or anywhere in this document, to infer congestion, waiting time, berth
occupancy, or any other operational condition — consistent with `operational_interpretation:
volume_only` (§2) and the same rule `PAT_STATISTICS` and `IMF_PORTWATCH` already carry.

## 9. Post-validation gate (Part D) — qualification status per field

| Aspect | Status |
|---|---|
| Endpoint | Confirmed live: `https://data.gov.sg/api/action/datastore_search` returned HTTP 200/JSON for both resources (§7). |
| Response schema/envelope | Confirmed live: matches the parser's assumed CKAN Datastore Search shape (§6 item 3, §7). |
| Fields | Confirmed live: `month`, `container_throughput` (resource 1); `month`, `number_of_vessels`, `gross_tonnage` (resource 2) — matching §2's human-confirmed names exactly. |
| Units | `number_of_vessels` and `month` carry no ambiguity. `container_throughput`'s unit remains **unverified and fail-closed** by deliberate decision (§8) — not published, not assigned a unit label. `gross_tonnage` is not wired into any capability (§8). |
| Freshness / data period | Observed: latest available month at 2026-07-31 retrieval was 2026-05 — a reporting lag of 61 days from that month's period end (2026-05-31) or 91 days from its period start (2026-05-01), depending which boundary is used; either reading is within the contract's `max_stale_minutes` (~73 days) figure, but that field is actually evaluated against collection-run/review recency (`collectors/source_health.py`), not directly against reporting lag — the two are related but not the same measurement. `result.total: 377` records exist per resource (full historical depth unread beyond the 5 most recent). The `Last-Modified` header values recorded in §7 are the response's own generation timestamps (seconds after the retrieval timestamp), not a freshness signal about the underlying data. |
| Personal data / third-party rights | Partially resolved: none of the fields actually requested/returned (`month`, `container_throughput`, `number_of_vessels`, `gross_tonnage`) is capable of carrying personal data or a third-party identifier, but §7's field-projected response cannot enumerate the full resource schema (it never requested, and so never saw, CKAN's own `_id` field, confirming the projection limits what a response can prove). The broader confirmation still rests on §1 item 4's human primary-source reading (§6 item 2). |
| Licence and attribution | Unchanged from §1 (WO-026 human-verified): Singapore Open Data Licence v1.0, attribution required, no endorsement implied. Not yet exercised — enablement is a separate decision. |
| Raw/derived publication boundary | Unchanged: `MPA_SG_STATISTICS.enabled: false`; no measurement or observation value from §7's evidence has been written to `dashboard/public/data/**`, `data/candidates/**`, `data/reviewed/**`, or `data/source_status/latest.json` — `current_port_series` and every other current-publication array remain empty. The registry's own qualification-level summary text (e.g. `observed_freshness`/`data_period` narrative strings, not measurement values) *is* mirrored into `dashboard/public/data/sources.json`, the same as every other source's qualification metadata already published there. The evidence artifact itself lives only at `docs/evidence/wo027_part_b_live_validation.json`, a qualification record, not a publication path. |
| Operational interpretation | Unchanged: `volume_only` for both series; no congestion/disruption inference drawn (§8). |
| Fail-closed behaviour | Confirmed intact end to end against the parser's own logic: `container_throughput` continues to be refused via `UnverifiedUnitError` even when fed a JSON envelope reconstructed from real, live-retrieved records (see `tests/test_data_gov_sg_adapter.py`) — the gate was never bypassed by having genuine live data available. This reconstructed test envelope carries only the fields §5 authorized retaining; §7's response was field-projected, so no test here proves the parser against the *actual, unprojected* raw response bytes (which were never retained per the retention allowlist) — a gap the parser's own field-presence checks already tolerate, since `result.fields`/`_id` are not read at all. |
| Test adequacy / regression protection | Extended: the retired-field-name and unit-refusal regression tests from Part A still pass; new tests added for the live-validation script's proxy/source failure-layer classification and the evidence artifact's retention-allowlist compliance (WO-027 Part D), including a top-level-keys check so an undeclared field added to the report in the future is caught, not only per-request fields. |

**Enablement, scheduling, and publication remain separate human decisions**, per Issue #56's
explicit instruction. This Work Order changes none of `MPA_SG_STATISTICS`'s `enabled`,
schedule, or publication state.
