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

#: A synthetic fixture record, built the way the ingest script builds one:
#: the reserved synthetic source identifier, the real publisher it stands in
#: for, and no retrieval timestamp because nothing was retrieved.
BASE = {
    "source_id": "SYNTHETIC_FIXTURE",
    "intended_source_id": "TH_CUSTOMS",
    "series_id": "th_export_value_neur",
    "period_key": "2026-01",
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "period_type": "month",
    "retrieved_at": None,
    "retrieval_status": "not_retrieved",
    "evidence_origin": "synthetic_test_fixture",
    "content_hash_scope": "local_fixture_payload",
    "fixture_created_at": "2026-07-24T00:00:00Z",
    "parser_version": "thai_customs_v1",
    "evidence_class": "synthetic_test_fixture",
    "content_sha256": content_hash("a", "b"),
}

#: The same record as it would be built from a genuinely retrieved response.
LIVE = {
    **BASE,
    "source_id": "TH_CUSTOMS",
    "intended_source_id": None,
    "retrieved_at": "2026-07-24T00:00:00Z",
    "retrieval_status": "retrieved",
    "evidence_origin": "live_retrieved",
    "content_hash_scope": "source_response",
    "fixture_created_at": None,
    "evidence_class": "official_statistic",
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


# --------------------------------------------------------------------------
# WO-010-R1: provenance is part of the contract, not decoration.
# --------------------------------------------------------------------------


def test_a_fixture_records_the_reserved_source_and_what_it_stands_in_for():
    record = build_observation(
        **BASE, value=1.0, value_status="available", unit="THB_million", currency="THB"
    )
    provenance = record["provenance"]
    assert provenance["source_id"] == "SYNTHETIC_FIXTURE"
    assert provenance["intended_source_id"] == "TH_CUSTOMS"
    assert provenance["evidence_origin"] == "synthetic_test_fixture"
    assert provenance["retrieval_status"] == "not_retrieved"
    assert provenance["content_hash_scope"] == "local_fixture_payload"


def test_a_fixture_may_not_be_attributed_to_a_real_publisher():
    """Attribution is the whole point: a generated number carrying a real
    source_id is indistinguishable downstream from a retrieved one."""
    with pytest.raises(ObservationContractError, match="not 'TH_CUSTOMS'"):
        build_observation(
            **{**BASE, "source_id": "TH_CUSTOMS"},
            value=1.0,
            value_status="available",
            unit="THB_million",
            currency="THB",
        )


def test_a_fixture_must_name_the_source_it_stands_in_for():
    with pytest.raises(ObservationContractError, match="intended_source_id"):
        build_observation(
            **{**BASE, "intended_source_id": None},
            value=1.0,
            value_status="available",
            unit="THB_million",
            currency="THB",
        )


def test_a_publishable_record_may_not_use_the_reserved_synthetic_identifier():
    with pytest.raises(ObservationContractError, match="reserved synthetic source identifier"):
        build_observation(
            **{**LIVE, "source_id": "SYNTHETIC_FIXTURE"},
            value=1.0,
            value_status="available",
            unit="THB_million",
            currency="THB",
        )


def test_a_record_that_retrieved_nothing_cannot_carry_a_retrieval_time():
    """``fixture_created_at`` is when the file was written. It is not a
    retrieval, and must never be copied into ``retrieved_at``."""
    with pytest.raises(ObservationContractError, match="nothing was retrieved"):
        build_observation(
            **{**BASE, "retrieved_at": "2026-07-24T00:00:00Z"},
            value=1.0,
            value_status="available",
            unit="THB_million",
            currency="THB",
        )


def test_a_retrieved_record_must_state_when_it_was_retrieved():
    with pytest.raises(ObservationContractError, match="no retrieved_at"):
        build_observation(
            **{**LIVE, "retrieved_at": None},
            value=1.0,
            value_status="available",
            unit="THB_million",
            currency="THB",
        )


def test_a_live_record_keeps_its_publisher_and_its_retrieval_time():
    record = build_observation(
        **LIVE, value=1.0, value_status="available", unit="THB_million", currency="THB"
    )
    provenance = record["provenance"]
    assert provenance["source_id"] == "TH_CUSTOMS"
    assert provenance["intended_source_id"] is None
    assert provenance["retrieved_at"] == "2026-07-24T00:00:00Z"
    assert provenance["content_hash_scope"] == "source_response"
