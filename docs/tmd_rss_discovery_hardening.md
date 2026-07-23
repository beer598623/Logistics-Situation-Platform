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

### Source-evidence table

Review round 1, finding 5: publication date and WO-003 event timestamps
alone do not separately establish each cited source's own retrieval date
and freshness. This table records both, per source/page, and states
`unknown` rather than guessing wherever a value was not independently
verified -- no page was re-fetched to produce this table; the WMO/TMD
reference-page rows record what was already cited in `config/sources.yaml`
prior to this increment.

| Source / page | Publication or last-updated date | Retrieval date | Evidence / event date or data period | Freshness limitation | Verified claim |
| --- | --- | --- | --- | --- | --- |
| TMD English CAP endpoint (`endpoint`) | unknown (no `Last-Modified` header returned) | 2026-07-23 | 2026-07-23 (WO-003 English live run) | No cadence established from one observation; may change without notice | Served RSS 2.x (`<rss>` root), HTTP 200, `Content-Type: text/xml`, no redirect, no ETag/Last-Modified |
| TMD Thai CAP endpoint (`alternate_endpoints[thai_language_cap]`) | unknown (no `Last-Modified` header returned) | 2026-07-23 | 2026-07-23 (WO-003 Thai live run) | No cadence established from one observation; may change without notice | Served RSS 2.x (`<rss>` root), HTTP 200, `Content-Type: text/xml`, no redirect, no ETag/Last-Modified |
| WMO Register of Alerting Authorities (TMD record, recId=164) | unknown (register page does not expose a per-record last-updated date) | 2026-07-23 | not applicable -- a static reference listing, not a time-bound event | Registration text alone does not establish current endpoint behavior; not re-verified live by this increment | Lists both TMD URLs above as "CAP Feed URL" |
| TMD RSS service page (`/en/service/rss`) | unknown (page does not expose a visible last-updated date) | 2026-07-23 | not applicable -- a static reference page, not a time-bound event | Page wording alone does not establish current endpoint behavior; not re-verified live by this increment | Labels the same feed(s) "CAP Warning" under "RSS format open data" |

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
   caller should do with the classification. `root_local_name` /
   `root_namespace` (and, in `rss_discovery.py`, the root tag echoed by
   `NotAnRssEnvelopeError`) are themselves attacker-controlled strings up
   to the response-size limit, so each is bounded to 200 characters at
   the point it is produced -- at the classifier/parser boundary itself,
   not left to the downstream report sanitizer (review round 2,
   finding 4).
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
- `<guid>` **only** when its own text is `http(s)://`-shaped -- the RSS
  `isPermaLink` attribute (which defaults to `"true"` when absent) is
  never consulted for this decision (review round 1, finding 3: trusting
  that default would let arbitrary non-URL guid text, including warning
  prose, be retained verbatim just because the publisher's unverified
  attribute claims it is a permalink)
- `<enclosure url=... type=...>` (URL string plus a bounded MIME-type
  string)
- `<pubDate>` **only** when it parses as a valid RFC 2822 timestamp,
  normalized to ISO-8601 UTC -- an unparseable value is dropped entirely,
  never retained as raw text
- each retained URL's `scheme`, `host` (`urlparse(...).hostname` --
  never the raw `netloc`, so embedded user-info is never exposed), and
  `path` (query strings and fragments are not separately retained as
  structured fields). Host comparison/storage considers only the
  hostname, deliberately ignoring any port (review round 1, finding 2):
  this is a discovery-only module that never connects to any candidate
  URL in this iteration, so a same-hostname/different-port candidate is
  grouped `same_host` here -- a future controlled fetch work order must
  treat host and port together as part of its own allowlist policy

Review round 2, finding 2 went further than the `host` field: the
retained **URL string itself** (`RssUrlCandidate.url`, and every
`link`/`guid`/`enclosure.url` value) also has any embedded user-info
stripped, via `collectors.url_redaction.redact_url_userinfo`, *before*
it is bounded or stored -- `https://user:pass@host/...` is never
retained verbatim anywhere, not merely re-derived correctly for the
`host` field. The manual-test script's report sanitizer
(`scripts/manual_live_source_test.py::_redact_string`) additionally
scrubs any `scheme://user@`/`scheme://user:pass@` pattern from every
string in the whole report tree as a second, independent line of
defense, mirroring the existing length-bounding layering below.

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

**Malformed `link`/`enclosure`/`guid` values are never retained verbatim,
even redacted (review round 3 finding 2; extended to `guid` in review
round 4).** `redact_url_userinfo` only strips user-info from a value
`urlsplit` recognizes as having an authority (`netloc`) component; a
malformed value that never parsed as having one in the first place --
for example a single-slash `https:/user:pass@host` form, or a value with
an invalid IPv6 authority like `https://user:pass@[bad` that makes
`urlsplit`/`urlparse` raise `ValueError` -- passes through that function
unchanged, so its own byte-length bounding was not sufficient to
guarantee no credential-shaped substring could reach a report. Starting
with a literal `http://`/`https://` prefix (the guid retention gate) is
*not* proof a value is well-formed enough to have a parsed authority
component -- round 3 fixed this for `link`/`enclosure`, but the `guid`
branch was still missing the same check, so a `guid` beginning with
`https://` but otherwise malformed could still leak verbatim. Any
`link`/`enclosure`/`guid` value `_classify_url` groups `malformed` is
therefore replaced entirely with a bounded, non-reversible marker
(`<malformed value: N chars, sha256=...>`) instead of the source text --
grouping and counts stay deterministic, but the value itself is never
re-exposed.

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
   - `envelope_classification` (present for `rss_discovery`, and, since
     review round 1 finding 4, also present as a structured field --
     not merely a diagnostic warning string -- for a `direct_cap`
     `MalformedCapAlertError`, per Section 3 item 4)
   - `forbidden_path_check` and `contract_state` (added identically to
     every report, success or failure, unchanged from before this
     increment)

   This never suppresses failure: the report's `errors` list is always
   non-empty on this path, so `main()`'s existing exit-code logic still
   returns `1`.

   **Review round 1, finding 4** additionally required `error_code` /
   `error_category` / `envelope_classification` to be exposed structurally
   even for failures an adapter already catches internally (a direct-CAP
   RSS rejection never raises past `TmdCapAdapter.collect()`; an RSS
   discovery DTD/XXE or Content-Type rejection never raises past
   `discover_rss()`). `collectors/error_classification.py` (new) is a
   single shared classifier both the adapter and this script call, so the
   same stable vocabulary applies whether a failure was caught inside the
   adapter or escaped to this script's own dispatch wrapper.
   `CollectionResult` and `RssDiscoveryOutcome` (both non-schema-bound;
   see Section 3) now carry `error_code` / `error_category` fields (and
   `CollectionResult` also carries `envelope_classification`), populated
   by the adapter itself, so `run_tmd_cap()` copies them straight into the
   report rather than only classifying an exception that already escaped.
   It also separates ordinary malformed (not well-formed) XML from a
   DTD/entity/oversize security rejection: `EnvelopeParseError` /
   `RssParseError` (new, category `parse`) versus `EnvelopeSecurityError`
   / `RssSecurityError` (unchanged, category `security`) --
   previously any parse failure during the hardened XML parse, including
   ordinary malformed XML with no security concern, was misclassified as
   a security rejection.
3. **Final error taxonomy (review round 2, finding 3).**
   `collectors/http_client.py`'s `ResponseTooLargeError` (raised by
   `ResilientHttpClient` itself for a real oversized HTTP response, before
   any XML parsing is even attempted) and the new `DiscoveryRedirectError`
   are both classified `security` by `collectors/error_classification.py`,
   the same category as the XML layer's own oversized-payload rejection --
   previously `ResponseTooLargeError` was unrecognized by the shared
   classifier and fell through to `unexpected`. The full stable vocabulary
   is now: `validation` (a `SystemExit`/bad-argument `ValueError`),
   `security` (`CapSecurityError`, `EnvelopeSecurityError`,
   `RssSecurityError`, `ResponseTooLargeError`, `DiscoveryRedirectError`),
   `parse` (`MalformedCapAlertError`, `NotAnRssEnvelopeError`,
   `EnvelopeParseError`, `RssParseError`), `content_type`
   (`UnexpectedContentTypeError`), and `unexpected` (anything else,
   including `UnexpectedNotModifiedError` below).
4. **Discovery fails closed on an uncacheable HTTP 304 (review round 3,
   finding 1).** `discover_rss()` never sends an `If-None-Match` or
   `If-Modified-Since` validator (it calls `get_no_redirect()` with no
   `etag`/`last_modified` argument), and discovery mode keeps no cached
   prior body. A 304 response in that context cannot establish the
   envelope kind, so it is no longer treated as a quiet success with
   `envelope_classification`/`discovery` left `null` and an empty
   `errors` list -- `discover_rss()` now raises `UnexpectedNotModifiedError`
   (new, in `collectors/adapters/tmd_cap.py`) for this case, which
   `main()`'s existing exit-code logic turns into a non-zero exit with a
   sanitized, structured report, exactly like any other adapter-handled
   failure.

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
- `TmdCapAdapter.discover_rss()` makes **exactly one physical HTTP
  request** per invocation, via `ResilientHttpClient.get_no_redirect()`
  (new). This method has no `attempts`/retry parameter at all -- there is
  no retry loop to configure -- and, more importantly, **never follows a
  redirect of any kind, including for the configured endpoint URL
  itself**: a 3xx response raises `DiscoveryRedirectError` via a custom
  `_NoRedirectHandler.redirect_request` before urllib would otherwise
  construct and send a second request to the redirect's `Location`
  target. `collect()`'s existing retry-and-redirect-following `get()` is
  completely unchanged and continues to serve `direct_cap` mode and
  GDACS exactly as before. No RSS item link, `guid`, or `enclosure` URL is
  ever fetched, followed, or resolved -- not same-host, not cross-host.
- Review round 1's initial fix (`get(..., attempts=1)`) was **not
  sufficient** and was superseded by `get_no_redirect()` above: capping
  the retry count does not stop `urlopen`'s default behavior of
  transparently following an HTTP redirect, which could otherwise still
  reach a second host (or, in principle, a private/internal address) even
  with `attempts=1` (review round 2, finding 1). Because discovery mode
  never follows a redirect at all, a successful discovery response was
  necessarily served directly by the requested endpoint's own host, so
  same-host/cross-host grouping uses that requested host, not
  `response.url` -- there is no separate "redirect-resolved origin" to
  consider in discovery mode.

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
