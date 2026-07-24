# Source-Priority Framework

**Work Order:** WO-009A
**Authorized baseline:** `7039b0b4513f3469a6ce649cb1e845a36e359a2a`
**Execution type:** Architecture, governance and documentation reset only

This document defines the source-priority matrix for the Thailand-Centric Multimodal
Logistics Intelligence platform, refining the general ordering in
`methodology/source_policy.md` for Logistics-specific use. **WO-009A documents this model
only. It does not qualify or enable new sources, and does not modify
`config/sources.yaml`.**

## Priority levels

### Priority 1 — Direct Logistics structured data

Candidate categories: Thailand Customs and trade; Thailand port and transport statistics;
domestic freight; global trade; maritime activity and connectivity; air-cargo indicators;
fuel and cost indicators; FX and relevant economic variables.

These are the analytical core (Layer 1 baseline indicators — see
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 6).

### Priority 2 — Official Logistics operational notices

Candidate categories: port and terminal authorities; canal authorities; customs; road and
rail operators; airports and aviation authorities; border authorities; carriers and
transport operators; sanctions and trade regulators.

These populate Layer 2 (Logistics Operational Events).

### Priority 3 — External-driver evidence

Candidate categories: geopolitical and security sources; economic authorities; energy and
commodity sources; weather and disaster sources.

These sources must not independently create a Logistics-impact conclusion. They populate
Layer 3 (External Drivers) and require the transmission chain in
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 3.4/9 before
contributing to any impact assessment.

### Priority 4 — Discovery leads

Candidate categories: public news; free industry reporting; vendor or social-media leads.

These require primary-source verification before material publication. Paid sources, if
ever recorded, may appear only in this tier as optional discovery leads — never as a
dependency for verifying or publishing a conclusion (free-only principle, Section 3.7 of
the scope document).

## Required source-candidate metadata

Every source candidate must eventually record the following fields before qualification.
This mirrors the fields already established by `config/sources.yaml` (see the `GDACS`,
`TMD_CAP`, `GSCPI`, `TH_CUSTOMS`, and `EPPO_FUEL` entries) and extends them for
Logistics-specific use:

| Field | Description |
|---|---|
| Access cost | Whether the source is free, free-with-registration, or paid. |
| Registration requirement | Whether account creation, API key, or similar is required. |
| Paywall status | Whether any part of the data is behind a paywall. |
| Redistribution status | Whether republishing derived data or metadata is permitted. |
| Machine-readability | Whether the source offers a structured, parseable format. |
| Publication cadence | The source's own stated or observed publication frequency. |
| Actual freshness | Freshness as independently observed, not merely as claimed. |
| Geography | Country/region coverage. |
| Logistics role | Which layer(s) and entity type(s) (Section 8 of the scope document) the source feeds. |
| Known limitations | Caveats, gaps, or unresolved conflicts (see the `TMD_CAP` entry in `config/sources.yaml` for the existing standard of detail). |
| Prototype eligibility | Whether the source currently qualifies for the free-only Prototype (Section 3.7 of the scope document). |
| Fallback source | An alternate source to use if this one is unavailable, if one exists. |

## Free-only qualification

A source is eligible for the public Prototype only when Priority-1/2/3 use does not depend
on a paid tier, and when access cost, licence status, and redistribution status are
recorded and reviewed. This document does not perform that review for any specific source;
`config/sources.yaml` remains the authoritative registry of reviewed source state, and no
entry in it is changed by WO-009A.

## Relationship to existing source governance

- `methodology/source_policy.md` remains the general, platform-wide source-priority
  ordering; this document is the Logistics-specific refinement referenced by
  `docs/thailand_multimodal_logistics_intelligence_scope.md`.
- `config/sources.yaml` remains the single authoritative, machine-readable source contract
  registry. This framework does not alter any field of any entry in it.
- Existing per-source governance records (e.g. Issue #15 for `TMD_CAP`) remain the
  authoritative disposition for that specific source and are not superseded by this
  framework document.
