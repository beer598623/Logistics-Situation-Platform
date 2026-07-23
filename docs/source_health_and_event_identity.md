# Source health and event identity (Implementation v0.1.2)

This note explains the two deterministic subsystems added in v0.1.2:
cadence-aware source health with purpose-aware coverage, and stable event
identity across the candidate → reviewed lifecycle. Neither subsystem
enables live network collection, changes impact severity logic, or alters
publishing thresholds; both are pure, testable functions over data already
present in the repository.

## Source health (`collectors/source_health.py`)

`evaluate_source_health(contract, runs, now=...)` turns one Source Contract
(`config/sources.yaml`) plus the full known history of Collection Run
manifests (`schemas/collection_run.schema.json`) for that source into a
`SourceHealth` record with one of six states:

| Status       | Meaning                                                                 |
|--------------|--------------------------------------------------------------------------|
| `fresh`      | Most recent successful run is within the source's cadence window.       |
| `stale`      | Past cadence but within `max_stale_minutes`.                            |
| `very_stale` | Past `max_stale_minutes` since the last success.                        |
| `no_data`    | No successful run has ever been recorded — a gap, not zero.             |
| `disabled`   | The source contract has `enabled: false`. Always wins over run history. |
| `error`      | The most recent run failed, even if an earlier run succeeded.           |

Key rules:

- **Disabled always wins.** A source with `enabled: false` reports
  `disabled` regardless of any run history, so existing disabled sources
  cannot be reinterpreted as healthy or broken.
- **`no_data` and `error` are distinct.** `no_data` means the source has
  never produced a successful run; `error` means the most recent attempt
  failed. A source can have a recorded past success and still be `error`
  right now — `last_success_at` and `last_checked_at` are tracked
  separately for exactly this reason.
- **Freshness never treats a gap as zero.** `item_count` is `None` (not
  `0`) whenever there is no successful run to count, and `validate.py`
  fails the build if any `no_data`/`error`/`disabled` source reports a
  literal `0`.
- **The freshness boundary comes from the contract**, not a hardcoded
  constant: `expected_cadence_minutes` when the source declares one,
  otherwise half of `max_stale_minutes`.

### Coverage roll-up

`evaluate_registry_health(registry, runs_by_source, now=...)` evaluates
every source in the registry, then groups sources by declared `purposes`
(e.g. `hazard_detection`, `thailand_weather_alerts`) into **capabilities**.
Each capability gets its own `sufficient` / `limited` / `insufficient`
status, decided in this exact order by `_capability_coverage`:

1. **Required-source gap first.** If *any* source backing the capability is
   `required_for_publication` and is not currently `fresh`/`stale` (i.e. it
   is `no_data`, `error`, `very_stale`, or even `disabled`), the capability
   is `insufficient` — full stop, regardless of what any other source
   backing the same capability is doing. This check runs *before* the "is
   anything live?" check below, specifically so a required source failing
   can never be hidden behind an unrelated optional source that happens to
   be fresh (a capability backed by one optional fresh source and one
   required, failed source is `insufficient`, not `sufficient`).
2. **Otherwise, sufficient if anything is live.** If no required-source gap
   applies, the capability is `sufficient` as soon as at least one backing
   source is `fresh` or `stale` — this covers the ordinary case where every
   backing source is either healthy or merely optional-and-degraded.
3. **Otherwise, insufficient only if *every* backing source is disabled.**
   The "no enabled source currently backs this capability" gap reason is
   reserved for when *all* supporting sources are `disabled` — one disabled
   source next to another enabled (even if degraded) source must not force
   this message, since something is in fact enabled and trying.
4. **Otherwise, limited.** At least one supporting source is enabled but
   none are live (e.g. `very_stale`, `error`, or `no_data`, mixed with any
   number of `disabled` siblings) — degraded, not absent.

`_overall_status` applies the same required-source-gap check first (via the
shared `_required_source_gap` helper) before rolling up per-capability
statuses, so **a required source outage can never be masked as "sufficient"
coverage** at the registry level either. Because coverage is computed per
capability, one source failing only degrades the capabilities it actually
backs — no source becomes publication-critical merely by being registered;
that only happens through the explicit `required_for_publication` flag on
its contract.

`schemas/source_status.schema.json` was extended with a `capabilities`
array (`capability`, `status`, `supporting_sources`, `gap_reason`) to carry
this breakdown; `data/source_status/latest.json` and the dashboard's
System Status section were regenerated/updated to render it.

`scripts/validate.py::source_status_checks` re-checks this precedence
independently at the data layer, since a hand-edited, stale, or partially
generated snapshot is not guaranteed to have come from the canonical
evaluator:

- A `sufficient` capability may never list a degraded
  `required_for_publication` supporting source, and a capability with one
  must be `insufficient` (not `limited`, not `sufficient`).
- **Whenever any source has a degraded required-source gap,
  `overall_status` must be `insufficient` — not just "not sufficient".**
  Because `_overall_status` can only ever produce `insufficient` in that
  situation, a snapshot claiming `overall_status: limited` (or
  `sufficient`) while a required source is degraded cannot have come from
  the evaluator and fails validation just as `sufficient` does.

## Event identity (`collectors/event_identity.py`)

`resolve_event_identity(...)` assigns each candidate or reviewed event a
`canonical_event_id` and lifecycle metadata that survive title rewrites and
re-collection:

1. **Prefer `source_id` + `external_event_id`.** If a source supplies a
   stable ID, an existing record with the same `source_id` and
   `external_event_id` is matched exactly (`merge_status:
   matched_external_id`).
2. **Otherwise use a controlled fingerprint.** `compute_event_fingerprint`
   hashes only normalized, structured fields — `primary_category`,
   `geography`, an event-date bucket (`event_date` or, if unknown yet,
   `publication_date`), `transport_modes`, and `segments` — never the
   title or any generated summary. An exact fingerprint match against a
   known event reuses its canonical ID (`merge_status:
   matched_fingerprint`).
3. **No match is `unmatched`.** A brand-new canonical ID is derived
   deterministically: `sha256("ext:<source_id>:<external_event_id>")` when
   an external ID is available, otherwise `sha256("fp:<fingerprint>")`,
   truncated to 16 hex characters and prefixed `CEVT-`. Because the input
   is fully determined by controlled fields, the same event always
   produces the same ID on any repeated run.

Because the fingerprint depends on category, geography, date bucket, mode,
and segment together, changing *any one* of those fields changes the
fingerprint and therefore prevents matching — a different mode, geography,
category, or date bucket that was **already known** can never resolve to
the same canonical event by accident (see the event-date exception below
for the one case where an *unknown* date becoming known must not split the
event).

`first_seen_at` is preserved from the matched record; `last_seen_at` always
advances to the current run; `last_changed_at` only advances when the
persisted `content_signature` differs from the newly computed one, so
lifecycle history reflects real content changes, not just re-observation.

### `content_signature` must be persisted, not recomputed in memory

`content_signature` is a plain SHA-256 hex digest (`^[0-9a-f]{64}$`),
produced by `compute_content_signature(title=..., text_fields=[...])`,
hashing exactly the free-text fields a caller documents as "content that
indicates a real change" — for this repository's fixtures that is `title`
+ `raw_claims` (+ `headline_summary`) for a candidate, and `title` +
`verified_facts` + `reported_claims` for a reviewed event.
`tests/test_data_contracts.py::test_content_signature_matches_its_documented_source_fields`
locks in exactly those field sets. Volatile fields such as `retrieved_at` or
`last_verified_at` must never be hashed, or every re-observation would look
like a content change.

`EventIdentity.to_dict()` returns `content_signature` as one of its fields
specifically so callers persist it into the candidate/reviewed JSON record
via the schema field of the same name
(`schemas/candidate_event.schema.json`, `schemas/reviewed_event.schema.json`
— both now require it). `resolve_event_identity` only ever *compares*
against `known_events[i]["content_signature"]`; it never recomputes a
previous signature itself. Skipping the persistence step means every future
call sees no prior signature to compare against and — because a match was
still found by fingerprint or external ID — would incorrectly treat
`last_changed_at` as advancing on every re-observation, even when nothing
changed. `tests/test_event_identity.py` covers this explicitly with a real
`json.dumps`/`json.loads` round trip (unchanged signature → stable
`last_changed_at`; changed signature → `last_changed_at` advances).

### Preserving identity when an unknown event date becomes known

The fingerprint's date bucket is `event_date or publication_date` — so a
candidate first observed with `event_date=None` fingerprints using
`publication_date`. If that date later resolves to a real, different
`event_date`, the fingerprint changes, and without special handling the
newer observation would look `unmatched` and mint a *new* canonical ID for
what is really the same event.

**A first attempt at this fix recomputed a "provisional" fingerprint from
the *new* observation's own `publication_date`.** That broke if
`publication_date` itself changed between observations (e.g. a source
revision, or a reviewed record built from different provenance than the
candidate) — the promotion lookup would search for the wrong bucket and
the event would still split. The fix that ships here instead **persists a
stable `identity_date_bucket`** on every candidate/reviewed record:

- `identity_date_bucket` freezes to the real `event_date` as soon as one is
  known.
- Until then, it freezes to whatever `publication_date` was in effect the
  *first* time the record was resolved — and, critically, it is carried
  forward unchanged on every subsequent match, never recomputed from a
  later observation's `publication_date`.
- `compute_event_fingerprint_from_bucket` is the single primitive that
  turns `(category, geography, date_bucket, modes, segments)` into a hash;
  both "today's fingerprint" and "the frozen bucket's fingerprint" go
  through it, so they're always comparable.

`resolve_event_identity` tries, in order: (1) external ID, (2) an exact
fingerprint match using this observation's own fields, (3)
`_find_by_frozen_bucket` — for each known record whose **own persisted
`event_date` is `None`**, recompute what its fingerprint would be using
*that record's own* `identity_date_bucket` (not this observation's
`publication_date` at all) plus this observation's current category,
geography, modes, and segments, and compare against the record's stored
`event_fingerprint`. Because step 3 never reads this observation's
`publication_date`, identity survives `publication_date` changing between
observations as well as `event_date` resolving from unknown to known —
even both at once. Requiring the known record's `event_date` to be `None`
(not just checking whether fingerprints coincide) is what keeps this safe:
a known record that already had a real event date is never eligible, so
the "different date bucket" guarantee above still holds. A known-event
dict that omits the `event_date` key entirely, or that has no persisted
`identity_date_bucket`, is conservatively treated as *ineligible* rather
than "unknown".

On a match through step 3, the canonical ID and `first_seen_at` are carried
forward unchanged; `identity_date_bucket` promotes to the real `event_date`
(now known), and the returned `event_fingerprint` is recomputed from that
promoted bucket — the record's identity is preserved while its precision
improves. `tests/test_event_identity.py` covers: unknown → known preserving
identity; unknown → known surviving a *simultaneous* `publication_date`
change (the scenario the first fix missed); a known record with a real
event date never reachable through this path even when dates would
otherwise coincide; and a known record missing `event_date` or
`identity_date_bucket` staying conservatively ineligible.

### Explicit candidate ↔ reviewed date-field mapping

Candidates store their identity date under `event_date`; reviewed events
store the same concept under `event_start` — the schemas were not unified
onto one field name. Rather than leaving that mapping as prose for callers
to remember, `collectors/event_identity.py` provides it as code:

- `event_date_from_candidate(candidate)` / `event_date_from_reviewed_event(event)`
  read the correct field for each record shape.
- `known_event_from_candidate(candidate)` / `known_event_from_reviewed_event(event)`
  build a full `known_events` entry (including the `event_date` mapping and
  every other field `resolve_event_identity` reads) from a stored record,
  so a caller never constructs that dict by hand.

`tests/test_event_identity.py::test_event_date_accessors_map_candidate_and_reviewed_fields_explicitly`
and `::test_known_event_builders_map_event_date_field_explicitly` test the
accessors directly;
`tests/test_data_contracts.py::test_reviewed_event_promotion_from_candidate_resolves_via_explicit_mapping`
replays a candidate → reviewed promotion end-to-end through
`resolve_event_identity` using these helpers and asserts it lands on the
same canonical event the fixtures already share.

### Known limitation: controlled-field collisions

This module intentionally implements **only exact matching** (external ID
or fingerprint/frozen-bucket). It does not run any similarity, clustering,
or AI-based deduplication — that is out of scope for this increment, and
no code path here ever *automatically* merges two events based on a
semantic or fuzzy relationship. The `merge_suggested`, `merged_approved`,
and `split_required` values exist in the `merge_status` enum for a human
reviewer's later decision, but nothing in this module assigns them.

That guarantee is about *semantic* merging, not about matching in general.
Exact-field matching is exactly that — exact: **two genuinely distinct
real-world incidents that happen to share the same category, geography,
date bucket, transport mode, and segment are indistinguishable by these
controlled fields alone**, and will resolve to the same canonical event.
This is a known limitation of deterministic fingerprinting, not a claim
that collisions cannot happen. A source-supplied `external_event_id`
sidesteps the risk entirely (matching never falls through to the
fingerprint when one is available); for sources without a stable ID, a
controlled-field collision is a gap this increment does not close and a
later increment (or human review, via `merge_suggested`/`split_required`)
is expected to handle.

`schemas/candidate_event.schema.json` and `schemas/reviewed_event.schema.json`
both gained: `source_id`, `external_event_id`, `source_revision`
(nullable), `canonical_event_id`, `event_fingerprint`, `merge_status`,
`first_seen_at`, `last_seen_at`, `last_changed_at`, `supersedes`,
`content_signature`, and `identity_date_bucket`. `reviewed_event.schema.json`
also gained `primary_category` (previously only on candidates) so the same
controlled fields are available for fingerprinting at every lifecycle
stage. `event_start` (reviewed) was not renamed to `event_date` — use the
explicit accessors above instead of reading the field by name.

## Migration notes

The existing Pasir Panjang negative-control candidate and reviewed event
were migrated in place: both now carry the same `canonical_event_id`
(`CEVT-c7df9e8cc1521246`) and `event_fingerprint`, computed from their
existing `primary_category`/`geography`/`event_date`/`transport_modes`/
`segments`. Both also carry the same `identity_date_bucket` (`2024-06-14`,
their shared known event date). The reviewed event's `merge_status` is
`matched_fingerprint` (it fingerprint-matches the candidate); the
candidate's is `unmatched` (nothing preceded it). Both records also gained
a real, persisted `content_signature` (candidate: hash of `title` +
`headline_summary` + `raw_claims`; reviewed event: hash of `title` +
`verified_facts` + `reported_claims`), computed with
`compute_content_signature`. No historical conclusion, severity, or status
in the negative-control sample was changed.

`data/source_status/latest.json` was regenerated with
`evaluate_registry_health` against the unchanged, all-disabled
`config/sources.yaml`; `overall_status` remains `insufficient` for the
same reason as before (no source is enabled), now broken down per
capability.
