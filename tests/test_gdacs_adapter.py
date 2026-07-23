from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from collectors.adapters.gdacs import (
    GdacsAdapter,
    MalformedGdacsRecordError,
    build_search_request,
    normalize_event,
    parse_event_list,
)
from collectors.registry import load_registry, source_by_id
from tests.conftest import FakeHttpClient

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gdacs" / "event_list_page1.json"


@pytest.fixture
def gdacs_contract() -> dict:
    registry = load_registry()
    return source_by_id(registry, "GDACS")


@pytest.fixture
def staging_record_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas" / "staging_record.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


# --- Request construction and encoding -------------------------------------


def test_build_search_request_is_deterministic(gdacs_contract: dict) -> None:
    request_a = build_search_request(gdacs_contract, from_date="2026-07-01", to_date="2026-07-23")
    request_b = build_search_request(gdacs_contract, from_date="2026-07-01", to_date="2026-07-23")
    assert request_a.to_url() == request_b.to_url()
    assert "fromdate=2026-07-01" in request_a.to_url()
    assert "todate=2026-07-23" in request_a.to_url()
    assert request_a.to_url().startswith(gdacs_contract["endpoint"])


def test_build_search_request_encodes_event_types_and_alert_levels_sorted(
    gdacs_contract: dict,
) -> None:
    request = build_search_request(
        gdacs_contract,
        from_date="2026-07-01",
        to_date="2026-07-23",
        event_types=["TC", "EQ"],
        alert_levels=["Red", "Orange"],
    )
    url = request.to_url()
    assert "eventlist=EQ%3BTC" in url
    assert "alertlevel=Orange%3BRed" in url


def test_build_search_request_rejects_missing_dates(gdacs_contract: dict) -> None:
    with pytest.raises(ValueError):
        build_search_request(gdacs_contract, from_date="", to_date="2026-07-23")


# --- 100-record maximum and pagination -------------------------------------


def test_official_page_size_cap_is_enforced(gdacs_contract: dict) -> None:
    with pytest.raises(ValueError):
        build_search_request(
            gdacs_contract, from_date="2026-07-01", to_date="2026-07-23", page_size=101
        )


def test_default_page_size_comes_from_contract(gdacs_contract: dict) -> None:
    request = build_search_request(gdacs_contract, from_date="2026-07-01", to_date="2026-07-23")
    assert request.page_size == 100
    assert gdacs_contract["pagination"]["max_page_size"] == 100


def test_page_number_is_encoded_in_request(gdacs_contract: dict) -> None:
    request = build_search_request(
        gdacs_contract, from_date="2026-07-01", to_date="2026-07-23", page_number=3, page_size=50
    )
    assert "pagenumber=3" in request.to_url()
    assert "pagesize=50" in request.to_url()


# --- Composite stable identity + episode/revision retention ----------------


def test_composite_stable_identity_and_revision() -> None:
    records, warnings = parse_event_list(FIXTURE.read_bytes())
    by_id = {record["source_external_id"]: record for record in records}
    assert "EQ:1234567" in by_id
    assert by_id["EQ:1234567"]["source_revision"] == "1"
    assert "FL:7654321" in by_id
    # The flood feature has no episodeid: revision must be None, never 0 or "".
    assert by_id["FL:7654321"]["source_revision"] is None


def test_stable_id_field_contract_is_composite(gdacs_contract: dict) -> None:
    assert gdacs_contract["stable_id_field"] == ["eventtype", "eventid"]
    assert gdacs_contract["revision_id_field"] == "episodeid"


# --- Missing optional fields -------------------------------------------------


def test_missing_optional_fields_do_not_crash_normalization() -> None:
    feature = {
        "type": "Feature",
        "properties": {
            "eventtype": "FL",
            "eventid": 42,
            "country": "Testland",
            "fromdate": "2026-07-01T00:00:00",
        },
        "geometry": None,
    }
    record, warnings = normalize_event(feature)
    assert record["source_external_id"] == "FL:42"
    assert record["source_revision"] is None
    assert "source_alert_level" not in record.get("source_signal", {})
    assert any("fallback title" in warning for warning in warnings)


# --- One malformed record among valid records --------------------------------


def test_one_malformed_record_does_not_discard_the_page() -> None:
    records, warnings = parse_event_list(FIXTURE.read_bytes())
    # Fixture has 3 features: 2 valid, 1 malformed (missing eventid).
    assert len(records) == 2
    assert any(warning.startswith("feature[2]: rejected") for warning in warnings)


def test_malformed_feature_missing_properties_is_rejected() -> None:
    with pytest.raises(MalformedGdacsRecordError):
        normalize_event({"type": "Feature"})


def test_malformed_feature_missing_geography_is_rejected() -> None:
    with pytest.raises(MalformedGdacsRecordError):
        normalize_event(
            {
                "type": "Feature",
                "properties": {"eventtype": "EQ", "eventid": 1, "fromdate": "2026-07-01T00:00:00"},
            }
        )


# --- Source alert level stays separate from platform severity ---------------


def test_source_alert_level_is_a_signal_not_platform_severity() -> None:
    records, _ = parse_event_list(FIXTURE.read_bytes())
    eq_record = next(r for r in records if r["source_external_id"] == "EQ:1234567")
    assert eq_record["source_signal"]["source_alert_level"] == "Orange"
    # The staging schema has no top-level severity/impact field at all --
    # the alert level only ever appears nested under source_signal.
    assert "severity" not in eq_record
    assert "impact_severity" not in eq_record
    assert "platform_severity" not in eq_record


# --- Date parsing and geometry handling --------------------------------------


def test_date_parsing_produces_event_and_publication_dates() -> None:
    records, _ = parse_event_list(FIXTURE.read_bytes())
    eq_record = next(r for r in records if r["source_external_id"] == "EQ:1234567")
    identity_inputs = eq_record["candidate_identity_inputs"]
    assert identity_inputs["event_date"] == "2026-07-20"
    assert identity_inputs["publication_date"] == "2026-07-20"


def test_valid_point_geometry_is_preserved() -> None:
    records, _ = parse_event_list(FIXTURE.read_bytes())
    eq_record = next(r for r in records if r["source_external_id"] == "EQ:1234567")
    geometry = eq_record["source_signal"]["geometry"]
    assert geometry == {"type": "Point", "coordinates": [120.98, 14.6]}


def test_invalid_geometry_degrades_with_a_warning_not_a_crash() -> None:
    feature = {
        "type": "Feature",
        "properties": {
            "eventtype": "EQ",
            "eventid": 999,
            "country": "Testland",
            "fromdate": "2026-07-01T00:00:00",
        },
        "geometry": {"type": "Point", "coordinates": [999.0, 999.0]},
    }
    record, warnings = normalize_event(feature)
    assert "geometry" not in record.get("source_signal", {})
    assert any("out of range" in warning for warning in warnings)


def test_malformed_datetime_falls_back_to_none_not_a_crash() -> None:
    feature = {
        "type": "Feature",
        "properties": {
            "eventtype": "EQ",
            "eventid": 1000,
            "country": "Testland",
            "fromdate": "not-a-date",
        },
        "geometry": None,
    }
    record, _ = normalize_event(feature)
    assert record["candidate_identity_inputs"]["event_date"] is None


# --- Staging record schema compliance + collect() integration --------------


def test_normalized_records_are_schema_valid_staging_records(staging_record_validator) -> None:
    records, _ = parse_event_list(FIXTURE.read_bytes())
    for record in records:
        record["content_sha256"] = "a" * 64
        errors = list(staging_record_validator.iter_errors(record))
        assert errors == []


def test_collect_end_to_end_with_fake_http_produces_no_network_access(gdacs_contract: dict) -> None:
    fake_http = FakeHttpClient(body=FIXTURE.read_bytes())
    adapter = GdacsAdapter(
        gdacs_contract,
        http=fake_http,
        from_date="2026-07-01",
        to_date="2026-07-23",
    )
    result = adapter.collect()
    assert result.run.status.value == "success"
    assert result.run.records_emitted == 2
    assert result.run.records_rejected == 1
    assert all(
        record["content_sha256"]
        == fake_http.get(
            result.run.request_url, timeout_seconds=1, max_response_bytes=10_000_000
        ).content_sha256
        for record in result.records
    )
