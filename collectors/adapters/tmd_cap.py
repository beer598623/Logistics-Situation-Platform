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

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from ..base import SourceAdapter
from ..error_classification import classify_error
from ..http_client import (
    PinnedResolution,
    UnexpectedContentTypeError,
    resolve_pinned_address,
    validate_content_type,
)
from ..models import CollectionResult, CollectionRun, RunStatus, SourceHealth, SourceStatus
from ..staging import build_staging_record
from ..url_redaction import redact_url_userinfo
from .cap import CapSecurityError, MalformedCapAlertError, parse_cap_alert
from .rss_discovery import discover_rss_candidates
from .tmd_candidate import (
    CandidateEnvelopeMismatchError,
    CandidateUnexpectedStatusError,
    build_candidate_reference,
    derive_candidate_request,
)
from .xml_envelope import CAP_ALERT, RSS, classify_envelope

ADAPTER_VERSION = "tmd_cap_v1"

#: WO-006 Scope B: a dedicated, hardcoded response-size bound for candidate
#: validation, deliberately independent of the source contract's
#: ``http.max_response_bytes`` (which governs the whole RSS/direct-CAP
#: feed, not a single candidate alert file). A single CAP <alert> document
#: is expected to be small; this cap is enforced by the pinned transport
#: itself before the body is ever handed to the XML parser.
CANDIDATE_MAX_RESPONSE_BYTES = 2_000_000

#: Small enumerated CAP fields (status/msgType/scope/sent) and provenance
#: strings (language/evidence run ID) are bounded independently of the
#: overall response-size cap above, mirroring the same "bound untrusted
#: values at the point they are extracted, not only at the final report
#: boundary" pattern already used in cap.py/xml_envelope.py/rss_discovery.py.
_MAX_CANDIDATE_FIELD_LENGTH = 64


def _bounded_field(
    value: str | None, *, max_length: int = _MAX_CANDIDATE_FIELD_LENGTH
) -> str | None:
    if value is None or len(value) <= max_length:
        return value
    omitted = len(value) - max_length
    return value[:max_length] + f"...(+{omitted} chars omitted)"


def redact_candidate_provenance_value(value: Any) -> dict[str, Any] | None:
    """A safe, non-reversible descriptor for one candidate-provenance
    value that has not (yet, or ever) passed structural validation
    (WO-007A round 1 review, finding 1).

    A value's raw text must never be echoed once it is known to have
    failed -- or has not yet passed -- ``build_candidate_reference``'s
    validation: a short credential- or token-shaped string typed into an
    operator-supplied field (``language``, ``candidate_filename``,
    ``evidence_run_id``, or ``evidence_item_index``) would otherwise
    survive verbatim in a public report artifact, since nothing upstream
    has bounded or sanitized it yet at that point. Retains only whether a
    value was supplied, its length, and a SHA-256 digest -- enough for a
    reviewer to compare two runs' rejected inputs without ever
    reconstructing the original text.

    Every non-``None`` value -- including an already-parsed
    ``evidence_item_index`` integer, in-range or not -- gets this same
    descriptor treatment; there is no int-shaped exception (WO-007A round
    2 review, finding 1: an out-of-range or overlong numeric
    ``evidence_item_index`` is still operator-supplied, unvalidated input,
    and purely-numeric free text (a PIN, an OTP, a numeric API key) is not
    inherently safer than alphanumeric text -- the whole point of "not yet
    validated" is that this function cannot itself tell the difference.
    Only a caller who has confirmed ``build_candidate_reference`` accepted
    the *complete* reference may use the real, validated integer instead
    of calling this function at all -- see ``validate_candidate``'s and
    ``run_tmd_candidate_cap_validation``'s post-success overwrite, and
    WO-007A round 1 review, finding 2, for why a non-numeric
    ``evidence_item_index`` string must never be silently dropped to
    ``None`` either.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return {
        "provided": True,
        "length": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest(),
    }


#: GitHub Actions' documented form for these two values: a bounded decimal
#: run ID and a 40-character hex commit SHA. Read from the environment
#: ("when safely available"), but validated at origin rather than trusted
#: blindly (WO-007A round 1 review, finding 3) -- this code also runs
#: outside a real GitHub Actions job (locally, in tests, or on a
#: misconfigured self-hosted runner), so neither is guaranteed to already
#: be well-formed.
_WORKFLOW_RUN_ID_RE = re.compile(r"^[0-9]{1,32}$")
_WORKFLOW_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_INVALID_WORKFLOW_RUN_ID_MARKER = "<invalid: GITHUB_RUN_ID did not match the expected form>"
_INVALID_WORKFLOW_SHA_MARKER = "<invalid: GITHUB_SHA did not match the expected form>"


def safe_workflow_run_id(raw: str | None) -> str | None:
    """Validate ``GITHUB_RUN_ID``'s documented bounded-numeric shape
    before it is retained anywhere in an outcome or report. ``None`` means
    the environment did not provide a value at all; the static marker
    means one was provided but did not match the expected form -- the two
    are kept distinguishable rather than collapsed to the same ``None``."""
    if raw is None:
        return None
    if _WORKFLOW_RUN_ID_RE.fullmatch(raw):
        return raw
    return _INVALID_WORKFLOW_RUN_ID_MARKER


def safe_workflow_sha(raw: str | None) -> str | None:
    """Same as ``safe_workflow_run_id`` for ``GITHUB_SHA``'s documented
    40-character hex commit SHA form."""
    if raw is None:
        return None
    if _WORKFLOW_SHA_RE.fullmatch(raw):
        return raw
    return _INVALID_WORKFLOW_SHA_MARKER


class UnexpectedNotModifiedError(RuntimeError):
    """Raised by ``TmdCapAdapter.discover_rss`` when the response is HTTP
    304 despite this request never sending an ``If-None-Match`` or
    ``If-Modified-Since`` validator (``discover_rss`` calls
    ``get_no_redirect`` with no ``etag``/``last_modified`` argument at
    all). Discovery mode keeps no cached prior body to fall back to, so a
    304 here cannot establish the envelope kind and must never be treated
    as a successful validation with no body (WO-004 review round 3,
    finding 1)."""


#: TMD's CAP endpoints are documented as XML. A response with any other
#: Content-Type (most commonly an HTML error/login page) is rejected before
#: parsing rather than fed to the XML parser. This allowlist is reused
#: unchanged for RSS discovery mode -- the source is still serving "some
#: XML" either way; the CAP-specific structural check lives in
#: parse_cap_alert's root-tag requirement, not here.
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
        # publication_date must come only from CAP <sent> (a verified
        # message-publication timestamp), never from onset/effective (the
        # hazard period) -- missing publication provenance stays null
        # rather than being inferred from the event date, mirroring the
        # GDACS datemodified-only rule in collectors/adapters/gdacs.py.
        sent = alert.get("sent")
        publication_date = sent[:10] if sent else None

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


@dataclass(slots=True)
class RssDiscoveryOutcome:
    """Result of one bounded, discovery-only GET against a TMD endpoint.

    Deliberately not shaped like ``schemas/collection_run.schema.json`` --
    RSS discovery never collects candidate records (``records_received`` /
    ``records_emitted`` / ``records_rejected`` do not apply to it), so it
    is a distinct, undocumented-by-schema diagnostic result rather than a
    ``CollectionRun``. This is a deliberate architecture separation: a
    ``CollectionRun`` is what a source adapter produces when it collects;
    RSS discovery never collects anything.
    """

    request_url: str
    response_url: str | None
    http_status: int | None
    content_type: str | None
    etag: str | None
    last_modified: str | None
    content_sha256: str | None
    workflow_sha: str | None
    envelope_classification: dict[str, Any] | None
    discovery: dict[str, Any] | None
    warnings: list[str]
    errors: list[str]
    error_code: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_url": self.request_url,
            "response_url": self.response_url,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_sha256": self.content_sha256,
            "workflow_sha": self.workflow_sha,
            "envelope_classification": self.envelope_classification,
            "discovery": self.discovery,
            "warnings": self.warnings,
            "errors": self.errors,
            "error_code": self.error_code,
            "error_category": self.error_category,
        }


@dataclass(slots=True)
class CandidateValidationOutcome:
    """Result of one WO-006 controlled single-candidate CAP validation.

    Deliberately distinct from ``CollectionResult``, ``RssDiscoveryOutcome``,
    and every schema under ``schemas/`` -- candidate validation never
    collects records and never creates a staging record, so this is not
    shaped like any of them. Every field here is either a bounded
    structural/provenance value or explicitly minimized (the CAP
    ``<identifier>`` is retained as length + SHA-256 only, never the raw
    value); raw XML and all free-text CAP content (headline, description,
    instruction, note, audience, web, contact, area description, geometry)
    are never present on this dataclass at all -- there is no field for
    them to occupy.

    WO-007A: ``language``, ``candidate_filename``, ``evidence_run_id``,
    and ``evidence_item_index`` are recorded so a Gate reviewer can see
    exactly which candidate a report describes -- including one rejected
    before any DNS or network activity. Each field holds the actual
    validated value (a plain ``str``/``int``) once
    ``build_candidate_reference`` has accepted it; before that, or if it
    never does, each instead holds a safe, non-reversible descriptor from
    ``redact_candidate_provenance_value`` (``{"provided": True, "length":
    ..., "sha256": ...}`` for a string, the integer itself for
    ``evidence_item_index``, or ``None``) -- never the raw rejected text
    (round 1 review, finding 1), and never silently dropped to ``None``
    just because it failed to parse as an integer (round 1 review,
    finding 2). ``workflow_run_id`` (``GITHUB_RUN_ID``) is retained
    alongside the existing ``workflow_sha`` (``GITHUB_SHA``) when the
    environment provides a value matching its documented form
    (``safe_workflow_run_id``/``safe_workflow_sha``); ``None`` means no
    value was provided, and a static marker means one was provided but
    was malformed (round 1 review, finding 3) -- neither ever echoes an
    unvalidated raw environment value.
    """

    operation: str
    mode: str
    language: str | dict[str, Any] | None
    candidate_filename: str | dict[str, Any] | None
    evidence_run_id: str | dict[str, Any] | None
    evidence_item_index: int | dict[str, Any] | None
    workflow_run_id: str | None
    workflow_sha: str | None
    request_url: str | None
    selected_ip: str | None
    address_family: str | None
    connected_ip_matches_selected: bool | None
    http_status: int | None
    content_type: str | None
    etag: str | None
    last_modified: str | None
    content_length: int | None
    content_sha256: str | None
    envelope_classification: dict[str, Any] | None
    cap_identifier_length: int | None
    cap_identifier_sha256: str | None
    cap_sent: str | None
    cap_status: str | None
    cap_msg_type: str | None
    cap_scope: str | None
    cap_info_count: int | None
    cap_languages: list[str]
    cap_reference_count: int | None
    cap_area_count: int | None
    #: Count only, never the parser's own warning text -- see
    #: ``validate_candidate``'s comment at the call site (ChatGPT review
    #: round 1, finding 4): ``parse_cap_alert``'s warnings embed the raw
    #: CAP identifier and bounded-but-real invalid timestamp/geometry
    #: source values, which this result model must never retain.
    cap_parser_warning_count: int | None
    warnings: list[str]
    errors: list[str]
    error_code: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "mode": self.mode,
            "language": self.language,
            "candidate_filename": self.candidate_filename,
            "evidence_run_id": self.evidence_run_id,
            "evidence_item_index": self.evidence_item_index,
            "workflow_run_id": self.workflow_run_id,
            "workflow_sha": self.workflow_sha,
            "request_url": self.request_url,
            "selected_ip": self.selected_ip,
            "address_family": self.address_family,
            "connected_ip_matches_selected": self.connected_ip_matches_selected,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_length": self.content_length,
            "content_sha256": self.content_sha256,
            "envelope_classification": self.envelope_classification,
            "cap_identifier_length": self.cap_identifier_length,
            "cap_identifier_sha256": self.cap_identifier_sha256,
            "cap_sent": self.cap_sent,
            "cap_status": self.cap_status,
            "cap_msg_type": self.cap_msg_type,
            "cap_scope": self.cap_scope,
            "cap_info_count": self.cap_info_count,
            "cap_languages": self.cap_languages,
            "cap_reference_count": self.cap_reference_count,
            "cap_area_count": self.cap_area_count,
            "cap_parser_warning_count": self.cap_parser_warning_count,
            "warnings": self.warnings,
            "errors": self.errors,
            "error_code": self.error_code,
            "error_category": self.error_category,
        }


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
        resolve_pinned: Callable[[str, int], PinnedResolution] | None = None,
    ) -> None:
        super().__init__(contract, http)
        self.language = language
        # WO-006 Scope B: injectable so tests can substitute a fully
        # in-memory resolver (no real DNS lookup) without touching
        # production networking code, mirroring how ``http`` above is
        # already injectable. Defaults to the real DNS-pinning resolver.
        self._resolve_pinned = resolve_pinned or resolve_pinned_address

    @property
    def endpoint(self) -> str:
        """Resolved lazily, on access, rather than at construction time
        (ChatGPT review round 1, finding 6): ``validate_candidate()``
        never reads this property at all, so constructing an adapter
        purely for candidate validation never touches
        ``config/sources.yaml``'s ``endpoint``/``alternate_endpoints``
        fields -- only ``collect()`` and ``discover_rss()`` do, exactly
        as before this change, just resolved on each access instead of
        once at ``__init__`` time."""
        return resolve_endpoint(self.contract, language=self.language)

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
        response_url: str | None = None
        content_type: str | None = None
        status = RunStatus.ERROR
        error_code: str | None = None
        error_category: str | None = None
        envelope_classification: dict[str, Any] | None = None

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
            # response.url is the redirect-resolved final URL, preserved
            # separately from the requested self.endpoint so a redirect
            # that changes host/path stays visible in the run manifest.
            # Redacted defensively (review round 2, finding 2) even though
            # this is a server-controlled value we do not otherwise trust.
            response_url = redact_url_userinfo(response.url)
            if response.status == 304:
                status = RunStatus.NOT_MODIFIED
            else:
                content_type, content_type_warning = validate_content_type(
                    response.headers, TMD_CAP_ALLOWED_CONTENT_TYPES
                )
                if content_type_warning:
                    warnings.append(content_type_warning)
                try:
                    alert, parse_warnings = parse_cap_alert(
                        response.body, max_bytes=int(http_contract["max_response_bytes"])
                    )
                except MalformedCapAlertError:
                    # Best-effort diagnostic only: classifying the same
                    # in-memory payload never performs a second network
                    # request and must never mask or replace the original
                    # error, so any classification failure is swallowed
                    # here and the original exception re-raised unchanged.
                    # The classification is kept both as a human-readable
                    # warning string (unchanged, for log readability) and,
                    # newly, as a structured field on the returned
                    # CollectionResult -- this is exactly the direct-CAP
                    # RSS-rejection path WO-003 observed, and review round
                    # 1 required it be exposed structurally, not only as
                    # a warning string.
                    try:
                        classification = classify_envelope(
                            response.body,
                            max_bytes=int(http_contract["max_response_bytes"]),
                            content_sha256=content_sha256,
                        )
                        envelope_classification = classification.to_dict()
                        warnings.append(
                            "envelope_classification: kind="
                            f"{classification.envelope_kind} "
                            f"root_local_name={classification.root_local_name!r} "
                            f"root_namespace={classification.root_namespace!r}"
                        )
                    except Exception:  # noqa: BLE001, S110 -- diagnostics must never mask the real error
                        pass
                    raise
                warnings.extend(parse_warnings)
                records, normalize_warnings = normalize_tmd_alert(
                    alert, content_sha256=content_sha256, source_url=self.endpoint
                )
                warnings.extend(normalize_warnings)
                status = RunStatus.SUCCESS
        except (CapSecurityError, MalformedCapAlertError) as exc:
            error_code, error_category = classify_error(exc)
            errors.append(f"{error_code}: {exc}")
            status = RunStatus.ERROR
        except Exception as exc:  # noqa: BLE001 -- surfaced as a run error, not a crash
            error_code, error_category = classify_error(exc)
            errors.append(f"{error_code}: {exc}")
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
            request_url=redact_url_userinfo(self.endpoint),
            response_url=response_url,
            content_type=content_type,
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
            records=records,
            run=run,
            health=health,
            warnings=warnings,
            errors=errors,
            error_code=error_code,
            error_category=error_category,
            envelope_classification=envelope_classification,
        )

    def discover_rss(self) -> RssDiscoveryOutcome:
        """Perform exactly one bounded, non-redirect-following GET against
        this adapter's endpoint, classify the envelope, and -- only if it
        classifies as RSS -- extract discovery-only structural metadata.

        This is a discovery-only operation: it never creates a staging
        record, never treats a non-CAP envelope as a CAP alert (Scope A
        stays untouched), and never fetches a discovered candidate URL --
        this method makes exactly one physical HTTP request and never
        follows a redirect (``ResilientHttpClient.get_no_redirect``), full
        stop. See ``collectors/adapters/xml_envelope.py`` and
        ``collectors/adapters/rss_discovery.py`` for the generic,
        source-agnostic parsers this method delegates to; nothing
        TMD-specific lives in either of those modules.
        """
        http_contract = self.contract["http"]
        warnings: list[str] = []
        errors: list[str] = []
        http_status: int | None = None
        content_sha256: str | None = None
        etag: str | None = None
        last_modified: str | None = None
        response_url: str | None = None
        content_type: str | None = None
        envelope_classification: dict[str, Any] | None = None
        discovery: dict[str, Any] | None = None
        error_code: str | None = None
        error_category: str | None = None

        try:
            # get_no_redirect() (not get()) makes exactly one physical
            # request and never follows a redirect at all -- a 3xx raises
            # DiscoveryRedirectError before any request to its Location
            # target is made (review round 2, finding 1: a plain
            # `attempts=1` on get() would still transparently follow a
            # redirect to another host or a private address, since retry
            # count and redirect-following are unrelated urllib
            # behaviors). No attempts/retry parameter exists here at all.
            response = self.http.get_no_redirect(
                self.endpoint,
                timeout_seconds=int(http_contract["timeout_seconds"]),
                max_response_bytes=int(http_contract["max_response_bytes"]),
            )
            http_status = response.status
            content_sha256 = response.content_sha256
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            response_url = redact_url_userinfo(response.url)
            if response.status == 304:
                # This request sent no If-None-Match/If-Modified-Since
                # (discover_rss never passes etag/last_modified to
                # get_no_redirect), and discovery mode keeps no cached
                # prior body -- an uncacheable 304 cannot establish the
                # envelope kind and must not silently exit 0 with
                # envelope_classification/discovery left null (review
                # round 3, finding 1). Fail closed instead.
                raise UnexpectedNotModifiedError(
                    "received HTTP 304 Not Modified, but this request sent no "
                    "validator and discovery mode has no cached prior body to "
                    "validate against; a 304 here cannot establish the "
                    "envelope kind"
                )
            content_type, content_type_warning = validate_content_type(
                response.headers, TMD_CAP_ALLOWED_CONTENT_TYPES
            )
            if content_type_warning:
                warnings.append(content_type_warning)

            max_bytes = int(http_contract["max_response_bytes"])
            classification = classify_envelope(
                response.body, max_bytes=max_bytes, content_sha256=content_sha256
            )
            envelope_classification = classification.to_dict()

            if classification.envelope_kind == RSS:
                # Grouping uses the requested endpoint's own host, not
                # response.url: since get_no_redirect() never follows a
                # redirect, a successful (non-raised) response was
                # necessarily served directly by self.endpoint's host,
                # so there is no separate "redirect-resolved origin" to
                # consider here.
                feed_host = urlparse(self.endpoint).hostname
                result, discovery_warnings = discover_rss_candidates(
                    response.body, max_bytes=max_bytes, feed_host=feed_host
                )
                discovery = result.to_dict()
                warnings.extend(discovery_warnings)
            else:
                warnings.append(
                    f"envelope classified as {classification.envelope_kind!r}, not "
                    "'rss'; no RSS discovery performed"
                )
        except Exception as exc:  # noqa: BLE001 -- surfaced as a discovery error, not a crash
            error_code, error_category = classify_error(exc)
            errors.append(f"{error_code}: {exc}")

        return RssDiscoveryOutcome(
            request_url=redact_url_userinfo(self.endpoint),
            response_url=response_url,
            http_status=http_status,
            content_type=content_type,
            etag=etag,
            last_modified=last_modified,
            content_sha256=content_sha256,
            workflow_sha=os.environ.get("GITHUB_SHA"),
            envelope_classification=envelope_classification,
            discovery=discovery,
            warnings=warnings,
            errors=errors,
            error_code=error_code,
            error_category=error_category,
        )

    def validate_candidate(
        self,
        *,
        candidate_filename: str,
        evidence_run_id: str,
        evidence_item_index: int,
    ) -> CandidateValidationOutcome:
        """WO-006 controlled single-candidate CAP validation (Scopes A-D).

        Always a live operation -- ``scripts/manual_live_source_test.py``
        only calls this when ``dry_run=false``, exactly like
        ``collect()``/``discover_rss()`` above. Validates the candidate
        reference and derives the fetch URL entirely from fixed policy
        (``collectors/adapters/tmd_candidate.py`` -- never from an
        arbitrary URL/host/port/path, and never from this contract), then
        resolves and pins DNS, makes exactly one physical HTTPS GET
        through ``ResilientHttpClient.get_pinned_candidate``, and -- only
        if the body classifies as ``cap_alert`` -- runs the unchanged,
        strict ``parse_cap_alert``. Never creates a staging record or
        candidate event; the returned outcome retains only bounded
        structural/provenance fields (never raw XML, never headline/
        description/instruction/web/contact/area/geocode/geometry text,
        and the CAP ``<identifier>`` only as length + SHA-256, never the
        raw value).
        """
        warnings: list[str] = []
        errors: list[str] = []
        error_code: str | None = None
        error_category: str | None = None

        request_url: str | None = None
        selected_ip: str | None = None
        address_family: str | None = None
        connected_ip_matches_selected: bool | None = None
        http_status: int | None = None
        content_type: str | None = None
        etag: str | None = None
        last_modified: str | None = None
        content_length: int | None = None
        content_sha256: str | None = None
        envelope_classification: dict[str, Any] | None = None
        cap_identifier_length: int | None = None
        cap_identifier_sha256: str | None = None
        cap_sent: str | None = None
        cap_status: str | None = None
        cap_msg_type: str | None = None
        cap_scope: str | None = None
        cap_info_count: int | None = None
        cap_languages: list[str] = []
        cap_reference_count: int | None = None
        cap_area_count: int | None = None
        cap_parser_warning_count: int | None = None

        # WO-007A round 1 review, findings 1-2: every provenance field
        # starts as a safe, non-reversible descriptor of the raw
        # caller-supplied value -- never the raw text itself, since
        # build_candidate_reference() below has not yet had a chance to
        # validate it (or may reject it outright). Only on successful
        # validation, below, are these replaced with the actual validated
        # values -- which are then known-safe (grammar/enum-bound ASCII).
        bounded_language: str | dict[str, Any] | None = redact_candidate_provenance_value(
            self.language
        )
        bounded_candidate_filename: str | dict[str, Any] | None = redact_candidate_provenance_value(
            candidate_filename
        )
        bounded_run_id: str | dict[str, Any] | None = redact_candidate_provenance_value(
            evidence_run_id
        )
        bounded_item_index: int | dict[str, Any] | None = redact_candidate_provenance_value(
            evidence_item_index
        )

        try:
            reference = build_candidate_reference(
                language=self.language,
                candidate_filename=candidate_filename,
                evidence_run_id=evidence_run_id,
                evidence_item_index=evidence_item_index,
            )
            # Validation succeeded: every field is now known to be a safe,
            # grammar/enum-bound value, so replace the pre-validation
            # descriptor with the actual validated text/integer.
            bounded_language = reference.language
            bounded_candidate_filename = reference.candidate_filename
            bounded_run_id = reference.evidence_run_id
            bounded_item_index = reference.evidence_item_index
            derived = derive_candidate_request(reference)
            request_url = redact_url_userinfo(derived.url)

            resolution = self._resolve_pinned(derived.hostname, derived.port)
            selected_ip = resolution.selected_ip
            address_family = resolution.address_family

            http_contract = self.contract["http"]
            response, connected_ip = self.http.get_pinned_candidate(
                hostname=derived.hostname,
                port=derived.port,
                path=derived.path,
                selected_ip=selected_ip,
                timeout_seconds=int(http_contract["timeout_seconds"]),
                max_response_bytes=CANDIDATE_MAX_RESPONSE_BYTES,
            )
            # get_pinned_candidate() itself now verifies the connected peer
            # matches selected_ip *before* sending any request byte
            # (ChatGPT review round 1, finding 2) -- a mismatch raises
            # PinnedConnectionError from inside that call and this line is
            # never reached with connected_ip != selected_ip. Recorded here
            # purely as evidence for the outcome, not as the enforcement
            # point.
            connected_ip_matches_selected = connected_ip == selected_ip
            http_status = response.status
            content_length = len(response.body)
            content_sha256 = response.content_sha256
            etag = _bounded_field(response.headers.get("etag"))
            last_modified = _bounded_field(response.headers.get("last-modified"))

            if response.status == 304:
                raise UnexpectedNotModifiedError(
                    "received HTTP 304 Not Modified, but this request sent no "
                    "validator and candidate validation has no cached prior "
                    "body to validate against"
                )
            if response.status != 200:
                raise CandidateUnexpectedStatusError(
                    f"candidate fetch returned unexpected HTTP status {response.status}; "
                    "expected 200"
                )

            # WO-006 Scope C requires a present, allowlisted Content-Type --
            # unlike collect()/discover_rss(), a missing header is not
            # merely a warning here (review round 1, finding 3). The raw
            # header value is bounded before it ever reaches an exception
            # message (finding 7); validate_content_type()'s own message
            # embeds the complete raw value, so a present-but-unexpected
            # type is re-raised with a bounded one instead of propagating
            # unchanged.
            raw_content_type = response.headers.get("content-type")
            try:
                content_type, _content_type_warning = validate_content_type(
                    response.headers, TMD_CAP_ALLOWED_CONTENT_TYPES
                )
            except UnexpectedContentTypeError as exc:
                # ChatGPT review round 3, finding 2: never embed the raw
                # parameter section in the rejection diagnostic either --
                # only the normalized base type the allowlist check itself
                # rejected on.
                rejected_base_type = _bounded_field(
                    (raw_content_type or "").split(";", 1)[0].strip().lower()
                )
                raise UnexpectedContentTypeError(
                    f"unexpected candidate Content-Type base {rejected_base_type!r}; "
                    "expected an allowlisted CAP/XML type"
                ) from exc
            if content_type is None:
                raise UnexpectedContentTypeError(
                    "candidate response had no Content-Type header; a narrow "
                    "XML/CAP allowlisted type is required for candidate validation"
                )
            # ChatGPT review round 2, finding 1 / round 3, finding 2: an
            # *allowlisted* base media type can still carry an arbitrary
            # parameter section (e.g. "application/xml; x=<canary>") --
            # validate_content_type() only checks the base type and
            # returns the header verbatim. Retain only the normalized,
            # already-allowlisted base type -- never the raw parameter
            # section, which is untrusted, source-controlled free text
            # with no structural meaning to candidate validation. Bounding
            # alone (round 2's fix) was not sufficient: a short canary
            # placed at the start of the parameter section would still
            # have survived within the first 64 characters.
            content_type = content_type.split(";", 1)[0].strip().lower()

            classification = classify_envelope(
                response.body,
                max_bytes=CANDIDATE_MAX_RESPONSE_BYTES,
                content_sha256=content_sha256,
            )
            envelope_classification = classification.to_dict()
            if classification.envelope_kind != CAP_ALERT:
                raise CandidateEnvelopeMismatchError(
                    f"candidate envelope classified as {classification.envelope_kind!r}, "
                    "not 'cap_alert'"
                )

            # Unchanged, strict CAP 1.2 parser -- exactly the same function
            # used by collect() above, never a relaxed or candidate-specific
            # variant.
            alert, parse_warnings = parse_cap_alert(
                response.body, max_bytes=CANDIDATE_MAX_RESPONSE_BYTES
            )
            # ChatGPT review round 1, finding 4: parse_cap_alert()'s own
            # warning strings are prefixed with the raw CAP <identifier>
            # and can embed bounded-but-real invalid timestamp/polygon/
            # circle/altitude/ceiling source values (cap.py's own
            # _bounded() only truncates length, it does not remove or hash
            # the value). Copying them verbatim into this outcome would
            # contradict the identifier-as-length/hash-only and no-
            # geometry/timestamp-source-value promises this result model
            # makes, so only the count is retained -- never the text.
            cap_parser_warning_count = len(parse_warnings)

            identifier = alert["identifier"]
            cap_identifier_length = len(identifier)
            cap_identifier_sha256 = hashlib.sha256(
                identifier.encode("utf-8", errors="surrogatepass")
            ).hexdigest()
            cap_sent = _bounded_field(alert.get("sent"))
            cap_status = _bounded_field(alert.get("status"))
            cap_msg_type = _bounded_field(alert.get("msgType"))
            cap_scope = _bounded_field(alert.get("scope"))
            infos = alert.get("info", [])
            cap_info_count = len(infos)
            cap_languages = sorted(
                {language for info in infos if (language := _bounded_field(info.get("language")))}
            )
            cap_reference_count = len(alert.get("references", []))
            cap_area_count = sum(len(info.get("area", [])) for info in infos)
        except Exception as exc:  # noqa: BLE001 -- surfaced as a structured validation error
            error_code, error_category = classify_error(exc)
            errors.append(f"{error_code}: {exc}")

        return CandidateValidationOutcome(
            operation="candidate_cap_validation",
            mode="live",
            language=bounded_language,
            candidate_filename=bounded_candidate_filename,
            evidence_run_id=bounded_run_id,
            evidence_item_index=bounded_item_index,
            workflow_run_id=safe_workflow_run_id(os.environ.get("GITHUB_RUN_ID")),
            workflow_sha=safe_workflow_sha(os.environ.get("GITHUB_SHA")),
            request_url=request_url,
            selected_ip=selected_ip,
            address_family=address_family,
            connected_ip_matches_selected=connected_ip_matches_selected,
            http_status=http_status,
            content_type=content_type,
            etag=etag,
            last_modified=last_modified,
            content_length=content_length,
            content_sha256=content_sha256,
            envelope_classification=envelope_classification,
            cap_identifier_length=cap_identifier_length,
            cap_identifier_sha256=cap_identifier_sha256,
            cap_sent=cap_sent,
            cap_status=cap_status,
            cap_msg_type=cap_msg_type,
            cap_scope=cap_scope,
            cap_info_count=cap_info_count,
            cap_languages=cap_languages,
            cap_reference_count=cap_reference_count,
            cap_area_count=cap_area_count,
            cap_parser_warning_count=cap_parser_warning_count,
            warnings=warnings,
            errors=errors,
            error_code=error_code,
            error_category=error_category,
        )
