"""CSV series adapter: fixture parsing and fail-closed behaviour.

Nothing in this file makes a network request, and nothing can: the adapter
parses bytes it is handed and has no fetch path at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from collectors.adapters.csv_series import (
    CsvContractError,
    CsvSeriesContract,
    ResponseTooLargeError,
    SeriesSpec,
    group_by_family,
    parse_csv_series,
)
from collectors.http_client import UnexpectedContentTypeError
from collectors.series_catalog import (
    COST_CONTRACT,
    INDICATOR_CONTRACT,
    PORT_CONTRACT,
    TRADE_CONTRACT,
)

FIXTURES = Path(__file__).parent / "fixtures" / "csv_series"
RETRIEVED = "2026-07-24T00:00:00Z"


def _parse(filename: str, contract: CsvSeriesContract, **kwargs):
    return parse_csv_series(
        (FIXTURES / filename).read_bytes(), contract, retrieved_at=RETRIEVED, **kwargs
    )


def _series(records, series_id):
    return [
        record
        for record in records
        if (record.get("series_id") or record.get("indicator_id")) == series_id
    ]


# ---------------------------------------------------------------------------
# Per-source fixture tests. These names are referenced by the enablement
# records in config/sources.yaml, so a source's claim that a fixture test
# exists is checkable.
# ---------------------------------------------------------------------------


def test_trade_fixture_parses():
    records = _parse("thailand_trade_by_lane_monthly.csv", TRADE_CONTRACT)
    exports = _series(records, "th_export_value_neur")
    assert len(exports) == 30
    assert exports[0]["flow_direction"] == "export"
    assert exports[0]["reporter_country_id"] == "TH"
    assert exports[0]["placement"]["lane_id"] == "LANE-OCEAN-TH-NEUR"
    assert all(record["provenance"]["source_id"] == "TH_CUSTOMS" for record in exports)


def test_port_fixture_parses():
    records = _parse("thailand_port_activity_monthly.csv", PORT_CONTRACT)
    calls = _series(records, "thailand_port_calls")
    assert len(calls) == 30
    assert calls[0]["metric"] == "vessel_calls"
    assert calls[0]["operational_interpretation"] == "volume_only"


def test_fuel_fixture_parses():
    records = _parse("cost_and_freight_monthly.csv", COST_CONTRACT)
    fuel = _series(records, "thailand_diesel_retail_price")
    assert len(fuel) == 30
    assert fuel[0]["cost_family"] == "retail_fuel"
    assert fuel[0]["quotation_claim"] == "not_a_quotation"


def test_gscpi_fixture_parses():
    records = _parse("baseline_indicators_monthly.csv", INDICATOR_CONTRACT)
    gscpi = _series(records, "gscpi_index")
    assert len(gscpi) == 30
    assert gscpi[0]["indicator_family"] == "global_baseline"
    assert gscpi[0]["baseline_definition"] is not None


def test_fx_fixture_parses():
    records = _parse("baseline_indicators_monthly.csv", INDICATOR_CONTRACT)
    fx = _series(records, "usd_thb_reference_rate")
    assert len(fx) == 30
    assert fx[0]["indicator_family"] == "fx"
    assert fx[0]["measurement"]["currency"] == "THB"


def test_connectivity_fixture_parses():
    records = _parse("baseline_indicators_monthly.csv", INDICATOR_CONTRACT)
    lsci = _series(records, "thailand_lsci")
    assert len(lsci) == 30
    assert lsci[0]["indicator_family"] == "connectivity"


# ---------------------------------------------------------------------------
# Missing values
# ---------------------------------------------------------------------------


def test_empty_cells_become_missing_not_zero():
    records = _parse("baseline_indicators_monthly.csv", INDICATOR_CONTRACT)
    lsci = _series(records, "thailand_lsci")
    missing = [record for record in lsci if record["measurement"]["value_status"] != "available"]
    assert len(missing) == 3
    for record in missing:
        assert record["measurement"]["value"] is None
        assert record["measurement"]["value_status"] == "missing"
        assert record["measurement"]["unit"] is None


@pytest.mark.parametrize("marker", ["", "-", "n/a", "NA", "null", "None", ".", ":"])
def test_recognised_missing_markers(marker):
    contract = CsvSeriesContract(
        source_id="TEST_SRC",
        parser_version="test_v1",
        period_column="period",
        series=(
            SeriesSpec(
                series_id="probe",
                family="indicator",
                value_column="value",
                unit="index_points",
                period_type="month",
                evidence_class="synthetic_test_fixture",
                attributes={"indicator_id": "probe", "indicator_name": "Probe"},
            ),
        ),
    )
    payload = f"period,value\n2026-01,{marker}\n".encode()
    record = parse_csv_series(payload, contract, retrieved_at=RETRIEVED)[0]
    assert record["measurement"]["value"] is None
    assert record["measurement"]["value_status"] == "missing"


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_unexpected_content_type_is_rejected_before_parsing():
    with pytest.raises(UnexpectedContentTypeError):
        _parse("cost_and_freight_monthly.csv", COST_CONTRACT, content_type="text/html")


def test_oversized_payload_is_rejected():
    with pytest.raises(ResponseTooLargeError, match="parser bound"):
        _parse("cost_and_freight_monthly.csv", COST_CONTRACT, max_bytes=100)


def test_too_many_rows_is_rejected():
    with pytest.raises(ResponseTooLargeError, match="row parser bound"):
        _parse("cost_and_freight_monthly.csv", COST_CONTRACT, max_rows=3)


def test_missing_required_column_is_rejected():
    payload = b"period,other\n2026-01,1.0\n"
    with pytest.raises(CsvContractError, match="missing required columns"):
        parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_ragged_row_is_rejected_rather_than_truncating_the_series():
    payload = b"period,published_at,usd_thb_rate,gscpi_index,thailand_lsci\n2026-01,x,1,2\n"
    with pytest.raises(CsvContractError, match="fields but the header declares"):
        parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_unparseable_period_is_rejected():
    payload = b"period,published_at,usd_thb_rate,gscpi_index,thailand_lsci\nQ1-2026,x,1,2,3\n"
    with pytest.raises(CsvContractError, match="not an ISO date or YYYY-MM month"):
        parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_non_numeric_token_is_rejected_rather_than_silently_dropped():
    payload = (
        b"period,published_at,usd_thb_rate,gscpi_index,thailand_lsci\n2026-01,x,about 34,2,3\n"
    )
    with pytest.raises(CsvContractError, match="neither a number nor a recognised"):
        parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_payload_that_is_not_utf8_is_rejected():
    with pytest.raises(CsvContractError, match="not valid UTF-8"):
        parse_csv_series(b"\xff\xfe\x00bad", INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_empty_payload_is_rejected():
    with pytest.raises(CsvContractError, match="no header row"):
        parse_csv_series(b"", INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


def test_overlong_field_is_rejected():
    payload = (
        b"period,published_at,usd_thb_rate,gscpi_index,thailand_lsci\n2026-01,"
        + b"x" * 600
        + b",1,2,3\n"
    )
    with pytest.raises(CsvContractError, match="character bound"):
        parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)


# ---------------------------------------------------------------------------
# Duplicates, revisions and grouping
# ---------------------------------------------------------------------------


def test_duplicate_source_rows_collapse_to_one_record():
    payload = (
        b"period,published_at,usd_thb_rate,gscpi_index,thailand_lsci\n"
        b"2026-01,2026-01-15T00:00:00Z,34.5,0.1,42.0\n"
        b"2026-01,2026-01-15T00:00:00Z,34.5,0.1,42.0\n"
    )
    records = parse_csv_series(payload, INDICATOR_CONTRACT, retrieved_at=RETRIEVED)
    assert len(_series(records, "usd_thb_reference_rate")) == 1


def test_a_later_revision_supersedes_the_earlier_value():
    contract = CsvSeriesContract(
        source_id="TEST_SRC",
        parser_version="test_v1",
        period_column="period",
        revision_column="revision",
        published_at_column="published_at",
        series=(
            SeriesSpec(
                series_id="probe",
                family="indicator",
                value_column="value",
                unit="index_points",
                period_type="month",
                evidence_class="synthetic_test_fixture",
                attributes={"indicator_id": "probe", "indicator_name": "Probe"},
            ),
        ),
    )
    payload = (
        b"period,published_at,revision,value\n"
        b"2026-01,2026-02-01T00:00:00Z,0,100\n"
        b"2026-01,2026-03-01T00:00:00Z,1,115\n"
    )
    records = parse_csv_series(payload, contract, retrieved_at=RETRIEVED)
    assert len(records) == 1
    assert records[0]["measurement"]["value"] == 115.0
    assert records[0]["provenance"]["revision_number"] == 1
    assert records[0]["provenance"]["revised_at"] == "2026-03-01T00:00:00Z"


def test_non_integer_revision_marker_is_rejected():
    contract = CsvSeriesContract(
        source_id="TEST_SRC",
        parser_version="test_v1",
        period_column="period",
        revision_column="revision",
        series=(
            SeriesSpec(
                series_id="probe",
                family="indicator",
                value_column="value",
                unit="index_points",
                period_type="month",
                evidence_class="synthetic_test_fixture",
                attributes={"indicator_id": "probe", "indicator_name": "Probe"},
            ),
        ),
    )
    with pytest.raises(CsvContractError, match="non-integer revision marker"):
        parse_csv_series(
            b"period,revision,value\n2026-01,r1,100\n", contract, retrieved_at=RETRIEVED
        )


def test_group_by_family_never_places_a_record_in_two_families():
    records = (
        _parse("thailand_trade_by_lane_monthly.csv", TRADE_CONTRACT)
        + _parse("thailand_port_activity_monthly.csv", PORT_CONTRACT)
        + _parse("cost_and_freight_monthly.csv", COST_CONTRACT)
        + _parse("baseline_indicators_monthly.csv", INDICATOR_CONTRACT)
    )
    grouped = group_by_family(records)
    total = sum(len(items) for items in grouped.values())
    assert total == len(records)
    assert len(grouped["trade_observations"]) == 660
    assert len(grouped["port_observations"]) == 90
    assert len(grouped["cost_observations"]) == 90
    assert len(grouped["indicator_observations"]) == 90


def test_content_hash_is_shared_by_every_record_from_one_payload():
    records = _parse("cost_and_freight_monthly.csv", COST_CONTRACT)
    hashes = {record["provenance"]["content_sha256"] for record in records}
    assert len(hashes) == 1
