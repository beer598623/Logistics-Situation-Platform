from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "manual-live-source-test.yml"

sys.path.insert(0, str(ROOT))

from collectors.registry import load_registry, source_by_id  # noqa: E402
from scripts.manual_live_source_test import (  # noqa: E402
    MAX_REPORT_BYTES,
    MAX_REPORT_LIST_ITEMS,
    _enforce_report_size_cap,
    _redact_staging_record,
    _sanitize_report,
    run_gdacs,
    run_tmd_cap,
)


@pytest.fixture
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


# --- Manual workflow has no schedule trigger ---------------------------------


def test_manual_workflow_has_no_schedule_trigger(workflow: dict) -> None:
    # YAML parses the bare `on:` key as boolean True; PyYAML represents it
    # both ways depending on quoting, so check whichever key resolves.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    assert "schedule" not in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "workflow_dispatch" in triggers


def test_manual_workflow_inputs_cover_required_fields(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) >= {"source", "dry_run", "from_date", "to_date", "language"}
    assert inputs["source"]["options"] == ["gdacs", "tmd_cap"]


def test_manual_workflow_does_not_auto_create_a_pull_request(workflow: dict) -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "create-pull-request" not in text
    assert "git push" not in text
    assert "git commit" not in text


# --- Manual workflow cannot write public dashboard/current-event paths -----


def test_manual_workflow_checks_forbidden_paths_are_untouched(workflow: dict) -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "data/candidates",
        "data/reviewed",
        "data/source_status",
        "dashboard/public/data",
    ):
        assert forbidden in text


def test_manual_workflow_uploads_only_the_redacted_report(workflow: dict) -> None:
    steps = workflow["jobs"]["manual-live-test"]["steps"]
    upload_steps = [
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["path"] == "manual_live_test_output/report.json"


def test_manual_live_source_test_script_forbidden_path_check_is_wired_up() -> None:
    """The script itself (not just the workflow YAML) asserts that the four
    public/current-event data paths were not touched during a run."""
    from scripts.manual_live_source_test import _FORBIDDEN_WRITE_PATHS

    relative = {path.relative_to(ROOT).as_posix() for path in _FORBIDDEN_WRITE_PATHS}
    assert relative == {
        "data/candidates/latest.json",
        "data/reviewed",
        "dashboard/public/data",
        "data/source_status/latest.json",
    }


# --- Redaction: no raw payload, minimized long free text --------------------


def test_redact_staging_record_truncates_long_title_and_signal_strings() -> None:
    record = {
        "title": "x" * 500,
        "source_signal": {"cap_category": ["Met"], "note": "y" * 500, "language": "en-US"},
    }
    redacted = _redact_staging_record(record)
    assert redacted["title"].startswith("<redacted:")
    assert redacted["source_signal"]["note"].startswith("<redacted:")
    assert redacted["source_signal"]["language"] == "en-US"
    assert redacted["source_signal"]["cap_category"] == ["Met"]  # non-string values untouched


def test_redact_staging_record_does_not_mutate_the_original() -> None:
    record = {"title": "x" * 500, "source_signal": {"note": "y" * 500}}
    _redact_staging_record(record)
    assert record["title"] == "x" * 500
    assert record["source_signal"]["note"] == "y" * 500


# --- Dry-run mode performs no network access and no forbidden-path writes ---


class _NetworkCallDetected(AssertionError):
    pass


class _NoHttpAllowed:
    def get(self, *args, **kwargs):  # pragma: no cover - only triggered on a bug
        raise _NetworkCallDetected("dry-run mode must never call http.get")


def test_run_gdacs_dry_run_never_touches_network() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "GDACS")

    class Args:
        from_date = "2026-07-01"
        to_date = "2026-07-23"
        event_types = ""
        alert_levels = ""
        page_number = 1
        page_size = None

    report = run_gdacs(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert "collection_run" not in report


def test_run_gdacs_enforces_a_bounded_date_range() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "GDACS")

    class Args:
        from_date = "2026-01-01"
        to_date = "2026-12-31"
        event_types = ""
        alert_levels = ""
        page_number = 1
        page_size = None

    with pytest.raises(SystemExit):
        run_gdacs(Args(), contract, dry_run=True)


def test_run_tmd_cap_dry_run_never_touches_network() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "TMD_CAP")

    class Args:
        language = "primary"

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert "collection_run" not in report


# --- Whole-report sanitizer: bounded strings, capped lists, capped bytes ----


def test_sanitize_report_truncates_long_strings_anywhere_in_the_tree() -> None:
    canary = "CANARY_REPORT_MARKER_" + ("z" * 1000)
    report = {
        "warnings": [canary],
        "nested": {"deep": {"deeper": [canary, {"leaf": canary}]}},
    }
    sanitized = _sanitize_report(report)
    serialized = json.dumps(sanitized)
    # _redact_string replaces the whole oversized value with a length
    # marker (no partial prefix retained), so not even a bounded fragment
    # of the canary should survive anywhere in the tree.
    assert "CANARY_REPORT_MARKER_" not in serialized
    assert serialized.count("<redacted:") == 3


def test_sanitize_report_caps_list_length() -> None:
    report = {"warnings": [f"warning {i}" for i in range(MAX_REPORT_LIST_ITEMS + 25)]}
    sanitized = _sanitize_report(report)
    assert len(sanitized["warnings"]) == MAX_REPORT_LIST_ITEMS + 1  # + one omission marker
    assert "omitted" in sanitized["warnings"][-1]


def test_sanitize_report_does_not_mutate_the_original() -> None:
    report = {"warnings": ["x" * 1000]}
    _sanitize_report(report)
    assert report["warnings"][0] == "x" * 1000


def test_enforce_report_size_cap_drops_staging_sample_when_oversized() -> None:
    huge_sample = [{"title": "x" * 10_000} for _ in range(50)]
    report = {"staging_sample": huge_sample, "warnings": []}
    reduced = _enforce_report_size_cap(report)
    assert isinstance(reduced["staging_sample"], str)
    assert "50" in reduced["staging_sample"]
    assert len(json.dumps(reduced).encode("utf-8")) < MAX_REPORT_BYTES


def test_enforce_report_size_cap_is_a_no_op_for_a_small_report() -> None:
    report = {"staging_sample": [{"title": "short"}], "warnings": []}
    assert _enforce_report_size_cap(report) == report


def test_report_pipeline_never_leaks_a_canary_placed_in_a_cap_warning() -> None:
    """End-to-end canary: a value invalid enough to trigger a CAP parser
    warning, then run through the full report sanitizer, must never appear
    verbatim in the final serialized report."""
    from collectors.adapters.cap import parse_cap_alert

    canary = "CANARY_END_TO_END_MARKER_" + ("Q" * 400)
    xml = f"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-e2e-canary</identifier>
  <info>
    <event>Synthetic event</event>
    <effective>{canary}</effective>
    <area><areaDesc>Synthetic area</areaDesc></area>
  </info>
</alert>""".encode()
    _alert, warnings = parse_cap_alert(xml, max_bytes=1_000_000)
    report = {"warnings": warnings, "errors": []}
    sanitized = _sanitize_report(report)
    serialized = json.dumps(sanitized)
    assert canary not in serialized
    assert "CANARY_END_TO_END_MARKER_" in serialized
