"""The observation contract: a missing value can never become a number."""

from __future__ import annotations

import pytest

from collectors.observations import (
    ObservationContractError,
    build_observation,
    build_record_id,
    content_hash,
    deduplicate_observations,
)

BASE = {
    "source_id": "TH_CUSTOMS",
    "series_id": "th_export_value_neur",
    "period_key": "2026-01",
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "period_type": "month",
    "retrieved_at": "2026-07-24T00:00:00Z",
    "parser_version": "thai_customs_v1",
    "evidence_class": "synthetic_test_fixture",
    "content_sha256": content_hash("a", "b"),
}


def test_available_value_is_carried_with_its_unit():
    record = build_observation(
        **BASE, value=1234.5, value_status="available", unit="THB_million", currency="THB"
    )
    assert record["measurement"]["value"] == 1234.5
    assert record["measurement"]["unit"] == "THB_million"
    assert record["provenance"]["record_id"].endswith("2026-01")


@pytest.mark.parametrize(
    "status", ["missing", "not_published", "suppressed", "retrieval_failed", "not_collected"]
)
def test_every_non_available_status_forces_a_null_value(status):
    record = build_observation(**BASE, value=None, value_status=status, unit=None, currency="THB")
    assert record["measurement"]["value"] is None
    assert record["measurement"]["value_status"] == status


def test_a_missing_observation_cannot_carry_zero():
    with pytest.raises(ObservationContractError, match="including zero"):
        build_observation(
            **BASE, value=0.0, value_status="missing", unit="THB_million", currency="THB"
        )


def test_a_missing_observation_cannot_carry_any_number():
    with pytest.raises(ObservationContractError, match="including zero"):
        build_observation(
            **BASE, value=42.0, value_status="not_published", unit="THB_million", currency="THB"
        )


def test_an_available_value_cannot_be_null():
    with pytest.raises(ObservationContractError, match="no value was parsed"):
        build_observation(
            **BASE, value=None, value_status="available", unit="THB_million", currency="THB"
        )


def test_an_available_value_must_record_its_unit():
    with pytest.raises(ObservationContractError, match="must record its unit"):
        build_observation(**BASE, value=1.0, value_status="available", unit=None, currency="THB")


def test_zero_is_a_legitimate_value_when_the_source_published_zero():
    """Zero is only forbidden as a *substitute* for missing, never as data."""
    record = build_observation(
        **BASE, value=0.0, value_status="available", unit="THB_million", currency="THB"
    )
    assert record["measurement"]["value"] == 0.0
    assert record["measurement"]["value_status"] == "available"


def test_record_id_is_deterministic_across_calls():
    first = build_record_id("EPPO_FUEL", "Thailand Diesel Retail", "2026-01")
    second = build_record_id("EPPO_FUEL", "thailand diesel retail", "2026-01")
    assert first == second == "OBS-EPPO_FUEL-thailand_diesel_retail-2026-01"


def test_deduplication_keeps_the_highest_revision():
    original = build_observation(
        **BASE, value=100.0, value_status="available", unit="THB_million", currency="THB"
    )
    revised = build_observation(
        **{**BASE, "revision_number": 2},
        value=115.0,
        value_status="available",
        unit="THB_million",
        currency="THB",
    )
    result = deduplicate_observations([original, revised])
    assert len(result) == 1
    assert result[0]["measurement"]["value"] == 115.0
    assert result[0]["provenance"]["revision_number"] == 2


def test_deduplication_does_not_merge_different_periods():
    january = build_observation(
        **BASE, value=100.0, value_status="available", unit="THB_million", currency="THB"
    )
    february = build_observation(
        **{**BASE, "period_key": "2026-02", "period_end": "2026-02-28"},
        value=110.0,
        value_status="available",
        unit="THB_million",
        currency="THB",
    )
    assert len(deduplicate_observations([january, february])) == 2


def test_extra_family_fields_are_preserved_at_the_top_level():
    record = build_observation(
        **BASE,
        value=1.0,
        value_status="available",
        unit="THB_million",
        currency="THB",
        extra={"flow_direction": "export", "measure": "value"},
    )
    assert record["flow_direction"] == "export"
    assert record["measure"] == "value"
