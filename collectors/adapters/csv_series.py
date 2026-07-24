"""Fixture-first bounded CSV series adapter.

One adapter serves every structured numeric source in Bundle 1 -- trade,
port activity, fuel, FX, freight benchmark and global baseline -- because
they all publish the same shape: a period column and one or more value
columns. What differs between them is metadata, and that lives in a
``SeriesSpec`` rather than in a per-source parser.

Safety posture, inherited from the repository's existing collector model and
not relaxed anywhere:

* The adapter parses **bytes it is handed**. It performs no fetching itself,
  so importing or testing it can never make a network request.
* Content type is validated against an explicit allowlist before parsing.
* Response size, row count, column count and field width are all bounded.
* A malformed row, an unparseable date, an unexpected header or a value that
  is neither a number nor a recognised missing-marker fails the whole parse
  rather than producing a partial series. Failing closed matters more than
  salvaging rows: a silently truncated trade series looks exactly like a
  trade collapse.
* An empty or explicitly-missing cell becomes ``value_status='missing'`` with
  a null value. It never becomes zero.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from ..http_client import validate_content_type
from ..observations import build_observation, content_hash, deduplicate_observations

#: Content types a CSV series may legitimately arrive as. An HTML error or
#: login page returned in place of data is rejected here, before parsing.
ALLOWED_CONTENT_TYPES = ("text/csv", "application/csv", "text/plain", "application/octet-stream")

#: Hard bounds. These are parser-level limits applied in addition to the
#: transport-level ``max_response_bytes`` in each source contract.
MAX_BYTES = 25_000_000
MAX_ROWS = 20_000
MAX_COLUMNS = 64
MAX_FIELD_LENGTH = 512

#: Cell contents recognised as an explicit "the source published no value
#: here" marker. Everything else that is not a number is a parse failure.
MISSING_MARKERS = frozenset({"", "-", "--", "n/a", "na", "nan", "null", "none", ".", ":"})

ObservationFamily = Literal["indicator", "trade", "port", "cost"]


class CsvContractError(ValueError):
    """Raised when the payload does not match the declared series contract.

    The message names the column or row at fault and never echoes cell
    contents, so a parse failure cannot leak restricted source content into
    a log or a CI artifact.
    """


class ResponseTooLargeError(ValueError):
    """Raised when the payload exceeds the parser's own byte or row bound."""


@dataclass(slots=True, frozen=True)
class SeriesSpec:
    """Everything needed to turn one CSV column into observation records."""

    series_id: str
    family: ObservationFamily
    value_column: str
    unit: str
    period_type: str
    evidence_class: str
    currency: str | None = None
    geography_id: str | None = None
    country_id: str | None = None
    transport_mode: str = "not_applicable"
    lane_id: str | None = None
    node_id: str | None = None
    known_limitations: tuple[str, ...] = ()
    #: Family-specific fields merged into the emitted record, e.g.
    #: ``{"flow_direction": "export", "measure": "value"}`` for a trade
    #: series or ``{"benchmark_class": "market_benchmark"}`` for a cost one.
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CsvSeriesContract:
    """The parse contract for one CSV payload."""

    source_id: str
    parser_version: str
    period_column: str
    series: tuple[SeriesSpec, ...]
    #: Optional column carrying the source's own publication timestamp.
    published_at_column: str | None = None
    #: Optional column carrying a per-row source record identifier.
    source_record_id_column: str | None = None
    #: Optional column carrying a revision marker.
    revision_column: str | None = None


def _period_bounds(period_value: str, period_type: str) -> tuple[str, str, str]:
    """Return ``(period_start, period_end, period_key)`` for a period cell.

    Only two period shapes are accepted: ``YYYY-MM`` for a month and a full
    ISO date for a day. Anything else is a contract error rather than a
    best-effort guess, because guessing a period silently mis-dates every
    derived change.
    """
    text = period_value.strip()
    if len(text) == 7 and text[4] == "-":
        try:
            year, month = int(text[:4]), int(text[5:7])
            start = date(year, month, 1)
        except ValueError as exc:
            raise CsvContractError("period column holds an unparseable YYYY-MM month") from exc
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1).toordinal() - 1
            end = date.fromordinal(end)
        if period_type != "month":
            raise CsvContractError(
                f"period column holds a month but the series declares period_type {period_type!r}"
            )
        return start.isoformat(), end.isoformat(), text
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise CsvContractError("period column value is not an ISO date or YYYY-MM month") from exc
    if period_type not in {"day", "point_in_time"}:
        raise CsvContractError(
            f"period column holds a date but the series declares period_type {period_type!r}"
        )
    return parsed.isoformat(), parsed.isoformat(), parsed.isoformat()


def _parse_value(cell: str) -> tuple[float | None, str]:
    """Return ``(value, value_status)`` for one cell.

    A recognised missing marker yields ``(None, 'missing')``. A number yields
    ``(value, 'available')``. Anything else raises, because an unrecognised
    token in a numeric column means the file is not what the contract says
    it is.
    """
    text = cell.strip()
    if text.lower() in MISSING_MARKERS:
        return None, "missing"
    normalized = text.replace(",", "").replace("−", "-")
    try:
        return float(normalized), "available"
    except ValueError as exc:
        raise CsvContractError(
            "value column contains a token that is neither a number nor a recognised missing marker"
        ) from exc


def parse_csv_series(
    payload: bytes,
    contract: CsvSeriesContract,
    *,
    retrieved_at: str,
    content_type: str | None = "text/csv",
    max_bytes: int = MAX_BYTES,
    max_rows: int = MAX_ROWS,
) -> list[dict[str, Any]]:
    """Parse a CSV payload into observation records.

    Raises rather than returning a partial result on any contract violation.
    """
    if content_type is not None:
        # Raises UnexpectedContentTypeError before any parsing happens, so an
        # HTML error or login page served in place of data is never read as CSV.
        validate_content_type({"content-type": content_type}, ALLOWED_CONTENT_TYPES)
    if len(payload) > max_bytes:
        raise ResponseTooLargeError(
            f"payload is {len(payload)} bytes, above the {max_bytes}-byte parser bound"
        )

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvContractError("payload is not valid UTF-8") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise CsvContractError("payload contains no header row") from exc

    if len(header) > MAX_COLUMNS:
        raise CsvContractError(
            f"header declares {len(header)} columns, above the {MAX_COLUMNS}-column bound"
        )
    header = [column.strip() for column in header]
    positions = {column: index for index, column in enumerate(header)}

    required = {contract.period_column, *(spec.value_column for spec in contract.series)}
    for optional in (
        contract.published_at_column,
        contract.source_record_id_column,
        contract.revision_column,
    ):
        if optional:
            required.add(optional)
    missing_columns = sorted(required - positions.keys())
    if missing_columns:
        raise CsvContractError(f"payload is missing required columns: {missing_columns}")

    payload_hash = content_hash(contract.source_id, contract.parser_version, text)
    records: list[dict[str, Any]] = []

    for row_number, row in enumerate(reader, start=2):
        if row_number - 1 > max_rows:
            raise ResponseTooLargeError(
                f"payload exceeds the {max_rows}-row parser bound at row {row_number}"
            )
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise CsvContractError(
                f"row {row_number} has {len(row)} fields but the header declares {len(header)}"
            )
        if any(len(cell) > MAX_FIELD_LENGTH for cell in row):
            raise CsvContractError(
                f"row {row_number} contains a field above the {MAX_FIELD_LENGTH}-character bound"
            )

        published_at = (
            row[positions[contract.published_at_column]].strip() or None
            if contract.published_at_column
            else None
        )
        source_record_id = (
            row[positions[contract.source_record_id_column]].strip() or None
            if contract.source_record_id_column
            else None
        )
        revision_raw = (
            row[positions[contract.revision_column]].strip() if contract.revision_column else ""
        )
        try:
            revision_number = int(revision_raw) if revision_raw else 0
        except ValueError as exc:
            raise CsvContractError(f"row {row_number} has a non-integer revision marker") from exc

        for spec in contract.series:
            period_start, period_end, period_key = _period_bounds(
                row[positions[contract.period_column]], spec.period_type
            )
            value, value_status = _parse_value(row[positions[spec.value_column]])
            records.append(
                build_observation(
                    source_id=contract.source_id,
                    series_id=spec.series_id,
                    period_key=period_key,
                    value=value,
                    value_status=value_status,
                    unit=spec.unit if value_status == "available" else None,
                    currency=spec.currency,
                    period_start=period_start,
                    period_end=period_end,
                    period_type=spec.period_type,
                    retrieved_at=retrieved_at,
                    parser_version=contract.parser_version,
                    evidence_class=spec.evidence_class,
                    content_sha256=payload_hash,
                    published_at=published_at,
                    revision_number=revision_number,
                    revised_at=published_at if revision_number > 0 else None,
                    source_record_id=source_record_id,
                    geography_id=spec.geography_id,
                    country_id=spec.country_id,
                    transport_mode=spec.transport_mode,
                    lane_id=spec.lane_id,
                    node_id=spec.node_id,
                    known_limitations=spec.known_limitations,
                    extra=dict(spec.attributes),
                )
            )

    return deduplicate_observations(records)


def group_by_family(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split parsed records into the four observation families.

    Family is inferred from the family-specific keys the ``SeriesSpec``
    contributed, so a record can never land in two families at once.
    """
    grouped: dict[str, list[dict[str, Any]]] = {
        "indicator_observations": [],
        "trade_observations": [],
        "port_observations": [],
        "cost_observations": [],
    }
    for record in records:
        if "flow_direction" in record:
            grouped["trade_observations"].append(dict(record))
        elif "metric" in record:
            grouped["port_observations"].append(dict(record))
        elif "cost_family" in record:
            grouped["cost_observations"].append(dict(record))
        else:
            grouped["indicator_observations"].append(dict(record))
    return grouped
