"""WO-026: fixture-first parser tests for the data.gov.sg Datastore Search
adapter.

This module never makes a network request, matching every other adapter
test in this package. See ``tests/fixtures/data_gov_sg/README.md`` for the
important caveat that these fixtures are an assumed, unverified response
shape, not a captured live response.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.contracts import schema_errors
from collectors.adapters.data_gov_sg import (
    DatastoreContractError,
    DatastoreSearchContract,
    DatastoreSeriesSpec,
    ResponseTooLargeError,
    parse_datastore_search_response,
)
from collectors.http_client import UnexpectedContentTypeError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "data_gov_sg"
CONTAINER_FIXTURE = FIXTURE_DIR / "container_throughput_monthly.json"
VESSEL_FIXTURE = FIXTURE_DIR / "vessel_arrivals_monthly.json"

CONTAINER_SPEC = DatastoreSeriesSpec(
    resource_id="d_da030f7028200d19ffcbe4a2d71af39c",
    series_id="singapore_container_throughput",
    month_field="month",
    value_field="total_teus",
    metric="container_throughput",
    operational_interpretation="volume_only",
    resolution="country",
    unit="teu",
    evidence_class="synthetic_test_fixture",
    geography_id="GEO-CTY-SG",
    country_id="SG",
    transport_mode="sea",
    known_limitations=(
        "Fixture stands in for an unverified data.gov.sg response shape (WO-026).",
        "Singapore is a transshipment hub for Thailand cargo; this is Singapore-hub "
        "activity, not a Thailand measurement, and is relevant to Thailand only "
        "through the transshipment mechanism.",
        "Throughput is a volume measure. It can never on its own establish "
        "congestion, waiting time or berth delay.",
    ),
    intended_source_id="MPA_SG_STATISTICS",
)

VESSEL_SPEC = DatastoreSeriesSpec(
    resource_id="d_d48c5a038904f6da3c603cd854b6c191",
    series_id="singapore_vessel_arrivals",
    month_field="month",
    value_field="total_vessels",
    metric="vessel_calls",
    operational_interpretation="volume_only",
    resolution="country",
    unit="vessels",
    evidence_class="synthetic_test_fixture",
    geography_id="GEO-CTY-SG",
    country_id="SG",
    transport_mode="sea",
    known_limitations=(
        "Fixture stands in for an unverified data.gov.sg response shape (WO-026).",
        "Singapore is a transshipment hub for Thailand cargo; this is Singapore-hub "
        "activity, not a Thailand measurement, and is relevant to Thailand only "
        "through the transshipment mechanism.",
    ),
    intended_source_id="MPA_SG_STATISTICS",
)


def _contract(spec: DatastoreSeriesSpec) -> DatastoreSearchContract:
    return DatastoreSearchContract(
        source_id="SYNTHETIC_FIXTURE",
        parser_version="data_gov_sg_v1",
        series=spec,
    )


# --- Happy path --------------------------------------------------------------


def test_container_throughput_fixture_parses_into_valid_port_observations() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    assert len(records) == 4
    for record in records:
        assert schema_errors(record, "port_transport_observation.schema.json") == []
        assert record["series_id"] == "singapore_container_throughput"
        assert record["metric"] == "container_throughput"
        assert record["operational_interpretation"] == "volume_only"
        assert record["resolution"] == "country"
        assert record["placement"]["geography_id"] == "GEO-CTY-SG"
        assert record["placement"]["country_id"] == "SG"
        # WO-026 review: these fixture records must never be mistaken for
        # live evidence -- the same publication-boundary guarantee every
        # other WO-010-style adapter carries.
        assert record["provenance"]["evidence_origin"] == "synthetic_test_fixture"
        assert record["provenance"]["dataset"] == "technical_demo"


def test_vessel_arrivals_fixture_parses_into_valid_port_observations() -> None:
    records = parse_datastore_search_response(VESSEL_FIXTURE.read_bytes(), _contract(VESSEL_SPEC))
    assert len(records) == 4
    for record in records:
        assert schema_errors(record, "port_transport_observation.schema.json") == []
        assert record["metric"] == "vessel_calls"


def test_empty_string_value_becomes_missing_not_zero() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    march = next(r for r in records if r["provenance"]["period_end"] == "2026-03-31")
    assert march["measurement"]["value"] is None
    assert march["measurement"]["value_status"] == "missing"
    assert march["measurement"]["unit"] is None


def test_json_null_value_becomes_missing_not_zero() -> None:
    records = parse_datastore_search_response(VESSEL_FIXTURE.read_bytes(), _contract(VESSEL_SPEC))
    april = next(r for r in records if r["provenance"]["period_end"] == "2026-04-30")
    assert april["measurement"]["value"] is None
    assert april["measurement"]["value_status"] == "missing"


def test_a_numeric_string_value_is_parsed_as_available() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    january = next(r for r in records if r["provenance"]["period_end"] == "2026-01-31")
    assert january["measurement"]["value"] == 3_120_000.0
    assert january["measurement"]["value_status"] == "available"
    assert january["measurement"]["unit"] == "teu"


def test_known_limitations_carry_the_transshipment_caveat() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    assert any(
        "transshipment mechanism" in limitation
        for limitation in records[0]["provenance"]["known_limitations"]
    )


def test_repeated_parsing_is_deterministic() -> None:
    first = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    second = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC)
    )
    assert first == second


# --- Fail-closed behaviour -----------------------------------------------


def test_wrong_resource_id_is_rejected() -> None:
    """A response for one dataset must never be attributed to another."""
    mismatched = DatastoreSeriesSpec(
        resource_id="d_wrong_resource_id_entirely",
        series_id="singapore_container_throughput",
        month_field="month",
        value_field="total_teus",
        metric="container_throughput",
        operational_interpretation="volume_only",
        resolution="country",
        unit="teu",
        evidence_class="synthetic_test_fixture",
        intended_source_id="MPA_SG_STATISTICS",
    )
    with pytest.raises(DatastoreContractError, match="resource_id"):
        parse_datastore_search_response(CONTAINER_FIXTURE.read_bytes(), _contract(mismatched))


def test_success_false_is_rejected() -> None:
    payload = json.dumps({"success": False, "result": {}}).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="success"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_missing_result_is_rejected() -> None:
    payload = json.dumps({"success": True}).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="result"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_records_not_a_list_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": "not-a-list",
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="records"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_row_missing_the_value_field_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"month": "2026-01"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="total_teus"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_malformed_month_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"month": "not-a-month", "total_teus": "100"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="month"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_non_numeric_value_string_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"month": "2026-01", "total_teus": "lots"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="value field"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_nan_json_literal_is_rejected() -> None:
    """json.loads accepts the non-standard NaN literal by default; this
    parser must not let it through as a real measurement (WO-026 review)."""
    payload = (
        b'{"success": true, "result": {"resource_id": "'
        + CONTAINER_SPEC.resource_id.encode("ascii")
        + b'", "records": [{"month": "2026-01", "total_teus": NaN}]}}'
    )
    with pytest.raises(DatastoreContractError, match="NaN"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_infinity_json_literal_is_rejected() -> None:
    payload = (
        b'{"success": true, "result": {"resource_id": "'
        + CONTAINER_SPEC.resource_id.encode("ascii")
        + b'", "records": [{"month": "2026-01", "total_teus": Infinity}]}}'
    )
    with pytest.raises(DatastoreContractError, match="Infinity"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_infinite_string_value_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"month": "2026-01", "total_teus": "inf"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="finite"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_row_missing_the_month_field_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"total_teus": "100"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="month"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_boolean_value_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SPEC.resource_id,
                "records": [{"month": "2026-01", "total_teus": True}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="boolean"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_wrong_content_type_is_rejected() -> None:
    with pytest.raises(UnexpectedContentTypeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(),
            _contract(CONTAINER_SPEC),
            content_type="text/html",
        )


def test_oversized_payload_is_rejected() -> None:
    with pytest.raises(ResponseTooLargeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC), max_bytes=10
        )


def test_too_many_records_is_rejected() -> None:
    with pytest.raises(ResponseTooLargeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SPEC), max_records=1
        )


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(DatastoreContractError, match="JSON"):
        parse_datastore_search_response(b"{not json", _contract(CONTAINER_SPEC))


def test_non_object_body_is_rejected() -> None:
    payload = json.dumps([1, 2, 3]).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="object"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


def test_row_not_an_object_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {"resource_id": CONTAINER_SPEC.resource_id, "records": ["not-an-object"]},
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="object"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SPEC))


# --- No network access ----------------------------------------------------


def test_importing_this_adapter_makes_no_network_request() -> None:
    """Matches the no-network guarantee every other adapter carries."""
    import socket

    def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("importing the adapter attempted a network connection")

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    socket.socket.connect = _forbidden
    socket.create_connection = _forbidden
    try:
        import importlib

        import collectors.adapters.data_gov_sg as module

        importlib.reload(module)
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection
