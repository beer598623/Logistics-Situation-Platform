#!/usr/bin/env python3
"""Parse the committed CSV fixtures into version-controlled observation records.

This is the collection path exercised end to end without a network request:
the same ``collectors/adapters/csv_series.py`` parser that a live collector
would use reads the fixtures through the same ``collectors/series_catalog.py``
contracts and writes normalized records to ``data/observations/``.

Running this on a clean tree must be a no-op. Because the fixtures are
deterministic and the record IDs are derived from source, series and period,
re-ingesting updates in place rather than duplicating -- which is the same
property live re-collection needs.

Usage::

    python scripts/ingest_fixtures.py [--check]

``--check`` reports whether the committed records are already up to date and
exits non-zero if they are not, without writing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.adapters.csv_series import group_by_family, parse_csv_series  # noqa: E402
from collectors.observations import deduplicate_observations  # noqa: E402
from collectors.series_catalog import FIXTURE_CONTRACTS  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "csv_series"
OUTPUT_DIR = ROOT / "data" / "observations"

#: Retrieval time recorded on every fixture-derived record. Fixed rather than
#: "now" so that re-ingesting is a no-op and the committed records stay
#: byte-stable. It is the date WO-010 ingested the fixtures.
FIXTURE_RETRIEVED_AT = "2026-07-24T00:00:00Z"

_FAMILY_FILES = {
    "indicator_observations": "indicator_observations.json",
    "trade_observations": "trade_observations.json",
    "port_observations": "port_observations.json",
    "cost_observations": "cost_observations.json",
}


def collect() -> dict[str, list[dict[str, Any]]]:
    """Parse every registered fixture and group the records by family."""
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in _FAMILY_FILES}
    for filename, contract in sorted(FIXTURE_CONTRACTS.items()):
        payload = (FIXTURE_DIR / filename).read_bytes()
        records = parse_csv_series(
            payload,
            contract,
            retrieved_at=FIXTURE_RETRIEVED_AT,
            content_type="text/csv",
        )
        for family, family_records in group_by_family(records).items():
            grouped[family].extend(family_records)
    return {
        family: sorted(
            deduplicate_observations(records),
            key=lambda record: record["provenance"]["record_id"],
        )
        for family, records in grouped.items()
    }


def render(family: str, records: list[dict[str, Any]]) -> str:
    document = {
        "version": "0.8",
        "family": family,
        "generated_by": "scripts/ingest_fixtures.py",
        "source_note": (
            "Parsed from the labelled synthetic fixtures in tests/fixtures/csv_series/ "
            "through collectors/adapters/csv_series.py. Every record carries "
            "evidence_class 'synthetic_test_fixture'. These are not published statistics."
        ),
        "record_count": len(records),
        "records": records,
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed records match the fixtures without writing.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    grouped = collect()
    stale: list[str] = []

    for family, records in grouped.items():
        target = OUTPUT_DIR / _FAMILY_FILES[family]
        rendered = render(family, records)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != rendered:
                stale.append(str(target.relative_to(ROOT)))
            continue
        target.write_text(rendered, encoding="utf-8")
        print(f"{target.relative_to(ROOT)}: {len(records)} records")

    if args.check:
        if stale:
            print("Observation records are out of date with the fixtures:")
            for path in stale:
                print(f"  - {path}")
            return 1
        print("Observation records are up to date with the fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
