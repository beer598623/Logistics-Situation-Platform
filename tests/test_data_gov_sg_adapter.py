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
from urllib.error import HTTPError, URLError

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
from scripts.wo027_part_b_live_validation import (
    APPROVED_RESPONSE_HEADERS,
    _classify_failure_layer,
)
from scripts.wo027_part_b_live_validation import (
    REQUESTS as PART_B_REQUESTS,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "data_gov_sg"
CONTAINER_FIXTURE = FIXTURE_DIR / "container_throughput_monthly.json"
VESSEL_FIXTURE = FIXTURE_DIR / "vessel_arrivals_monthly.json"
PART_B_EVIDENCE = ROOT / "docs" / "evidence" / "wo027_part_b_live_validation.json"

#: Exactly the fields Issue #56 authorizes retaining in the Part B evidence
#: artifact, per request entry. Nothing else may appear.
_APPROVED_EVIDENCE_FIELDS = frozenset(
    {
        "sequence",
        "label",
        "request_url",
        "retrieval_timestamp",
        "outcome",
        "failure_layer",
        "http_status",
        "content_type",
        "response_bytes",
        "content_sha256",
        "resource_id",
        "result_total",
        "returned_field_names",
        "records",
        "approved_response_headers",
        "parser_outcome",
        "error",
    }
)

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
    # A literal count, not a scaled aggregate -- no unit/scale ambiguity,
    # unlike container_throughput. Must be explicit: unit_verified now
    # defaults to False (WO-027 fail-closed fix), so a series that is
    # genuinely fine to parse has to say so affirmatively.
    unit_verified=True,
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


def test_omitting_unit_verified_defaults_to_false_and_refuses_to_parse() -> None:
    """WO-027 review: the dangerous failure mode is failing *open* (parsing
    with a guessed unit), not failing closed. A spec that simply omits
    ``unit_verified`` -- never sets it either way -- must default to
    ``False`` and refuse to parse; a caller must affirmatively mark a
    series as verified rather than getting that for free by omission."""
    spec_without_the_keyword = DatastoreSeriesSpec(
        resource_id=UNVERIFIED_CONTAINER_SPEC.resource_id,
        series_id=UNVERIFIED_CONTAINER_SPEC.series_id,
        month_field=UNVERIFIED_CONTAINER_SPEC.month_field,
        value_field=UNVERIFIED_CONTAINER_SPEC.value_field,
        metric=UNVERIFIED_CONTAINER_SPEC.metric,
        operational_interpretation=UNVERIFIED_CONTAINER_SPEC.operational_interpretation,
        resolution=UNVERIFIED_CONTAINER_SPEC.resolution,
        unit=UNVERIFIED_CONTAINER_SPEC.unit,
        evidence_class=UNVERIFIED_CONTAINER_SPEC.evidence_class,
        # unit_verified deliberately omitted -- this is the point of the test.
    )
    assert spec_without_the_keyword.unit_verified is False
    with pytest.raises(UnverifiedUnitError):
        parse_datastore_search_response(
            CONTAINER_FIXTURE.read_bytes(), _contract(spec_without_the_keyword)
        )


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
    assert records, "fixture must actually produce records for this check to mean anything"
    # Checks the whole serialized record, not just top-level keys, so a
    # leak into a nested dict (e.g. measurement/extra) would still be caught.
    for record in records:
        assert "gross_tonnage" not in json.dumps(record)


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


# --- WO-027 Part B/D: live-validation script and evidence artifact ----------


def test_part_b_requests_are_exactly_the_two_issue_56_authorized() -> None:
    """The script must never drift from the exact, human-authorized URLs."""
    assert len(PART_B_REQUESTS) == 2
    urls = [spec["url"] for spec in PART_B_REQUESTS]
    assert urls == [
        "https://data.gov.sg/api/action/datastore_search"
        "?resource_id=d_da030f7028200d19ffcbe4a2d71af39c"
        "&limit=5&sort=month%20desc&fields=month,container_throughput",
        "https://data.gov.sg/api/action/datastore_search"
        "?resource_id=d_d48c5a038904f6da3c603cd854b6c191"
        "&limit=5&sort=month%20desc&fields=month,number_of_vessels,gross_tonnage",
    ]


def test_classify_failure_layer_detects_proxy_tunnel_failure() -> None:
    """A CONNECT-tunnel rejection (e.g. an org egress-policy 403/407) must be
    reported as a proxy-layer failure, never mistaken for a data.gov.sg
    source response."""
    exc = URLError(OSError("Tunnel connection failed: 403 Forbidden"))
    assert _classify_failure_layer(exc) == "proxy"


def test_classify_failure_layer_detects_source_http_error() -> None:
    """An HTTPError that made it past the tunnel is a real response from the
    source, not the proxy -- must never be mislabelled 'proxy'."""
    exc = HTTPError("https://data.gov.sg/x", 403, "Forbidden", {}, None)
    assert _classify_failure_layer(exc) == "source"


def test_classify_failure_layer_falls_back_to_client_for_unrecognized_errors() -> None:
    exc = TimeoutError("timed out")
    assert _classify_failure_layer(exc) == "client"


def test_part_b_evidence_artifact_exists_and_is_valid_json() -> None:
    assert PART_B_EVIDENCE.exists(), "WO-027 Part B evidence artifact must be committed"
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    assert report["work_order"] == "WO-027"
    assert report["issue"] == 56


def test_part_b_evidence_has_exactly_two_requests_matching_the_authorized_urls() -> None:
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    assert len(report["requests"]) == 2
    for entry, spec in zip(report["requests"], PART_B_REQUESTS, strict=True):
        assert entry["request_url"] == spec["url"]
        assert entry["resource_id"] == spec["expected_resource_id"]


def test_part_b_evidence_retains_only_the_approved_fields() -> None:
    """Issue #56 names an exact retention allowlist. Nothing outside it may
    appear in a committed request entry -- this is a regression test against
    a future edit accidentally widening what gets retained/published."""
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    for entry in report["requests"]:
        extra = set(entry.keys()) - _APPROVED_EVIDENCE_FIELDS
        assert not extra, f"unapproved fields retained in evidence: {extra}"
        assert set(entry["approved_response_headers"].keys()) <= set(APPROVED_RESPONSE_HEADERS)


def test_part_b_evidence_never_retains_more_than_five_records_per_request() -> None:
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    for entry in report["requests"]:
        if entry["records"] is not None:
            assert len(entry["records"]) <= 5


def test_part_b_evidence_requests_both_succeeded() -> None:
    """Pinned so a future re-run that silently regresses to a transport
    failure cannot slip past review unnoticed."""
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    for entry in report["requests"]:
        assert entry["outcome"] == "success"
        assert entry["http_status"] == 200
        assert entry["content_type"] in {"application/json", "text/json"}


def test_part_b_live_validated_vessel_envelope_parses_through_the_real_parser() -> None:
    """Reconstructs a minimal Datastore Search envelope from the WO-027 Part B
    live-retrieved vessel-arrivals records (not a fixture) and confirms the
    real parser accepts it end to end -- proving the parser was validated
    against genuinely live data, not only hand-written fixtures."""
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    vessel_entry = next(
        r for r in report["requests"] if r["resource_id"] == VESSEL_SPEC.resource_id
    )
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": vessel_entry["resource_id"],
                "records": vessel_entry["records"],
                "total": vessel_entry["result_total"],
            },
        }
    ).encode("utf-8")
    records = parse_datastore_search_response(payload, _contract(VESSEL_SPEC))
    assert len(records) == len(vessel_entry["records"])
    for record in records:
        assert schema_errors(record, "port_transport_observation.schema.json") == []
        assert record["measurement"]["value_status"] == "available"


def test_part_b_live_validated_container_envelope_still_refuses_to_parse() -> None:
    """The unit-unverified fail-closed gate must hold even against a real,
    successfully-fetched live response -- confirming the gate was never
    conditioned on "no live data available yet" as an implicit escape
    hatch (WO-027 Part C: unit_verified stays False by deliberate decision)."""
    report = json.loads(PART_B_EVIDENCE.read_text(encoding="utf-8"))
    container_entry = next(
        r for r in report["requests"] if r["resource_id"] == UNVERIFIED_CONTAINER_SPEC.resource_id
    )
    payload = json.dumps(
        {
            "success": True,
            "result": {
                "resource_id": container_entry["resource_id"],
                "records": container_entry["records"],
                "total": container_entry["result_total"],
            },
        }
    ).encode("utf-8")
    with pytest.raises(UnverifiedUnitError):
        parse_datastore_search_response(payload, _contract(UNVERIFIED_CONTAINER_SPEC))


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
