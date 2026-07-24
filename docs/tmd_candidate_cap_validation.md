# TMD controlled single-candidate CAP validation (Implementation v0.2.2)

Publication date of this note: **2026-07-24**.

This is a narrowly-scoped follow-up to
[`docs/tmd_rss_discovery_hardening.md`](tmd_rss_discovery_hardening.md)
(Implementation v0.2.1, WO-004) and WO-005 (Issue #10, pure evidence
gathering, no code change), written for WO-006 (Issue #11). It adds a
fixture-first, manually triggered validation path that can fetch and
structurally validate **exactly one** human-selected TMD candidate CAP
file discovered by WO-005, without accepting an arbitrary URL and without
weakening the strict CAP 1.2 parser.

**This document and its code do not authorize a live candidate fetch.**
No live candidate fetch was performed to write it; every example and test
in this increment uses synthetic fixtures only. A live fetch requires a
separate, future WO-007 plus explicit human approval. This increment also
does **not** authorize source enablement, scheduling, staging
publication, dashboard publication, any licensing conclusion, any
logistics-impact conclusion, or parsing RSS/CAP warning prose into
events.

> **Amended by WO-007A** (Issue #13 Gate 1 follow-up; see
> [`docs/tmd_candidate_evidence_contract.md`](tmd_candidate_evidence_contract.md)):
> `CandidateValidationOutcome` (Section 5 below) gained two fields,
> `candidate_filename` and `workflow_run_id`, alongside the fields already
> documented here, and both the dry-run and live `candidate_cap_validation`
> reports gained a `candidate_reference` object. On a *rejected* candidate
> reference, `language`/`candidate_filename`/`evidence_run_id`/
> `evidence_item_index` hold a safe, non-reversible descriptor
> (`{"provided", "length", "sha256"}`) rather than the raw submitted
> value -- with no exception for an already-parsed integer
> `evidence_item_index`, since purely-numeric text is not inherently safer
> than alphanumeric text. Nothing else in this document changed -- Sections
> 1-4 and 6-11 remain accurate as written for WO-006 (Implementation
> v0.2.2); this increment still does not authorize a live candidate fetch.

## 1. WO-005 evidence this increment builds on

WO-005 (Issue #10, closed) used the already-merged WO-004 discovery path
(`TmdCapAdapter.discover_rss()`) under four separate human-triggered
gates to observe -- not fetch -- candidate CAP filenames referenced by
both TMD RSS feeds. No code changed as part of WO-005; it is pure
operational evidence.

| Gate | Run | Artifact | Endpoint | HTTP status | Content-Type | Redirect | Response SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| English discovery | [`30028391246`](https://github.com/beer598623/Logistics-Situation-Platform/actions/runs/30028391246) | `8572242298` | `https://www.tmd.go.th/en/api/xml/CAP` | 200 | `text/xml` | none | `c145f05d3ee26496fa030fae7e5e8f4ee76ee96a2ac2286123d6a67bd4008121` |
| Thai discovery | [`30028626385`](https://github.com/beer598623/Logistics-Situation-Platform/actions/runs/30028626385) | `8572331123` | `https://www.tmd.go.th/api/xml/CAP` | 200 | `text/xml` | none | `ecbf2c716e5a4922f2a1931ac79025054148f1a0cb36ddf695627286353d8cf7` |

Both feeds independently listed 6 items / 6 same-host `link` candidates.
The newest filename was observed independently in **both** language
feeds: `CAPTMD20260723155032_2.xml`, at:

- English: `/uploads/CAP/en/CAPTMD20260723155032_2.xml`
- Thai: `/uploads/CAP/CAPTMD20260723155032_2.xml`

**These observations establish candidate discovery only** -- not
reachability, not CAP-1.2-ness, not cross-language semantic equivalence,
and not publication suitability. This increment's own strict validation
path (Sections 3-4 below) is what would establish reachability/CAP-1.2-ness
for one candidate, if and when a future WO-007 authorizes running it
live.

## 2. Architecture: six separate concerns

This increment adds two new modules and one adapter method, keeping the
following concerns in six separate places. Nothing here reuses or
weakens RSS discovery, direct-CAP collection, or GDACS collection.

1. **Candidate reference validation and URL derivation**
   (`collectors/adapters/tmd_candidate.py`, new, source-agnostic
   structural validators plus TMD-fixed policy constants). Accepts
   *only* a language selector, candidate filename, evidence workflow run
   ID, and evidence item index -- there is no field on
   `CandidateReference` capable of carrying a URL, host, port, query, or
   fragment, so those are structurally impossible to inject, not merely
   rejected by a runtime check. `derive_candidate_request()` builds the
   fetch target entirely from fixed constants
   (`CANDIDATE_SCHEME="https"`, `CANDIDATE_HOSTNAME="www.tmd.go.th"`,
   `CANDIDATE_PORT=443`, and one of two fixed path prefixes selected by
   the language enum) -- never from `config/sources.yaml`. See Section 3
   for the exact rejection list.
2. **Candidate-only pinned transport**
   (`collectors/http_client.py::ResilientHttpClient.get_pinned_candidate`,
   plus `resolve_pinned_address()`, new). A third, strictly more
   restrictive transport method alongside the existing `get()`
   (retrying, redirect-following; GDACS and direct-CAP) and
   `get_no_redirect()` (single request, no redirect; RSS discovery).
   Shares no connection-building code with either. See Section 4.
3. **Envelope classification** (`collectors/adapters/xml_envelope.py`,
   unchanged, WO-004) -- reused as-is; the fetched body must classify as
   `cap_alert` before the strict parser is ever called.
4. **CAP 1.2 parsing** (`collectors/adapters/cap.py::parse_cap_alert`,
   unchanged) -- the exact same function `collect()` already used,
   called with the exact same root-tag requirement
   (`{urn:oasis:names:tc:emergency:cap:1.2}alert`). No code in this file
   changed for WO-006.
5. **Minimized validation result**
   (`collectors/adapters/tmd_cap.py::CandidateValidationOutcome`, new)
   -- deliberately distinct from `CollectionResult`, `RssDiscoveryOutcome`,
   and every schema under `schemas/`. See Section 5 for the exact
   retained/excluded field list.
6. **TMD profile method**
   (`collectors/adapters/tmd_cap.py::TmdCapAdapter.validate_candidate`,
   new) -- the only place that wires the five pieces above together:
   validate the reference, derive the URL, resolve and pin DNS, make one
   pinned GET, classify the envelope, and -- only if `cap_alert` -- parse
   strictly and minimize the result. Never calls `normalize_tmd_alert`
   and never produces a staging record. `TmdCapAdapter.endpoint` is a
   lazy property, resolved only when `collect()`/`discover_rss()` read
   it -- constructing an adapter and calling `validate_candidate()`
   never touches `config/sources.yaml`'s `endpoint`/`alternate_endpoints`
   fields at all (ChatGPT review round 1, finding 6: the original
   implementation resolved the contract endpoint unconditionally at
   `__init__` time, even for a candidate-only adapter instance).

## 3. Candidate reference grammar and rejections (Scope A)

Inputs to `build_candidate_reference()`:

- `language`: exactly `"primary"` or `"thai_language_cap"` (the same
  enum `resolve_endpoint()` already uses for the contract-driven
  endpoints, though this module never reads the contract).
- `candidate_filename`: must fully match
  `^CAPTMD[0-9]{14}_[0-9]+\.xml$` (`CAPTMD` + 14 ASCII digits + `_` +
  one-or-more ASCII digits + `.xml`), ASCII-only, at most 100
  characters.
- `evidence_run_id`: a bounded, purely numeric string (a GitHub Actions
  run ID). Provenance only.
- `evidence_item_index`: an integer in `[0, rss_discovery.MAX_ITEMS)`
  (`[0, 50)`) -- the same bound the discovery parser itself enforces on
  how many RSS items it ever considers. Provenance only.

**Candidate evidence fields are provenance, not authorization.** Passing
a syntactically valid run ID/item index does not itself permit a fetch --
a live workflow gate still requires a human to have selected a filename
they actually observed in a reviewed WO-005 (or later) discovery
artifact; this module has no way to verify that claim itself.

Every one of the following is rejected **before any DNS or network
activity**, with a specific `CandidateReferenceError` message
(`tests/test_tmd_candidate.py` has one test per case):

- a full URL, or any string containing `://`, in place of a bare filename
- an embedded alternate host or port (structurally impossible in any
  case -- there is no host/port field on the input model at all)
- user-info (`@`)
- a query string (`?`) or fragment (`#`)
- a forward slash or backslash (path separator)
- a dot segment (`..`)
- percent-encoded characters (`%`) of any kind, including encoded
  separators or traversal sequences
- control characters (including NUL)
- any non-ASCII character, including Unicode digit/letter lookalikes
  (full-width digits, Cyrillic homoglyphs, etc.) -- checked both via an
  explicit `str.isascii()` guard and, redundantly, because the grammar
  regex itself only matches literal ASCII `[0-9]` character classes
- an empty, overlong (>100 char), or otherwise grammar-invalid filename
- an unknown language label
- an evidence run ID that is empty, non-numeric, URL-shaped, or overlong
- an evidence item index that is negative, `>= 50`, non-integer, or a
  `bool` (explicitly rejected even though `bool` is an `int` subclass in
  Python, so `True`/`False` can never silently pass as `1`/`0`)

## 4. Candidate-only pinned DNS/TLS transport (Scope B)

`ResilientHttpClient.get_pinned_candidate()` and its companion
`resolve_pinned_address()` implement, in order:

1. **Resolve only** the fixed hostname `www.tmd.go.th` for port `443`
   (`socket.getaddrinfo`, `IPPROTO_TCP`). A resolver failure or an empty
   answer raises `DnsResolutionError`.
2. **Reject the whole resolution** if it is empty, or if **any** returned
   address is not globally routable. "Not globally routable" is checked
   explicitly for private (RFC 1918), loopback, link-local, multicast,
   reserved, and unspecified addresses, plus Python's own `is_global`
   property as a catch-all for any other special-purpose range. A mixed
   answer (one legitimate address alongside one non-global one) is
   rejected in its entirety via `NonGlobalAddressError` -- fail closed,
   never silently filtered to "just use the good one."
3. **Select exactly one** surviving address deterministically: sorted
   IPv4 first (lowest numeric value); IPv6 is only considered at all if
   no IPv4 address was returned.
4. **Connect directly** to that one selected IP address
   (`socket.create_connection`, never re-resolving the hostname), then
   TLS-wrap that socket with `server_hostname=` the fixed hostname
   (`ssl.SSLContext.wrap_socket`) -- so certificate verification and SNI
   are still performed against `www.tmd.go.th`, never against the raw IP
   literal. The `Host` header sent over that connection is likewise the
   hostname, not the IP (`http.client`'s `skip_host` mechanism, driven by
   passing an explicit `Host` header). If context creation or the TLS
   handshake itself raises after `create_connection()` already
   succeeded, `_open_pinned_socket()` explicitly closes the connected
   raw socket before re-raising -- ownership only transfers to the
   caller once a fully wrapped socket is returned (ChatGPT review round
   3, finding 3: the original implementation left that raw socket
   unclosed on either failure, since the caller never received a
   reference to it to close). **The transport itself** -- not
   just the calling adapter -- reads the peer IP the socket actually
   connected to and compares it (via `ipaddress.ip_address` equality) to
   the DNS-selected IP **before constructing the HTTP request or sending
   any byte**: a mismatch closes the socket and raises
   `PinnedConnectionError` immediately, so a spoofed or unexpected peer
   is never sent the candidate request in the first place (ChatGPT
   review round 1, finding 2 -- the original implementation performed
   this check only after the full request/response cycle had already
   completed). This whole boundary -- reading `getpeername()`,
   canonicalizing both addresses via `ipaddress.ip_address`, and
   comparing -- is itself wrapped in a `try/finally` that closes the
   socket on *any* failure path (an `OSError` from `getpeername()`
   itself, an unparseable peer address, or an outright mismatch), and
   every one of those failure paths raises the same sanitized
   `PinnedConnectionError` rather than an unclassified exception
   (ChatGPT review round 2, finding 2 -- the original fix for round 1
   finding 2 still left `getpeername()` itself unguarded and could leak
   the socket on that specific failure).
5. **No environment proxy.** This path never touches `urllib.request`
   (the only thing in `collectors/http_client.py` that consults
   `HTTP_PROXY`/`HTTPS_PROXY`); it is a raw socket plus `http.client`.
6. **Exactly one physical GET.** No retry parameter exists on this
   method at all (mirroring `get_no_redirect()`'s precedent). No
   fallback to a second address, no second request of any kind.
7. **Every 3xx is rejected** before any `Location` could be followed
   (`PinnedRedirectError`) -- except HTTP 304 (see next item), which is
   technically in the 3xx range but is not a redirect (it carries no
   `Location`).
8. **HTTP 304 is treated as a structured failure** by the *adapter*
   (`validate_candidate`, not the transport itself): this request never
   sends `If-None-Match`/`If-Modified-Since`, and candidate validation
   keeps no cached prior body, so an uncacheable 304 cannot establish
   anything and raises `UnexpectedNotModifiedError` -- reusing the exact
   same class and rationale already established for `discover_rss()` in
   WO-004.
9. **Response metadata and the streamed body are both bounded** before
   parsing. All line-oriented response *metadata* -- the status line,
   headers, and, for a chunked response, every subsequent chunk-size/
   framing line and every trailer line -- is capped at 64 KiB
   (`_MAX_PINNED_HEADER_BYTES`), enforced *while it is being streamed* --
   `_HeaderCappedSocket` wraps the connected socket so every read file
   `http.client` obtains from it (via `makefile("rb")`) is a
   `_BoundedHeaderFile`, which counts every byte `http.client` reads via
   `readline()` -- for the *entire lifetime of the response*, not only
   during initial header parsing -- and raises `ResponseTooLargeError`
   the moment the aggregate exceeds the cap. This deliberately never
   stops counting after the first blank line: `http.client` reuses the
   same file object, via the same `readline()` mechanism, for a chunked
   response's chunk-size/framing lines and its trailer section after the
   terminal `0\r\n` chunk (`_read_next_chunk_size`,
   `_read_and_discard_trailer`) -- counting only the initial block would
   let a response with a tiny CAP body carry an arbitrarily large
   aggregate trailer block through completely uncounted (ChatGPT review
   round 3, finding 1). Actual chunk/body *content* is read exclusively
   via `read()`/`readinto()`, never via `readline()`, so this
   metadata-only cap never constrains the body itself, which is bounded
   completely separately and explicitly, at
   `TmdCapAdapter.CANDIDATE_MAX_RESPONSE_BYTES` (2,000,000 bytes -- a
   dedicated, hardcoded bound for one candidate alert file, deliberately
   independent of the TMD source contract's much larger
   `http.max_response_bytes`, which governs the whole feed). Exceeding
   either raises `ResponseTooLargeError` before the body is handed to any
   XML parser. (Round 2, finding 4, first fixed the *timing* of this
   check -- moving it from after `http.client` had already parsed a
   complete block to during streaming -- but originally still stopped
   counting after the initial header block; round 3 extended it to cover
   the whole response's lifetime.)
10. **Post-handshake socket/protocol failures are sanitized, not leaked.**
   A TLS read/write failure after the handshake (`ssl.SSLError`) raises
   `PinnedTlsError`; any other connection-level failure while writing the
   request or reading the response/headers (`OSError`, including
   `TimeoutError`) raises `PinnedConnectionError`; an `http.client`
   protocol-level failure also raises `PinnedConnectionError`. None of
   these propagate the platform's raw exception text -- each is a short,
   static, human-authored message (ChatGPT review round 1, finding 5;
   the original implementation only wrapped `http.client.HTTPException`
   here, letting a post-handshake `OSError`/`ssl.SSLError` escape
   unclassified as `unexpected`).

GDACS, direct-CAP (`get()`), and RSS-discovery (`get_no_redirect()`)
transports are unaffected -- this method shares no connection-building
code with either of them.

## 5. Strict CAP validation and the minimized result (Scopes C/D)

`TmdCapAdapter.validate_candidate()` runs, in order, once a pinned
response is in memory:

1. HTTP status must be `200` (304 is checked and rejected first, as a
   distinct structured failure per Section 4 item 8; any other non-200
   status raises `CandidateUnexpectedStatusError`).
2. `Content-Type` must be **present** and in the existing narrow
   allowlist (`TMD_CAP_ALLOWED_CONTENT_TYPES` -- `application/cap+xml`,
   `application/xml`, `text/xml`; unchanged, reused from WO-002).
   Candidate validation is stricter here than `collect()`/
   `discover_rss()`: those two treat a *missing* Content-Type header as
   a non-fatal warning (some sources omit it), but a candidate response
   with no Content-Type at all raises `UnexpectedContentTypeError` and
   aborts before any XML parsing (ChatGPT review round 1, finding 3).
   A *present-but-unexpected* type still raises the same exception, but
   with the raw header value bounded to 64 characters before it ever
   enters the exception message (finding 7) -- the shared
   `validate_content_type()`'s own message embeds the complete raw
   value, so candidate validation re-raises with a bounded one instead.
   A *present-and-allowlisted* type retains **only the normalized base
   media type** (e.g. `application/xml`) -- never the raw parameter
   section at all, which is untrusted, source-controlled free text with
   no structural meaning to candidate validation.
   `validate_content_type()` only checks the base media type and
   returns the full header verbatim, so an allowlisted type with an
   arbitrary parameter (e.g. `application/xml; x=<canary>`) would
   otherwise reach `CandidateValidationOutcome.content_type` intact.
   Bounding that value to 64 characters (round 2, finding 1) was not
   sufficient on its own: a short canary placed at the very start of the
   parameter section would still have survived within the first 64
   characters of the bounded raw value. The same normalization is
   applied to the *rejected*-type diagnostic message too (a
   present-but-disallowed type, e.g. `text/html; x=<canary>`, is
   reported by its normalized rejected base type only, e.g.
   `'text/html'`, never the raw parameter section) (ChatGPT review round
   2, finding 1; round 3, finding 2).
3. The response-size cap (Section 4 item 9) was already enforced by the
   transport before this point.
4. `classify_envelope()` (WO-004, unchanged) runs on the in-memory body.
5. The classified `envelope_kind` must be exactly `cap_alert` --
   anything else (`rss`, `atom`, `other_xml`) raises
   `CandidateEnvelopeMismatchError`, never falls through to the CAP
   parser.
6. `parse_cap_alert()` (`collectors/adapters/cap.py`, **unmodified**)
   validates the exact CAP 1.2 root
   (`{urn:oasis:names:tc:emergency:cap:1.2}alert`) exactly as it always
   has for `collect()`. `tests/test_cap_parser.py` is untouched and
   still green.

The fetched body is held in memory only for the duration of this call
and discarded afterward -- it is never written to disk, never logged,
and never becomes a staging record or candidate event.

`CandidateValidationOutcome` retains **only**:

- `operation`, `mode`, `language` -- the actual validated value once
  `build_candidate_reference` accepts it, else a safe, non-reversible
  descriptor (WO-007A; see
  [`docs/tmd_candidate_evidence_contract.md`](tmd_candidate_evidence_contract.md)
  Section 2) -- never the raw caller-supplied text once a value is known
  to have failed, or not yet passed, validation
- `candidate_filename` (WO-007A, same accepted-value-or-descriptor rule)
  -- so a Gate reviewer can see exactly which candidate a report
  describes, including one rejected before any DNS or network activity,
  without the report ever carrying unvalidated free text
- `evidence_run_id` (same rule), `evidence_item_index` (same rule with no
  exception for an already-parsed integer -- an out-of-range or overlong
  numeric value is descriptor-ified exactly like a non-numeric one;
  WO-007A round 2 review, finding 1)
- `workflow_run_id` (WO-007A, `GITHUB_RUN_ID`), `workflow_sha`
  (`GITHUB_SHA`) -- each `None` if the environment provided no value, a
  static invalid-form marker if it provided one that did not match
  GitHub's documented form for either (WO-007A, validated at origin),
  or the actual value otherwise
- `request_url` (derived, then redacted defensively even though it can
  never carry user-info by construction), `selected_ip`,
  `address_family`, `connected_ip_matches_selected`
- `http_status`, `content_type`, `etag`, `last_modified` (the latter two
  bounded to 64 characters at extraction, independent of the final
  report sanitizer -- ChatGPT review round 1, finding 7), `content_length`,
  `content_sha256`
- `envelope_classification` (WO-004's existing structural dict)
- `cap_identifier_length` and `cap_identifier_sha256` -- **the raw CAP
  `<identifier>` is never retained**, only its length and a SHA-256
  digest, mirroring `rss_discovery.py`'s existing `_malformed_marker`
  non-reversible-marker pattern
- `cap_sent`, `cap_status`, `cap_msg_type`, `cap_scope` (each bounded to
  64 characters independently, at extraction time)
- `cap_info_count`, `cap_languages` (bounded, deduplicated, sorted),
  `cap_reference_count`, `cap_area_count`
- `cap_parser_warning_count` -- **a count only**, never
  `parse_cap_alert()`'s own warning text. That text is itself prefixed
  with the raw CAP `<identifier>` and can embed bounded-but-real invalid
  timestamp/polygon/circle/altitude/ceiling source values (`cap.py`'s
  own `_bounded()` helper only truncates length; it does not remove or
  hash the value). Retaining those strings verbatim would contradict
  both the identifier-as-length/hash-only promise and the
  no-geometry/timestamp-source-value exclusion below, so only the count
  is kept (ChatGPT review round 1, finding 4).
- `warnings`, `errors`, `error_code`, `error_category` -- populated only
  by this method's own static, human-authored messages (transport/
  reference/envelope/status/content-type failures), never by
  `parse_cap_alert()`'s warning text

It **never** retains: raw XML; `title`/`headline`/`event`/`description`/
`instruction`/`note`/`audience` prose; `web`, `contact`, `addresses`,
area descriptions; polygon, circle, altitude, ceiling, or geocode
values; source-provided warning text or HTML; credentials, cookies,
authorization headers, TLS secrets, or full exception payloads; a
staging record, canonical event ID, platform severity, or
logistics-impact assessment. `tests/test_manual_workflow.py` and
`tests/test_tmd_cap_adapter.py` each assert every canary free-text field
in the synthetic bilingual fixture (`headline`, `description`,
`instruction`, `web`, `contact`, `areaDesc`, polygon coordinates, the
geocode value) never appears anywhere in the outcome or the final
sanitized `report.json`; a parallel set of tests does the same for the
synthetic `invalid_geometry_and_timestamps.xml` fixture's identifier and
invalid timestamp/polygon/circle source values, which reach
`validate_candidate()` only via `parse_cap_alert()`'s warning strings.

Every untrusted string is bounded twice: once at the point it is
extracted in `validate_candidate()` (`_bounded_field`, 64 characters),
and again, unconditionally, by
`scripts/manual_live_source_test.py::_sanitize_report` at the final
report boundary -- the same two-layer pattern already established by
`cap.py`/`xml_envelope.py`/`rss_discovery.py`.

## 6. Error taxonomy additions (Scope F)

`collectors/error_classification.py` now also maps:

| Exception | Category |
| --- | --- |
| `CandidateReferenceError` (`tmd_candidate.py`) | `validation` (falls through the existing generic `ValueError` branch) |
| `DnsResolutionError` (`http_client.py`) | `security` |
| `NonGlobalAddressError` (`http_client.py`) | `security` |
| `PinnedRedirectError` (`http_client.py`) | `security` |
| `PinnedTlsError` (`http_client.py`) | `security` |
| `PinnedConnectionError` (`http_client.py`) | `security` |
| `CandidateEnvelopeMismatchError` (`tmd_candidate.py`) | `parse` |
| `CandidateUnexpectedStatusError` (`tmd_candidate.py`) | `unexpected` (falls through the default branch) |
| `UnexpectedNotModifiedError` (reused, `tmd_cap.py`) | `unexpected` (unchanged from WO-004) |
| `ResponseTooLargeError` / `UnexpectedContentTypeError` (reused) | `security` / `content_type` (unchanged) |
| `CapSecurityError` / `MalformedCapAlertError` (reused, unmodified) | `security` / `parse` (unchanged) |

`CandidateUnexpectedStatusError` and `CandidateEnvelopeMismatchError` are
defined in `collectors/adapters/tmd_candidate.py`, not
`collectors/adapters/tmd_cap.py` where they are actually raised, solely
to avoid a circular import: `tmd_cap.py` imports `classify_error` from
`collectors/error_classification.py`, and `error_classification.py`
needs to import these two exception classes to classify them, so they
live in the one module (`tmd_candidate.py`) that has no dependency on
`error_classification.py` at all.

No error message or report field ever includes the raw candidate
payload, certificate contents, credentials, or unbounded network
exception text -- every raised exception's message is a short, static,
human-authored string (see the class docstrings in `http_client.py` and
`tmd_candidate.py`), never an interpolated raw value beyond a status
code or byte count. This holds for post-handshake transport failures
too: `get_pinned_candidate()` catches `ssl.SSLError` (-> `PinnedTlsError`)
and `OSError`/`TimeoutError` (-> `PinnedConnectionError`) around the
request/response exchange itself, not only around the initial connect,
so a mid-exchange failure is classified the same stable way rather than
escaping as an unclassified `unexpected` exception carrying the
platform's own exception text (Section 4 item 10).

## 7. Manual workflow operation (Scope E)

`.github/workflows/manual-live-source-test.yml` gained one new
`tmd_operation` choice, `candidate_cap_validation`, and three new
optional string inputs: `candidate_filename`, `candidate_evidence_run_id`,
`candidate_item_index`. The workflow remains `workflow_dispatch`-only
(no `schedule`, `push`, `pull_request`, or `repository_dispatch`
trigger), `permissions: contents: read` is unchanged, and both existing
safety steps ("Confirm public dashboard/current-event data are
unchanged" and "Upload redacted manual-test report only") remain
`if: always()` and continue to check/upload exactly as before.

`scripts/manual_live_source_test.py::run_tmd_candidate_cap_validation()`
is a new function, not a branch grafted onto the existing
`run_tmd_cap()` after endpoint resolution -- this operation never
resolves a contract endpoint at all. Its `--candidate-item-index` CLI
argument deliberately does **not** use `argparse`'s `type=int`: a GitHub
Actions `workflow_dispatch` string input has no integer type and may
arrive empty, and converting it inside the function (falling back to the
raw string on a `ValueError`) means an empty or non-numeric value still
reaches `build_candidate_reference()` for a clean, structured
`CandidateReferenceError` in the report, rather than an uncaught
`argparse` crash before any report can be written.

- **`dry_run: true` (default):** validates the candidate reference and
  derives the request URL via `build_candidate_reference()` /
  `derive_candidate_request()` only -- **zero DNS resolution and zero
  network calls**, verified by
  `tests/test_manual_workflow.py::test_run_tmd_candidate_cap_validation_dry_run_derives_url_with_zero_network`.
- **`dry_run: false` (live mode):** is fully implemented
  (`TmdCapAdapter.validate_candidate()`) but **must not be executed under
  WO-006** -- Issue #11 authorizes implementation only.

No write occurs under `data/candidates`, `data/reviewed`,
`data/source_status`, or `dashboard/public/data` for this operation,
exactly as for the existing operations -- the workflow's existing
forbidden-path check is unaware of, and does not need to change for,
this new operation, since it already checks the same fixed path list
regardless of which `tmd_operation` ran. Only one sanitized `report.json`
artifact is produced; no raw response body is ever written to disk.

## 8. SSRF and request-count boundary summary

- Arbitrary URL/host/port/path input is **structurally impossible**: the
  candidate reference model has no field capable of carrying one
  (Section 3).
- DNS/IP validation **fails closed**: an empty answer, a resolver error,
  or *any* non-global address in the answer set all reject the whole
  resolution (Section 4, items 1-2).
- The connection is **pinned to the validated, selected IP**, with
  correct TLS hostname verification and `Host` header still targeting
  the real hostname (Section 4, item 4), and the adapter explicitly
  re-verifies the connected IP equals the selected IP before proceeding.
- **Exactly one physical candidate GET** is possible per invocation; no
  retry, fallback address, or second request exists in this transport
  (Section 4, items 6-7).
- **Redirects and retries are impossible** in this operation -- both
  structurally (no retry parameter, no code path that constructs a
  second request) and behaviorally (every 3xx except 304 raises before
  any `Location` could be read).
- This operation still makes **at most one URL request total** -- it
  never also fetches the RSS feed in the same operation; the candidate
  filename is supplied by the caller (sourced from a separately reviewed
  WO-005-style discovery artifact), not rediscovered live.

## 9. Instructions (implementation-only; do not run live under WO-006)

Via `.github/workflows/manual-live-source-test.yml`:

1. Go to Actions -> "Manual live source test (GDACS / TMD CAP)" -> "Run
   workflow".
2. `source: tmd_cap`, `tmd_operation: candidate_cap_validation`.
3. `language: primary` or `thai_language_cap`.
4. `candidate_filename`: a bare filename matching
   `CAPTMD<14 digits>_<digits>.xml`, as observed in a reviewed discovery
   artifact (e.g. `CAPTMD20260723155032_2.xml` from WO-005, Section 1).
5. `candidate_evidence_run_id` / `candidate_item_index`: the discovery
   run ID and item index the filename was observed at (provenance only).
6. Leave `dry_run: true` to see the derived request URL with **zero
   network calls**. **Do not set `dry_run: false` under WO-006** -- a
   live fetch requires WO-007 and explicit human approval first.

## 10. Criteria for a future WO-007 dry/live validation sequence

Before any future work order may execute `dry_run: false` for
`candidate_cap_validation`, it must confirm, in writing and before
execution:

- the specific candidate filename(s) to validate, each traceable to a
  specific, reviewed discovery workflow run ID and item index
- explicit human approval of running this exact, already-implemented
  code path live, for this exact candidate, distinct from and in
  addition to the code-level approval this PR itself requests
- a plan for what happens to the (still non-published, still
  non-staging) validation result afterward -- this increment's outcome
  is diagnostic only and creates no staging record or event by design
- confirmation that `TMD_CAP.enabled`, `machine_readable_status`, and
  `licence_status` remain unchanged unless a *separate*, later, reviewed
  decision changes them

## 11. Explicit statement: no logistics impact assessment

Nothing in this increment -- the candidate reference validator, the
pinned transport, the reused strict CAP parser, or the manual workflow's
new `candidate_cap_validation` operation -- assesses, infers, or emits
any operational logistics impact (transport, facility, port, airport,
warehouse, trade, inventory, cost, capacity, service, or
business-continuity disruption) of any kind. A structurally validated
CAP candidate is hazard/context-signal provenance only, exactly as
`docs/gdacs_tmd_cap_pilot.md` Section 5 and
`docs/tmd_rss_discovery_hardening.md` Section 9 already establish for
the existing GDACS, direct-CAP, and RSS-discovery paths.
`TMD_CAP.enabled` remains `false`, `machine_readable_status` remains
`unverified`, `licence_status` remains `pending_review`,
`required_for_publication` remains `false`, and no schedule was added,
by this document and by this increment's code. The TMD
copyright/deep-link policy conflict recorded in
`docs/gdacs_tmd_cap_pilot.md` and
`docs/tmd_rss_discovery_hardening.md` is **not** resolved by assumption
here either.
