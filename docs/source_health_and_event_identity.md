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
status:

- `sufficient` — at least one source backing the capability is `fresh` or
  `stale`.
- `insufficient` — a source `required_for_publication` for that capability
  is `no_data`/`error`/`very_stale`, or no enabled source backs it at all.
- `limited` — otherwise degraded (e.g. only a `very_stale` non-required
  source).

The overall `overall_status` can only be `sufficient` when every
capability is; it is `insufficient` whenever any `required_for_publication`
source has a gap, so **a required source outage can never be masked as
"sufficient" coverage**. Because coverage is computed per capability, one
source failing only degrades the capabilities it actually backs — no
source becomes publication-critical merely by being registered; that only
happens through the explicit `required_for_publication` flag on its
contract.

`schemas/source_status.schema.json` was extended with a `capabilities`
array (`capability`, `status`, `supporting_sources`, `gap_reason`) to carry
this breakdown; `data/source_status/latest.json` and the dashboard's
System Status section were regenerated/updated to render it.

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
category, or date bucket can never resolve to the same canonical event by
accident.

`first_seen_at` is preserved from the matched record; `last_seen_at` always
advances to the current run; `last_changed_at` only advances when a
caller-supplied `content_signature` (e.g. a hash of title + claims) differs
from the previous one, so lifecycle history reflects real content changes,
not just re-observation.

### No automatic merging

This module intentionally implements **only exact matching** (external ID
or fingerprint). It does not run any similarity, clustering, or AI-based
deduplication — that is out of scope for this increment. The
`merge_suggested`, `merged_approved`, and `split_required` values exist in
the `merge_status` enum for a human reviewer's later decision, but no code
path here ever assigns them automatically; two events can only become
`matched_fingerprint` when their controlled fields are byte-for-byte equal
after normalization. This is what makes an unsafe automatic merge
impossible by design.

`schemas/candidate_event.schema.json` and `schemas/reviewed_event.schema.json`
both gained: `source_id`, `external_event_id`, `source_revision`
(nullable), `canonical_event_id`, `event_fingerprint`, `merge_status`,
`first_seen_at`, `last_seen_at`, `last_changed_at`, and `supersedes`.
`reviewed_event.schema.json` also gained `primary_category` (previously
only on candidates) so the same controlled fields are available for
fingerprinting at every lifecycle stage.

## Migration notes

The existing Pasir Panjang negative-control candidate and reviewed event
were migrated in place: both now carry the same `canonical_event_id`
(`CEVT-c7df9e8cc1521246`) and `event_fingerprint`, computed from their
existing `primary_category`/`geography`/`event_date`/`transport_modes`/
`segments`. The reviewed event's `merge_status` is `matched_fingerprint`
(it fingerprint-matches the candidate); the candidate's is `unmatched`
(nothing preceded it). No historical conclusion, severity, or status in
the negative-control sample was changed.

`data/source_status/latest.json` was regenerated with
`evaluate_registry_health` against the unchanged, all-disabled
`config/sources.yaml`; `overall_status` remains `insufficient` for the
same reason as before (no source is enabled), now broken down per
capability.
