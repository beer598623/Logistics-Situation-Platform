#!/usr/bin/env python3
"""Rebuild the derived DuckDB analytical warehouse from version-controlled data.

The warehouse is generated, never committed. Version-controlled JSON under
``data/`` stays the reviewable source of truth; this script produces a
queryable copy of it for analysis. Running it twice over unchanged inputs
produces identical content, which ``tests/test_warehouse.py`` asserts by
comparing content fingerprints across two clean builds.

Usage::

    python scripts/build_warehouse.py [--path warehouse/logistics.duckdb]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.warehouse import DEFAULT_WAREHOUSE_PATH, build_warehouse  # noqa: E402


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def assemble_bundle() -> dict[str, Any]:
    """Collect every version-controlled record the warehouse loads."""
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    dimensions = _load(ROOT / "data/reference/dimensions.json")
    return {
        "sources": registry["sources"],
        "dimensions": dimensions,
        "lanes": _load(ROOT / "data/reference/lanes.json")["lanes"],
        "indicator_observations": _load(ROOT / "data/observations/indicator_observations.json")[
            "records"
        ],
        "trade_observations": _load(ROOT / "data/observations/trade_observations.json")["records"],
        "port_observations": _load(ROOT / "data/observations/port_observations.json")["records"],
        "cost_observations": _load(ROOT / "data/observations/cost_observations.json")["records"],
        "events": _load(ROOT / "data/events/events.json")["events"],
        "event_evidence": _load(ROOT / "data/events/event_evidence.json")["evidence"],
        "lane_assessments": _load(ROOT / "data/assessments/lane_assessments.json")["assessments"],
        "source_health": _load(ROOT / "data/source_status/latest.json")["sources"],
        "assessment_history": _load(ROOT / "data/assessments/assessment_history.json")["entries"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_WAREHOUSE_PATH))
    args = parser.parse_args()

    target = Path(args.path)
    counts = build_warehouse(assemble_bundle(), target)

    print(f"Warehouse rebuilt at {target}")
    for table in sorted(counts):
        print(f"  {table:<40} {counts[table]:>6}")
    print(
        "\nThis file is generated and gitignored. The Dashboard reads static JSON and never "
        "depends on a DuckDB service."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
