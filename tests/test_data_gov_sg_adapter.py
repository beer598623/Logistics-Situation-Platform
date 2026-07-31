"""WO-026/WO-027: fixture-first parser tests for the data.gov.sg Datastore
Search adapter.

This module never makes a network request, matching every other adapter
test in this package. See ``tests/fixtures/data_gov_sg/README.md`` for the
fixture provenance and the still-open container-throughput unit question.

Two container-throughput specs exist here on purpose:

* ``CONTAINER_SHAPE_SPEC`` (``unit_verified=True``) exercises the parser's
  generic JSON-shape mechanics (missing fields, malformed JSON, wrong
  content type, and so on) that have nothing to do with the unit question.
  It is a test fixture only -- the real registered series never uses a spec
  shaped like this.
* ``UNVERIFIED_CONTAINER_SPEC`` (``unit_verified=False``) matches what the
  real ``MPA_SG_STATISTICS`` registry entry actually requires: parsing must
  be refused outright until the unit/scale is verified against real
  evidence (WO-027).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from analysis.contracts import schema_errors
from collectors.adapters.data_gov_sg import (
    DatastoreContractError,
    DatastoreSearchContract,
    DatastoreSeriesSpec,
    ResponseTooLargeError,
    UnverifiedUnitError,
    parse_datastore_search_response,
)
from collectors.http_client import UnexpectedContentTypeError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "data_gov_sg"
CONTAINER_FIXTURE = FIXTURE_DIR / "container_throughput_monthly.json"
VESSEL_FIXTURE = FIXTURE_DIR / "vessel_arrivals_monthly.json"

#: WO-027: the two field names WO-026 guessed and the human independently
#: confirmed were wrong. Must never reappear anywhere this module touches.
RETIRED_FIELD_NAMES = ("total_teus", "total_vessels")

_KNOWN_LIMITATIONS = (
    "Fixture stands in for an unverified data.gov.sg response shape.",
    "Singapore is a transshipment hub for Thailand cargo; this is Singapore-hub "
    "activity, not a Thailand measurement, and is relevant to Thailand only "
    "through the transshipment mechanism.",
)

#: Generic shape-testing spec only -- see module docstring. Uses the
#: confirmed field name (``container_throughput``) but is deliberately
#: ``unit_verified=True`` so tests unrelated to the unit question can reach
#: past the WO-027 refusal gate. ``unit="teu"`` here is a placeholder for
#: shape testing, not a verified claim.
CONTAINER_SHAPE_SPEC = DatastoreSeriesSpec(
    resource_id="d_da030f7028200d19ffcbe4a2d71af39c",
    series_id="singapore_container_throughput",
    month_field="month",
    value_field="container_throughput",
    metric="container_throughput",
    operational_interpretation="volume_only",
    resolution="country",
    unit="teu",
    unit_verified=True,
    evidence_class="synthetic_test_fixture",
    geography_id="GEO-CTY-SG",
    country_id="SG",
    transport_mode="sea",
    known_limitations=_KNOWN_LIMITATIONS,
    intended_source_id="MPA_SG_STATISTICS",
)

#: The shape actually registered for MPA_SG_STATISTICS's container-throughput
#: series (WO-027): unit/scale unverified, so parsing must be refused.
UNVERIFIED_CONTAINER_SPEC = replace(CONTAINER_SHAPE_SPEC, unit_verified=False)

VESSEL_SPEC = DatastoreSeriesSpec(
    resource_id="d_d48c5a038904f6da3c603cd854b6c191",
    series_id="singapore_vessel_arrivals",
    month_field="month",
    value_field="number_of_vessels",
    metric="vessel_calls",
    operational_interpretation="volume_only",
    resolution="country",
    unit="vessels",
    evidence_class="synthetic_test_fixture",
    geography_id="GEO-CTY-SG",
    country_id="SG",
    transport_mode="sea",
    known_limitations=_KNOWN_LIMITATIONS,
    intended_source_id="MPA_SG_STATISTICS",
)


def _contract(spec: DatastoreSeriesSpec) -> DatastoreSearchContract:
    return DatastoreSearchContract(
        source_id="SYNTHETIC_FIXTURE",
        parser_version="data_gov_sg_v1",
        series=spec,
    )


# --- WO-027: retired field names must never come back ------------------------


def test_retired_field_names_are_absent_from_the_adapter_module() -> None:
    adapter_source = (ROOT / "collectors" / "adapters" / "data_gov_sg.py").read_text(
        encoding="utf-8"
    )
    for name in RETIRED_FIELD_NAMES:
        assert name not in adapter_source, f"{name!r} must not reappear in data_gov_sg.py"


def test_retired_field_names_are_absent_from_the_fixtures() -> None:
    for fixture in (CONTAINER_FIXTURE, VESSEL_FIXTURE):
        text = fixture.read_text(encoding="utf-8")
        for name in RETIRED_FIELD_NAMES:
            assert name not in text, f"{name!r} must not reappear in {fixture.name}"


def test_registered_specs_use_the_confirmed_field_names() -> None:
    assert CONTAINER_SHAPE_SPEC.value_field == "container_throughput"
    assert VESSEL_SPEC.value_field == "number_of_vessels"


# --- WO-027: unit-unverified refusal -----------------------------------------


def test_unit_unverified_series_refuses_to_parse() -> None:
    with pytest.raises(UnverifiedUnitError, match="unit/scale"):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(UNVERIFIED_CONTAINER_SPEC)
        )


def test_unit_unverified_refusal_happens_before_the_payload_is_even_opened() -> None:
    """The refusal is a policy gate, not a payload defect -- garbage bytes
    that would otherwise fail as invalid JSON must still surface the unit
    error, proving the check runs first."""
    with pytest.raises(UnverifiedUnitError):
        parse_datastore_search_response(b"not json at all", _contract(UNVERIFIED_CONTAINER_SPEC))


def test_unverified_unit_error_is_a_datastore_contract_error() -> None:
    assert issubclass(UnverifiedUnitError, DatastoreContractError)


def test_vessel_arrivals_is_not_unit_blocked() -> None:
    """Only the container-throughput series has an open unit question; a
    literal vessel count carries no such ambiguity and must parse normally."""
    records = parse_datastore_search_response(VESSEL_FIXTURE.read_bytes(), _contract(VESSEL_SPEC))
    assert len(records) == 4


# --- Happy path (shape spec only; see module docstring) ----------------------


def test_container_throughput_fixture_parses_into_valid_port_observations() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
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


def test_gross_tonnage_is_present_in_the_fixture_but_not_parsed() -> None:
    """WO-027: gross_tonnage is a confirmed real field, but the human
    decision requires it to be assessed separately before it becomes a
    published capability -- it must not silently ride along on the vessel
    spec."""
    raw = json.loads(VESSEL_FIXTURE.read_bytes())
    assert "gross_tonnage" in {field["id"] for field in raw["result"]["fields"]}
    assert VESSEL_SPEC.value_field != "gross_tonnage"
    records = parse_datastore_search_response(VESSEL_FIXTURE.read_bytes(), _contract(VESSEL_SPEC))
    assert all("gross_tonnage" not in record for record in records)


def test_empty_string_value_becomes_missing_not_zero() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
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
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
    )
    january = next(r for r in records if r["provenance"]["period_end"] == "2026-01-31")
    assert january["measurement"]["value"] == 3_120_000.0
    assert january["measurement"]["value_status"] == "available"


def test_known_limitations_carry_the_transshipment_caveat() -> None:
    records = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
    )
    assert any(
        "transshipment mechanism" in limitation
        for limitation in records[0]["provenance"]["known_limitations"]
    )


def test_repeated_parsing_is_deterministic() -> None:
    first = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
    )
    second = parse_datastore_search_response(
        CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC)
    )
    assert first == second


# --- Fail-closed behaviour -----------------------------------------------


def test_wrong_resource_id_is_rejected() -> None:
    """A response for one dataset must never be attributed to another."""
    mismatched = replace(CONTAINER_SHAPE_SPEC, resource_id="d_wrong_resource_id_entirely")
    with pytest.raises(DatastoreContractError, match="resource_id"):
        parse_datastore_search_response(CONTAINER_FIXTURE.read_bytes(), _contract(mismatched))


def test_success_false_is_rejected() -> None:
    payload = json.dumps({"success": False, "result": {}}).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="success"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_missing_result_is_rejected() -> None:
    payload = json.dumps({"success": True}).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="result"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_records_not_a_list_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": "not-a-list",
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="records"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_row_missing_the_value_field_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"month": "2026-01"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="container_throughput"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_malformed_month_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"month": "not-a-month", "container_throughput": "100"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="month"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_non_numeric_value_string_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"month": "2026-01", "container_throughput": "lots"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="value field"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_nan_json_literal_is_rejected() -> None:
    """json.loads accepts the non-standard NaN literal by default; this
    parser must not let it through as a real measurement (WO-026 review)."""
    payload = (
        b'{"success": true, "result": {"resource_id": "'
        + CONTAINER_SHAPE_SPEC.resource_id.encode("ascii")
        + b'", "records": [{"month": "2026-01", "container_throughput": NaN}]}}'
    )
    with pytest.raises(DatastoreContractError, match="non-standard JSON constant"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_infinity_json_literal_is_rejected() -> None:
    payload = (
        b'{"success": true, "result": {"resource_id": "'
        + CONTAINER_SHAPE_SPEC.resource_id.encode("ascii")
        + b'", "records": [{"month": "2026-01", "container_throughput": Infinity}]}}'
    )
    with pytest.raises(DatastoreContractError, match="non-standard JSON constant"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_infinite_string_value_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"month": "2026-01", "container_throughput": "inf"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="finite"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_row_missing_the_month_field_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"container_throughput": "100"}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="month"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_boolean_value_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": [{"month": "2026-01", "container_throughput": True}],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="boolean"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_wrong_content_type_is_rejected() -> None:
    with pytest.raises(UnexpectedContentTypeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(),
            _contract(CONTAINER_SHAPE_SPEC),
            content_type="text/html",
        )


def test_oversized_payload_is_rejected() -> None:
    with pytest.raises(ResponseTooLargeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC), max_bytes=10
        )


def test_too_many_records_is_rejected() -> None:
    with pytest.raises(ResponseTooLargeError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(CONTAINER_SHAPE_SPEC), max_records=1
        )


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(DatastoreContractError, match="JSON"):
        parse_datastore_search_response(b"{not json", _contract(CONTAINER_SHAPE_SPEC))


def test_non_object_body_is_rejected() -> None:
    payload = json.dumps([1, 2, 3]).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="object"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


def test_row_not_an_object_is_rejected() -> None:
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": CONTAINER_SHAPE_SPEC.resource_id,
                "records": ["not-an-object"],
            },
        }
    ).encode("utf-8")
    with pytest.raises(DatastoreContractError, match="object"):
        parse_datastore_search_response(payload, _contract(CONTAINER_SHAPE_SPEC))


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
