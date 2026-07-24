#!/usr/bin/env python3
"""Controlled manual live-test entry point for GDACS / TMD CAP (Scope D).

This script is the *only* place in the repository that may perform a live
network fetch against GDACS or TMD, and it is only ever invoked by
``.github/workflows/manual-live-source-test.yml``, which is
``workflow_dispatch``-only (no schedule, no push trigger). It never writes
to ``data/candidates/latest.json``, ``data/reviewed/**``,
``dashboard/public/data/**``, or ``data/source_status/latest.json`` -- it
only writes a redacted JSON report to ``manual_live_test_output/`` (a
git-ignored, workflow-artifact-only directory) and never commits anything.

A successful run here does not change ``machine_readable_status``,
``licence_status``, or ``enabled`` on any source contract; those changes
require a separate, reviewed pull request.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.adapters.gdacs import GdacsAdapter, build_search_request  # noqa: E402
from collectors.adapters.tmd_candidate import (  # noqa: E402
    build_candidate_reference,
    derive_candidate_request,
)
from collectors.adapters.tmd_cap import (  # noqa: E402
    TmdCapAdapter,
    redact_candidate_provenance_value,
    resolve_endpoint,
    safe_workflow_run_id,
    safe_workflow_sha,
)
from collectors.error_classification import classify_error  # noqa: E402
from collectors.registry import load_registry, source_by_id  # noqa: E402

OUTPUT_DIR = ROOT / "manual_live_test_output"
MAX_GDACS_DATE_SPAN_DAYS = 31
MAX_REDACTED_STRING_LENGTH = 300
MAX_STAGING_SAMPLE_SIZE = 5
MAX_REPORT_LIST_ITEMS = 50
MAX_REPORT_BYTES = 200_000
MAX_SANITIZE_DEPTH = 8

#: Matches the user-info component of an http(s) URL (``user:pass@`` or
#: ``user@``) anywhere inside a string. This is the report-level second
#: line of defense (review round 2, finding 2): every URL field an adapter
#: produces is already redacted at the source via
#: ``collectors.url_redaction.redact_url_userinfo``, but this pattern is
#: applied unconditionally to *every* string in the report -- including one
#: a future field might add without routing it through that helper -- the
#: same "first pass at creation time, second pass at the artifact boundary"
#: layering ``_sanitize_report`` already uses for length bounding.
_URL_USERINFO_PATTERN = re.compile(r"(https?://)[^\s/@]+@")

# Paths this workflow must never write to, checked defensively even though
# this script never opens them.
_FORBIDDEN_WRITE_PATHS = (
    ROOT / "data" / "candidates" / "latest.json",
    ROOT / "data" / "reviewed",
    ROOT / "dashboard" / "public" / "data",
    ROOT / "data" / "source_status" / "latest.json",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=["gdacs", "tmd_cap"])
    parser.add_argument(
        "--dry-run",
        default="true",
        choices=["true", "false"],
        help="true (default): validate contract/request construction only, no network "
        "call. false: perform one live fetch through the bounded HTTP client.",
    )
    parser.add_argument(
        "--from-date", default=None, help="GDACS only: SEARCH fromdate (YYYY-MM-DD)"
    )
    parser.add_argument("--to-date", default=None, help="GDACS only: SEARCH todate (YYYY-MM-DD)")
    parser.add_argument(
        "--event-types", default="", help="GDACS only: comma-separated eventtype list"
    )
    parser.add_argument(
        "--alert-levels", default="", help="GDACS only: comma-separated alertlevel list"
    )
    parser.add_argument("--page-number", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=None)
    parser.add_argument(
        "--language",
        default="primary",
        help="TMD CAP only: 'primary' for the English endpoint, or an alternate_endpoints "
        "label (e.g. 'thai_language_cap') for the Thai endpoint.",
    )
    parser.add_argument(
        "--tmd-operation",
        default="direct_cap",
        choices=["direct_cap", "rss_discovery", "candidate_cap_validation"],
        help="TMD CAP only: 'direct_cap' (default; current strict CAP behavior), "
        "'rss_discovery' (classify and inspect one RSS envelope only -- never fetches "
        "any discovered item link or enclosure), or 'candidate_cap_validation' "
        "(WO-006: validate exactly one human-selected candidate CAP file through the "
        "DNS-pinned candidate transport -- never fetches an arbitrary URL).",
    )
    parser.add_argument(
        "--candidate-filename",
        default=None,
        help="candidate_cap_validation only: a bare filename matching "
        "CAPTMD<14 digits>_<digits>.xml -- never a URL, path, or host.",
    )
    parser.add_argument(
        "--candidate-evidence-run-id",
        default=None,
        help="candidate_cap_validation only: the WO-005 discovery workflow run ID the "
        "candidate filename was observed in. Provenance only -- not itself an "
        "authorization to fetch.",
    )
    parser.add_argument(
        "--candidate-item-index",
        default=None,
        help="candidate_cap_validation only: the discovery item index (bounded to "
        "rss_discovery.MAX_ITEMS) the candidate filename was observed at. Deliberately "
        "not `type=int` -- an empty or non-numeric workflow input string is passed "
        "through to build_candidate_reference() for a clean, structured "
        "CandidateReferenceError rather than an uncaught argparse crash.",
    )
    return parser.parse_args(argv)


def _candidate_reference_report(
    *,
    language: Any,
    candidate_filename: Any,
    evidence_run_id: Any,
    evidence_item_index: Any,
    request_url: str | None,
) -> dict[str, Any]:
    """Assemble the ``candidate_reference`` object retained on both the
    dry-run and live ``candidate_cap_validation`` reports (WO-007A).

    Gate 1 review of WO-006's dry-run artifact found that the sanitized
    report did not retain the exact candidate provenance fields (filename,
    evidence run ID, evidence item index) needed for independent review --
    only the derived ``request_url`` was present, and only on success. This
    object is built the same way whether the candidate reference was
    accepted or rejected, so a reviewer can see exactly what was requested
    even when validation failed before any DNS or network activity.

    Every caller must already have passed each of ``language``,
    ``candidate_filename``, ``evidence_run_id``, and ``evidence_item_index``
    through ``collectors.adapters.tmd_cap.redact_candidate_provenance_value``
    (or supplied the actual validated value once accepted) -- this function
    performs no redaction of its own (WO-007A round 1 review, finding 1: a
    value must never be echoed here in raw, unvalidated form)."""
    return {
        "language": language,
        "candidate_filename": candidate_filename,
        "candidate_evidence_run_id": evidence_run_id,
        "candidate_evidence_item_index": evidence_item_index,
        "request_url": request_url,
    }


def _redact_string(value: str) -> str:
    value = _URL_USERINFO_PATTERN.sub(r"\1", value)
    if len(value) <= MAX_REDACTED_STRING_LENGTH:
        return value
    return f"<redacted: {len(value)} chars>"


def _redact_staging_record(record: dict[str, Any]) -> dict[str, Any]:
    """Minimize source text before this record is written to a public artifact.

    Titles are truncated; any long free-text value inside ``source_signal``
    is replaced with a length marker. Neither this function nor any caller
    ever has access to the raw XML/JSON response body -- adapters only ever
    return normalized staging records, so there is nothing to redact there.
    This is a semantic, field-aware first pass; ``_sanitize_report`` below
    is the unconditional, whole-report backstop that still applies even if
    a future field is added here without updating this function.
    """
    redacted = copy.deepcopy(record)
    if isinstance(redacted.get("title"), str):
        redacted["title"] = _redact_string(redacted["title"])
    signal = redacted.get("source_signal")
    if isinstance(signal, dict):
        for key, value in list(signal.items()):
            if isinstance(value, str):
                signal[key] = _redact_string(value)
    return redacted


def _sanitize_report(value: Any, *, _depth: int = 0) -> Any:
    """Recursively bound every string and list in the report before it is
    written to disk, printed to the Actions log, or uploaded as an
    artifact.

    This is intentionally unconditional -- it walks every value in the
    report (top-level ``warnings``/``errors``, nested dicts/lists, URLs,
    geography, field-mapping notes, and the already-redacted
    ``staging_sample``) rather than trusting that each producer already
    bounded its own output. A CAP parser warning can legitimately embed
    attacker-controlled XML text (see ``collectors/adapters/cap.py``'s own
    ``_bounded`` helper, which is a first line of defense at
    warning-creation time); this is the second, independent line of
    defense at the artifact boundary.
    """
    if _depth > MAX_SANITIZE_DEPTH:
        return "<redacted: report nesting too deep>"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        kept = value[:MAX_REPORT_LIST_ITEMS]
        sanitized = [_sanitize_report(item, _depth=_depth + 1) for item in kept]
        omitted = len(value) - len(kept)
        if omitted > 0:
            sanitized.append(f"<redacted: {omitted} more list items omitted>")
        return sanitized
    if isinstance(value, dict):
        return {key: _sanitize_report(val, _depth=_depth + 1) for key, val in value.items()}
    return value


def _enforce_report_size_cap(report: dict[str, Any]) -> dict[str, Any]:
    """Drop the (largest, least essential) staging_sample entirely if the
    fully-sanitized report still exceeds a total byte cap, rather than
    uploading an unbounded artifact."""
    serialized_length = len(json.dumps(report).encode("utf-8"))
    if serialized_length <= MAX_REPORT_BYTES:
        return report
    reduced = dict(report)
    omitted_count = len(reduced.get("staging_sample") or [])
    reduced["staging_sample"] = (
        f"<redacted: {omitted_count} record(s) omitted -- report exceeded the "
        f"{MAX_REPORT_BYTES}-byte cap>"
    )
    return reduced


def _check_forbidden_paths_untouched(before: dict[Path, float | None]) -> list[str]:
    problems = []
    for path in _FORBIDDEN_WRITE_PATHS:
        existed_before = before.get(path)
        if path.exists():
            mtime = path.stat().st_mtime
            if existed_before is None or mtime != existed_before:
                problems.append(f"{path.relative_to(ROOT)} was created or modified by this run")
        elif existed_before is not None:
            problems.append(f"{path.relative_to(ROOT)} existed before this run and is now missing")
    return problems


def _snapshot_forbidden_paths() -> dict[Path, float | None]:
    return {
        path: (path.stat().st_mtime if path.exists() else None) for path in _FORBIDDEN_WRITE_PATHS
    }


def run_gdacs(args: argparse.Namespace, contract: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    from_date = args.from_date
    to_date = args.to_date
    if not from_date or not to_date:
        raise SystemExit("--from-date and --to-date are required for source=gdacs")
    span_days = (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days
    if span_days < 0:
        raise SystemExit("--to-date must not be before --from-date")
    if span_days > MAX_GDACS_DATE_SPAN_DAYS:
        raise SystemExit(
            f"GDACS manual test date range spans {span_days} days, exceeding the "
            f"{MAX_GDACS_DATE_SPAN_DAYS}-day bound enforced by this workflow"
        )

    event_types = [item for item in args.event_types.split(",") if item]
    alert_levels = [item for item in args.alert_levels.split(",") if item]

    request = build_search_request(
        contract,
        from_date=from_date,
        to_date=to_date,
        event_types=event_types,
        alert_levels=alert_levels,
        page_number=args.page_number,
        page_size=args.page_size,
    )
    report: dict[str, Any] = {
        "request_url": request.to_url(),
        "page_number": request.page_number,
        "page_size": request.page_size,
    }

    if dry_run:
        report["mode"] = "dry_run"
        report["note"] = "Request constructed and validated only; no network call was made."
        return report

    adapter = GdacsAdapter(
        contract,
        from_date=from_date,
        to_date=to_date,
        event_types=event_types,
        alert_levels=alert_levels,
        page_number=args.page_number,
        page_size=args.page_size,
    )
    result = adapter.collect()
    report["mode"] = "live"
    report["collection_run"] = result.run.to_dict()
    report["record_counts"] = {
        "received": result.run.records_received,
        "emitted": result.run.records_emitted,
        "rejected": result.run.records_rejected,
    }
    report["warnings"] = result.warnings
    report["errors"] = result.errors
    report["error_code"] = result.error_code
    report["error_category"] = result.error_category
    report["envelope_classification"] = result.envelope_classification
    report["staging_sample"] = [
        _redact_staging_record(record) for record in result.records[:MAX_STAGING_SAMPLE_SIZE]
    ]
    return report


def run_tmd_candidate_cap_validation(
    args: argparse.Namespace, contract: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """WO-006: validate exactly one human-selected candidate CAP file.

    Kept as a separate function from ``run_tmd_cap`` (not a branch inside
    it after endpoint resolution) because this operation never resolves a
    contract endpoint at all -- the fetch target is derived entirely from
    fixed policy (``collectors/adapters/tmd_candidate.py``), never from
    ``config/sources.yaml``. Dry run validates the candidate reference and
    derives the request URL with zero DNS or network activity; live mode
    is implemented here but must never be invoked under WO-006 (Issue #11
    authorizes implementation only, not a live candidate fetch).
    """
    report: dict[str, Any] = {
        "operation": "candidate_cap_validation",
        # WO-007A round 1 review, finding 1: this top-level echo of the
        # language selector must never be the raw, unvalidated value
        # either -- it starts as the same safe descriptor
        # candidate_reference.language uses, and is replaced with the
        # actual validated value only once build_candidate_reference()
        # (dry run) / validate_candidate() (live) accepts it, below.
        "language": redact_candidate_provenance_value(args.language),
        # WO-007A: retained on both dry-run and live reports whenever the
        # environment provides them (a GitHub Actions run), so a Gate
        # reviewer can trace a report back to the exact workflow run that
        # produced it. Read once, here, from the same environment for both
        # modes -- neither is itself network or DNS activity. Validated at
        # origin (round 1 review, finding 3): None means no value was
        # provided; a static marker means one was provided but did not
        # match GITHUB_RUN_ID/GITHUB_SHA's documented form.
        "workflow_run_id": safe_workflow_run_id(os.environ.get("GITHUB_RUN_ID")),
        "workflow_sha": safe_workflow_sha(os.environ.get("GITHUB_SHA")),
    }

    # A GitHub Actions workflow_dispatch input has no integer type -- this
    # is always a string, possibly empty. Converting it here (rather than
    # via argparse's `type=int`) means an empty or non-numeric value still
    # reaches build_candidate_reference() for a clean, structured
    # CandidateReferenceError instead of crashing before any report can be
    # written.
    raw_item_index = args.candidate_item_index
    try:
        item_index: Any = (
            int(raw_item_index) if raw_item_index not in (None, "") else raw_item_index
        )
    except (TypeError, ValueError):
        item_index = raw_item_index

    if dry_run:
        report["mode"] = "dry_run"
        # WO-007A round 1 review, findings 1-2: start from a safe,
        # non-reversible descriptor of each raw caller-supplied value --
        # never the raw text itself, since build_candidate_reference()
        # below has not yet had a chance to validate it (or may reject it
        # outright). This is the exact same helper, and the exact same
        # "descriptor first, real value only on success" sequencing,
        # ``TmdCapAdapter.validate_candidate`` uses for the live path, so
        # a rejected reference produces identical evidence in both modes
        # -- including a non-numeric item_index string, which now gets a
        # descriptor here too instead of surviving raw or being lost.
        report["candidate_reference"] = _candidate_reference_report(
            language=redact_candidate_provenance_value(args.language),
            candidate_filename=redact_candidate_provenance_value(args.candidate_filename),
            evidence_run_id=redact_candidate_provenance_value(args.candidate_evidence_run_id),
            evidence_item_index=redact_candidate_provenance_value(item_index),
            request_url=None,
        )
        try:
            reference = build_candidate_reference(
                language=args.language,
                candidate_filename=args.candidate_filename,
                evidence_run_id=args.candidate_evidence_run_id,
                evidence_item_index=item_index,
            )
            derived = derive_candidate_request(reference)
            report["request_url"] = derived.url
            # Validation succeeded: every field is now known-safe
            # (grammar/enum-bound ASCII), so replace the pre-validation
            # descriptor with the actual validated value.
            report["language"] = reference.language
            report["candidate_reference"] = _candidate_reference_report(
                language=reference.language,
                candidate_filename=reference.candidate_filename,
                evidence_run_id=reference.evidence_run_id,
                evidence_item_index=reference.evidence_item_index,
                request_url=derived.url,
            )
            report["note"] = (
                "Candidate reference validated and request URL derived from fixed "
                "policy only; zero DNS resolution and zero network calls were made."
            )
        except Exception as exc:  # noqa: BLE001 -- surfaced as a structured dry-run error
            error_code, error_category = classify_error(exc)
            report["error_code"] = error_code
            report["error_category"] = error_category
            report["errors"] = [f"{error_code}: {exc}"]
            # candidate_reference already holds the pre-validation
            # descriptor set above; nothing further to redact here.
        return report

    adapter = TmdCapAdapter(contract, language=args.language)
    outcome = adapter.validate_candidate(
        candidate_filename=args.candidate_filename,
        evidence_run_id=args.candidate_evidence_run_id,
        evidence_item_index=item_index,
    )
    report["mode"] = "live"
    report["candidate_validation"] = outcome.to_dict()
    # outcome.language is already the actual validated value on success,
    # or the same safe pre-validation descriptor on rejection -- never the
    # raw, unvalidated language string either way.
    report["language"] = outcome.language
    report["candidate_reference"] = _candidate_reference_report(
        language=outcome.language,
        candidate_filename=outcome.candidate_filename,
        evidence_run_id=outcome.evidence_run_id,
        evidence_item_index=outcome.evidence_item_index,
        request_url=outcome.request_url,
    )
    report["warnings"] = outcome.warnings
    report["errors"] = outcome.errors
    report["error_code"] = outcome.error_code
    report["error_category"] = outcome.error_category
    return report


def run_tmd_cap(
    args: argparse.Namespace, contract: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    operation = args.tmd_operation
    if operation == "candidate_cap_validation":
        return run_tmd_candidate_cap_validation(args, contract, dry_run)

    endpoint = resolve_endpoint(contract, language=args.language)
    report: dict[str, Any] = {
        "operation": operation,
        "endpoint": endpoint,
        "language": args.language,
    }

    if dry_run:
        report["mode"] = "dry_run"
        report["note"] = (
            f"Endpoint resolved from contract only for operation={operation!r}; "
            "no network call was made."
        )
        return report

    adapter = TmdCapAdapter(contract, language=args.language)

    if operation == "rss_discovery":
        outcome = adapter.discover_rss()
        report["mode"] = "live"
        report["fetch"] = {
            "request_url": outcome.request_url,
            "response_url": outcome.response_url,
            "http_status": outcome.http_status,
            "content_type": outcome.content_type,
            "etag": outcome.etag,
            "last_modified": outcome.last_modified,
            "content_sha256": outcome.content_sha256,
            "workflow_sha": outcome.workflow_sha,
        }
        report["envelope_classification"] = outcome.envelope_classification
        report["discovery"] = outcome.discovery
        report["warnings"] = outcome.warnings
        report["errors"] = outcome.errors
        report["error_code"] = outcome.error_code
        report["error_category"] = outcome.error_category
        return report

    result = adapter.collect()
    report["mode"] = "live"
    report["collection_run"] = result.run.to_dict()
    report["record_counts"] = {
        "received": result.run.records_received,
        "emitted": result.run.records_emitted,
        "rejected": result.run.records_rejected,
    }
    report["warnings"] = result.warnings
    report["errors"] = result.errors
    # A direct-CAP failure that stems from receiving a non-CAP envelope
    # (e.g. the WO-003 "received rss" rejection) is handled inside
    # TmdCapAdapter.collect() itself, not raised to this caller -- expose
    # its structured error_code/error_category and, when computed, the
    # envelope classification here too, rather than leaving them buried in
    # a warning string only.
    report["error_code"] = result.error_code
    report["error_category"] = result.error_category
    report["envelope_classification"] = result.envelope_classification
    # Never include the raw XML payload or full description/instruction text:
    # staging records never carry those fields in the first place (see
    # collectors/adapters/tmd_cap.py::normalize_tmd_alert), and the redaction
    # below additionally truncates any long free-text source_signal value.
    report["staging_sample"] = [
        _redact_staging_record(record) for record in result.records[:MAX_STAGING_SAMPLE_SIZE]
    ]
    return report


def _classify_error_category(exc: BaseException) -> str:
    """Map an exception to a short, stable error category for the report.

    Thin wrapper over ``collectors.error_classification.classify_error``,
    kept so existing callers/tests can ask for just the category string.
    Best-effort classification only -- an unrecognized exception type
    still yields a result (category ``"unexpected"``), never a reason to
    skip writing a report.
    """
    return classify_error(exc)[1]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = args.dry_run == "true"

    registry = load_registry()
    contract = source_by_id(registry, args.source.upper())

    before = _snapshot_forbidden_paths()

    try:
        if args.source == "gdacs":
            report = run_gdacs(args, contract, dry_run)
        else:
            report = run_tmd_cap(args, contract, dry_run)
    except (SystemExit, Exception) as exc:
        # Scope F: an expected adapter/parser failure or an unexpected
        # exception raised before/outside an adapter's own try/except must
        # still produce a sanitized diagnostic report -- the forbidden-path
        # snapshot was already taken above, and the check below still runs
        # against it regardless of this branch. This must never suppress
        # the failure: the returned report always carries a non-empty
        # "errors" list, so the exit-code check further down still returns
        # non-zero.
        error_message = (
            str(exc.code) if isinstance(exc, SystemExit) else f"{type(exc).__name__}: {exc}"
        )
        error_code, error_category = classify_error(exc)
        report = {
            "mode": "dry_run" if dry_run else "live",
            "operation": getattr(args, "tmd_operation", None) if args.source == "tmd_cap" else None,
            "endpoint": None,
            "error_code": error_code,
            "error_category": error_category,
            "warnings": [],
            "errors": [error_message],
        }

    problems = _check_forbidden_paths_untouched(before)
    report["source_id"] = contract["id"]
    report["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    report["forbidden_path_check"] = "clean" if not problems else problems
    report["contract_state"] = {
        "enabled": contract["enabled"],
        "machine_readable_status": contract["machine_readable_status"],
        "licence_status": contract["licence_status"],
        "note": "A successful manual test does not change these fields; that requires a "
        "separate reviewed pull request.",
    }

    # Unconditional final pass: bound every string/list in the whole
    # report, then drop the staging sample entirely if it is still too
    # large. This must run after every field above has been added.
    report = _sanitize_report(report)
    report = _enforce_report_size_cap(report)

    OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = OUTPUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if problems:
        print("FAIL: forbidden dashboard/candidate paths were touched:", problems, file=sys.stderr)
        return 1
    if report.get("errors"):
        print("Manual live test completed with errors; see report for details.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
