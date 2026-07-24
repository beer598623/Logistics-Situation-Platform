#!/usr/bin/env python3
"""Generate the labelled synthetic CSV fixtures used by WO-010.

**These files contain no real published statistics.** No source could be
live-validated in the WO-010 execution environment (see
``docs/source_qualification_report.md``), so the Ocean MVP is demonstrated on
synthetic fixtures rather than on invented numbers presented as real data.
Every observation derived from these files carries
``evidence_class: "synthetic_test_fixture"``, and the Dashboard states on its
face that live coverage is insufficient.

The generator is committed, and its output is committed, so a reviewer can
regenerate the fixtures and confirm byte-for-byte that nothing in them was
hand-tuned to make an analysis look better than it is. Values are produced by
a fixed seed and a deterministic formula; deliberate gaps are inserted so the
missing-is-not-zero path is exercised by real data rather than only by unit
tests.

Usage::

    python scripts/generate_synthetic_fixtures.py

Regenerating must be a no-op on a clean tree. ``tests/test_fixture_integrity.py``
asserts exactly that.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "csv_series"

#: 30 months ending 2026-06 gives 24 months of year-over-year comparisons plus
#: the 12-month lead-in those comparisons need.
START_YEAR, START_MONTH = 2024, 1
MONTHS = 30

LANES = (
    ("LANE-OCEAN-TH-EASIA-CN", "easia_cn", 1.00),
    ("LANE-OCEAN-TH-JPKR", "jpkr", 0.55),
    ("LANE-OCEAN-TH-ASEAN-SG", "asean_sg", 0.85),
    ("LANE-OCEAN-TH-SASIA", "sasia", 0.35),
    ("LANE-OCEAN-TH-MEGULF", "megulf", 0.30),
    ("LANE-OCEAN-TH-NEUR", "neur", 0.45),
    ("LANE-OCEAN-TH-MED", "med", 0.20),
    ("LANE-OCEAN-TH-USWC", "uswc", 0.60),
    ("LANE-OCEAN-TH-USEC", "usec", 0.30),
    ("LANE-OCEAN-TH-OCEANIA", "oceania", 0.18),
    ("LANE-OCEAN-TH-DOMESTIC", "domestic", 0.25),
)

#: (series slug, period index) pairs deliberately left unpublished, so the
#: platform has to show a real gap rather than a zero.
DELIBERATE_GAPS = {
    ("export_value_med", 28),
    ("export_value_med", 29),
    ("import_value_oceania", 29),
    ("thailand_lsci", 27),
    ("thailand_lsci", 28),
    ("thailand_lsci", 29),
}


def months() -> list[str]:
    periods = []
    year, month = START_YEAR, START_MONTH
    for _ in range(MONTHS):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return periods


def _wave(index: int, *, base: float, trend: float, amplitude: float, phase: float) -> float:
    """Deterministic seasonal series: linear trend plus one annual cycle."""
    seasonal = amplitude * math.sin((2 * math.pi * (index + phase)) / 12.0)
    return base * (1.0 + trend * index) + seasonal


def _cell(slug: str, index: int, value: float, digits: int = 1) -> str:
    if (slug, index) in DELIBERATE_GAPS:
        return ""
    return f"{value:.{digits}f}"


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def generate_trade() -> None:
    header = ["period", "published_at"]
    for _, slug, _ in LANES:
        header.extend([f"export_value_{slug}", f"import_value_{slug}"])

    rows: list[list[str]] = []
    for index, period in enumerate(months()):
        row = [period, f"{period}-28T00:00:00Z"]
        for lane_index, (_, slug, weight) in enumerate(LANES):
            export_value = _wave(
                index,
                base=90_000.0 * weight,
                trend=0.004,
                amplitude=6_000.0 * weight,
                phase=lane_index,
            )
            import_value = _wave(
                index,
                base=78_000.0 * weight,
                trend=0.003,
                amplitude=5_200.0 * weight,
                phase=lane_index + 3,
            )
            row.append(_cell(f"export_value_{slug}", index, export_value))
            row.append(_cell(f"import_value_{slug}", index, import_value))
        rows.append(row)
    _write(FIXTURE_DIR / "thailand_trade_by_lane_monthly.csv", header, rows)


def generate_port() -> None:
    header = [
        "period",
        "published_at",
        "laem_chabang_teu",
        "bangkok_port_teu",
        "thailand_port_calls",
    ]
    rows = []
    for index, period in enumerate(months()):
        rows.append(
            [
                period,
                f"{period}-25T00:00:00Z",
                _cell("laem_chabang_teu", index, _wave(index, base=760_000, trend=0.0035, amplitude=48_000, phase=1), 0),
                _cell("bangkok_port_teu", index, _wave(index, base=118_000, trend=0.0012, amplitude=9_000, phase=4), 0),
                _cell("thailand_port_calls", index, _wave(index, base=1_450, trend=0.0018, amplitude=95, phase=2), 0),
            ]
        )
    _write(FIXTURE_DIR / "thailand_port_activity_monthly.csv", header, rows)


def generate_cost() -> None:
    header = [
        "period",
        "published_at",
        "thailand_diesel_retail",
        "brent_crude",
        "container_freight_benchmark",
    ]
    rows = []
    for index, period in enumerate(months()):
        rows.append(
            [
                period,
                f"{period}-20T00:00:00Z",
                _cell("thailand_diesel_retail", index, _wave(index, base=31.5, trend=0.0022, amplitude=1.35, phase=5), 2),
                _cell("brent_crude", index, _wave(index, base=79.0, trend=0.0015, amplitude=6.4, phase=0), 2),
                _cell(
                    "container_freight_benchmark",
                    index,
                    _wave(index, base=1_820.0, trend=0.006, amplitude=240.0, phase=7),
                    1,
                ),
            ]
        )
    _write(FIXTURE_DIR / "cost_and_freight_monthly.csv", header, rows)


def generate_indicators() -> None:
    header = ["period", "published_at", "usd_thb_rate", "gscpi_index", "thailand_lsci"]
    rows = []
    for index, period in enumerate(months()):
        rows.append(
            [
                period,
                f"{period}-15T00:00:00Z",
                _cell("usd_thb_rate", index, _wave(index, base=34.6, trend=0.0009, amplitude=0.85, phase=3), 3),
                _cell("gscpi_index", index, _wave(index, base=0.16, trend=0.010, amplitude=0.42, phase=6), 3),
                _cell("thailand_lsci", index, _wave(index, base=42.5, trend=0.0011, amplitude=1.1, phase=2), 2),
            ]
        )
    _write(FIXTURE_DIR / "baseline_indicators_monthly.csv", header, rows)


def main() -> int:
    generate_trade()
    generate_port()
    generate_cost()
    generate_indicators()
    print(f"Synthetic fixtures written to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
