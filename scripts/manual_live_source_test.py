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
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.adapters.gdacs import GdacsAdapter, build_search_request  # noqa: E402
from collectors.adapters.tmd_cap import TmdCapAdapter, resolve_endpoint  # noqa: E402
from collectors.registry import load_registry, source_by_id  # noqa: E402

OUTPUT_DIR = ROOT / "manual_live_test_output"
MAX_GDACS_DATE_SPAN_DAYS = 31
MAX_REDACTED_STRING_LENGTH = 300
MAX_STAGING_SAMPLE_SIZE = 5

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
    return parser.parse_args(argv)


def _redact_string(value: str) -> str:
    if len(value) <= MAX_REDACTED_STRING_LENGTH:
        return value
    return f"<redacted: {len(value)} chars>"


def _redact_staging_record(record: dict[str, Any]) -> dict[str, Any]:
    """Minimize source text before this record is written to a public artifact.

    Titles are truncated; any long free-text value inside ``source_signal``
    is replaced with a length marker. Neither this function nor any caller
    ever has access to the raw XML/JSON response body -- adapters only ever
    return normalized staging records, so there is nothing to redact there.
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
    report["staging_sample"] = [
        _redact_staging_record(record) for record in result.records[:MAX_STAGING_SAMPLE_SIZE]
    ]
    return report


def run_tmd_cap(
    args: argparse.Namespace, contract: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    endpoint = resolve_endpoint(contract, language=args.language)
    report: dict[str, Any] = {"endpoint": endpoint, "language": args.language}

    if dry_run:
        report["mode"] = "dry_run"
        report["note"] = "Endpoint resolved from contract only; no network call was made."
        return report

    adapter = TmdCapAdapter(contract, language=args.language)
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
    # Never include the raw XML payload or full description/instruction text:
    # staging records never carry those fields in the first place (see
    # collectors/adapters/tmd_cap.py::normalize_tmd_alert), and the redaction
    # below additionally truncates any long free-text source_signal value.
    report["staging_sample"] = [
        _redact_staging_record(record) for record in result.records[:MAX_STAGING_SAMPLE_SIZE]
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = args.dry_run == "true"

    registry = load_registry()
    contract = source_by_id(registry, args.source.upper())

    before = _snapshot_forbidden_paths()

    if args.source == "gdacs":
        report = run_gdacs(args, contract, dry_run)
    else:
        report = run_tmd_cap(args, contract, dry_run)

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
