# data.gov.sg fixture provenance

Both fixtures here are **synthetic** — invented placeholder numbers for shape testing, not real
MPA statistics. As of WO-027 the **field names and dataset (resource) identifiers are
human-confirmed against the primary `data.gov.sg` pages**, correcting WO-026's guessed field
names (`total_teus`, `total_vessels`, both wrong). See `docs/mpa_sg_statistics_qualification.md`
for the full reconciliation record and the confirmed endpoint
(`https://data.gov.sg/api/action/datastore_search`).

- `resource_id` in each fixture is the confirmed dataset identifier:
  - Container Throughput, Monthly: `d_da030f7028200d19ffcbe4a2d71af39c`
  - Vessel Arrivals (>75 GT) Total, Monthly: `d_d48c5a038904f6da3c603cd854b6c191`

- `container_throughput_monthly.json` uses the confirmed field `container_throughput`
  (not `total_teus`). Includes one record with an empty string value
  (`"container_throughput": ""`), exercising the missing-value path via a string marker.
  **The unit/scale of this field is still unverified** (WO-027): the raw numeric scale does
  not obviously match individual TEUs against official MPA annual statements (41.12M TEU for
  2024, 44.66M TEU for 2025). `collectors/adapters/data_gov_sg.py`'s parser refuses to parse
  this series at all (`DatastoreSeriesSpec.unit_verified=False`) until that is resolved by a
  controlled live validation — this fixture exists to exercise that refusal path in tests, not
  to demonstrate a working parse.
- `vessel_arrivals_monthly.json` uses the confirmed fields `number_of_vessels` (not
  `total_vessels`) and `gross_tonnage`. Includes one record with a JSON `null` value for
  `number_of_vessels`, exercising the missing-value path via the other representation a real
  API might plausibly use. `gross_tonnage` is present in the fixture to match the confirmed
  response shape but is **not** wired into any parsed capability — the human decision recorded
  on Issue #56 requires it to be assessed separately before it is added.

The response *envelope* shape (`{"success", "result": {"resource_id", "fields", "records",
"total"}}`, the standard CKAN Datastore Search convention) is now confirmed to match the real
API — see WO-027 Part B's bounded live validation, `docs/mpa_sg_statistics_qualification.md`
§7. This fixture's own `_id`/`fields` block was never re-verified against that live validation,
because the live requests used a `fields=` projection and never received data.gov.sg's own
`result.fields` schema block back for the fields actually requested — so nothing here confirms
or contradicts this fixture's `fields` array in particular, only the envelope's outer shape.

**These fixture values remain shape-only, not magnitude-calibrated — this is now visible by
direct comparison, not merely a caveat.** WO-027 Part B's live validation retrieved real
`number_of_vessels` (~10,900-12,000/month) and `gross_tonnage` (~257,000-293,000/month) values
that are roughly an order of magnitude and roughly 400x different from this fixture's invented
`number_of_vessels` (~3,400-3,600) and `gross_tonnage` (~109,800,000-114,900,000) figures
respectively. This is expected and does not indicate an error in either the fixture or the live
data: the fixture was never intended to be numerically realistic (see this file's opening
paragraph), and WO-027 deliberately did not update it to match live magnitudes, preserving the
fixture/live evidence-origin boundary `docs/mpa_sg_statistics_qualification.md` and every other
WO-010-style adapter maintain — a fixture must never be silently reshaped to imitate a specific
live observation, or a future reader could mistake a fixture-derived value for a real one.

No data.gov.sg content or attribution text is reproduced here.
