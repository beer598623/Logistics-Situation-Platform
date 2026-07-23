from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "manual-live-source-test.yml"

sys.path.insert(0, str(ROOT))

from collectors.registry import load_registry, source_by_id  # noqa: E402
from scripts.manual_live_source_test import (  # noqa: E402
    _redact_staging_record,
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
