"""GDACS event-list adapter (Scope B, WO-002 Implementation v0.2).

Builds deterministic requests against the official GDACS event-list SEARCH
endpoint and normalizes GeoJSON/JSON event-list responses into staging
records (``schemas/staging_record.schema.json``). This adapter never infers
operational logistics impact: GDACS alert levels and impact estimates are
model outputs, carried through unchanged as an explicit ``source_alert_level``
/ ``source_signal``, never as platform severity. See
``docs/gdacs_tmd_cap_pilot.md`` for the full design rationale and verified
source facts this adapter relies on.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from ..base import SourceAdapter
from ..models import CollectionResult, CollectionRun, RunStatus, SourceHealth, SourceStatus
from ..staging import build_staging_record

ADAPTER_VERSION = "gdacs_v1"

#: GDACS documents a 100-record maximum per page (GDACS_API_quickstart_v1.pdf).
#: No official fixed polling cadence was found; this cap is the one hard
#: numeric limit verified against the official documentation.
OFFICIAL_MAX_PAGE_SIZE = 100

_KNOWN_LIMITATIONS = (
    "GDACS alert levels and impact estimates are model outputs (a hazard/"
    "context signal), not verified operational logistics impact.",
    "No official fixed polling cadence or public rate-limit quota was found "
    "for GDACS; expected_cadence_minutes is unknown.",
    "Automatic GDACS notifications may contain uncertainty or error, do not "
    "replace national authorities, and have no guaranteed completeness or "
    "timeliness.",
)

_FIELD_MAPPING_NOTES = (
    "source_external_id = properties.eventtype + ':' + properties.eventid "
    "(composite stable identity, not eventid alone).",
    "source_revision = properties.episodeid (episode/revision identity, "
    "kept separate from source_external_id).",
    "source_signal.source_alert_level = properties.alertlevel (or "
    "episodealertlevel) -- a source hazard signal, never platform severity.",
    "candidate_identity_inputs.event_date = properties.fromdate (date "
    "component only); publication_date = properties.todate or "
    "properties.datemodified, falling back to fromdate.",
    "geography = [properties.iso3, properties.country], filtered to "
    "whichever of the two the response actually provided.",
)


class MalformedGdacsRecordError(ValueError):
    """Raised for one malformed feature; callers downgrade this to a warning
    and continue processing the remaining features on the page."""


@dataclass(slots=True, frozen=True)
class GdacsSearchRequest:
    """A fully-specified, deterministic GDACS SEARCH request."""

    endpoint: str
    from_date: str
    to_date: str
    event_types: tuple[str, ...] = ()
    alert_levels: tuple[str, ...] = ()
    page_number: int = 1
    page_size: int = OFFICIAL_MAX_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page_size < 1:
            raise ValueError("GDACS page_size must be at least 1")
        if self.page_size > OFFICIAL_MAX_PAGE_SIZE:
            raise ValueError(
                f"GDACS page_size {self.page_size} exceeds the official maximum of "
                f"{OFFICIAL_MAX_PAGE_SIZE} records per page"
            )
        if self.page_number < 1:
            raise ValueError("GDACS page_number must be at least 1")
        if not self.from_date or not self.to_date:
            raise ValueError("GDACS search requires an explicit fromdate and todate")

    def to_url(self) -> str:
        """Render a deterministic, sorted query string for this request."""
        params: dict[str, str] = {
            "fromdate": self.from_date,
            "todate": self.to_date,
            "pagenumber": str(self.page_number),
            "pagesize": str(self.page_size),
        }
        if self.event_types:
            params["eventlist"] = ";".join(sorted(self.event_types))
        if self.alert_levels:
            params["alertlevel"] = ";".join(sorted(self.alert_levels))
        query = urlencode(sorted(params.items()))
        return f"{self.endpoint}?{query}"


def build_search_request(
    contract: Mapping[str, Any],
    *,
    from_date: str,
    to_date: str,
    event_types: Sequence[str] = (),
    alert_levels: Sequence[str] = (),
    page_number: int = 1,
    page_size: int | None = None,
) -> GdacsSearchRequest:
    """Build a deterministic request from a Source Contract and explicit inputs.

    ``page_size`` defaults to the contract's configured ``pagination.page_size``
    (or the official 100-record maximum if the contract does not set one) and
    is always bounded by ``pagination.max_page_size`` when the contract
    declares it, in addition to the hardcoded ``OFFICIAL_MAX_PAGE_SIZE``.
    """
    pagination = contract.get("pagination", {})
    contract_max = pagination.get("max_page_size") or OFFICIAL_MAX_PAGE_SIZE
    effective_max = min(OFFICIAL_MAX_PAGE_SIZE, contract_max)
    resolved_page_size = page_size or pagination.get("page_size") or effective_max
    if resolved_page_size > effective_max:
        raise ValueError(
            f"Requested page_size {resolved_page_size} exceeds the source contract's "
            f"maximum of {effective_max} records per page"
        )
    return GdacsSearchRequest(
        endpoint=str(contract["endpoint"]),
        from_date=from_date,
        to_date=to_date,
        event_types=tuple(event_types),
        alert_levels=tuple(alert_levels),
        page_number=page_number,
        page_size=resolved_page_size,
    )


def _parse_gdacs_datetime(value: Any) -> str | None:
    """Parse a GDACS timestamp into an ISO-8601 UTC date-time, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _date_only(iso_datetime: str | None) -> str | None:
    if not iso_datetime:
        return None
    return iso_datetime[:10]


def _extract_geometry(feature: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (validated geometry, warning). Invalid geometry degrades to
    None with a warning rather than rejecting the whole record."""
    geometry = feature.get("geometry")
    if geometry is None:
        return None, None
    if not isinstance(geometry, Mapping):
        return None, "geometry is present but not an object; dropped"

    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geom_type == "Point" and isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        lon, lat = coordinates[0], coordinates[1]
        if (
            isinstance(lon, (int, float))
            and isinstance(lat, (int, float))
            and -180.0 <= lon <= 180.0
            and -90.0 <= lat <= 90.0
        ):
            return {"type": "Point", "coordinates": [lon, lat]}, None
        return None, f"Point geometry coordinates out of range: {coordinates!r}"

    if geom_type in {"Polygon", "MultiPolygon"} and isinstance(coordinates, (list, tuple)):
        return {"type": geom_type, "coordinates": coordinates}, None

    return None, f"unrecognized or malformed geometry type: {geom_type!r}"


def normalize_event(feature: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normalize one GDACS GeoJSON feature into a staging record.

    Raises ``MalformedGdacsRecordError`` if the feature lacks the minimum
    fields required for stable identity or geography; callers must catch
    this per-record so one malformed feature does not discard an otherwise
    valid page.
    """
    warnings: list[str] = []
    if not isinstance(feature, Mapping):
        raise MalformedGdacsRecordError("feature is not an object")

    properties = feature.get("properties")
    if not isinstance(properties, Mapping):
        raise MalformedGdacsRecordError("feature.properties is missing or not an object")

    eventtype = properties.get("eventtype")
    eventid = properties.get("eventid")
    if not eventtype or eventid is None:
        raise MalformedGdacsRecordError(
            "feature.properties is missing eventtype and/or eventid; stable identity requires both"
        )
    source_external_id = f"{eventtype}:{eventid}"

    episodeid = properties.get("episodeid")
    source_revision = str(episodeid) if episodeid is not None else None

    country = properties.get("country")
    iso3 = properties.get("iso3")
    geography = [value for value in (iso3, country) if isinstance(value, str) and value]
    if not geography:
        raise MalformedGdacsRecordError(
            f"{source_external_id}: feature has neither country nor iso3; cannot "
            "establish geography"
        )

    from_date = _parse_gdacs_datetime(properties.get("fromdate"))
    to_date = _parse_gdacs_datetime(properties.get("todate"))
    date_modified = _parse_gdacs_datetime(properties.get("datemodified"))
    publication_time = to_date or date_modified or from_date
    event_date = _date_only(from_date)
    publication_date = _date_only(publication_time) or event_date

    alert_level = properties.get("alertlevel") or properties.get("episodealertlevel")
    alert_score = properties.get("alertscore")
    if alert_score is None:
        alert_score = properties.get("episodealertscore")
    source_signal: dict[str, Any] = {}
    if alert_level is not None:
        source_signal["source_alert_level"] = alert_level
    if alert_score is not None:
        source_signal["source_alert_score"] = alert_score
    severity_data = properties.get("severitydata")
    if isinstance(severity_data, Mapping):
        if severity_data.get("severity") is not None:
            source_signal["source_severity_value"] = severity_data.get("severity")
        if severity_data.get("severitytext"):
            source_signal["source_severity_text"] = severity_data.get("severitytext")

    geometry, geometry_warning = _extract_geometry(feature)
    if geometry_warning:
        warnings.append(f"{source_external_id}: {geometry_warning}")
    if geometry is not None:
        source_signal["geometry"] = geometry

    title = properties.get("name") or properties.get("eventname")
    if not title:
        title = f"GDACS {eventtype} event {eventid}"
        warnings.append(
            f"{source_external_id}: no source-provided name/eventname; used a fallback title"
        )

    source_url = None
    url_field = properties.get("url")
    if isinstance(url_field, Mapping):
        source_url = url_field.get("report") or url_field.get("details")
    elif isinstance(url_field, str):
        source_url = url_field

    version = properties.get("version")
    if version is not None:
        source_signal["source_version"] = version

    record = build_staging_record(
        source_id="GDACS",
        retrieved_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        content_sha256="",  # filled in by the caller from the raw response bytes
        parser_version=ADAPTER_VERSION,
        source_external_id=source_external_id,
        source_revision=source_revision,
        source_publication_time=publication_time,
        title=str(title),
        source_url=source_url,
        primary_category="weather_natural_hazard",
        geography=geography,
        transport_modes=[],
        segments=[],
        event_date=event_date,
        publication_date=publication_date,
        source_signal=source_signal,
        field_mapping_notes=list(_FIELD_MAPPING_NOTES),
        warnings=list(warnings),
        known_limitations=list(_KNOWN_LIMITATIONS),
    )
    return record, warnings


def parse_event_list(
    payload: bytes | str | Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a GDACS event-list response into staging records.

    Every feature is attempted independently: a malformed feature is
    rejected with a structured warning and does not discard the rest of an
    otherwise valid page. Does not perform any network access.
    """
    if isinstance(payload, (bytes, str)):
        data = json.loads(payload)
    else:
        data = payload

    if not isinstance(data, Mapping):
        raise MalformedGdacsRecordError("GDACS response body is not a JSON object")

    features = data.get("features")
    if features is None:
        # Some GDACS endpoints return a bare list rather than a FeatureCollection.
        features = data if isinstance(data, list) else []
    if not isinstance(features, list):
        raise MalformedGdacsRecordError("GDACS response 'features' is not a list")

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, feature in enumerate(features):
        try:
            record, record_warnings = normalize_event(feature)
        except MalformedGdacsRecordError as exc:
            warnings.append(f"feature[{index}]: rejected -- {exc}")
            continue
        records.append(record)
        warnings.extend(record_warnings)
    return records, warnings


class GdacsAdapter(SourceAdapter):
    """Adapter for the official GDACS event-list SEARCH endpoint.

    Only used by the controlled manual live-test workflow (Scope D); it is
    never invoked on a schedule and never writes to published dashboard
    data. Instantiate with explicit search parameters -- there is no
    implicit "collect everything" mode.
    """

    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        contract: Mapping[str, Any],
        http=None,
        *,
        from_date: str,
        to_date: str,
        event_types: Sequence[str] = (),
        alert_levels: Sequence[str] = (),
        page_number: int = 1,
        page_size: int | None = None,
    ) -> None:
        super().__init__(contract, http)
        self.request = build_search_request(
            contract,
            from_date=from_date,
            to_date=to_date,
            event_types=event_types,
            alert_levels=alert_levels,
            page_number=page_number,
            page_size=page_size,
        )

    def collect(self) -> CollectionResult:
        started_dt = datetime.now(UTC).replace(microsecond=0)
        started_at = started_dt.isoformat().replace("+00:00", "Z")
        http_contract = self.contract["http"]
        url = self.request.to_url()
        warnings: list[str] = []
        errors: list[str] = []
        records: list[dict[str, Any]] = []
        http_status: int | None = None
        content_sha256: str | None = None
        status = RunStatus.ERROR

        try:
            response = self.http.get(
                url,
                timeout_seconds=int(http_contract["timeout_seconds"]),
                max_response_bytes=int(http_contract["max_response_bytes"]),
                attempts=int(self.contract["retry"]["attempts"]),
            )
            http_status = response.status
            content_sha256 = response.content_sha256
            if response.status == 304:
                status = RunStatus.NOT_MODIFIED
            else:
                records, parse_warnings = parse_event_list(response.body)
                for record in records:
                    record["content_sha256"] = content_sha256
                warnings.extend(parse_warnings)
                status = RunStatus.SUCCESS
        except Exception as exc:  # noqa: BLE001 -- surfaced as a run error, not a crash
            errors.append(str(exc))
            status = RunStatus.ERROR

        completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        run = CollectionRun(
            run_id=f"COL-{started_dt.strftime('%Y%m%dT%H%M%SZ')}-GDACS",
            source_id="GDACS",
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            workflow_sha=None,
            adapter_version=self.adapter_version,
            request_url=url,
            http_status=http_status,
            etag=None,
            last_modified=None,
            content_sha256=content_sha256,
            records_received=len(records) + sum(1 for w in warnings if w.startswith("feature[")),
            records_emitted=len(records),
            records_rejected=sum(1 for w in warnings if w.startswith("feature[")),
            data_cutoff_at=completed_at,
            warnings=warnings,
            errors=errors,
        )
        health = SourceHealth(
            source_id="GDACS",
            status=SourceStatus.DISABLED
            if not self.contract.get("enabled", False)
            else (SourceStatus.FRESH if status == RunStatus.SUCCESS else SourceStatus.ERROR),
            last_checked_at=completed_at,
            last_success_at=completed_at if status == RunStatus.SUCCESS else None,
            last_error=errors[-1] if errors else None,
            item_count=len(records) if status == RunStatus.SUCCESS else None,
            required_for_publication=bool(self.contract.get("required_for_publication", False)),
            max_stale_minutes=int(self.contract["max_stale_minutes"]),
        )
        return CollectionResult(
            records=records, run=run, health=health, warnings=warnings, errors=errors
        )
