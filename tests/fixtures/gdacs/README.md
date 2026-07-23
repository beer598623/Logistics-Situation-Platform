# GDACS fixture provenance

`event_list_page1.json` is a **synthetic** fixture written for this pilot. It
is not copied from a live GDACS response. Its shape documents the field
structure described in the official GDACS API quick-start guide and Swagger
definition referenced in Issue #5 and `docs/gdacs_tmd_cap_pilot.md`:

- <https://gdacs.org/Documents/2025/GDACS_API_quickstart_v1.pdf>
- <https://www.gdacs.org/gdacsapi/swagger/index.html>

The fixture is a GeoJSON `FeatureCollection` with three `features`:

1. A fully-populated earthquake (`EQ`) feature exercising every documented
   field: `eventtype`, `eventid`, `episodeid`, alert level/score,
   `fromdate`/`todate`/`datemodified`, `country`/`iso3`, `geometry`
   (`Point`), a report `url`, and `severitydata`.
2. A flood (`FL`) feature with several optional fields omitted
   (`episodeid`, `severitydata`, `alertscore`, `geometry`) to exercise
   "missing optional fields must not crash the parser."
3. A deliberately malformed feature missing `eventid` entirely, to exercise
   "one malformed record must not discard an otherwise valid page."

No GDACS content, attribution text, or imagery is reproduced here beyond
the field names and structure GDACS documents publicly for API integration.
