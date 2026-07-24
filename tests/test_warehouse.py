"""Derived DuckDB warehouse: clean build, idempotent rebuild, revisions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

duckdb = pytest.importorskip("duckdb", reason="duckdb is a pinned runtime dependency")

from analysis.warehouse import (  # noqa: E402
    SCHEMA_STATEMENTS,
    build_warehouse,
    export_tables,
    fingerprint,
)
from scripts.build_warehouse import assemble_bundle  # noqa: E402

EXPECTED_TABLES = {
    "dim_source",
    "dim_geography",
    "dim_country",
    "dim_transport_mode",
    "dim_logistics_node",
    "dim_lane",
    "dim_chokepoint",
    "fact_indicator_observation",
    "fact_trade_observation",
    "fact_port_or_transport_observation",
    "fact_cost_observation",
    "fact_observation_revision",
    "fact_event",
    "fact_event_evidence",
    "fact_lane_assessment",
    "fact_impact_assessment",
    "fact_preparedness_option",
    "fact_source_health",
    "fact_assessment_history",
}


@pytest.fixture(scope="module")
def bundle():
    return assemble_bundle()


def test_the_schema_covers_every_conceptual_entity():
    created = {
        statement.split("CREATE TABLE ", 1)[1].split(" ", 1)[0]
        for statement in SCHEMA_STATEMENTS
        if statement.strip().startswith("CREATE TABLE")
    }
    assert created == EXPECTED_TABLES


def test_clean_build_populates_every_table(tmp_path, bundle):
    counts = build_warehouse(bundle, tmp_path / "clean.duckdb")
    assert set(counts) == EXPECTED_TABLES
    assert counts["dim_lane"] == 11
    assert counts["fact_impact_assessment"] == counts["fact_event"] * 9
    assert all(count > 0 for count in counts.values())


def test_rebuilding_over_an_existing_database_is_idempotent(tmp_path, bundle):
    target = tmp_path / "idempotent.duckdb"
    first_counts = build_warehouse(bundle, target)
    first = fingerprint(export_tables(target))
    second_counts = build_warehouse(bundle, target)
    second = fingerprint(export_tables(target))
    assert first_counts == second_counts
    assert first == second


def test_two_independent_clean_builds_agree(tmp_path, bundle):
    left = fingerprint(export_tables_for(bundle, tmp_path / "a.duckdb"))
    right = fingerprint(export_tables_for(bundle, tmp_path / "b.duckdb"))
    assert left == right


def export_tables_for(bundle, path):
    build_warehouse(bundle, path)
    return export_tables(path)


def test_duplicate_observations_collapse_to_one_current_row(tmp_path, bundle):
    duplicated = dict(bundle)
    duplicated["cost_observations"] = bundle["cost_observations"] + bundle["cost_observations"]
    counts = build_warehouse(duplicated, tmp_path / "dupes.duckdb")
    assert counts["fact_cost_observation"] == len(bundle["cost_observations"])


def test_a_revision_supersedes_the_current_row_but_history_is_preserved(tmp_path, bundle):
    original = bundle["cost_observations"][0]
    revised = {
        **original,
        "provenance": {**original["provenance"], "revision_number": 3},
        "measurement": {**original["measurement"], "value": 999.0},
    }
    revised_bundle = dict(bundle)
    revised_bundle["cost_observations"] = bundle["cost_observations"] + [revised]

    target = tmp_path / "revisions.duckdb"
    counts = build_warehouse(revised_bundle, target)
    assert counts["fact_cost_observation"] == len(bundle["cost_observations"])

    tables = export_tables(target)
    record_id = original["provenance"]["record_id"]
    current = [row for row in tables["fact_cost_observation"] if row["record_id"] == record_id]
    assert len(current) == 1
    assert current[0]["value"] == 999.0
    assert current[0]["revision_number"] == 3

    history = [row for row in tables["fact_observation_revision"] if row["record_id"] == record_id]
    assert {row["revision_number"] for row in history} == {0, 3}


def test_missing_observations_land_in_the_warehouse_as_null_not_zero(tmp_path, bundle):
    target = tmp_path / "missing.duckdb"
    build_warehouse(bundle, target)
    tables = export_tables(target)
    missing = [
        row for row in tables["fact_indicator_observation"] if row["value_status"] != "available"
    ]
    assert missing, "the fixture set must contain at least one missing observation"
    assert all(row["value"] is None for row in missing)


def test_the_warehouse_file_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "warehouse/" in gitignore or "*.duckdb" in gitignore


def test_no_generated_database_is_committed():
    assert not list((ROOT / "warehouse").glob("*.duckdb")) or _is_ignored()


def _is_ignored() -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", "warehouse/logistics.duckdb"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
    )
    return result.returncode == 0
