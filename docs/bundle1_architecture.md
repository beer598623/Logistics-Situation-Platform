# Bundle 1 implementation architecture

**Work Order:** WO-010
**Authorized baseline:** `e2acb7794f09eea89a7d48042aa6e367e382d4d8`
**Delivery bundle:** Bundle 1 — Common Foundation + Ocean Logistics Intelligence MVP
**Status:** implemented, pending independent review

This document describes what WO-010 actually built. Where a capability is planned rather
than implemented, it says so explicitly.

## 1. What is implemented and what is not

| Capability | Status |
|---|---|
| Common multimodal data foundation (18 conceptual entities) | **Implemented** |
| Thailand-centred Ocean lane model (11 lane groups) | **Implemented** |
| Deterministic indicators and documented threshold rules | **Implemented** |
| Event model with lifecycle, clustering and transmission chains | **Implemented** |
| Nine-area impact assessment | **Implemented** |
| Scenario outlooks and conditional preparedness options | **Implemented** |
| Human-triggered ChatGPT package, contracts and rejection rules | **Implemented** |
| Historical analytical validation (8 cases) | **Implemented** |
| Static Dashboard (7 sections) | **Implemented** |
| Derived DuckDB warehouse | **Implemented** |
| **Live source collection** | **Not enabled.** No source could be live-validated; see §7 |
| Air Cargo module | Planned (Bundle 2) |
| Land, Rail and Border module | Planned (Bundle 3) |
| Private Decision Overlay | Planned (Phase 7), local-only |

## 2. Layered architecture

The four layers from `docs/thailand_multimodal_logistics_intelligence_scope.md` §6 map onto
concrete artefacts:

| Layer | Artefacts |
|---|---|
| **1 — Logistics baseline** | `data/observations/{indicator,trade,port,cost}_observations.json`, derived by `analysis/indicators.py` |
| **2 — Operational events** | `data/events/events.json` where `event_class = direct_operational_event` |
| **3 — External drivers** | Same file, `event_class = external_driver`; admitted only with a complete chain |
| **4 — Assessment and outlook** | `data/assessments/{lane_assessments,thailand_assessment,assessment_history}.json` |

## 3. Data flow

```
config/sources.yaml                     contracts, qualification, enablement blockers
  │
  ├─ collectors/adapters/csv_series.py  bounded numeric parsing
  ├─ collectors/adapters/notice_feed.py bounded notice and discovery intake
  │        (both fixture-first; neither fetches anything itself)
  ↓
data/observations/**, data/events/**    version-controlled, reviewable source of truth
  │
  ↓  analysis/{indicators,thresholds,reference,events,assessments,scenarios}.py
data/assessments/**                     derived, deterministic, byte-stable
  │
  ├─→ scripts/build_warehouse.py  →  warehouse/logistics.duckdb   [generated, gitignored]
  │
  └─→ scripts/build_dashboard.py  →  dashboard/public/data/*.json  →  static site

data/** ─→ scripts/build_review_package.py ─→ data/review/packages/*.json
             │
             │  [human runs ChatGPT out-of-band — no API call from this repository]
             ↓
           data/review/inbound/*.json
             │  scripts/import_review.py       schema + Gate I rejection rules
             ↓  scripts/review_decision.py     explicit human approve/reject, archives prior
           data/assessments/approved/*.json ─→ Dashboard "AI Outlook" section
```

## 4. Module inventory

### `collectors/` — normalization, never interpretation

Pre-existing (unchanged): `http_client` (bounded fetch, no-redirect discovery transport,
DNS-pinned candidate transport), `registry`, `models`, `staging`, `source_health`,
`event_identity`, `error_classification`, `url_redaction`, and the CAP/TMD/GDACS/RSS
adapters.

Added by WO-010:

- `observations.py` — the single builder for every `fact_*_observation` record. Enforces
  the value/`value_status` invariant at construction time.
- `series_catalog.py` — metadata mapping CSV columns to observation records, so one generic
  parser serves every structured numeric source.
- `adapters/csv_series.py` — bounded CSV parser, fail-closed.
- `adapters/notice_feed.py` — bounded RSS/Atom notice and discovery intake, plus the manual
  reviewed-notice path. Records a discovered link; never follows one.

### `analysis/` — deterministic interpretation

- `contracts.py` — shared JSON Schema registry and validation.
- `thresholds.py` — the seven documented direction rules.
- `indicators.py` — series derivation with explicit gap accounting.
- `reference.py` — dimension access, lane membership, Thailand-relevance resolution.
- `events.py` — clustering, transmission-chain completeness, evidence rules, event
  semantic validation.
- `assessments.py` — nine-domain roll-up, point-forecast and preparedness guards.
- `scenarios.py` — deterministic base/deterioration/improvement generation.
- `review_package.py` — ChatGPT package assembly and the Gate I rejection rules.
- `warehouse.py` — derived DuckDB schema and loader.

### `scripts/` — entry points

`generate_synthetic_fixtures` → `ingest_fixtures` → `build_events_from_cases` →
`build_analysis` → `run_historical_validation` → `build_warehouse` → `build_dashboard`,
plus `validate`, `collect --dry-run`, `build_review_package`, `import_review`,
`review_decision`, and the pre-existing `manual_live_source_test`.

Every generator has a `--check` mode that regenerates in memory and fails if the committed
output no longer matches its inputs. `tests/test_derived_outputs.py` runs all of them.

## 5. Separation of deterministic analysis from AI interpretation

This separation is structural, not stylistic:

- `analysis/` computes directions from documented rule IDs. Every published direction cites
  the rule that produced it, and `scripts/validate.py` rejects a direction that cites a rule
  which could not have been applied.
- The Dashboard's *AI Outlook* section reads **only** `data/assessments/approved/`. Nothing
  else can reach it.
- The deterministic lane outlooks are shown in the same section but under their own heading
  and explicitly labelled as not being an AI assessment.

## 6. Extensibility to Air and Land

No shared entity encodes an Ocean-only assumption. This is asserted by tests, not just
stated — see `tests/test_reference_and_lanes.py`:

- `observation_common.schema.json` permits `sea`, `air`, `road`, `rail`, `border`,
  `inland_waterway`, `multimodal` and `not_applicable`.
- `dim_logistics_node` already carries an airport (`NODE-THBKKAIR`) and a border crossing
  (`NODE-THSDK`); `dim_chokepoint` already carries a road/border corridor
  (`CHK-THSDK-BKH`). None carries data yet — they exist so the claim is checkable.
- `port_transport_observation.schema.json` is named for transport, not ports, and its metric
  enum already includes `aircraft_movements`, `border_crossings` and `rail_movements`.
- A Lane carries its mode as data. Adding an Air lane is a new record, not a schema change.

See `docs/air_land_extension_points.md`.

## 7. The material limitation of this delivery

Outbound network access in the WO-010 execution environment was blocked by policy, and the
repository's own governance requires live source contact to run through the human-triggered
`manual-live-source-test` workflow rather than from an automated executor. Consequently:

- **No source is enabled.** All 15 registry contracts remain `enabled: false`, each with its
  exact unresolved blockers recorded.
- **All numeric series are labelled synthetic test fixtures**
  (`evidence_class: synthetic_test_fixture`), generated by a committed generator whose
  output is byte-reproducible.
- **All event evidence is a historical validation fixture** carrying the publisher's
  original URL and an explicit statement that the content was not retrieved.
- **Live coverage is declared insufficient** on the Dashboard's face, in the build status,
  in the source-health snapshot and in every lane assessment.

This is the Section 8 fallback disposition and the Section 13 technical-MVP outcome the Work
Order provides for. See `docs/source_qualification_report.md` and `docs/known_data_gaps.md`.

## 8. Related documents

`data_model_and_persistence.md`, `source_qualification_report.md`,
`source_enablement_decisions.md`, `ocean_lane_selection.md`, `indicator_definitions.md`,
`freight_proxy_limitations.md`, `port_pressure_interpretation.md`, `event_lifecycle.md`,
`external_driver_admission.md`, `chatgpt_review_workflow.md`, `human_review_process.md`,
`historical_validation.md`, `dashboard_user_guide.md`, `operations_runbook.md`,
`security_and_privacy_boundary.md`, `known_data_gaps.md`, `air_land_extension_points.md`.
