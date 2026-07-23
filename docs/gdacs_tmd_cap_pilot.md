# GDACS + TMD CAP controlled integration pilot (Implementation v0.2)

Publication date of this research gate: **2026-07-23**.

This note documents the design of the first controlled source-integration
pilot for two candidate hazard/context sources: **GDACS** (Global Disaster
Alert and Coordination System) and **TMD CAP** (Thai Meteorological
Department warnings via a generic CAP 1.2 parser). It is fixture-first and
manually triggered only. Neither source is enabled for live collection;
neither publishes anything to the public dashboard; nothing here changes
impact-severity, Thailand-relevance, preparedness, or publishing-threshold
methodology. Methodology ownership, source-reuse decisions, and final
review remain with ChatGPT and the human approval gate (see
`methodology/source_policy.md`, `methodology/source_reuse_policy.md`).

## 1. Official source references

### GDACS

- API quick start: <https://gdacs.org/Documents/2025/GDACS_API_quickstart_v1.pdf>
- Swagger/OpenAPI: <https://www.gdacs.org/gdacsapi/swagger/index.html>
- Terms/disclaimer: <https://www.gdacs.org/About/termofuse.aspx>
- Static feed directory: <https://www.gdacs.org/contentdata/xml/>
- SEARCH endpoint (used by `collectors/adapters/gdacs.py`):
  `https://www.gdacs.org/gdacsapi/api/Events/geteventlist/SEARCH`

### TMD CAP

- WMO Register entry for Thailand/TMD: <https://alertingauthority.wmo.int/authorities.php?recId=164>
- English CAP endpoint (primary, `config/sources.yaml` `endpoint`):
  <https://www.tmd.go.th/en/api/xml/CAP>
- Thai CAP endpoint (alternate, `alternate_endpoints[0]`):
  <https://www.tmd.go.th/api/xml/CAP>
- TMD RSS/open-data page: <https://www.tmd.go.th/en/service/rss>
- TMD copyright notice (`terms_url`): <https://www.tmd.go.th/content/copyright>
- TMD website policy (`reuse_reference_urls`): <https://www.tmd.go.th/content/policy>
- CAP 1.2 standard: <https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html>

## 2. Verified facts vs. unresolved assumptions

### Verified (recorded as fact in `config/sources.yaml`)

- GDACS SEARCH responses are capped at 100 records per page; `pagenumber`
  and optionally `pagesize` page through more. `pagination.max_page_size`
  now records this cap explicitly, and `collectors/adapters/gdacs.py`
  enforces it in code (`build_search_request` raises if a caller requests
  more than the contract allows, and `GdacsSearchRequest.__post_init__`
  raises above the hardcoded `OFFICIAL_MAX_PAGE_SIZE = 100` regardless of
  contract).
- GDACS stable event identity requires **both** `eventtype` and `eventid`;
  `episodeid` is a separate episode/revision axis. `stable_id_field` is now
  the composite `["eventtype", "eventid"]`, and `revision_id_field` records
  `episodeid` separately.
- No official fixed GDACS polling cadence or rate-limit quota was found in
  the referenced documentation. `expected_cadence_minutes` is now `null`
  (previously incorrectly asserted as `6`) -- unknown is represented as
  unknown, not as a guessed number.
- TMD is WMO-registered as Thailand's alerting authority for Geo/Met
  hazards, with both a Thai and an English CAP feed URL. The English
  endpoint is `endpoint`; the Thai endpoint is recorded generically via
  `alternate_endpoints` (see Section 6) rather than hardcoded in an
  adapter.
- TMD's copyright notice permits non-commercial public republication with
  attribution; TMD's separate website policy requires written permission
  for deep-linking to internal pages. Both URLs are now recorded
  (`terms_url` + `reuse_reference_urls`), and `known_limitations` states
  plainly that these two statements are not fully aligned.

### Unresolved / still assumptions

- Whether TMD's CAP endpoints are reachable, return the declared content
  type, and are parseable as CAP 1.2 has **not** been verified live. This
  pilot ships with `machine_readable_status: unverified` for TMD_CAP and
  intentionally does not change it -- only the controlled manual workflow
  (Section 7), run and reviewed by a human, can produce that evidence, and
  even then a passing run does not itself flip the flag (Section 8).
  GDACS's `machine_readable_status: verified` and `licence_status:
  reviewed` were already true in the v0.1 registry and are unchanged by
  this pilot; this pilot did not re-verify them and makes no new claim
  about GDACS's live reachability either.
- Whether TMD's copyright/deep-link conflict resolves in favour of
  automated collection is a licensing question for human/ChatGPT review,
  not something this code resolves. `licence_status` stays
  `pending_review` and no code path in this pilot changes it.
- The exact GDACS GeoJSON property set is taken from the quick-start guide
  and Swagger definition, not from a captured live response (see Section
  4 on fixture provenance) -- some property names/types could differ in
  practice and would surface as parser warnings, not silent data loss,
  the first time a real response is reviewed under Section 7.

## 3. Event / episode / message identity rules

| Source | External ID | Revision/episode axis | Notes |
| --- | --- | --- | --- |
| GDACS | `f"{eventtype}:{eventid}"` (composite) | `episodeid` (via `source_revision`) | `stable_id_field` is `["eventtype", "eventid"]`; `eventid` alone is not stable across event types. |
| TMD CAP | CAP `<identifier>` | Not separately modeled; `msgType`/`references` preserved instead | CAP has no separate "revision" field distinct from `identifier`; an `Update`/`Cancel` message gets its *own* `identifier` and points back at the prior message via `<references>` (`sender,identifier,sent` triples). `source_revision` is left `null` for CAP records; associating an Update/Cancel with what it references is a later, human-reviewed step this pilot does not automate. |

Both adapters produce **staging records** only
(`schemas/staging_record.schema.json`, Section 6) -- neither assigns a
`canonical_event_id` or writes to `data/candidates/latest.json`. That
promotion step (`collectors/event_identity.resolve_event_identity`) is
unchanged by this pilot and remains a separate, later, human-reviewed
stage that would consume `candidate_identity_inputs` from a staging record.

## 4. Fixture provenance and attribution

No live TMD payload is committed, per the issue's explicit prohibition.

- **GDACS** (`tests/fixtures/gdacs/`): a **synthetic** GeoJSON fixture
  documenting the field structure described in the GDACS API quick-start
  guide and Swagger definition (Section 1) -- not copied from a live
  response. See `tests/fixtures/gdacs/README.md`.
- **CAP/TMD** (`tests/fixtures/cap/`): **synthetic** CAP 1.2 documents
  following the public OASIS CAP 1.2 element structure -- none are copied
  from any live TMD bulletin. See `tests/fixtures/cap/README.md` for the
  provenance of each individual fixture (bilingual alert, Update message,
  invalid-geometry case, missing-identifier case, DTD/XXE attack payload).

## 5. Hazard signal vs. operational logistics impact separation

Both adapters carry source-native classifications only under an explicit
`source_signal` object on the staging record -- never as a platform
severity/impact field:

- GDACS: `source_signal.source_alert_level` / `source_alert_score` (and,
  where present, `source_severity_value`/`source_severity_text` from
  `severitydata`, plus `geometry` and `source_version`). GDACS alert
  levels and impact estimates are model outputs -- a hazard/context
  signal -- and are never mapped to platform logistics severity anywhere
  in `collectors/adapters/gdacs.py`.
- CAP/TMD: `source_signal.severity`/`urgency`/`certainty` (the CAP enums),
  `cap_category`, `msgType`, `status`, `scope`, `references`, `language`.
  A TMD warning establishes official hazard/warning status only; nothing
  in `collectors/adapters/tmd_cap.py` or `collectors/adapters/cap.py`
  infers or emits an observed transport, facility, port, airport,
  warehouse, or trade disruption. Every staging record's
  `known_limitations` states this explicitly, and missing operational
  evidence stays absent (not a zero or "no impact" value) -- staging
  records simply carry no impact/severity field for a later, human-driven
  promotion step to populate as `insufficient_evidence` if nothing else is
  known.

## 6. Schema/contract extensions (Scope A)

`schemas/source_contract.schema.json` gained five **optional**,
additive fields so pre-existing contracts (GSCPI, TH_CUSTOMS, EPPO_FUEL)
remain valid unmodified (locked in by
`tests/test_source_contracts_v02.py::test_source_contract_schema_extension_is_additive_and_optional`):

1. `alternate_endpoints`: `[{label, url}]` -- generic language/mirror
   endpoints, used by TMD_CAP for the Thai CAP feed. Not hardcoded in any
   adapter; `collectors/adapters/tmd_cap.py::resolve_endpoint` reads it
   from the contract by label.
2. `reuse_reference_urls`: `[{label, url}]` -- additional licence/reuse
   reference documents beyond the single `terms_url`, used by TMD_CAP to
   record its website-policy URL and WMO registration alongside its
   copyright notice without conflating the three.
3. `stable_id_field` widened (backward-compatibly) to also accept an array
   of 2+ field names for composite identity (GDACS: `["eventtype",
   "eventid"]`); a bare string or `null` still validates unchanged.
4. `revision_id_field`: optional nullable string naming the
   episode/revision field (GDACS: `episodeid`).
5. `pagination.max_page_size`: optional integer documenting a hard
   per-page cap (GDACS: `100`), independent of the existing
   `pagination.page_size` default.

`schemas/staging_record.schema.json` is new (Scope E): it is the shared
output contract both adapters build through
`collectors/staging.py::build_staging_record`, carrying source ID,
retrieval time, content hash, parser version, source external ID,
`candidate_identity_inputs` (the controlled fields a later promotion step
would pass to `resolve_event_identity`), source publication/sent time,
source revision, `source_signal` (hazard/context only), field-mapping
notes, warnings, and known limitations. It intentionally has no impact,
severity-of-disruption, or `canonical_event_id` field.

## 7. Manual workflow instructions (Scope D)

`.github/workflows/manual-live-source-test.yml` is **`workflow_dispatch`
only** -- no `schedule`, no `push`/`pull_request` trigger, no automatic PR
creation. To run it:

1. Go to Actions -> "Manual live source test (GDACS / TMD CAP)" -> "Run
   workflow".
2. Choose `source` (`gdacs` or `tmd_cap`).
3. Leave `dry_run` at `true` to only validate request construction (no
   network call at all); set it to `false` to perform one real fetch
   through `collectors/http_client.ResilientHttpClient` (timeout, response
   size limit, retry policy all sourced from the contract) followed by
   parsing and normalization.
4. For `gdacs`, set `from_date`/`to_date` (bounded to a 31-day span by
   `scripts/manual_live_source_test.py::MAX_GDACS_DATE_SPAN_DAYS`) and
   optionally `event_types`/`alert_levels`.
5. For `tmd_cap`, set `language` to `primary` (English) or
   `thai_language_cap` (Thai), matching `alternate_endpoints`.

The workflow uploads exactly one artifact: a redacted JSON report
(`manual_live_test_output/report.json`) containing the collection-run
manifest, safe status fields (HTTP status, content hash, record counts),
parser warnings/errors, and a staging-record sample with long free-text
values truncated (`scripts/manual_live_source_test.py::_redact_staging_record`).
For TMD, the raw XML payload is never written to disk or uploaded --
adapters only ever return normalized staging records, which never carry
full `description`/`instruction` text in the first place. A `git status
--porcelain` check on `data/candidates`, `data/reviewed`,
`data/source_status`, and `dashboard/public/data` runs as a workflow step
and fails the job if any of those paths changed; the script itself also
snapshots and re-checks those same paths before writing its report.

## 8. Criteria for moving a source forward

**Unverified/disabled -> controlled staging** (this pilot's end state):

- A working adapter with fixture-backed tests (this PR).
- At least one successful controlled manual workflow run against the real
  endpoint, with a human reviewing the redacted report for content-type
  and parseability -- this is what would let `machine_readable_status`
  move to `verified` for TMD_CAP, via a **separate, reviewed pull
  request**, never automatically from a passing workflow run.
- For TMD_CAP specifically: a resolved position on the copyright/deep-link
  conflict (`licence_status` -> `reviewed`), decided by human/ChatGPT
  review, not by this code.

**Controlled staging -> production candidate collection** (out of scope
for this pilot):

- `enabled: true` in `config/sources.yaml`, gated by
  `scripts/validate.py::source_contract_checks` (requires
  `machine_readable_status: verified` and `licence_status: reviewed`
  before a source may be enabled).
- A scheduled or otherwise automated collection trigger -- explicitly not
  added in this pilot.
- A defined promotion path from staging record to
  `data/candidates/latest.json` via `resolve_event_identity`, with human
  review before anything reaches `data/reviewed/**` or
  `dashboard/public/data/**`.

## 9. Known limitations and follow-ups

- CAP `<addresses>`/`<incidents>` are parsed as plain whitespace-delimited
  tokens (`collectors/adapters/cap.py::_space_delimited`); CAP's optional
  quoted multi-word token syntax is not unescaped. Acceptable for a
  hazard-context signal; would need real quote-aware parsing if this field
  becomes load-bearing later.
- GDACS `eventtype` is mapped to the single taxonomy category
  `weather_natural_hazard` for every hazard type (earthquake, flood,
  cyclone, etc.) rather than a finer-grained mapping -- a future increment
  could split this out if the taxonomy grows a dedicated category per
  hazard type.
- TMD geography falls back to a country-level `"Thailand"` token when a
  CAP `<info>` block has no `<area>` with a `geocode`/`areaDesc`; this is
  coarser than a real sub-national geocode and is flagged with an explicit
  warning every time it triggers.
- Neither adapter's `collect()` method is exercised against a live
  response in CI (by design -- "No network calls in unit tests"); the
  first live validation only happens through the controlled manual
  workflow, reviewed by a human.
