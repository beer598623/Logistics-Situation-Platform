# Security and privacy boundary

**Work Order:** WO-010 · **Status:** implemented

## 1. What WO-010 changed about the security posture

Nothing was weakened. The pre-existing fail-closed collector model is preserved and reused
unchanged; the two adapters added are strictly more restricted than the ones that existed,
because neither of them fetches anything at all.

Specifically **unchanged**: `collectors/http_client.py` (bounded fetch, no-redirect
discovery transport, DNS-pinned candidate transport with fail-closed non-global-address
rejection), the strict CAP 1.2 parser, the TMD candidate evidence contract, and the
`manual-live-source-test` workflow's gates.

The strict TMD/CAP safety boundary is untouched. `TMD_CAP` and `GDACS` remain disabled, and
`tests/test_derived_outputs.py` asserts that WO-010 added no qualification or enablement
record to either.

## 2. Network posture

| Property | State |
|---|---|
| Network in default CI | **None.** `validate-pr.yml` runs lint, validation, dry run, build and tests, all offline |
| Network in the new adapters | **None.** Both parse bytes they are handed; neither has a fetch path |
| Network at import time | **None.** A test imports every module in a fresh interpreter with sockets disabled |
| Arbitrary user-supplied fetch URLs | **None.** No code path accepts one |
| Following a discovered link | **Never.** A link found in a feed is recorded, never requested |
| The one authorized live path | `manual-live-source-test.yml`, `workflow_dispatch` only |

## 3. Fail-closed parsing

Both new adapters reject rather than salvage:

| Condition | Behaviour |
|---|---|
| Unexpected content type | Rejected **before** parsing, via the existing `validate_content_type` allowlist |
| Oversized payload | Rejected against a parser-level byte bound, in addition to the contract's transport bound |
| Too many rows or entries | Rejected |
| Ragged row, missing column, overlong field | Rejected — the whole parse fails rather than returning a partial series |
| Unparseable period | Rejected. A guessed period silently mis-dates every derived change |
| Token that is neither a number nor a recognised missing marker | Rejected |
| Well-formed XML that is not a notice feed | Rejected. "No entries" and "wrong document" are different answers |
| Entry with no title | Rejected |
| Unrecognised publication date | Recorded as `null`, never invented |

A silently truncated trade series looks exactly like a trade collapse, which is why partial
success is not an option here.

## 4. Content boundaries

- **No raw responses, caches or snapshots** in the repository. `raw_snapshot_path` is always
  null and a test asserts it.
- **Claims capped at 600 characters** by the evidence contract and by both intake paths, so
  no full copyrighted article can enter the repository through either route.
- **Only headline metadata and the publisher's own URL** are retained from discovery
  sources; article bodies are never fetched.
- **User-info stripped** from every retained URL via the existing `redact_url_userinfo`, so
  a `user:password@host` URL cannot leave a credential in a record.
- **Error messages carry no response content** — only structural detail such as which column
  or row was at fault.

## 5. Credentials

No credential exists in this repository and none is required to build, validate, test or
publish anything.

`BOT_FX` is the only registered candidate requiring an API key, and it is **disabled for
that reason**: a key is a credential, no credential-handling mechanism exists here, and
WO-010 deliberately does not introduce one. Enabling it requires a separate secrets decision.

## 6. Private data boundary

The Public Intelligence Core holds organization-neutral information only. It contains **no**
shipment plans, freight quotations, booking or cut-off dates, container demand, tractor
availability, turnaround time, warehouse capacity, inventory exposure or customer
commitments.

This is not merely absent, it is structurally impossible to publish accidentally: no schema
in `schemas/` has a field for any of it, and `analysis/assessments.py` rejects preparedness
options containing organization-specific phrasing such as "your fleet" or "your shipment".

The Private Decision Overlay remains out of scope and local-only, per the approved
architecture.

## 7. Provenance integrity

Every observation carries a content hash, a parser version, a retrieval time and, where the
source provides them, a publication time, a revision time and a source revision. Record IDs
are deterministic, so re-collection updates rather than duplicates, and revisions are
preserved rather than overwritten.

Cluster keys are recomputed at validation time and a mismatch is rejected, so a tampered or
stale key cannot survive.

## 8. Dependency posture

One dependency added: `duckdb==1.4.1`, pinned in `requirements.txt`, `requirements.lock` and
`pyproject.toml`, and recorded in `THIRD_PARTY_NOTICES.md`. It is free and open source, it
is used only to build a derived, gitignored artefact, and the published Dashboard has no
dependency on it whatsoever.

The Dashboard loads **no external JavaScript, stylesheet, font or image**. A test asserts
that the only absolute URL in the page is the repository link in the footer, and that the
script fetches nothing outside its own `data/` directory.

## 9. What a reviewer should still check independently

- That no committed file contains a credential, key or token.
- That the notice and discovery intake paths genuinely cannot be induced to fetch a
  discovered link.
- That the licence and redistribution positions recorded for each source match what the
  publisher actually states, once someone can read those terms.
- That the `manual-live-source-test` workflow still has no automated trigger.
