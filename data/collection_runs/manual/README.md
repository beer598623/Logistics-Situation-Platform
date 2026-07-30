# Manual-intake review events

`collectors/collection_runs.py::load_manual_review_events()` reads every
`*.json` file in this directory, validates each event inside its `events`
array against `schemas/manual_review_event.schema.json`, and groups them by
`source_id`. These are deliberately **not** shaped like a collection run
manifest (`schemas/collection_run.schema.json`): nothing was fetched over a
network, so there is no request URL, HTTP status or response content hash to
record.

WO-010-R4 §7: beyond schema validity, the loader also enforces, failing
closed (raising) rather than silently dropping an event or a file:

- the containing filename must equal the event's own `source_id` (a file
  named `MANUAL_NOTICE_INTAKE.json` may only carry events for that source);
- the `source_id` must exist in the source registry and be an allowed
  manual-intake contract (`access_method: manual`,
  `qualification.manual_intake_status: allowed`);
- `event_id` must be unique across every file in this directory;
- `underlying_publisher` must be recorded whenever the source contract's
  `qualification.underlying_publisher_required` is true;
- `reviewed_at` must not be later than the build's as-of time (the current
  Build Context -- see `analysis/build_context.py`).

File shape:

```json
{
  "version": "0.8",
  "source_id": "MANUAL_NOTICE_INTAKE",
  "events": [
    {
      "event_id": "MAN-20260101T000000Z-MANUAL_NOTICE_INTAKE",
      "source_id": "MANUAL_NOTICE_INTAKE",
      "reviewed_at": "2026-01-01T00:00:00Z",
      "reviewer_record": "A. Reviewer",
      "status": "reviewed",
      "record_count": 1,
      "related_record_ids": ["EVD-MANUAL-20260101-001"],
      "data_cutoff_at": "2026-01-01T00:00:00Z",
      "bounded_content_confirmed": true,
      "underlying_publisher": "Example Port Authority",
      "content_sha256": null,
      "known_limitations": []
    }
  ]
}
```

No human has ever recorded a notice through this intake path, so this
directory holds no event files. `collectors/source_health.py` treats a
manual-intake source with no recorded event as `disabled` -- matching the
source registry's own `enabled: false` -- and only computes a real
freshness status (`fresh` / `stale` / `very_stale`) once at least one
review event exists, dated by that event's `reviewed_at` rather than by
any collection-run manifest, and only once that event validates.
