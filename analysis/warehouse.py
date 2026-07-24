"""Derived DuckDB analytical warehouse.

The warehouse is **derived**, never authoritative. Version-controlled JSON
under ``data/`` remains the reviewable source of truth; this module rebuilds a
queryable copy from it. That direction is deliberate: a reviewer diffs JSON,
not a binary database, and the generated ``.duckdb`` file is gitignored.

Three properties are guaranteed and tested:

* **Deterministic.** Schema creation is a fixed statement list, applied in
  order, with no migration state.
* **Idempotent.** Building twice over the same inputs produces the same
  content. The build drops and recreates rather than appending.
* **Revision-preserving.** When the same ``record_id`` appears more than once
  with different revision numbers, the current table keeps the highest
  revision and ``fact_observation_revision`` keeps every version, so history
  is never silently overwritten.

The browser never talks to DuckDB. The Dashboard reads static JSON that
``scripts/build_dashboard.py`` exports, so the published site has no
server-side dependency at all.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Default location of the generated database. Gitignored.
DEFAULT_WAREHOUSE_PATH = ROOT / "warehouse" / "logistics.duckdb"

#: Ordered DDL. Tables are dropped and recreated on every build, which is what
#: makes the build idempotent without any migration bookkeeping.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    "DROP TABLE IF EXISTS fact_assessment_history",
    "DROP TABLE IF EXISTS fact_source_health",
    "DROP TABLE IF EXISTS fact_preparedness_option",
    "DROP TABLE IF EXISTS fact_impact_assessment",
    "DROP TABLE IF EXISTS fact_lane_assessment",
    "DROP TABLE IF EXISTS fact_event_evidence",
    "DROP TABLE IF EXISTS fact_event",
    "DROP TABLE IF EXISTS fact_observation_revision",
    "DROP TABLE IF EXISTS fact_cost_observation",
    "DROP TABLE IF EXISTS fact_port_or_transport_observation",
    "DROP TABLE IF EXISTS fact_trade_observation",
    "DROP TABLE IF EXISTS fact_indicator_observation",
    "DROP TABLE IF EXISTS dim_chokepoint",
    "DROP TABLE IF EXISTS dim_lane",
    "DROP TABLE IF EXISTS dim_logistics_node",
    "DROP TABLE IF EXISTS dim_transport_mode",
    "DROP TABLE IF EXISTS dim_country",
    "DROP TABLE IF EXISTS dim_geography",
    "DROP TABLE IF EXISTS dim_source",
    """
    CREATE TABLE dim_source (
        source_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        owner VARCHAR NOT NULL,
        source_class VARCHAR NOT NULL,
        access_method VARCHAR,
        format VARCHAR,
        machine_readable_status VARCHAR,
        licence_status VARCHAR,
        access_cost VARCHAR,
        redistribution_status VARCHAR,
        reuse_status VARCHAR,
        prototype_eligibility VARCHAR,
        publication_cadence VARCHAR,
        observed_freshness VARCHAR,
        data_period VARCHAR,
        logistics_role VARCHAR,
        enabled BOOLEAN NOT NULL,
        required_for_publication BOOLEAN NOT NULL,
        live_validation_status VARCHAR,
        blockers VARCHAR,
        known_limitations VARCHAR
    )
    """,
    """
    CREATE TABLE dim_geography (
        geography_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        level VARCHAR NOT NULL,
        parent_geography_id VARCHAR,
        thailand_relationship VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE dim_country (
        country_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        iso3 VARCHAR,
        region_geography_id VARCHAR NOT NULL,
        thailand_relationship VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE dim_transport_mode (
        mode_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        module_status VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE dim_logistics_node (
        node_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        node_type VARCHAR NOT NULL,
        country_id VARCHAR NOT NULL,
        geography_id VARCHAR NOT NULL,
        unlocode VARCHAR,
        modes VARCHAR NOT NULL,
        thailand_relationship VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE dim_lane (
        lane_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        mode VARCHAR NOT NULL,
        direction VARCHAR NOT NULL,
        resolution VARCHAR NOT NULL,
        origin_label VARCHAR NOT NULL,
        destination_label VARCHAR NOT NULL,
        country_ids VARCHAR NOT NULL,
        node_ids VARCHAR NOT NULL,
        chokepoint_ids VARCHAR NOT NULL,
        data_period_used VARCHAR,
        review_date VARCHAR NOT NULL,
        status VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE dim_chokepoint (
        chokepoint_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        chokepoint_type VARCHAR NOT NULL,
        geography_id VARCHAR NOT NULL,
        modes VARCHAR NOT NULL,
        operating_authority VARCHAR,
        thailand_relationship VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE fact_indicator_observation (
        record_id VARCHAR PRIMARY KEY,
        indicator_id VARCHAR NOT NULL,
        indicator_name VARCHAR NOT NULL,
        indicator_family VARCHAR,
        source_id VARCHAR NOT NULL,
        source_record_id VARCHAR,
        geography_id VARCHAR,
        country_id VARCHAR,
        transport_mode VARCHAR NOT NULL,
        lane_id VARCHAR,
        node_id VARCHAR,
        value DOUBLE,
        value_status VARCHAR NOT NULL,
        unit VARCHAR,
        currency VARCHAR,
        period_start DATE,
        period_end DATE,
        period_type VARCHAR NOT NULL,
        published_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL,
        revised_at TIMESTAMPTZ,
        revision_number INTEGER NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        parser_version VARCHAR NOT NULL,
        source_revision VARCHAR,
        evidence_class VARCHAR NOT NULL,
        baseline_definition VARCHAR,
        known_limitations VARCHAR
    )
    """,
    """
    CREATE TABLE fact_trade_observation (
        record_id VARCHAR PRIMARY KEY,
        series_id VARCHAR NOT NULL,
        flow_direction VARCHAR NOT NULL,
        reporter_country_id VARCHAR NOT NULL,
        partner_country_id VARCHAR,
        partner_scope VARCHAR NOT NULL,
        partner_label VARCHAR,
        commodity_scope VARCHAR,
        measure VARCHAR NOT NULL,
        source_id VARCHAR NOT NULL,
        source_record_id VARCHAR,
        geography_id VARCHAR,
        country_id VARCHAR,
        transport_mode VARCHAR NOT NULL,
        lane_id VARCHAR,
        node_id VARCHAR,
        value DOUBLE,
        value_status VARCHAR NOT NULL,
        unit VARCHAR,
        currency VARCHAR,
        period_start DATE,
        period_end DATE,
        period_type VARCHAR NOT NULL,
        published_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL,
        revised_at TIMESTAMPTZ,
        revision_number INTEGER NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        parser_version VARCHAR NOT NULL,
        source_revision VARCHAR,
        evidence_class VARCHAR NOT NULL,
        known_limitations VARCHAR
    )
    """,
    """
    CREATE TABLE fact_port_or_transport_observation (
        record_id VARCHAR PRIMARY KEY,
        series_id VARCHAR NOT NULL,
        metric VARCHAR NOT NULL,
        operational_interpretation VARCHAR NOT NULL,
        resolution VARCHAR,
        source_id VARCHAR NOT NULL,
        source_record_id VARCHAR,
        geography_id VARCHAR,
        country_id VARCHAR,
        transport_mode VARCHAR NOT NULL,
        lane_id VARCHAR,
        node_id VARCHAR,
        value DOUBLE,
        value_status VARCHAR NOT NULL,
        unit VARCHAR,
        currency VARCHAR,
        period_start DATE,
        period_end DATE,
        period_type VARCHAR NOT NULL,
        published_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL,
        revised_at TIMESTAMPTZ,
        revision_number INTEGER NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        parser_version VARCHAR NOT NULL,
        source_revision VARCHAR,
        evidence_class VARCHAR NOT NULL,
        known_limitations VARCHAR
    )
    """,
    """
    CREATE TABLE fact_cost_observation (
        record_id VARCHAR PRIMARY KEY,
        series_id VARCHAR NOT NULL,
        cost_family VARCHAR NOT NULL,
        benchmark_class VARCHAR NOT NULL,
        quotation_claim VARCHAR NOT NULL,
        route_scope VARCHAR,
        applies_to_thailand VARCHAR,
        source_id VARCHAR NOT NULL,
        source_record_id VARCHAR,
        geography_id VARCHAR,
        country_id VARCHAR,
        transport_mode VARCHAR NOT NULL,
        lane_id VARCHAR,
        node_id VARCHAR,
        value DOUBLE,
        value_status VARCHAR NOT NULL,
        unit VARCHAR,
        currency VARCHAR,
        period_start DATE,
        period_end DATE,
        period_type VARCHAR NOT NULL,
        published_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL,
        revised_at TIMESTAMPTZ,
        revision_number INTEGER NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        parser_version VARCHAR NOT NULL,
        source_revision VARCHAR,
        evidence_class VARCHAR NOT NULL,
        known_limitations VARCHAR
    )
    """,
    """
    CREATE TABLE fact_observation_revision (
        observation_family VARCHAR NOT NULL,
        record_id VARCHAR NOT NULL,
        revision_number INTEGER NOT NULL,
        value DOUBLE,
        value_status VARCHAR NOT NULL,
        revised_at TIMESTAMPTZ,
        retrieved_at TIMESTAMPTZ NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        PRIMARY KEY (observation_family, record_id, revision_number)
    )
    """,
    """
    CREATE TABLE fact_event (
        event_id VARCHAR PRIMARY KEY,
        canonical_event_id VARCHAR NOT NULL,
        title VARCHAR NOT NULL,
        event_class VARCHAR NOT NULL,
        event_type VARCHAR NOT NULL,
        lifecycle_status VARCHAR NOT NULL,
        event_date DATE,
        event_end_date DATE,
        publication_date DATE,
        retrieval_date TIMESTAMPTZ NOT NULL,
        geography_ids VARCHAR NOT NULL,
        country_ids VARCHAR NOT NULL,
        node_ids VARCHAR,
        chokepoint_ids VARCHAR,
        modes VARCHAR NOT NULL,
        operator_or_entity VARCHAR,
        thailand_relevance VARCHAR NOT NULL,
        event_severity VARCHAR,
        transmission_completeness VARCHAR NOT NULL,
        negative_operational_evidence BOOLEAN,
        publication_status VARCHAR NOT NULL,
        human_review_required BOOLEAN NOT NULL,
        human_review_status VARCHAR NOT NULL,
        cluster_id VARCHAR,
        cluster_key VARCHAR NOT NULL,
        last_reviewed_at TIMESTAMPTZ NOT NULL,
        closure_basis VARCHAR
    )
    """,
    """
    CREATE TABLE fact_event_evidence (
        evidence_id VARCHAR PRIMARY KEY,
        event_id VARCHAR NOT NULL,
        source_id VARCHAR NOT NULL,
        source_name VARCHAR NOT NULL,
        source_class VARCHAR NOT NULL,
        source_url VARCHAR,
        source_record_id VARCHAR,
        claim VARCHAR NOT NULL,
        claim_type VARCHAR NOT NULL,
        evidence_role VARCHAR NOT NULL,
        relation VARCHAR NOT NULL,
        strength VARCHAR NOT NULL,
        scope_supported VARCHAR NOT NULL,
        event_date DATE,
        publication_date DATE,
        retrieved_at TIMESTAMPTZ NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        parser_version VARCHAR NOT NULL,
        licence_status VARCHAR NOT NULL,
        redistribution_status VARCHAR
    )
    """,
    """
    CREATE TABLE fact_lane_assessment (
        assessment_id VARCHAR PRIMARY KEY,
        lane_id VARCHAR NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL,
        data_cutoff_at TIMESTAMPTZ,
        overall_direction VARCHAR NOT NULL,
        attention_level VARCHAR NOT NULL,
        domain VARCHAR NOT NULL,
        domain_direction VARCHAR NOT NULL,
        threshold_rule_id VARCHAR,
        data_period VARCHAR,
        freshness_status VARCHAR NOT NULL,
        PRIMARY KEY (assessment_id, domain)
    )
    """,
    """
    CREATE TABLE fact_impact_assessment (
        event_id VARCHAR NOT NULL,
        area VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        severity VARCHAR NOT NULL,
        relevance VARCHAR NOT NULL,
        geographic_scope VARCHAR NOT NULL,
        time_horizon VARCHAR NOT NULL,
        expected_duration VARCHAR NOT NULL,
        evidence_strength VARCHAR NOT NULL,
        confidence VARCHAR NOT NULL,
        transmission_mechanism VARCHAR,
        evidence_ids VARCHAR,
        known_limitations VARCHAR,
        PRIMARY KEY (event_id, area)
    )
    """,
    """
    CREATE TABLE fact_preparedness_option (
        subject_type VARCHAR NOT NULL,
        subject_id VARCHAR NOT NULL,
        option_index INTEGER NOT NULL,
        option_type VARCHAR NOT NULL,
        description VARCHAR NOT NULL,
        applicable_to VARCHAR NOT NULL,
        trigger_condition VARCHAR NOT NULL,
        exit_condition VARCHAR NOT NULL,
        evidence_basis VARCHAR,
        PRIMARY KEY (subject_type, subject_id, option_index)
    )
    """,
    """
    CREATE TABLE fact_source_health (
        source_id VARCHAR PRIMARY KEY,
        status VARCHAR NOT NULL,
        last_checked_at TIMESTAMPTZ,
        last_success_at TIMESTAMPTZ,
        last_error VARCHAR,
        item_count INTEGER,
        required_for_publication BOOLEAN NOT NULL,
        max_stale_minutes INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE fact_assessment_history (
        history_id VARCHAR PRIMARY KEY,
        subject_type VARCHAR NOT NULL,
        subject_id VARCHAR NOT NULL,
        revision_number INTEGER NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL,
        action VARCHAR NOT NULL,
        content_sha256 VARCHAR NOT NULL,
        supersedes_history_id VARCHAR,
        summary VARCHAR NOT NULL,
        reviewer_record VARCHAR,
        archive_path VARCHAR
    )
    """,
)

def _joined(values: Iterable[Any] | None) -> str | None:
    if values is None:
        return None
    items = [str(value) for value in values]
    return "|".join(items) if items else ""


def _dedupe_keep_latest_revision(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Collapse duplicate ``record_id``s, keeping the highest revision.

    Returns ``(current, all_versions)``. Every version is retained in the
    second list so that ``fact_observation_revision`` preserves history --
    a later revision updates what is current without erasing what was
    previously published.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        record_id = record["provenance"]["record_id"]
        revision = int(record["provenance"].get("revision_number", 0))
        existing = by_id.get(record_id)
        if existing is None or revision >= int(existing["provenance"].get("revision_number", 0)):
            by_id[record_id] = record
    return [by_id[key] for key in sorted(by_id)], list(records)


def _observation_row(record: Mapping[str, Any]) -> dict[str, Any]:
    provenance = record["provenance"]
    measurement = record["measurement"]
    placement = record["placement"]
    return {
        "record_id": provenance["record_id"],
        "source_id": provenance["source_id"],
        "source_record_id": provenance.get("source_record_id"),
        "geography_id": placement.get("geography_id"),
        "country_id": placement.get("country_id"),
        "transport_mode": placement["transport_mode"],
        "lane_id": placement.get("lane_id"),
        "node_id": placement.get("node_id"),
        "value": measurement.get("value"),
        "value_status": measurement["value_status"],
        "unit": measurement.get("unit"),
        "currency": measurement.get("currency"),
        "period_start": provenance.get("period_start"),
        "period_end": provenance.get("period_end"),
        "period_type": provenance["period_type"],
        "published_at": provenance.get("published_at"),
        "retrieved_at": provenance["retrieved_at"],
        "revised_at": provenance.get("revised_at"),
        "revision_number": int(provenance.get("revision_number", 0)),
        "content_sha256": provenance["content_sha256"],
        "parser_version": provenance["parser_version"],
        "source_revision": provenance.get("source_revision"),
        "evidence_class": provenance["evidence_class"],
        "known_limitations": _joined(provenance.get("known_limitations")),
    }


def _insert(connection: Any, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ", ".join("?" for _ in columns)
    statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    connection.executemany(statement, [[row[column] for column in columns] for row in rows])


def create_schema(connection: Any) -> None:
    """Apply the deterministic schema. Safe to call on an existing database."""
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)


def load_bundle(bundle: Mapping[str, Any], connection: Any) -> dict[str, int]:
    """Load one already-assembled data bundle into an open connection.

    Returns per-table row counts so the caller can report what was built
    without querying the database again.
    """
    counts: dict[str, int] = {}

    sources = []
    for source in bundle.get("sources", []):
        qualification = source.get("qualification", {})
        enablement = source.get("enablement", {})
        sources.append(
            {
                "source_id": source["id"],
                "name": source["name"],
                "owner": source["owner"],
                "source_class": source["source_class"],
                "access_method": source.get("access_method"),
                "format": source.get("format"),
                "machine_readable_status": source.get("machine_readable_status"),
                "licence_status": source.get("licence_status"),
                "access_cost": qualification.get("access_cost"),
                "redistribution_status": qualification.get("redistribution_status"),
                "reuse_status": qualification.get("reuse_status"),
                "prototype_eligibility": qualification.get("prototype_eligibility"),
                "publication_cadence": qualification.get("publication_cadence"),
                "observed_freshness": qualification.get("observed_freshness"),
                "data_period": qualification.get("data_period"),
                "logistics_role": _joined(qualification.get("logistics_role")),
                "enabled": bool(source.get("enabled")),
                "required_for_publication": bool(source.get("required_for_publication")),
                "live_validation_status": enablement.get("live_validation_status"),
                "blockers": _joined(enablement.get("blockers")),
                "known_limitations": _joined(source.get("known_limitations")),
            }
        )
    _insert(connection, "dim_source", sources)
    counts["dim_source"] = len(sources)

    dimensions = bundle.get("dimensions", {})
    geographies = [
        {
            "geography_id": item["geography_id"],
            "name": item["name"],
            "level": item["level"],
            "parent_geography_id": item.get("parent_geography_id"),
            "thailand_relationship": item["thailand_relationship"],
        }
        for item in dimensions.get("geographies", [])
    ]
    _insert(connection, "dim_geography", geographies)
    counts["dim_geography"] = len(geographies)

    countries = [
        {
            "country_id": item["country_id"],
            "name": item["name"],
            "iso3": item.get("iso3"),
            "region_geography_id": item["region_geography_id"],
            "thailand_relationship": item["thailand_relationship"],
        }
        for item in dimensions.get("countries", [])
    ]
    _insert(connection, "dim_country", countries)
    counts["dim_country"] = len(countries)

    modes = [
        {
            "mode_id": item["mode_id"],
            "name": item["name"],
            "module_status": item["module_status"],
        }
        for item in dimensions.get("transport_modes", [])
    ]
    _insert(connection, "dim_transport_mode", modes)
    counts["dim_transport_mode"] = len(modes)

    nodes = [
        {
            "node_id": item["node_id"],
            "name": item["name"],
            "node_type": item["node_type"],
            "country_id": item["country_id"],
            "geography_id": item["geography_id"],
            "unlocode": item.get("unlocode"),
            "modes": _joined(item["modes"]),
            "thailand_relationship": item["thailand_relationship"],
        }
        for item in dimensions.get("logistics_nodes", [])
    ]
    _insert(connection, "dim_logistics_node", nodes)
    counts["dim_logistics_node"] = len(nodes)

    chokepoints = [
        {
            "chokepoint_id": item["chokepoint_id"],
            "name": item["name"],
            "chokepoint_type": item["chokepoint_type"],
            "geography_id": item["geography_id"],
            "modes": _joined(item["modes"]),
            "operating_authority": item.get("operating_authority"),
            "thailand_relationship": item["thailand_relationship"],
        }
        for item in dimensions.get("chokepoints", [])
    ]
    _insert(connection, "dim_chokepoint", chokepoints)
    counts["dim_chokepoint"] = len(chokepoints)

    lanes = [
        {
            "lane_id": lane["lane_id"],
            "name": lane["name"],
            "mode": lane["mode"],
            "direction": lane["direction"],
            "resolution": lane["resolution"],
            "origin_label": lane["origin_scope"]["label"],
            "destination_label": lane["destination_scope"]["label"],
            "country_ids": _joined(lane["country_ids"]),
            "node_ids": _joined(lane.get("node_ids", [])),
            "chokepoint_ids": _joined(lane.get("chokepoint_ids", [])),
            "data_period_used": lane.get("data_period_used"),
            "review_date": lane["review_date"],
            "status": lane["status"],
        }
        for lane in bundle.get("lanes", [])
    ]
    _insert(connection, "dim_lane", lanes)
    counts["dim_lane"] = len(lanes)

    revision_rows: list[dict[str, Any]] = []
    families = {
        "fact_indicator_observation": (
            "indicator_observations",
            lambda record: {
                "indicator_id": record["indicator_id"],
                "indicator_name": record["indicator_name"],
                "indicator_family": record.get("indicator_family"),
                "baseline_definition": record.get("baseline_definition"),
            },
        ),
        "fact_trade_observation": (
            "trade_observations",
            lambda record: {
                "series_id": record["series_id"],
                "flow_direction": record["flow_direction"],
                "reporter_country_id": record["reporter_country_id"],
                "partner_country_id": record.get("partner_country_id"),
                "partner_scope": record["partner_scope"],
                "partner_label": record.get("partner_label"),
                "commodity_scope": record.get("commodity_scope"),
                "measure": record["measure"],
            },
        ),
        "fact_port_or_transport_observation": (
            "port_observations",
            lambda record: {
                "series_id": record["series_id"],
                "metric": record["metric"],
                "operational_interpretation": record["operational_interpretation"],
                "resolution": record.get("resolution"),
            },
        ),
        "fact_cost_observation": (
            "cost_observations",
            lambda record: {
                "series_id": record["series_id"],
                "cost_family": record["cost_family"],
                "benchmark_class": record["benchmark_class"],
                "quotation_claim": record["quotation_claim"],
                "route_scope": record.get("route_scope"),
                "applies_to_thailand": record.get("applies_to_thailand"),
            },
        ),
    }

    for table, (bundle_key, extra) in families.items():
        records = bundle.get(bundle_key, [])
        current, all_versions = _dedupe_keep_latest_revision(records)
        rows = [{**extra(record), **_observation_row(record)} for record in current]
        _insert(connection, table, rows)
        counts[table] = len(rows)
        for record in all_versions:
            provenance = record["provenance"]
            revision_rows.append(
                {
                    "observation_family": table,
                    "record_id": provenance["record_id"],
                    "revision_number": int(provenance.get("revision_number", 0)),
                    "value": record["measurement"].get("value"),
                    "value_status": record["measurement"]["value_status"],
                    "revised_at": provenance.get("revised_at"),
                    "retrieved_at": provenance["retrieved_at"],
                    "content_sha256": provenance["content_sha256"],
                }
            )

    deduped_revisions: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in revision_rows:
        deduped_revisions[
            (row["observation_family"], row["record_id"], row["revision_number"])
        ] = row
    ordered_revisions = [deduped_revisions[key] for key in sorted(deduped_revisions)]
    _insert(connection, "fact_observation_revision", ordered_revisions)
    counts["fact_observation_revision"] = len(ordered_revisions)

    events = bundle.get("events", [])
    event_rows = []
    impact_rows = []
    preparedness_rows = []
    for event in events:
        clustering = event.get("clustering", {})
        human_review = event.get("human_review", {})
        event_rows.append(
            {
                "event_id": event["event_id"],
                "canonical_event_id": event["canonical_event_id"],
                "title": event["title"],
                "event_class": event["event_class"],
                "event_type": event["event_type"],
                "lifecycle_status": event["lifecycle_status"],
                "event_date": event.get("event_date"),
                "event_end_date": event.get("event_end_date"),
                "publication_date": event.get("publication_date"),
                "retrieval_date": event["retrieval_date"],
                "geography_ids": _joined(event["geography_ids"]),
                "country_ids": _joined(event.get("country_ids", [])),
                "node_ids": _joined(event.get("node_ids", [])),
                "chokepoint_ids": _joined(event.get("chokepoint_ids", [])),
                "modes": _joined(event["modes"]),
                "operator_or_entity": event.get("operator_or_entity"),
                "thailand_relevance": event["thailand_relevance"],
                "event_severity": event.get("event_severity"),
                "transmission_completeness": event["transmission_chain"]["completeness"],
                "negative_operational_evidence": bool(
                    event.get("negative_operational_evidence", False)
                ),
                "publication_status": event["publication_status"],
                "human_review_required": bool(human_review.get("required", False)),
                "human_review_status": human_review.get("status", "not_required"),
                "cluster_id": clustering.get("cluster_id"),
                "cluster_key": clustering["cluster_key"],
                "last_reviewed_at": event["last_reviewed_at"],
                "closure_basis": event.get("closure_basis"),
            }
        )
        for impact in event.get("impact_assessments", []):
            impact_rows.append(
                {
                    "event_id": event["event_id"],
                    "area": impact["area"],
                    "status": impact["status"],
                    "severity": impact["severity"],
                    "relevance": impact["relevance"],
                    "geographic_scope": impact["geographic_scope"],
                    "time_horizon": impact["time_horizon"],
                    "expected_duration": impact["expected_duration"],
                    "evidence_strength": impact["evidence_strength"],
                    "confidence": impact["confidence"],
                    "transmission_mechanism": _joined(impact.get("transmission_mechanism")),
                    "evidence_ids": _joined(impact.get("evidence_ids")),
                    "known_limitations": _joined(impact.get("known_limitations")),
                }
            )
        for index, option in enumerate(event.get("preparedness_options", [])):
            preparedness_rows.append(
                {
                    "subject_type": "event",
                    "subject_id": event["event_id"],
                    "option_index": index,
                    "option_type": option["option_type"],
                    "description": option["description"],
                    "applicable_to": option["applicable_to"],
                    "trigger_condition": option["trigger_condition"],
                    "exit_condition": option["exit_condition"],
                    "evidence_basis": _joined(option.get("evidence_basis")),
                }
            )
    _insert(connection, "fact_event", event_rows)
    counts["fact_event"] = len(event_rows)
    _insert(connection, "fact_impact_assessment", impact_rows)
    counts["fact_impact_assessment"] = len(impact_rows)

    evidence_rows = [
        {
            "evidence_id": item["evidence_id"],
            "event_id": item["event_id"],
            "source_id": item["source_id"],
            "source_name": item["source_name"],
            "source_class": item["source_class"],
            "source_url": item.get("source_url"),
            "source_record_id": item.get("source_record_id"),
            "claim": item["claim"],
            "claim_type": item["claim_type"],
            "evidence_role": item["evidence_role"],
            "relation": item["relation"],
            "strength": item["strength"],
            "scope_supported": item["scope_supported"],
            "event_date": item.get("event_date"),
            "publication_date": item.get("publication_date"),
            "retrieved_at": item["retrieved_at"],
            "content_sha256": item["content_sha256"],
            "parser_version": item["parser_version"],
            "licence_status": item["licence_status"],
            "redistribution_status": item.get("redistribution_status"),
        }
        for item in bundle.get("event_evidence", [])
    ]
    _insert(connection, "fact_event_evidence", evidence_rows)
    counts["fact_event_evidence"] = len(evidence_rows)

    assessment_rows = []
    for assessment in bundle.get("lane_assessments", []):
        for domain in assessment["domain_assessments"]:
            assessment_rows.append(
                {
                    "assessment_id": assessment["assessment_id"],
                    "lane_id": assessment["lane_id"],
                    "generated_at": assessment["generated_at"],
                    "data_cutoff_at": assessment.get("data_cutoff_at"),
                    "overall_direction": assessment["overall_direction"],
                    "attention_level": assessment["attention_level"],
                    "domain": domain["domain"],
                    "domain_direction": domain["direction"],
                    "threshold_rule_id": domain.get("threshold_rule_id"),
                    "data_period": domain.get("data_period"),
                    "freshness_status": domain["freshness"]["status"],
                }
            )
        for index, option in enumerate(assessment.get("preparedness_options", [])):
            preparedness_rows.append(
                {
                    "subject_type": "lane",
                    "subject_id": assessment["lane_id"],
                    "option_index": index,
                    "option_type": option["option_type"],
                    "description": option["description"],
                    "applicable_to": option["applicable_to"],
                    "trigger_condition": option["trigger_condition"],
                    "exit_condition": option["exit_condition"],
                    "evidence_basis": _joined(option.get("evidence_basis")),
                }
            )
    _insert(connection, "fact_lane_assessment", assessment_rows)
    counts["fact_lane_assessment"] = len(assessment_rows)

    _insert(connection, "fact_preparedness_option", preparedness_rows)
    counts["fact_preparedness_option"] = len(preparedness_rows)

    health_rows = [
        {
            "source_id": item["source_id"],
            "status": item["status"],
            "last_checked_at": item.get("last_checked_at"),
            "last_success_at": item.get("last_success_at"),
            "last_error": item.get("last_error"),
            "item_count": item.get("item_count"),
            "required_for_publication": bool(item.get("required_for_publication", False)),
            "max_stale_minutes": int(item["max_stale_minutes"]),
        }
        for item in bundle.get("source_health", [])
    ]
    _insert(connection, "fact_source_health", health_rows)
    counts["fact_source_health"] = len(health_rows)

    history_rows = [
        {
            "history_id": item["history_id"],
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "revision_number": int(item["revision_number"]),
            "recorded_at": item["recorded_at"],
            "action": item["action"],
            "content_sha256": item["content_sha256"],
            "supersedes_history_id": item.get("supersedes_history_id"),
            "summary": item["summary"],
            "reviewer_record": item.get("reviewer_record"),
            "archive_path": item.get("archive_path"),
        }
        for item in bundle.get("assessment_history", [])
    ]
    _insert(connection, "fact_assessment_history", history_rows)
    counts["fact_assessment_history"] = len(history_rows)

    return counts


def build_warehouse(
    bundle: Mapping[str, Any],
    path: Path | str | None = None,
) -> dict[str, int]:
    """Create (or rebuild) the derived warehouse and return row counts.

    ``duckdb`` is imported lazily so that every other module in this package
    -- and the whole schema-validation path -- keeps working in an
    environment where the warehouse is not being built.
    """
    import duckdb

    target = Path(path) if path is not None else DEFAULT_WAREHOUSE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(target))
    try:
        create_schema(connection)
        return load_bundle(bundle, connection)
    finally:
        connection.close()


def export_tables(path: Path | str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read every warehouse table back as plain records.

    Used by the clean-rebuild test to compare two builds, and available to
    the Dashboard export step when a derived query is more convenient than
    re-deriving from JSON.
    """
    import duckdb

    target = Path(path) if path is not None else DEFAULT_WAREHOUSE_PATH
    connection = duckdb.connect(str(target), read_only=True)
    try:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        ]
        result: dict[str, list[dict[str, Any]]] = {}
        for table in table_names:
            cursor = connection.execute(f"SELECT * FROM {table}")  # noqa: S608
            columns = [description[0] for description in cursor.description]
            result[table] = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return result
    finally:
        connection.close()


def fingerprint(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Stable content hash of an exported warehouse, for rebuild comparison."""
    import hashlib

    payload = json.dumps(tables, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
