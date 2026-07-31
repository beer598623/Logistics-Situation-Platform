#!/usr/bin/env python3
"""WO-027 Part B: bounded controlled live validation of data.gov.sg (Issue #56).

Executes **exactly two** sequential GET requests against the two data.gov.sg
Datastore Search resources named in Issue #56's human-authorized validation
package (``docs/mpa_sg_statistics_qualification.md`` §5) -- never more, never
fewer, never in parallel, never retried. This script performs the fetch only;
it does not enable, schedule, or publish ``MPA_SG_STATISTICS``, and it never
writes to ``dashboard/public/data/**``, ``data/candidates/**``,
``data/reviewed/**``, or ``data/source_status/latest.json``.

Bounds (all human-authorized, all enforced here, none configurable via CLI):

* Exactly the two URLs below, GET, sequential.
* 30-second timeout per request.
* 5,000,000-byte maximum response body per request.
* No retry on any failure.
* No redirect ever followed (``ResilientHttpClient.get_no_redirect``: a 3xx
  response raises before a second request could be constructed).
* ``application/json`` (or ``text/json``) content type required; anything
  else raises before the body is parsed.
* No API key, no account, no cookie, no credential is sent or accepted.

On any transport-level anomaly on request 1 (proxy 403/407, DNS failure,
redirect, wrong content type, oversized body, timeout, or any other
exception) this script stops immediately: request 2 is never attempted, no
retry occurs, and a structured failure record is written distinguishing a
proxy/environment-layer failure from an actual data.gov.sg source response.
A failure on request 2 (which only happens after request 1 already
succeeded, since both requests are individually authorized) is recorded the
same way; it does not retroactively invalidate request 1's evidence.

Only the fields listed in Issue #56 as retainable are written to the output
report: request URL (already credential-free), retrieval timestamp, HTTP
status, content type, response byte count, SHA-256, ``resource_id``,
``result.total``, returned field names, exactly the returned records (each
request already asks for ``limit=5``, so this is never more than five),
ETag/Last-Modified when present, and the parser outcome or a structured
error. Unrelated response fields, request/account identifiers, and
unrestricted raw dumps are never written.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.http_client import (  # noqa: E402
    DiscoveryRedirectError,
    ResilientHttpClient,
    ResponseTooLargeError,
    UnexpectedContentTypeError,
    validate_content_type,
)

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5_000_000
ALLOWED_CONTENT_TYPES = ("application/json", "text/json")

#: Exactly the two requests Issue #56 human-authorized. Order and URL text
#: (including %20 encoding and field order) match the issue and
#: docs/mpa_sg_statistics_qualification.md §5 verbatim -- this script must
#: never be pointed at a different URL, resource_id, or field list.
REQUESTS: tuple[dict[str, str], ...] = (
    {
        "label": "container_throughput_monthly",
        "url": (
            "https://data.gov.sg/api/action/datastore_search"
            "?resource_id=d_da030f7028200d19ffcbe4a2d71af39c"
            "&limit=5&sort=month%20desc&fields=month,container_throughput"
        ),
        "expected_resource_id": "d_da030f7028200d19ffcbe4a2d71af39c",
    },
    {
        "label": "vessel_arrivals_monthly",
        "url": (
            "https://data.gov.sg/api/action/datastore_search"
            "?resource_id=d_d48c5a038904f6da3c603cd854b6c191"
            "&limit=5&sort=month%20desc&fields=month,number_of_vessels,gross_tonnage"
        ),
        "expected_resource_id": "d_d48c5a038904f6da3c603cd854b6c191",
    },
)

#: Response headers explicitly named as retainable by Issue #56. Nothing
#: else from the response's header block is ever copied into the report.
APPROVED_RESPONSE_HEADERS = ("content-type", "etag", "last-modified")

#: Substring urllib/http.client use in the OSError raised by
#: http.client.HTTPConnection._tunnel() when the CONNECT proxy itself
#: refuses or fails the tunnel (e.g. an org egress-policy 403/407) --
#: distinct from an HTTPError actually returned by data.gov.sg after a
#: successful tunnel. Matching on this lets the report state which layer
#: produced a given failure rather than mischaracterizing a proxy denial as
#: a source response, or vice versa.
_PROXY_TUNNEL_FAILURE_MARKER = "Tunnel connection failed"


@dataclass(slots=True)
class RequestOutcome:
    label: str
    request_url: str
    retrieval_timestamp: str
    outcome: str  # "success" | "transport_failure"
    failure_layer: str | None  # "proxy" | "source" | "client" | None
    http_status: int | None
    content_type: str | None
    response_bytes: int | None
    content_sha256: str | None
    resource_id: str | None
    result_total: int | None
    returned_field_names: list[str] | None
    records: list[dict[str, Any]] | None
    approved_response_headers: dict[str, str]
    parser_outcome: str
    error: dict[str, str] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "request_url": self.request_url,
            "retrieval_timestamp": self.retrieval_timestamp,
            "outcome": self.outcome,
            "failure_layer": self.failure_layer,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "response_bytes": self.response_bytes,
            "content_sha256": self.content_sha256,
            "resource_id": self.resource_id,
            "result_total": self.result_total,
            "returned_field_names": self.returned_field_names,
            "records": self.records,
            "approved_response_headers": self.approved_response_headers,
            "parser_outcome": self.parser_outcome,
            "error": self.error,
        }


def _classify_failure_layer(exc: BaseException) -> str:
    message = str(exc)
    cause = exc.__cause__
    if _PROXY_TUNNEL_FAILURE_MARKER in message or (
        cause is not None and _PROXY_TUNNEL_FAILURE_MARKER in str(cause)
    ):
        return "proxy"
    if isinstance(exc, HTTPError):
        return "source"
    if isinstance(exc, (DiscoveryRedirectError, UnexpectedContentTypeError, ResponseTooLargeError)):
        return "source"
    return "client"


def _execute_one(spec: dict[str, str]) -> RequestOutcome:
    client = ResilientHttpClient(user_agent="Logistics-Situation-Platform/0.1.2 (WO-027 Part B)")
    retrieval_timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    try:
        response = client.get_no_redirect(
            spec["url"],
            timeout_seconds=TIMEOUT_SECONDS,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )
    except (
        HTTPError,
        URLError,
        DiscoveryRedirectError,
        ResponseTooLargeError,
        TimeoutError,
    ) as exc:
        return RequestOutcome(
            label=spec["label"],
            request_url=spec["url"],
            retrieval_timestamp=retrieval_timestamp,
            outcome="transport_failure",
            failure_layer=_classify_failure_layer(exc),
            http_status=getattr(exc, "code", None),
            content_type=None,
            response_bytes=None,
            content_sha256=None,
            resource_id=None,
            result_total=None,
            returned_field_names=None,
            records=None,
            approved_response_headers={},
            parser_outcome="not_run",
            error={"exception_type": type(exc).__name__, "message": str(exc)},
        )

    approved_headers = {
        key: response.headers[key] for key in APPROVED_RESPONSE_HEADERS if key in response.headers
    }

    try:
        content_type, _warning = validate_content_type(response.headers, ALLOWED_CONTENT_TYPES)
    except UnexpectedContentTypeError as exc:
        return RequestOutcome(
            label=spec["label"],
            request_url=spec["url"],
            retrieval_timestamp=retrieval_timestamp,
            outcome="transport_failure",
            failure_layer="source",
            http_status=response.status,
            content_type=response.headers.get("content-type"),
            response_bytes=len(response.body),
            content_sha256=response.content_sha256,
            resource_id=None,
            result_total=None,
            returned_field_names=None,
            records=None,
            approved_response_headers=approved_headers,
            parser_outcome="not_run",
            error={"exception_type": type(exc).__name__, "message": str(exc)},
        )

    parser_outcome = "not_attempted"
    resource_id = None
    result_total = None
    returned_field_names = None
    records: list[dict[str, Any]] | None = None
    parse_error: dict[str, str] | None = None

    try:
        payload = json.loads(response.body.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError("response 'success' field is not true")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("response 'result' is missing or not an object")
        resource_id = result.get("resource_id")
        result_total = result.get("total")
        raw_records = result.get("records")
        if isinstance(raw_records, list):
            records = raw_records[:5]
        # The envelope's own "fields" schema block uses whatever key naming
        # convention this CKAN instance's API version emits (observed here:
        # entries without a usable "id"/"name" key this parser recognises).
        # Rather than guess at that shape, derive the returned field names
        # from the records CKAN actually sent back -- dict key order is
        # preserved by Python's json.loads and matches the response byte
        # order, so the first record's keys are exactly the "returned field
        # names" Issue #56 asks to retain, with no re-request needed.
        fields = result.get("fields")
        if records:
            returned_field_names = list(records[0].keys())
        elif isinstance(fields, list):
            returned_field_names = [f.get("id") if isinstance(f, dict) else f for f in fields]
        if resource_id != spec["expected_resource_id"]:
            raise ValueError(
                f"result.resource_id {resource_id!r} does not match expected "
                f"{spec['expected_resource_id']!r}"
            )
        parser_outcome = "envelope_parsed_ok"
    except (ValueError, AttributeError, TypeError) as exc:
        parser_outcome = "envelope_parse_error"
        parse_error = {"exception_type": type(exc).__name__, "message": str(exc)}

    return RequestOutcome(
        label=spec["label"],
        request_url=spec["url"],
        retrieval_timestamp=retrieval_timestamp,
        outcome="success",
        failure_layer=None,
        http_status=response.status,
        content_type=content_type,
        response_bytes=len(response.body),
        content_sha256=response.content_sha256,
        resource_id=resource_id,
        result_total=result_total,
        returned_field_names=returned_field_names,
        records=records,
        approved_response_headers=approved_headers,
        parser_outcome=parser_outcome,
        error=parse_error,
    )


def main() -> int:
    report: dict[str, Any] = {
        "work_order": "WO-027",
        "issue": 56,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "requests": [],
        "stopped_after_sequence": None,
        "stop_reason": None,
    }

    outcomes: list[RequestOutcome] = []
    for sequence, spec in enumerate(REQUESTS, start=1):
        outcome = _execute_one(spec)
        outcomes.append(outcome)
        report["requests"].append({"sequence": sequence, **outcome.to_dict()})
        if outcome.outcome != "success":
            report["stopped_after_sequence"] = sequence
            report["stop_reason"] = (
                f"request {sequence} ({spec['label']}) returned a "
                f"{outcome.failure_layer}-layer transport failure; per WO-027 Part B "
                "bounds, no retry and no further requests are attempted"
            )
            break

    report_path = ROOT / "docs" / "evidence" / "wo027_part_b_live_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if any(outcome.outcome != "success" for outcome in outcomes):
        print("WO-027 Part B stopped on a transport-level anomaly; see report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
