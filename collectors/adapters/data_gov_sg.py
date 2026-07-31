"""Fixture-first bounded parser for Singapore's data.gov.sg Datastore Search API.

Scope of this module (WO-026): **parsing only**. It turns a Datastore Search
JSON response into ``port_transport_observation`` records. It performs no
fetching itself -- there is deliberately no ``SourceAdapter``/``collect()``
wired to a live endpoint here, because the exact endpoint path and the exact
JSON field names below have not been independently confirmed by this
repository (this environment's ``WebFetch`` could not reach ``data.gov.sg`` --
see ``docs/mpa_sg_statistics_qualification.md``). The response shape parsed
here is the standard CKAN Datastore Search convention data.gov.sg's own
developer documentation names ("Datastore Search"), not a captured live
response. Confirming the real field names is the first step of the
controlled live-validation this Work Order explicitly does not perform.

Safety posture, matching every other adapter in this package:

* The parser consumes **bytes it is handed**. Importing or testing this
  module can never make a network request.
* Content type is validated against an explicit allowlist before parsing.
* Response size and record count are bounded.
* A missing field, a malformed month, or a value that is neither a number
  nor a recognised missing-marker fails the whole parse rather than
  producing a partial series -- the same fail-closed posture
  ``collectors/adapters/csv_series.py`` uses for the same reason.
* An empty or explicitly-missing cell becomes ``value_status='missing'``
  with a null value. It never becomes zero.
* The response's own ``result.resource_id`` must match the dataset the
  caller asked to parse, so a caller can never be handed one dataset's
  response and mistake it for another's.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from analysis.provenance import TECHNICAL_DEMO

from ..http_client import validate_content_type
from ..observations import build_observation, content_hash, deduplicate_observations

ADAPTER_VERSION = "data_gov_sg_v1"

#: data.gov.sg's Datastore Search API is documented as returning JSON.
ALLOWED_CONTENT_TYPES = ("application/json", "text/json")

#: Hard bounds. In addition to the transport-level ``max_response_bytes`` a
#: future source contract would carry.
MAX_BYTES = 5_000_000
MAX_RECORDS = 2_000
MAX_FIELD_LENGTH = 256

#: Cell contents recognised as an explicit "no value published" marker,
#: matching ``csv_series.py``'s convention.
MISSING_MARKERS = frozenset({"", "-", "--", "n/a", "na", "nan", "null", "none", "."})


class DatastoreContractError(ValueError):
    """Raised when the payload does not match the declared dataset contract.

    The message never echoes cell contents, so a parse failure cannot leak
    restricted source content into a log or a CI artifact.
    """


class ResponseTooLargeError(ValueError):
    """Raised when the payload exceeds the parser's own byte or record bound."""


@dataclass(slots=True, frozen=True)
class DatastoreSeriesSpec:
    """Everything needed to turn one Datastore Search resource into
    ``port_transport_observation`` records.

    ``month_field`` and ``value_field`` are this WO's best-effort guess at
    data.gov.sg's actual JSON field names, following common data.gov.sg
    naming convention -- **not independently confirmed**. Confirming them
    against a real response is the first action of the controlled
    live-validation this module does not perform.
    """

    resource_id: str
    series_id: str
    month_field: str
    value_field: str
    metric: str
    operational_interpretation: str
    #: Actual geographic resolution of the observation
    #: (``port_transport_observation.schema.json``'s ``resolution`` enum).
    #: Both selected datasets are Singapore-wide aggregates, not a single
    #: terminal, so ``country`` is the correct value for both -- never
    #: ``node``, which would misrepresent a national total as port-level.
    resolution: str
    unit: str
    evidence_class: str
    period_type: str = "month"
    geography_id: str | None = None
    country_id: str | None = None
    transport_mode: str = "not_applicable"
    known_limitations: tuple[str, ...] = ()
    #: Where records built from this spec come from. Defaults to the
    #: synthetic fixture origin, matching every other WO-010-style spec
    #: until a real collection run supplies ``live_retrieved`` explicitly.
    evidence_origin: str = "synthetic_test_fixture"
    #: The production source candidate a fixture stands in for. Required
    #: whenever ``evidence_origin`` is a fixture origin.
    intended_source_id: str | None = None


@dataclass(slots=True, frozen=True)
class DatastoreSearchContract:
    """The parse contract for one Datastore Search JSON payload.

    ``source_id`` is the source the payload actually came from. For a local
    fixture that is the reserved synthetic identifier, never the publisher
    the fixture imitates.
    """

    source_id: str
    parser_version: str
    series: DatastoreSeriesSpec


def _parse_period(value: str) -> tuple[str, str, str]:
    """Return ``(period_start, period_end, period_key)`` for a ``YYYY-MM``
    month string -- the only period shape this parser accepts, matching the
    "Monthly" cadence both selected datasets publish at."""
    text = value.strip()
    if len(text) != 7 or text[4] != "-":
        raise DatastoreContractError("month field is not a YYYY-MM string")
    try:
        year, month = int(text[:4]), int(text[5:7])
        start = date(year, month, 1)
    except ValueError as exc:
        raise DatastoreContractError("month field does not parse as a calendar month") from exc
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date.fromordinal(date(year, month + 1, 1).toordinal() - 1)
    return start.isoformat(), end.isoformat(), text


def _finite_or_raise(value: float) -> float:
    """Reject NaN/Infinity: never a real throughput or vessel-call count.

    ``json.loads`` accepts the non-standard ``NaN``/``Infinity``/``-Infinity``
    literals by default, and ``float()`` accepts ``"inf"``/``"infinity"``
    strings; neither is a recognised missing-marker, and a non-finite value
    would pass schema validation (jsonschema treats ``nan`` as a number) and
    then serialize as invalid JSON (``json.dumps`` emits bare ``NaN`` /
    ``Infinity``, which RFC 8259 does not permit). Caught here rather than
    left to whatever reads the record next.
    """
    if not math.isfinite(value):
        raise DatastoreContractError(
            "value field is not a finite number (NaN or Infinity), which is neither a "
            "real measurement nor a recognised missing marker"
        )
    return value


def _parse_value(cell: Any) -> tuple[float | None, str]:
    """Return ``(value, value_status)`` for one field value.

    Accepts a number or a numeric string (Datastore Search commonly returns
    numeric fields as strings); anything else that is not a recognised
    missing marker is a contract error rather than a best-effort guess.
    """
    if cell is None:
        return None, "missing"
    if isinstance(cell, bool):
        raise DatastoreContractError("value field is a boolean, not a number")
    if isinstance(cell, (int, float)):
        return _finite_or_raise(float(cell)), "available"
    if isinstance(cell, str):
        text = cell.strip()
        if text.lower() in MISSING_MARKERS:
            return None, "missing"
        normalized = text.replace(",", "")
        try:
            parsed = float(normalized)
        except ValueError as exc:
            raise DatastoreContractError(
                "value field contains a token that is neither a number nor a recognised "
                "missing marker"
            ) from exc
        return _finite_or_raise(parsed), "available"
    raise DatastoreContractError(f"value field has an unsupported type: {type(cell).__name__}")


def parse_datastore_search_response(
    payload: bytes,
    contract: DatastoreSearchContract,
    *,
    retrieved_at: str | None = None,
    fixture_created_at: str | None = None,
    retrieval_status: str = "not_retrieved",
    content_hash_scope: str = "local_fixture_payload",
    dataset: str = TECHNICAL_DEMO,
    content_type: str | None = "application/json",
    max_bytes: int = MAX_BYTES,
    max_records: int = MAX_RECORDS,
) -> list[dict[str, Any]]:
    """Parse one Datastore Search JSON response into observation records.

    Raises rather than returning a partial result on any contract
    violation, matching ``csv_series.parse_csv_series``.
    """
    if content_type is not None:
        # Raises before any parsing happens, so an HTML error or login page
        # served in place of data is never read as JSON.
        validate_content_type({"content-type": content_type}, ALLOWED_CONTENT_TYPES)
    if len(payload) > max_bytes:
        raise ResponseTooLargeError(
            f"payload is {len(payload)} bytes, above the {max_bytes}-byte parser bound"
        )

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatastoreContractError("payload is not valid UTF-8") from exc

    def _reject_non_finite_constant(token: str) -> float:
        # json.loads accepts the non-standard NaN/Infinity/-Infinity literals
        # by default; parse_constant is the hook that intercepts them before
        # they become a Python float that would otherwise sail through
        # _parse_value's isinstance(cell, (int, float)) branch unfinished.
        raise DatastoreContractError(
            f"payload contains the non-standard JSON constant {token!r}, not a real number"
        )

    try:
        data = json.loads(text, parse_constant=_reject_non_finite_constant)
    except json.JSONDecodeError as exc:
        raise DatastoreContractError("payload is not valid JSON") from exc

    if not isinstance(data, Mapping):
        raise DatastoreContractError("response body is not a JSON object")
    if data.get("success") is not True:
        raise DatastoreContractError("response 'success' field is not true")

    result = data.get("result")
    if not isinstance(result, Mapping):
        raise DatastoreContractError("response 'result' is missing or not an object")

    spec = contract.series
    resource_id = result.get("resource_id")
    if resource_id != spec.resource_id:
        raise DatastoreContractError(
            f"response result.resource_id {resource_id!r} does not match the expected "
            f"dataset {spec.resource_id!r} -- refusing to attribute one dataset's response "
            "to another"
        )

    records_field = result.get("records")
    if not isinstance(records_field, list):
        raise DatastoreContractError("response 'result.records' is missing or not a list")
    if len(records_field) > max_records:
        raise ResponseTooLargeError(
            f"response carries {len(records_field)} records, above the {max_records}-record "
            "parser bound"
        )

    payload_hash = content_hash(contract.source_id, contract.parser_version, text)
    out: list[dict[str, Any]] = []

    for index, row in enumerate(records_field):
        if not isinstance(row, Mapping):
            raise DatastoreContractError(f"result.records[{index}] is not an object")
        if spec.month_field not in row:
            raise DatastoreContractError(
                f"result.records[{index}] is missing the expected field {spec.month_field!r}"
            )
        if spec.value_field not in row:
            raise DatastoreContractError(
                f"result.records[{index}] is missing the expected field {spec.value_field!r}"
            )

        month_raw = row[spec.month_field]
        if not isinstance(month_raw, str) or len(month_raw) > MAX_FIELD_LENGTH:
            raise DatastoreContractError(
                f"result.records[{index}] field {spec.month_field!r} is not a bounded string"
            )
        period_start, period_end, period_key = _parse_period(month_raw)
        value, value_status = _parse_value(row[spec.value_field])

        out.append(
            build_observation(
                source_id=contract.source_id,
                series_id=spec.series_id,
                period_key=period_key,
                value=value,
                value_status=value_status,
                unit=spec.unit if value_status == "available" else None,
                currency=None,
                period_start=period_start,
                period_end=period_end,
                period_type=spec.period_type,
                retrieved_at=retrieved_at,
                retrieval_status=retrieval_status,
                content_hash_scope=content_hash_scope,
                dataset=dataset,
                evidence_origin=spec.evidence_origin,
                intended_source_id=spec.intended_source_id,
                fixture_created_at=fixture_created_at,
                parser_version=contract.parser_version,
                evidence_class=spec.evidence_class,
                content_sha256=payload_hash,
                geography_id=spec.geography_id,
                country_id=spec.country_id,
                transport_mode=spec.transport_mode,
                known_limitations=spec.known_limitations,
                extra={
                    "series_id": spec.series_id,
                    "metric": spec.metric,
                    "operational_interpretation": spec.operational_interpretation,
                    "resolution": spec.resolution,
                },
            )
        )

    return deduplicate_observations(out)


def group_by_family(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every record this module produces is a port observation.

    Kept as its own function, matching ``csv_series.group_by_family``'s
    shape, so a caller does not need to special-case which module produced
    which records.
    """
    return {"port_observations": [dict(record) for record in records]}
