# TMD RSS envelope discovery and failure-path hardening (Implementation v0.2.1)

Publication date of this note: **2026-07-23**.

This is a narrowly-scoped follow-up to
[`docs/gdacs_tmd_cap_pilot.md`](gdacs_tmd_cap_pilot.md) (Implementation
v0.2), written for WO-004 (Issue #8) after WO-003's controlled live
validation (Issue #7) observed that both recorded TMD "CAP" endpoints
currently serve an RSS envelope rather than a direct CAP 1.2 alert. It
does **not** authorize source enablement, scheduling, production
candidate publication, dashboard publication, any reuse/licensing
conclusion, or treating RSS/CAP warning text as an observed logistics
impact. Nothing in this increment weakens the strict CAP 1.2 parser.

## 1. WO-003 run IDs and event evidence

- Event date: **2026-07-23**.
- English live run: <https://github.com/beer598623/Logistics-Situation-Platform/actions/runs/30005593850>
- Thai live run: <https://github.com/beer598623/Logistics-Situation-Platform/actions/runs/30005964446>

Both runs observed, independently, for their respective URL:

- HTTP `200`
- `Content-Type: text/xml`
- no redirect
- no `ETag` or `Last-Modified`
- XML root local name `rss`
- strict CAP parser error: expected
  `{urn:oasis:names:tc:emergency:cap:1.2}alert`, received `rss`
- zero staging records emitted
- the script-level forbidden-path check remained `clean`
- the workflow-level forbidden-path step was **skipped** because the
  preceding script step had already failed (the gap this increment's
  Scope F closes -- see Section 5)
- only the redacted `report.json` artifact was uploaded

## 2. Verified facts vs. conflicting official descriptions vs. inference

### Verified

- Both TMD URLs recorded in `config/sources.yaml` (`endpoint` and the
  `thai_language_cap` entry in `alternate_endpoints`) returned a
  well-formed RSS 2.x envelope (`<rss>` root, no namespace) on
  2026-07-23, not a CAP 1.2 `<alert>` document.
- The strict CAP 1.2 parser (`collectors/adapters/cap.py::parse_cap_alert`)
  correctly rejected both responses via its existing exact-root-tag check
  -- no code change was needed or made to produce this result, and none is
  made now to weaken it (Scope A).

### Conflicting official descriptions (recorded, not resolved)

- The WMO Register of Alerting Authorities still lists both TMD URLs as
  **CAP Feed URLs**: <https://alertingauthority.wmo.int/authorities.php?recId=164>
- TMD's own RSS service page presents **"CAP Warning"** under **"RSS
  format open data"**: <https://www.tmd.go.th/en/service/rss>

These two descriptions do not agree with each other, and neither is
overridden by the other here. `config/sources.yaml`'s `known_limitations`
for `TMD_CAP` records both verbatim, side by side, per the issue's
explicit instruction not to resolve this conflict by assumption.

### Inference this document does *not* make

- That the RSS envelope is a permanent replacement for a direct CAP 1.2
  alert at these URLs. One observation date does not establish cadence or
  permanence; the endpoint's behavior may change again.
- That RSS `<title>`/`<description>` warning prose (never retained by this
  increment in the first place -- see Section 4) constitutes an observed
  transport, facility, port, airport, warehouse, or trade disruption. A
  hazard/warning signal, direct-CAP or RSS-discovered, is not a logistics
  impact assessment; no logistics impact assessment is performed anywhere
  in this increment.

### Unresolved questions

- Whether the CAP-shaped resource WMO and TMD's own RSS page both
  reference is reachable at some *other*, not-yet-recorded URL (e.g. a
  same-host `<link>`/`<enclosure>` discoverable from the RSS envelope) is
  an open question this increment deliberately leaves open: discovery
  identifies such candidate URLs structurally (Section 4) but never
  fetches any of them (Section 6).
- Whether TMD's copyright/deep-link conflict (documented in
  `docs/gdacs_tmd_cap_pilot.md`) applies differently to an RSS envelope
  than to a direct CAP alert is a licensing question for human/ChatGPT
  review, not something this code resolves.

## 3. Architecture: four separate code paths

This increment adds two new, fully generic modules and one adapter method,
keeping four concerns in four separate places:

1. **Envelope classification** (`collectors/adapters/xml_envelope.py`,
   new) -- inspects a bounded XML payload's root element and returns
   *only* structural metadata (root local name, root namespace, a
   classified `envelope_kind` of `cap_alert` / `rss` / `atom` /
   `other_xml`, content length, and the content SHA-256 the HTTP layer
   already computed). Generic across any source; contains nothing
   TMD-specific. Never creates a staging record and never decides what a
   caller should do with the classification.
2. **RSS discovery** (`collectors/adapters/rss_discovery.py`, new) --
   discovery-only RSS 2.x parsing, generic across any RSS source. Raises
   rather than silently reinterpreting a non-`<rss>` root. Has no HTTP
   client at all (Section 6).
3. **CAP 1.2 parsing** (`collectors/adapters/cap.py`, unchanged) -- still
   requires the root element to be exactly
   `{urn:oasis:names:tc:emergency:cap:1.2}alert`; RSS, Atom, and any other
   envelope are still rejected as malformed, exactly as before this
   increment (Scope A). `tests/test_cap_parser.py` is unmodified and still
   green.
4. **TMD profile** (`collectors/adapters/tmd_cap.py`) -- the only place
   that knows about TMD's contract (endpoint, `alternate_endpoints`,
   content-type allowlist). It gained one new method, `discover_rss()`,
   which performs the single bounded fetch, calls the generic classifier,
   and -- only when the classified kind is `rss` -- calls the generic RSS
   discovery parser. `collect()` (the existing direct-CAP path) is
   unchanged except for one addition: when `parse_cap_alert` raises
   `MalformedCapAlertError`, `collect()` now also classifies the
   already-in-memory response body (no second request) and appends the
   classification as a diagnostic warning -- this is exactly what
   surfaces the "received rss" detail for `direct_cap` mode failures, the
   same failure WO-003 observed.

A feed wrapper and a CAP message are different contracts. Nothing in this
architecture ever lets an RSS envelope satisfy the CAP parser, and nothing
in the RSS discovery parser ever creates a candidate/staging record.

## 4. Structural metadata: retained vs. excluded

`collectors/adapters/rss_discovery.py::discover_rss_candidates` retains,
per RSS `<item>`, only:

- item index
- `<link>` (a URL string, bounded to 500 characters)
- `<guid>` **only** when it is `isPermaLink="true"` (the RSS default) or
  otherwise looks like an `http(s)://` URL
- `<enclosure url=... type=...>` (URL string plus a bounded MIME-type
  string)
- `<pubDate>` **only** when it parses as a valid RFC 2822 timestamp,
  normalized to ISO-8601 UTC -- an unparseable value is dropped entirely,
  never retained as raw text
- each retained URL's `scheme`, `host` (netloc), and `path` (query strings
  and fragments are not separately retained as structured fields)

It never retains, under any circumstance:

- full `<title>` or `<description>` text
- `<instruction>`-equivalent or any HTML content
- the raw XML payload
- any source-provided warning prose

Every retained URL string is still bounded (500 characters) and every
warning string is bounded (matching `collectors/adapters/cap.py`'s
120-character `_bounded` convention), and the manual workflow's existing
whole-report sanitizer (`scripts/manual_live_source_test.py::_sanitize_report`)
still applies as an unconditional second pass regardless.

The discovery result groups every retained URL into exactly one of:

- `same_host_urls` -- same host as the feed's own configured endpoint
- `cross_host_urls` -- a different host
- `non_http_values` -- a non-`http(s)` scheme (e.g. `mailto:`)
- `malformed_urls` -- did not parse as a URL with a scheme and host at all

plus a deduplicated, sorted list of `candidate_media_types` seen across
`<enclosure type="...">` values. Grouping is deterministic: the same input
always produces the same groups in the same order.

## 5. Failure-path hardening (Scope F)

Two independent fixes:

1. **Workflow YAML.** `.github/workflows/manual-live-source-test.yml`'s
   "Confirm public dashboard/current-event data are unchanged" step now
   runs with `if: always()` (previously it did not, which is exactly why
   WO-003's evidence shows it was skipped after the script step's expected
   failure). The artifact-upload step already had `if: always()` and is
   unchanged. Neither change weakens the gate: the job still fails if the
   script step failed, and the confirm-step's own `test -z` check still
   independently fails the job if a forbidden path was touched -- "the
   workflow must still fail when: the source script fails, or the
   forbidden-path check fails" holds both ways, including together.
2. **Script.** `scripts/manual_live_source_test.py::main()` now wraps the
   `run_gdacs`/`run_tmd_cap` dispatch in a `try/except (SystemExit,
   Exception)`. The forbidden-path snapshot is taken *before* this dispatch
   (unchanged), and the forbidden-path check still runs *after* it
   regardless of whether the `try` block raised. On any exception --
   whether an adapter's own already-handled parser/security failure (which
   returns a normal report with a non-empty `errors` list, as before) or an
   exception raised outside any adapter's try/except (e.g. `resolve_endpoint`
   rejecting a bad `--language`/`--tmd-operation` combination) -- a
   sanitized diagnostic report is still produced, containing:
   - `mode` / `operation`
   - `endpoint` (when known; `None` when resolution itself failed)
   - `error_code` (the exception's class name) and `error_category` (one
     of `validation`, `security`, `parse`, `content_type`, `unexpected`)
   - `envelope_classification` (present for `rss_discovery`, and appended
     as a diagnostic warning for a `direct_cap` `MalformedCapAlertError`,
     per Section 3 item 4)
   - `forbidden_path_check` and `contract_state` (added identically to
     every report, success or failure, unchanged from before this
     increment)

   This never suppresses failure: the report's `errors` list is always
   non-empty on this path, so `main()`'s existing exit-code logic still
   returns `1`.

## 6. SSRF and follow-link boundary

This increment is discovery only:

- No arbitrary URL input was added anywhere -- `rss_discovery` mode still
  only ever fetches the one endpoint already recorded in
  `config/sources.yaml` for `TMD_CAP` (via the existing `--language`
  selection between `endpoint` and `alternate_endpoints`), exactly like
  `direct_cap` mode.
- `collectors/adapters/rss_discovery.py` has no HTTP client, imports none,
  and cannot reach the network under any input it is given -- discovering
  a candidate URL is structurally incapable of fetching it. This is not
  merely a policy comment; there is no code path in that module capable of
  making a request.
- `TmdCapAdapter.discover_rss()` makes **exactly one** bounded GET request
  per invocation, the same request budget as `collect()`. No RSS item
  link, `guid`, or `enclosure` URL is ever fetched, followed, or resolved
  -- not same-host, not cross-host.
- No redirect discovered *within* an RSS item is followed; the one HTTP
  request already made by `ResilientHttpClient` still resolves at most the
  redirect chain for the single configured endpoint URL itself (unchanged,
  pre-existing behavior also used by `direct_cap` mode and GDACS).

**Any future controlled fetch of a discovered candidate URL requires a
separate work order** with, at minimum: explicit host allowlisting,
DNS/IP protections (rebinding and private-range checks), an explicit
redirect policy, a request-count bound, and human approval before
implementation -- none of which exist in this increment, deliberately.

## 7. Discovery-mode instructions

Via `.github/workflows/manual-live-source-test.yml`:

1. Go to Actions -> "Manual live source test (GDACS / TMD CAP)" -> "Run
   workflow".
2. `source: tmd_cap`.
3. `tmd_operation: rss_discovery` (default remains `direct_cap`, i.e. the
   existing strict CAP behavior is unaffected unless explicitly opted
   into discovery mode).
4. `language: primary` or `thai_language_cap`, exactly as for `direct_cap`.
5. Leave `dry_run: true` to see which endpoint and operation would be used
   with **zero network calls**; set `dry_run: false` to perform the one
   bounded GET and produce a redacted classification/discovery report.

The redacted report artifact (`manual_live_test_output/report.json`, the
same single artifact `direct_cap` mode uploads) gains, for
`rss_discovery`: `operation`, `fetch` (request/response URL, HTTP status,
content type, ETag/Last-Modified, content hash, `workflow_sha` --
deliberately not shaped like `schemas/collection_run.schema.json`, since
discovery never collects a candidate record; see
`collectors/adapters/tmd_cap.py::RssDiscoveryOutcome`'s docstring),
`envelope_classification`, and `discovery` (the grouped candidate lists
from Section 4). No new field in this report is ever the raw XML payload.

## 8. Criteria for a future controlled candidate-link fetch work order

Before any future work order may fetch a URL discovered by this increment,
it must explicitly define, in writing and before implementation:

- an exact, reviewed host allowlist (not "same host as the feed," which
  this increment already computes but does not treat as authorization to
  fetch)
- DNS resolution and private/loopback/link-local IP-range protections
  against the resolved address, not just the hostname string
- an explicit redirect policy (follow/deny, and how many hops)
- a hard bound on total requests per workflow run
- human approval of the specific work order before any code is written,
  matching the review model this repository has used for every prior
  source-integration increment

## 9. Explicit statement: no logistics impact assessment

Nothing in this increment -- the envelope classifier, the RSS discovery
parser, the `direct_cap` diagnostic enrichment, or the manual workflow's
new `rss_discovery` operation -- assesses, infers, or emits any
operational logistics impact (transport, facility, port, airport,
warehouse, or trade disruption) of any kind. A classified envelope kind
and a discovered candidate URL are both structural, hazard/context-signal
metadata only, exactly as `docs/gdacs_tmd_cap_pilot.md` Section 5 already
establishes for the existing GDACS and direct-CAP paths. `TMD_CAP.enabled`,
`machine_readable_status`, and `licence_status` are all unchanged by this
document and by this increment's code.
