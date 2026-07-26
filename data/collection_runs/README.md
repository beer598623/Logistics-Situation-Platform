# Collection run history

`collectors/collection_runs.py::load_collection_runs()` reads every
`*.json` file in this directory and groups the `runs` array inside each by
`source_id`. Each run is validated against
`schemas/collection_run.schema.json` before `evaluate_registry_health()` is
allowed to see it.

File shape:

```json
{
  "version": "0.8",
  "source_id": "EXAMPLE_SOURCE",
  "runs": [
    { "run_id": "COL-20260101T000000Z-EXAMPLE_SOURCE", "source_id": "EXAMPLE_SOURCE", "...": "..." }
  ]
}
```

No source in this repository has ever completed a live collection run, so
this directory holds no run files. That absence is the honest answer:
`load_collection_runs()` returns an empty mapping for a missing or empty
directory, and Source Health reports every automated source as `no_data`
rather than silently treating "nothing recorded" as "nothing to report."

See `data/collection_runs/manual/README.md` for the separate,
non-network manual-intake review event format.
