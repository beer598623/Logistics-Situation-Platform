"""TMD CAP profile over the generic CAP 1.2 parser (Scope C, WO-002 v0.2).

This module is a *thin* profile: it knows how to pick an endpoint from the
TMD Source Contract (``config/sources.yaml``) -- including the alternate
Thai-language endpoint recorded generically as ``alternate_endpoints``,
never hardcoded here -- and how to turn one parsed CAP alert
(``collectors/adapters/cap.py``) into staging records
(``schemas/staging_record.schema.json``). It contains no TMD-specific
parsing logic; all CAP 1.2 structure is handled by the generic parser.

A TMD warning establishes official Thai hazard/warning status only. It
must never be treated as, or converted into, an observed transport,
facility, port, airport, warehouse, or trade disruption -- that
distinction is enforced by never emitting anything but a hazard/context
``source_signal`` here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..base import SourceAdapter
from ..http_client import validate_content_type
from ..models import CollectionResult, CollectionRun, RunStatus, SourceHealth, SourceStatus
from ..staging import build_staging_record
from .cap import CapSecurityError, MalformedCapAlertError, parse_cap_alert

ADAPTER_VERSION = "tmd_cap_v1"

#: TMD's CAP endpoints are documented as XML. A response with any other
#: Content-Type (most commonly an HTML error/login page) is rejected before
#: parsing rather than fed to the XML parser.
TMD_CAP_ALLOWED_CONTENT_TYPES = ("application/cap+xml", "application/xml", "text/xml")

_KNOWN_LIMITATIONS = (
    "TMD's copyright notice permits non-commercial public republication with "
    "attribution, but its separate website policy requires written permission "
    "for deep-linking to internal pages; this conflict is not resolved by this "
    "adapter and licence_status remains pending_review.",
    "machine_readable_status remains unverified until the controlled manual "
    "workflow validates the live endpoint's content type and parseability.",
    "A TMD warning establishes official hazard/warning status only -- it does "
    "not by itself establish observed transport, facility, or logistics "
    "disruption; missing operational evidence must remain insufficient_evidence, "
    "never zero or no-material-impact.",
)

_FIELD_MAPPING_NOTES = (
    "source_external_id = CAP <identifier> (the CAP message ID).",
    "One staging record is produced per CAP <info> block so multilingual "
    "content is preserved independently; translated text is never merged "
    "into a single asserted fact.",
    "source_references = CAP <references> triples verbatim (CAP has no "
    "single-value revision field, so source_revision stays null here and "
    "Update/Cancel cross-message association lives in this dedicated field "
    "instead); source_signal.msgType is kept separately as a quick-glance "
    "hazard/context signal.",
    "source_url is always the contract-level CAP endpoint, never the "
    "source-provided CAP <web> deep link, while TMD's deep-link permission "
    "question remains pending_review.",
    "geography = area geocode values when present, else areaDesc text, else "
    "a Thailand country-level fallback when neither is provided.",
)

_DEFAULT_GEOGRAPHY_FALLBACK = "Thailand"


def resolve_endpoint(contract: Mapping[str, Any], *, language: str = "primary") -> str:
    """Resolve the CAP endpoint URL for a language from the Source Contract.

    ``language="primary"`` returns ``contract["endpoint"]`` (the English CAP
    endpoint). Any other value is looked up by ``label`` in the contract's
    ``alternate_endpoints`` list -- e.g. ``language="thai_language_cap"`` for
    the Thai endpoint recorded in ``config/sources.yaml``. No URL is
    hardcoded in this adapter; it only reads what the contract declares.
    """
    if language == "primary":
        endpoint = contract.get("endpoint")
        if not endpoint:
            raise ValueError("Source contract has no primary endpoint configured")
        return str(endpoint)

    for alternate in contract.get("alternate_endpoints", []) or []:
        if alternate.get("label") == language:
            url = alternate.get("url")
            if not url:
                raise ValueError(f"Alternate endpoint {language!r} has no url configured")
            return str(url)

    raise ValueError(f"Source contract has no alternate endpoint labelled {language!r}")


def _area_geography(area: Mapping[str, Any]) -> list[str]:
    geocode_values = [entry["value"] for entry in area.get("geocode", []) if entry.get("value")]
    if geocode_values:
        return geocode_values
    if area.get("areaDesc"):
        return [str(area["areaDesc"])]
    return []


def normalize_tmd_alert(
    alert: Mapping[str, Any],
    *,
    content_sha256: str,
    source_url: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn one parsed CAP alert into one staging record per <info> block.

    Each ``info`` block keeps its own language, headline, and hazard signal
    independently -- content from different languages is never merged into
    one asserted fact. Returns ``(records, warnings)``; a CAP alert with no
    <info> blocks yields no records and a warning, since there is nothing to
    normalize.
    """
    warnings: list[str] = []
    infos = alert.get("info", [])
    if not infos:
        warnings.append(f"{alert['identifier']}: alert has no <info> blocks; nothing to normalize")
        return [], warnings

    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []

    for index, info in enumerate(infos):
        context = (
            f"{alert['identifier']} info[{index}] ({info.get('language') or 'unknown language'})"
        )

        geography: list[str] = []
        for area in info.get("area", []):
            geography.extend(_area_geography(area))
        geography = list(dict.fromkeys(geography))  # de-duplicate, preserve order
        if not geography:
            geography = [_DEFAULT_GEOGRAPHY_FALLBACK]
            warnings.append(
                f"{context}: no areaDesc/geocode found; geography fell back to "
                f"{_DEFAULT_GEOGRAPHY_FALLBACK!r}"
            )

        title = info.get("headline") or info.get("event")
        if not title:
            language_label = info.get("language") or "unknown language"
            title = f"TMD CAP alert {alert['identifier']} ({language_label})"
            warnings.append(f"{context}: no headline/event text; used a fallback title")

        event_date = None
        for candidate_field in ("onset", "effective"):
            value = info.get(candidate_field)
            if value:
                event_date = value[:10]
                break
        publication_date = (alert.get("sent") or event_date or "")[:10] or None

        source_signal: dict[str, Any] = {
            "language": info.get("language"),
            "cap_category": info.get("category"),
            "urgency": info.get("urgency"),
            "severity": info.get("severity"),
            "certainty": info.get("certainty"),
            "responseType": info.get("responseType"),
            "msgType": alert.get("msgType"),
            "status": alert.get("status"),
            "scope": alert.get("scope"),
        }
        source_signal = {key: value for key, value in source_signal.items() if value}

        record = build_staging_record(
            source_id="TMD_CAP",
            retrieved_at=retrieved_at,
            content_sha256=content_sha256,
            parser_version=ADAPTER_VERSION,
            source_external_id=alert["identifier"],
            source_revision=None,
            source_publication_time=alert.get("sent"),
            title=str(title),
            # Always the contract-level endpoint -- never the CAP <web>
            # deep link the source may supply, while TMD's deep-link
            # permission question remains pending_review (see
            # _FIELD_MAPPING_NOTES and known_limitations).
            source_url=source_url,
            primary_category="weather_natural_hazard",
            geography=geography,
            transport_modes=[],
            segments=[],
            event_date=event_date,
            publication_date=publication_date,
            source_signal=source_signal,
            source_references=alert.get("references", []),
            field_mapping_notes=list(_FIELD_MAPPING_NOTES),
            warnings=[],
            known_limitations=list(_KNOWN_LIMITATIONS),
        )
        records.append(record)

    return records, warnings


class TmdCapAdapter(SourceAdapter):
    """Adapter for the TMD CAP 1.2 warning feed.

    Only used by the controlled manual live-test workflow (Scope D); it is
    never invoked on a schedule and never writes to published dashboard
    data. Never uploads the raw XML payload or full description/instruction
    text -- that redaction is enforced by the workflow, not this class, but
    this class never asserts an operational logistics impact regardless.
    """

    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        contract: Mapping[str, Any],
        http=None,
        *,
        language: str = "primary",
    ) -> None:
        super().__init__(contract, http)
        self.language = language
        self.endpoint = resolve_endpoint(contract, language=language)

    def collect(self) -> CollectionResult:
        started_dt = datetime.now(UTC).replace(microsecond=0)
        started_at = started_dt.isoformat().replace("+00:00", "Z")
        http_contract = self.contract["http"]
        warnings: list[str] = []
        errors: list[str] = []
        records: list[dict[str, Any]] = []
        http_status: int | None = None
        content_sha256: str | None = None
        etag: str | None = None
        last_modified: str | None = None
        status = RunStatus.ERROR

        try:
            response = self.http.get(
                self.endpoint,
                timeout_seconds=int(http_contract["timeout_seconds"]),
                max_response_bytes=int(http_contract["max_response_bytes"]),
                attempts=int(self.contract["retry"]["attempts"]),
            )
            http_status = response.status
            content_sha256 = response.content_sha256
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            if response.status == 304:
                status = RunStatus.NOT_MODIFIED
            else:
                _content_type, content_type_warning = validate_content_type(
                    response.headers, TMD_CAP_ALLOWED_CONTENT_TYPES
                )
                if content_type_warning:
                    warnings.append(content_type_warning)
                alert, parse_warnings = parse_cap_alert(
                    response.body, max_bytes=int(http_contract["max_response_bytes"])
                )
                warnings.extend(parse_warnings)
                records, normalize_warnings = normalize_tmd_alert(
                    alert, content_sha256=content_sha256, source_url=self.endpoint
                )
                warnings.extend(normalize_warnings)
                status = RunStatus.SUCCESS
        except (CapSecurityError, MalformedCapAlertError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            status = RunStatus.ERROR
        except Exception as exc:  # noqa: BLE001 -- surfaced as a run error, not a crash
            errors.append(f"{type(exc).__name__}: {exc}")
            status = RunStatus.ERROR

        completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        run = CollectionRun(
            run_id=f"COL-{started_dt.strftime('%Y%m%dT%H%M%SZ')}-TMD_CAP",
            source_id="TMD_CAP",
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            workflow_sha=os.environ.get("GITHUB_SHA"),
            adapter_version=self.adapter_version,
            request_url=self.endpoint,
            http_status=http_status,
            etag=etag,
            last_modified=last_modified,
            content_sha256=content_sha256,
            records_received=len(records),
            records_emitted=len(records),
            records_rejected=0,
            # TMD's CAP feed is a live "current warnings" snapshot with no
            # bounded query window (unlike GDACS's dated SEARCH request),
            # so retrieval time is the only meaningful data-period bound.
            data_cutoff_at=completed_at,
            warnings=warnings,
            errors=errors,
        )
        health = SourceHealth(
            source_id="TMD_CAP",
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
