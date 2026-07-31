# MPA Singapore statistics (data.gov.sg) — qualification record

**Work Order:** WO-026 · **Status:** offline engineering only — not enabled, not live-tested
**Source ID:** `MPA_SG_STATISTICS` · **Registry:** `config/sources.yaml`

This document records what was actually verified about this candidate, as opposed to what is
merely assumed pending confirmation — the same discipline `docs/deployment_verification.md`
and `docs/source_qualification_report.md` apply elsewhere in this repository.

## 0. Why this document exists, and its central limitation

The Ocean Minimum Live Core research (recorded on Issue #54) found that `WebFetch` is blocked
for every external host in this environment: `data.go.th`, `gdcatalog.go.th`,
`portwatch.imf.org`, `newyorkfed.org`, and `data.gov.sg` itself all returned HTTP 403. This
means **no primary source page for this candidate has been directly read by an automated
agent** — the research pass could only use search-engine snippets, and this Work Order's
parser and fixtures are built against the *documented convention* data.gov.sg's own developer
pages name ("Datastore Search"), not a captured response.

**What changes that limitation here:** a human read the primary `data.gov.sg` pages directly
and recorded the findings in §1 below. That is the only reason this source carries
`licence_status: reviewed` rather than `pending_review` — the first source in this registry to
reach that status through direct primary-text verification rather than being pre-existing
(`GDACS`) or a bounded intake mechanism (`MANUAL_NOTICE_INTAKE`).

Everything **not** explicitly attributed to that human verification in §1 remains an
engineering assumption, flagged as such, and is not license or fact until independently
confirmed.

## 1. Human-verified licence findings (Issue #54, human decision)

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
   been read (see §6).
4. The official MPA dataset pages label the following as free forever for personal or
   commercial use under the Open Data Licence: Container Throughput (Monthly), Registered
   Vessels and Shipping Tonnage (Monthly), and monthly cargo-throughput total/breakdown
   datasets.
5. Official data.gov.sg developer documentation states that public read APIs (Datastore
   Search) can be accessed without an API key. Anonymous access has lower rate limits,
   including 4 Datastore Search calls per 10 seconds and 2 dataset-download calls per 10
   seconds. An API key is recommended for higher production limits but is not required for
   initial low-frequency access.

## 2. Selected datasets and capability mapping

Two datasets, both monthly, both Singapore-wide aggregates (not per-terminal), registered
under one contract (matching `PAT_STATISTICS`'s one-contract/multiple-series pattern):

| Dataset | Resource ID | Metric | `port_transport_observation.metric` |
|---|---|---|---|
| Container Throughput, Monthly | `d_da030f7028200d19ffcbe4a2d71af39c` | Container volume moved | `container_throughput` |
| Vessel Arrivals (>75 GT) Total, Monthly | `d_d48c5a038904f6da3c603cd854b6c191` | Vessel call count | `vessel_calls` |

Both resource IDs come from the prior research pass's search-engine citations of the dataset
landing pages, **not** an independent fetch by this repository, and must be reconfirmed as
part of the controlled live validation in §5.

**Capability mapping.** Neither dataset measures Thailand directly. Per
`docs/air_land_extension_points.md`'s and `docs/known_data_gaps.md`'s established discipline
of stating a mechanism rather than asserting relevance, both are registered with
`logistics_role: [external_driver_context]`, not `thailand_port_or_maritime_activity` — that
enum value is reserved for a genuine Thailand measurement.
`docs/ocean_lane_selection.md` already documents Singapore's role for
`LANE-OCEAN-TH-ASEAN-SG`: "Singapore hub condition is a real Thailand input... through the
transshipment mechanism," and the pre-registered reference node `NODE-SGSIN` (Port of
Singapore, `thailand_relationship: transit_or_chokepoint`) already exists for exactly this
reason. This source, once enabled, would give that existing relationship a real number instead
of leaving it purely structural — it does not create a new capability commitment.

`operational_interpretation: volume_only` on both metrics (already a valid enum value —
no schema change was needed): a throughput or vessel-call count can never on its own establish
congestion, waiting time or berth delay, the same rule `PAT_STATISTICS` and `IMF_PORTWATCH`
already carry.

## 3. What this Work Order implemented

- `config/sources.yaml`: the `MPA_SG_STATISTICS` contract, `licence_status: reviewed`,
  `enabled: false`. Full `qualification`/`enablement` blocks record what is confirmed
  (licence position, §1) separately from what is not (endpoint, field names, personal-data
  absence, §6).
- `collectors/adapters/data_gov_sg.py`: a fixture-first, bounded, fail-closed JSON parser for
  the standard CKAN Datastore Search response envelope
  (`{"success", "result": {"resource_id", "fields", "records", "total"}}`), producing
  `port_transport_observation` records via the shared `build_observation` helper — the same
  provenance machinery every other adapter in this repository uses. Deliberately **does not**
  include a `SourceAdapter.collect()` HTTP-fetching class: the endpoint is unconfirmed, and
  writing a request-construction method against a guessed URL would misrepresent an assumption
  as engineering-complete. That piece is deferred to the live-validation Work Order once §5's
  package is approved and the endpoint is confirmed.
- `tests/fixtures/data_gov_sg/`: two fixtures, explicitly labelled unverified (see their own
  `README.md`), exercising both missing-value representations (`""` and JSON `null`) a real
  API might plausibly use.
- `tests/test_data_gov_sg_adapter.py`: 22 tests — schema validation against
  `port_transport_observation.schema.json`, missing-value handling, fail-closed behaviour
  (wrong resource ID, malformed month, non-numeric value, oversized payload, too many records,
  wrong content type, malformed JSON), and a no-network-at-import guarantee. The two
  highest-value checks (resource-ID mismatch rejection, missing-value-not-zero) were
  mutation-verified: each was broken on purpose, confirmed to fail the corresponding test, then
  restored.
- `docs/source_qualification_report.md`, `docs/source_enablement_decisions.md`,
  `docs/bundle1_architecture.md`: registry-source-count and candidate-register updates
  (`tests/test_documentation_registry_coverage.py` enforces the count stays in sync).

## 4. What this Work Order explicitly did not do

Per the human decision on Issue #54, none of the following happened, and none is authorized
by this document:

- No live network request to `data.gov.sg` or any MPA endpoint.
- No source enablement — `enabled: false` in `config/sources.yaml`.
- No collection schedule — `enablement.schedule_justified: false`,
  `collection_schedule: null`.
- No external account or API key created.
- No publication of MPA values as current Dashboard evidence — every record this Work Order's
  fixtures produce carries `evidence_origin: synthetic_test_fixture` and
  `dataset: technical_demo`, the same publication-boundary machinery
  (`analysis/provenance.py`) that keeps every other unqualified fixture out of the current
  view.

## 5. Draft controlled live-validation package (for the next human gate — not executed)

This is a **draft for review**, not an authorization to proceed. Per the human decision, this
must be presented and approved before any request is made.

| Item | Draft value |
|---|---|
| Exact dataset IDs | `d_da030f7028200d19ffcbe4a2d71af39c` (Container Throughput, Monthly), `d_d48c5a038904f6da3c603cd854b6c191` (Vessel Arrivals >75GT, Monthly) — **both require reconfirmation**, see §6 |
| Endpoint | Not confirmed. Best-effort candidate, following the standard CKAN Datastore Search action path: `GET https://data.gov.sg/api/action/datastore_search?resource_id=<id>` — or data.gov.sg's newer poll-download API if that has superseded it. **This is the first thing the live validation must confirm, not assume.** |
| Why each dataset is needed | Container throughput and vessel-call counts are the two metrics the capability mapping in §2 selected as the Ocean Minimum Live Core's regional-hub-activity role (R2 in the prior research pass) |
| Maximum request count | 2 (one GET per resource_id), single controlled run, matching the `manual-live-source-test` workflow's existing one-request-per-source discipline for `TMD_CAP`/`GDACS` |
| Anonymous rate-limit compliance | 2 requests, sequential, well under the documented 4-per-10-seconds Datastore Search limit (§1 item 5) |
| Timeout / max response size | 30 seconds / 5,000,000 bytes, matching `http.timeout_seconds` / `http.max_response_bytes` already set in the contract |
| Fields retained | `month` (or the confirmed real field name), the numeric value field, `resource_id` — only what §2's parser needs |
| Fields explicitly not retained | Any field not named above; no raw response body is committed to the repository, matching the existing GDACS/TMD_CAP artifact-redaction convention |
| Attribution text (draft, pending confirmation the wording matches the licence's requirement) | "Source: Maritime and Port Authority of Singapore, via data.gov.sg, under the Singapore Open Data Licence v1.0. Accessed \<date\>." |
| Raw / derived publication boundary | Not decided by this document. `publication_use: raw_values_permitted` is what the licence supports (§1); *whether* this platform actually publishes raw values, a derived direction only, or nothing until further review is a separate publication decision, distinct from what the licence allows |
| Artifact and log contents | Response status, headers (etag/last-modified if present), content hash, and the parsed record count — matching every other adapter's `CollectionRun` shape. No response body persisted beyond the bounded fixture-style excerpt existing conventions use |
| Cleanup / rollback plan | The run writes nothing to `dashboard/public` or `data/observations/` — `enabled: false` means no automated path reads its output. If the validation reveals the assumed field names or endpoint are wrong, the fix is confined to `collectors/adapters/data_gov_sg.py` and this document; nothing published is affected |

## 6. Explicit open questions (must be resolved before the live validation in §5 proceeds)

1. **Exact endpoint path.** Is it the CKAN `datastore_search` action, or has data.gov.sg's
   newer poll-download API superseded it for these datasets? Unconfirmed.
2. **Exact JSON field names.** `month` / `total_teus` / `total_vessels` in
   `collectors/adapters/data_gov_sg.py` and the test fixtures are this Work Order's
   best-effort assumption, not an observed fact.
3. **Dataset (resource) IDs.** Read from search-engine snippets of the landing pages, not
   fetched directly. Must be reconfirmed.
4. **Personal data / third-party rights / patents / trademarks / design rights.** The licence
   (§1 item 3) excludes these from its grant. An aggregate monthly statistics series is
   expected to carry none, but this is an expectation, not yet a confirmed fact about the real
   response.
5. **Whether an API key would ever become necessary.** Per the human decision, none is
   requested initially; the expected monthly cadence (2 requests total, ever, for validation;
   at most 2 requests per scheduled collection if ever enabled) sits far under the documented
   anonymous limit, so this is not expected to become a blocker, but is not proven until
   observed.

None of these blocks this Work Order's offline engineering. All of them block the next gate
(§5) and enablement.
