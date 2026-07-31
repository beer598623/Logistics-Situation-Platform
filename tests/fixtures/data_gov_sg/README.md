# data.gov.sg fixture provenance

Both fixtures here are **synthetic and unverified against a live response.**
This environment's `WebFetch` tool is blocked for every external host
(see `docs/mpa_sg_statistics_qualification.md` §0), so no primary
data.gov.sg API response has ever been directly observed by this
repository. Everything in these files is a best-effort approximation of the
standard CKAN Datastore Search response envelope
(`{"success", "result": {"resource_id", "fields", "records", "total"}}`) that
data.gov.sg's own developer documentation names ("Datastore Search"), not a
capture of a real response.

Confirming the real field names (`month` / `total_teus` / `total_vessels`
below are this Work Order's assumption, not an observed fact) is the first
action of the controlled live-validation this Work Order explicitly does not
perform (WO-026; see the human decision recorded on Issue #54).

- `resource_id` in each fixture is the dataset identifier cited in the prior
  research pass's search results:
  - Container Throughput, Monthly: `d_da030f7028200d19ffcbe4a2d71af39c`
  - Vessel Arrivals (>75 GT) Total, Monthly: `d_d48c5a038904f6da3c603cd854b6c191`

  These identifiers themselves come from search-engine snippets of the
  dataset landing pages, not a direct fetch, and must also be reconfirmed.

- `container_throughput_monthly.json` includes one record with an empty
  string value (`"total_teus": ""`), exercising the missing-value path via
  a string marker.
- `vessel_arrivals_monthly.json` includes one record with a JSON `null`
  value, exercising the missing-value path via the other representation a
  real API might plausibly use.

No data.gov.sg content, attribution text, or real published figures are
reproduced here — the numeric values are invented placeholders for shape
testing only, not real MPA statistics.
