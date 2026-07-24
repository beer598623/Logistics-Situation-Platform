"""Threshold rules and series derivation.

The recurring assertion in this file: when an input is missing, the answer is
``insufficient_evidence`` or ``None`` — never ``stable`` and never ``0``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from analysis.indicators import ROLLING_WINDOW, change_for_basis, derive_series, to_points
from analysis.thresholds import INSUFFICIENT, RULES, combine_directions, rule

NOW = datetime(2026, 7, 24, tzinfo=UTC)
DOCS = Path(__file__).resolve().parents[1] / "docs" / "indicator_definitions.md"


def observation(period: str, value: float | None, *, status: str = "available", **overrides):
    year, month = period.split("-")
    last_day = {
        "01": 31,
        "02": 28,
        "03": 31,
        "04": 30,
        "05": 31,
        "06": 30,
        "07": 31,
        "08": 31,
        "09": 30,
        "10": 31,
        "11": 30,
        "12": 31,
    }[month]
    provenance = {
        "record_id": f"OBS-TEST-probe-{period}",
        "source_id": "TEST_SRC",
        "source_record_id": None,
        "period_start": f"{year}-{month}-01",
        "period_end": f"{year}-{month}-{last_day}",
        "period_type": "month",
        "published_at": f"{year}-{month}-{last_day}T00:00:00Z",
        "retrieved_at": "2026-07-24T00:00:00Z",
        "revised_at": None,
        "revision_number": 0,
        "content_sha256": "a" * 64,
        "parser_version": "test_v1",
        "source_revision": None,
        "evidence_class": "synthetic_test_fixture",
        "known_limitations": [],
    }
    provenance.update(overrides.pop("provenance", {}))
    return {
        "provenance": provenance,
        "measurement": {
            "value": value,
            "value_status": status,
            "unit": "index_points",
            "currency": None,
        },
        "placement": {
            "geography_id": None,
            "country_id": None,
            "transport_mode": "not_applicable",
            "lane_id": None,
            "node_id": None,
        },
    }


def month_series(values: list[float | None], start_year: int = 2025) -> list[dict]:
    records = []
    year, month = start_year, 1
    for value in values:
        records.append(
            observation(
                f"{year:04d}-{month:02d}",
                value,
                status="available" if value is not None else "missing",
            )
        )
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return records


# ---------------------------------------------------------------------------
# Threshold rules
# ---------------------------------------------------------------------------


def test_every_rule_returns_insufficient_evidence_for_a_missing_change():
    for rule_id, threshold in RULES.items():
        assert threshold.evaluate(None, observations_used=999) == INSUFFICIENT, rule_id


def test_every_rule_returns_insufficient_evidence_below_its_minimum_observations():
    for rule_id, threshold in RULES.items():
        assert (
            threshold.evaluate(100.0, observations_used=threshold.min_observations - 1)
            == INSUFFICIENT
        ), rule_id


def test_higher_is_worse_rules_read_a_rise_as_deterioration():
    fuel = rule("FUEL-MOM-V1")
    assert fuel.higher_is_worse is True
    assert fuel.evaluate(5.0, observations_used=12) == "deteriorating"
    assert fuel.evaluate(-5.0, observations_used=12) == "improving"
    assert fuel.evaluate(0.5, observations_used=12) == "stable"


def test_higher_is_better_rules_read_a_rise_as_improvement():
    trade = rule("TH-TRADE-YOY-V1")
    assert trade.higher_is_worse is False
    assert trade.evaluate(10.0, observations_used=24) == "improving"
    assert trade.evaluate(-10.0, observations_used=24) == "deteriorating"
    assert trade.evaluate(1.0, observations_used=24) == "stable"


def test_port_volume_rule_is_documented_as_volume_only():
    """The rule that could most easily be mistaken for congestion says so."""
    assert "VOLUME ONLY" in rule("PORT-VOLUME-YOY-V1").description
    assert "congestion" in rule("PORT-VOLUME-YOY-V1").description.lower()


def test_freight_rule_states_it_is_not_a_quotation():
    description = rule("FREIGHT-BENCHMARK-MOM-V1").description
    assert "never a Thailand shipment quotation" in description


def test_unknown_rule_id_raises():
    with pytest.raises(KeyError):
        rule("NO-SUCH-RULE")


def test_every_rule_id_appears_in_the_narrative_documentation():
    text = DOCS.read_text(encoding="utf-8")
    for rule_id in RULES:
        assert rule_id in text, f"{rule_id} is not documented in docs/indicator_definitions.md"


def test_every_documented_rule_id_exists_in_code():
    text = DOCS.read_text(encoding="utf-8")
    documented = set(re.findall(r"\b[A-Z]+(?:-[A-Z0-9]+)+-V[0-9]+\b", text))
    assert documented <= set(RULES), f"documented but not implemented: {documented - set(RULES)}"


# ---------------------------------------------------------------------------
# Direction combination
# ---------------------------------------------------------------------------


def test_no_directions_at_all_is_insufficient_not_stable():
    assert combine_directions([]) == INSUFFICIENT
    assert combine_directions([INSUFFICIENT, INSUFFICIENT]) == INSUFFICIENT


def test_disagreement_becomes_mixed():
    assert combine_directions(["improving", "deteriorating"]) == "mixed"
    assert combine_directions(["mixed", "stable"]) == "mixed"


def test_insufficient_entries_never_become_stable():
    assert combine_directions([INSUFFICIENT, "deteriorating"]) == "deteriorating"
    assert combine_directions([INSUFFICIENT, "stable"]) == "stable"


# ---------------------------------------------------------------------------
# Series derivation
# ---------------------------------------------------------------------------


def test_derivation_reports_gaps_rather_than_zeros():
    records = month_series([100.0, None, 120.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.periods_total == 3
    assert derivation.periods_available == 2
    assert derivation.periods_missing == 1
    assert derivation.current_value == 120.0
    assert any("not treated as zero" in item for item in derivation.limitations)


def test_month_over_month_requires_the_immediately_preceding_month():
    records = month_series([100.0, None, 120.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.month_over_month_pct is None
    assert any("immediately preceding month" in item for item in derivation.limitations)


def test_month_over_month_is_computed_when_the_prior_month_exists():
    records = month_series([100.0, 110.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.month_over_month_pct == pytest.approx(10.0)


def test_year_over_year_needs_the_same_month_one_year_earlier():
    records = month_series([100.0] * 12 + [130.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.year_over_year_pct == pytest.approx(30.0)


def test_year_over_year_is_none_when_the_prior_year_period_is_missing():
    values: list[float | None] = [100.0] * 13
    values[0] = None
    derivation = derive_series("probe", month_series(values), now=NOW)
    assert derivation.year_over_year_pct is None
    assert any("one year earlier" in item for item in derivation.limitations)


def test_year_over_year_never_substitutes_a_nearby_period():
    """A 10-month-old reading must not be reported as a year-over-year change."""
    records = month_series([100.0, None, None, 150.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.year_over_year_pct is None


def test_percentage_change_against_a_zero_basis_is_undefined_not_infinite():
    records = month_series([0.0, 50.0])
    derivation = derive_series("probe", records, now=NOW)
    assert derivation.previous_period_change_pct is None
    assert derivation.previous_period_change == 50.0
    assert any("is zero" in item for item in derivation.limitations)


def test_rolling_average_is_withheld_when_the_window_is_incomplete():
    derivation = derive_series("probe", month_series([100.0, 110.0]), now=NOW)
    assert derivation.rolling_average is None
    assert derivation.rolling_window_used == 0
    assert any("Rolling average needs" in item for item in derivation.limitations)


def test_rolling_average_uses_the_documented_window():
    derivation = derive_series("probe", month_series([90.0, 100.0, 110.0]), now=NOW)
    assert derivation.rolling_average == pytest.approx(100.0)
    assert derivation.rolling_window_used == ROLLING_WINDOW


def test_no_baseline_means_no_deviation_is_published():
    derivation = derive_series("probe", month_series([100.0, 110.0]), now=NOW)
    assert derivation.deviation_from_baseline is None
    assert any("No baseline is defined" in item for item in derivation.limitations)


def test_deviation_is_published_when_a_baseline_is_explicit():
    derivation = derive_series(
        "probe",
        month_series([0.4]),
        baseline_definition="Zero, the publisher's own stated series average.",
        baseline_value=0.0,
        now=NOW,
    )
    assert derivation.deviation_from_baseline == pytest.approx(0.4)


def test_a_series_with_no_usable_point_is_no_data_not_fresh():
    derivation = derive_series("probe", month_series([None, None]), now=NOW)
    assert derivation.freshness.status == "no_data"
    assert derivation.freshness.age_days is None
    assert derivation.current_value is None


def test_freshness_degrades_with_age():
    fresh = derive_series(
        "probe", month_series([1.0], start_year=2026), max_stale_minutes=10080, now=NOW
    )
    assert fresh.freshness.status == "very_stale"
    recent = derive_series(
        "probe",
        [observation("2026-07", 1.0)],
        max_stale_minutes=525600,
        expected_cadence_minutes=44640,
        now=NOW,
    )
    assert recent.freshness.status == "fresh"


def test_a_single_observation_states_that_no_change_can_be_computed():
    derivation = derive_series("probe", month_series([100.0]), now=NOW)
    assert derivation.previous_period_change is None
    assert any("not an unchanged series" in item for item in derivation.limitations)


def test_revision_status_is_reported():
    records = month_series([100.0])
    records[0]["provenance"]["revision_number"] = 2
    records[0]["provenance"]["revised_at"] = "2026-03-01T00:00:00Z"
    assert derive_series("probe", records, now=NOW).revision_status == "revised"


def test_records_without_a_period_end_cannot_be_ordered_and_are_dropped():
    records = month_series([100.0, 110.0])
    records[0]["provenance"]["period_end"] = None
    assert len(to_points(records)) == 1


def test_change_for_basis_rejects_an_unknown_basis():
    derivation = derive_series("probe", month_series([100.0, 110.0]), now=NOW)
    with pytest.raises(ValueError, match="Unknown threshold basis"):
        change_for_basis(derivation, "vibes")
