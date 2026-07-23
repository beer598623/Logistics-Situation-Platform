# RSS/envelope fixture provenance

All fixtures in this directory are **synthetic**, written for WO-004
(Issue #8) to exercise the generic XML-envelope classifier
(`collectors/adapters/xml_envelope.py`) and the discovery-only RSS 2.x
parser (`collectors/adapters/rss_discovery.py`). None are copied from a
live TMD feed or any other live source, per this work order's explicit
prohibition on committing a live TMD payload. Hosts used throughout
(`feed.example.test`, `other.example.test`) are deliberately fictitious
(RFC 2606 `.test`), not TMD's real hostnames, so no fixture could be
mistaken for a captured live response or a real TMD deep link.

- `same_host_link.xml` -- an RSS 2.0 feed whose single item's `<link>` and
  `<guid>` are both on the feed's own configured host
  (`feed.example.test`), used to prove same-host grouping.
- `enclosure_media_type.xml` -- an RSS 2.0 feed whose item has an
  `<enclosure url="..." type="application/cap+xml">`, used to prove
  enclosure URL/type retention.
- `cross_host_link.xml` -- an RSS 2.0 feed whose item's `<link>` points at
  a different host (`other.example.test`), used to prove cross-host
  grouping.
- `malformed_link.xml` -- an RSS 2.0 feed whose item's `<link>` is not a
  well-formed URL at all, used to prove malformed URLs are bounded
  warnings/groupings, not crashes.
- `long_title_description_canary.xml` -- an RSS 2.0 feed with a very long
  `<title>`/`<description>` containing a unique canary marker string, used
  to prove that free-text title/description content is never retained or
  echoed anywhere in discovery output, warnings, or the manual workflow's
  report.
- `atom_feed.xml` -- a minimal Atom `<feed>` root (a different envelope
  kind entirely), used to prove the classifier recognizes Atom and that it
  is never misread as RSS or CAP.
- `unrelated_xml.xml` -- an arbitrary, unrelated XML root
  (`<catalog>...</catalog>`), used to prove the classifier's `other_xml`
  fallback.
- `guid_canary_non_url.xml` -- an RSS 2.0 feed whose single item has
  **no** `<link>`, and a `<guid>` (no `isPermaLink` attribute, so it
  defaults to `"true"` per the RSS spec) containing a unique canary marker
  that is *not* URL-shaped. Added for review-round-1 finding 3: proves a
  non-URL guid is never retained verbatim just because `isPermaLink`
  defaults to true -- retention must depend on the value's own shape, not
  the publisher's unverified claim.

The CAP fixtures already committed under `tests/fixtures/cap/` are reused
directly (not duplicated here) for: direct-CAP-alert envelope
classification (`valid_bilingual_alert.xml`), DTD/XXE rejection
(`dtd_entity_attack.xml`), and oversized-payload rejection (constructed
in-memory in the relevant tests, as already done for the CAP parser's own
tests) -- see `tests/test_xml_envelope.py` and
`tests/test_rss_discovery.py`.
