# Notice-feed fixtures

Synthetic test fixtures only. Every host is a `.invalid` domain, which by
RFC 2606 can never resolve, so no test in this repository can accidentally
reach a real publisher.

- `official_notice_rss.xml` — RSS notice feed. The second item deliberately
  embeds `user:secret@` in its link so the user-info redaction path is
  exercised, and the first item carries tracking parameters so URL
  canonicalization is exercised.
- `discovery_atom.xml` — Atom discovery feed. Records parsed from it must
  carry `evidence_role: discovery_only`.
- `not_a_feed.xml` — well-formed XML that is not a notice feed. The parser
  must reject it rather than returning an empty result, because "no entries"
  and "wrong document" are different answers.
