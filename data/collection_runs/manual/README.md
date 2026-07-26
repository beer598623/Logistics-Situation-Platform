# Manual-intake review events

`collectors/collection_runs.py::load_manual_review_events()` reads every
`*.json` file in this directory and groups the `events` array inside each by
`source_id`. These are deliberately **not** shaped like a collection run
manifest (`schemas/collection_run.schema.json`): nothing was fetched over a
network, so there is no request URL, HTTP status or content hash to record.

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
      "reviewer": "A. Reviewer",
      "record_count": 1,
      "status": "reviewed"
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
any collection-run manifest.
