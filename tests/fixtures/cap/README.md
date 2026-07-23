# CAP 1.2 fixture provenance

All fixtures in this directory are **synthetic**, written for this pilot to
exercise the generic CAP 1.2 parser (`collectors/adapters/cap.py`) and the
TMD profile (`collectors/adapters/tmd_cap.py`). None are copied from a live
TMD feed or any other live CAP source, per Issue #5's explicit prohibition
on committing a live TMD XML payload.

- `valid_bilingual_alert.xml` -- a well-formed CAP 1.2 `Alert` message with
  two `<info>` blocks (`en-US`, `th-TH`), a polygon and a geocode area, used
  as the primary "everything parses" fixture and as the base for the TMD
  profile's bilingual normalization test.
- `update_references_prior_alert.xml` -- a CAP `Update` message whose
  `<references>` points at `valid_bilingual_alert.xml`'s identifier, used to
  test that `msgType`/`references` are preserved for later association.
- `invalid_geometry_and_timestamps.xml` -- otherwise well-formed, but its
  `<info>` block has an unclosed polygon ring, an out-of-range circle, and an
  invalid `effective` timestamp, used to test that a malformed area/timestamp
  is dropped with a warning rather than crashing the whole parse.
- `missing_identifier.xml` -- omits the required `<identifier>`, used to test
  that this (and only this class of top-level defect) aborts parsing.
- `dtd_entity_attack.xml` -- declares a `DOCTYPE` with an external entity
  (classic XXE shape), used to test that the hardened parser rejects it
  before any entity resolution is attempted.
- The "oversized payload" test constructs its input in-memory in
  `tests/test_cap_parser.py` rather than committing a large fixture file.

The CAP 1.2 element structure follows the public OASIS standard
(<https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html>); no content
is reproduced from any TMD bulletin, and no TMD copyright- or
policy-restricted material appears in this directory.
