# Data model and persistence

**Work Order:** WO-010 · **Status:** implemented

## 1. Persistence decision

**Version-controlled JSON is the source of truth. DuckDB is a derived read model.**

| Layer | Location | Committed? | Authority |
|---|---|---|---|
| Reference dimensions | `data/reference/` | yes | authoritative |
| Observations | `data/observations/` | yes | authoritative |
| Events and evidence | `data/events/` | yes | authoritative |
| Assessments and history | `data/assessments/` | yes | authoritative (derived, byte-stable) |
| Review packages and decisions | `data/review/`, `data/assessments/approved/` | yes | authoritative |
| Analytical warehouse | `warehouse/logistics.duckdb` | **no — gitignored** | derived only |
| Dashboard payloads | `dashboard/public/data/` | yes | derived only |
| Raw responses, caches, credentials | — | **never** | must not exist |

### Why this direction

A reviewer can diff JSON. A reviewer cannot diff a binary database. Since every material
conclusion this platform publishes has to be independently checkable, the reviewable form
has to be the authoritative one, and anything faster has to be reproducible from it.

### DuckDB adoption

DuckDB is adopted as the preferred derived warehouse, with the Work Order's conditions met:

| Requirement | How it is met |
|---|---|
| Pin the dependency | `duckdb==1.4.1` in `requirements.txt`, `requirements.lock` and `pyproject.toml` |
| Deterministic schema creation | `analysis/warehouse.py::SCHEMA_STATEMENTS`, a fixed ordered statement list with no migration state |
| Idempotent creation | Tables are dropped and recreated on every build; two builds produce identical content fingerprints |
| Clean rebuild test | `tests/test_warehouse.py::test_rebuilding_over_an_existing_database_is_idempotent` and `::test_two_independent_clean_builds_agree` |
| Exclude generated files | `.gitignore` covers `warehouse/`, `*.duckdb`, `*.duckdb.wal`; a test asserts the path is ignored |
| No browser dependency on a DuckDB service | The Dashboard reads static JSON only; a test asserts the page fetches nothing outside `data/` |

Timestamps are stored as ISO-8601 `VARCHAR` rather than `TIMESTAMPTZ`. The source records
already carry exact UTC strings; storing them verbatim avoids both a lossy coercion and
DuckDB's optional timezone-database dependency, in a read model where the JSON remains the
authority on every value.

## 2. Conceptual entities

All eighteen entities named in the approved architecture are implemented.

| Entity | Contract | Storage | Warehouse table |
|---|---|---|---|
| `dim_source` | `source_contract.schema.json` | `config/sources.yaml` | `dim_source` |
| `dim_geography` | `reference_dimensions.schema.json` | `data/reference/dimensions.json` | `dim_geography` |
| `dim_country` | same | same | `dim_country` |
| `dim_transport_mode` | same | same | `dim_transport_mode` |
| `dim_logistics_node` | same | same | `dim_logistics_node` |
| `dim_chokepoint` | same | same | `dim_chokepoint` |
| `dim_lane` | `lane.schema.json` | `data/reference/lanes.json` | `dim_lane` |
| `fact_indicator_observation` | `indicator_observation.schema.json` | `data/observations/indicator_observations.json` | `fact_indicator_observation` |
| `fact_trade_observation` | `trade_observation.schema.json` | `data/observations/trade_observations.json` | `fact_trade_observation` |
| `fact_port_or_transport_observation` | `port_transport_observation.schema.json` | `data/observations/port_observations.json` | `fact_port_or_transport_observation` |
| `fact_cost_observation` | `cost_observation.schema.json` | `data/observations/cost_observations.json` | `fact_cost_observation` |
| `fact_event` | `logistics_event.schema.json` | `data/events/events.json` | `fact_event` |
| `fact_event_evidence` | `event_evidence.schema.json` | `data/events/event_evidence.json` | `fact_event_evidence` |
| `fact_lane_assessment` | `lane_assessment.schema.json` | `data/assessments/lane_assessments.json` | `fact_lane_assessment` |
| `fact_impact_assessment` | `impact_assessment.schema.json` | embedded in each event | `fact_impact_assessment` |
| `fact_preparedness_option` | `preparedness_option.schema.json` | embedded in events and lane assessments | `fact_preparedness_option` |
| `fact_source_health` | `source_status.schema.json` | `data/source_status/latest.json` | `fact_source_health` |
| `fact_assessment_history` | `assessment_history.schema.json` | `data/assessments/assessment_history.json` | `fact_assessment_history` |

Plus `fact_observation_revision`, a warehouse-only table that keeps every version of every
observation so a revision never erases what was previously published.

## 3. The observation contract

Every observation carries three blocks, defined once in
`schemas/observation_common.schema.json` and referenced by all four families:

- **`provenance`** — `record_id`, `source_id`, `source_record_id`, period start/end/type,
  `published_at`, `retrieved_at`, `revised_at`, `revision_number`, `content_sha256`,
  `parser_version`, `source_revision`, `evidence_class`, `known_limitations`.
- **`measurement`** — `value`, `value_status`, `unit`, `currency`.
- **`placement`** — `geography_id`, `country_id`, `transport_mode`, `lane_id`, `node_id`.

### Missing is never zero

`value` is non-null **if and only if** `value_status` is `available`. This is enforced in
three independent places, so no single mistake can defeat it:

1. `collectors/observations.py::build_observation` raises `ObservationContractError` at
   construction time.
2. `schemas/observation_common.schema.json` documents the rule and constrains the enum.
3. `scripts/validate.py::observation_checks` re-checks every committed record.

The permitted non-available statuses are `missing`, `not_published`, `suppressed`,
`retrieval_failed` and `not_collected` — each says something different about *why* there is
no value.

Zero is a legitimate value when the source published zero. What is forbidden is zero as a
*substitute* for absence. `tests/test_observation_contract.py` asserts both directions.

### Record identity, duplicates and revisions

`record_id` is `OBS-<SOURCE>-<series>-<period>`, derived deterministically. Re-collecting a
period therefore **updates** rather than duplicates. When two records share a `record_id`,
the higher `revision_number` becomes current and every version is retained in
`fact_observation_revision`.

## 4. Contracts added by WO-010

`observation_common`, `indicator_observation`, `trade_observation`,
`port_transport_observation`, `cost_observation`, `reference_dimensions`, `lane`,
`logistics_event`, `event_evidence`, `lane_assessment`, `scenario_outlook`,
`assessment_history`, `review_package_input`, `review_package_output` — fourteen new files,
plus additive `qualification` and `enablement` blocks on `source_contract.schema.json`.

The pre-existing contracts (`candidate_event`, `collection_run`, `decision_package`,
`evidence`, `impact_assessment`, `preparedness_option`, `reviewed_event`, `solution`,
`source_status`, `staging_record`) are unchanged. `impact_assessment` and
`preparedness_option` are reused directly by the new event model rather than duplicated.

### Why `qualification` and `enablement` are optional at schema level

They are mandatory in practice — `scripts/validate.py` requires both on every WO-010 source
and reports any source lacking them. They are not JSON-Schema-required so that the
pre-existing `TMD_CAP` and `GDACS` contracts, which WO-010 is prohibited from modifying,
remain valid unchanged.

## 5. Reproducibility

Every generated artefact has a `--check` mode:

```bash
python scripts/generate_synthetic_fixtures.py   # regenerating must be a no-op
python scripts/ingest_fixtures.py --check
python scripts/build_events_from_cases.py --check
python scripts/build_analysis.py --check
```

`build_analysis.py` pins "now" to a fixed `DATA_CUTOFF` rather than the wall clock, so
freshness ages — and therefore the published directions — are stable across rebuilds.
`tests/test_derived_outputs.py` runs every check.
