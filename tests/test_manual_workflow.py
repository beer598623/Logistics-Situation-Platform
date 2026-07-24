from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "manual-live-source-test.yml"

sys.path.insert(0, str(ROOT))

from collectors.adapters.cap import CapSecurityError, MalformedCapAlertError  # noqa: E402
from collectors.adapters.rss_discovery import (  # noqa: E402
    NotAnRssEnvelopeError,
    RssParseError,
    RssSecurityError,
)
from collectors.adapters.tmd_candidate import (  # noqa: E402
    CandidateEnvelopeMismatchError,
    CandidateReferenceError,
    CandidateUnexpectedStatusError,
)
from collectors.adapters.tmd_cap import TmdCapAdapter as RealTmdCapAdapter  # noqa: E402
from collectors.adapters.xml_envelope import EnvelopeParseError, EnvelopeSecurityError  # noqa: E402
from collectors.http_client import (  # noqa: E402
    DnsResolutionError,
    NonGlobalAddressError,
    PinnedConnectionError,
    PinnedRedirectError,
    PinnedTlsError,
    UnexpectedContentTypeError,  # noqa: E402
)
from collectors.registry import load_registry, source_by_id  # noqa: E402
from scripts import manual_live_source_test  # noqa: E402
from scripts.manual_live_source_test import (  # noqa: E402
    MAX_REPORT_BYTES,
    MAX_REPORT_LIST_ITEMS,
    _classify_error_category,
    _enforce_report_size_cap,
    _redact_staging_record,
    _sanitize_report,
    main,
    run_gdacs,
    run_tmd_cap,
)
from tests.conftest import FakeHttpClient, fake_resolve_pinned  # noqa: E402

CAP_FIXTURES = ROOT / "tests" / "fixtures" / "cap"
RSS_FIXTURES = ROOT / "tests" / "fixtures" / "rss"


@pytest.fixture
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _install_fake_tmd_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: bytes,
    headers: dict[str, str] | None = None,
    status: int = 200,
    response_url: str | None = None,
    resolve_pinned=None,
    raise_on_get_pinned_candidate: Exception | None = None,
    connected_ip_override: str | None = None,
) -> FakeHttpClient:
    """Make ``run_tmd_cap``'s live-mode adapter construction (inside
    ``scripts.manual_live_source_test``) return a real ``TmdCapAdapter``
    wired to a ``FakeHttpClient`` instead of the real network client, so
    ``main()`` can be exercised end-to-end (full report construction,
    sanitization, forbidden-path check, exit code) with zero network
    access. WO-006: also wires an injectable ``resolve_pinned`` (defaults
    to a fake DNS-pinning resolver -- never the real one -- so
    ``candidate_cap_validation`` live mode never performs real DNS
    resolution in a test either)."""
    fake_http = FakeHttpClient(
        body=body, status=status, headers=headers or {}, response_url=response_url
    )
    fake_http.raise_on_get_pinned_candidate = raise_on_get_pinned_candidate
    fake_http.connected_ip_override = connected_ip_override
    resolver = resolve_pinned or fake_resolve_pinned()

    def _factory(contract, http=None, *, language="primary", resolve_pinned=None):
        return RealTmdCapAdapter(
            contract, http=fake_http, language=language, resolve_pinned=resolver
        )

    monkeypatch.setattr(manual_live_source_test, "TmdCapAdapter", _factory)
    return fake_http


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


# --- Scope E: bounded TMD discovery-mode input --------------------------------


def test_manual_workflow_has_a_bounded_tmd_operation_input(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "tmd_operation" in inputs
    assert inputs["tmd_operation"]["default"] == "direct_cap"
    assert inputs["tmd_operation"]["options"] == [
        "direct_cap",
        "rss_discovery",
        "candidate_cap_validation",
    ]


# --- WO-006 Scope E: candidate_cap_validation workflow inputs ---------------


def test_manual_workflow_has_candidate_validation_inputs(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert {"candidate_filename", "candidate_evidence_run_id", "candidate_item_index"} <= set(
        inputs
    )
    for name in ("candidate_filename", "candidate_evidence_run_id", "candidate_item_index"):
        assert inputs[name]["required"] is False


def test_manual_workflow_still_has_no_schedule_after_candidate_validation_addition(
    workflow: dict,
) -> None:
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}


def test_manual_workflow_permissions_are_read_only(workflow: dict) -> None:
    assert workflow["permissions"] == {"contents": "read"}


# --- Scope F: safety checks still run after an expected script failure -----


def test_manual_workflow_confirm_step_runs_even_after_a_prior_failure(workflow: dict) -> None:
    steps = workflow["jobs"]["manual-live-test"]["steps"]
    confirm_steps = [
        step
        for step in steps
        if step.get("name") == "Confirm public dashboard/current-event data are unchanged"
    ]
    assert len(confirm_steps) == 1
    assert confirm_steps[0]["if"] == "always()"


def test_manual_workflow_upload_step_runs_even_after_a_prior_failure(workflow: dict) -> None:
    steps = workflow["jobs"]["manual-live-test"]["steps"]
    upload_steps = [
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["if"] == "always()"


def test_manual_workflow_script_step_has_no_continue_on_error(workflow: dict) -> None:
    """The run-script step must not silently swallow a non-zero exit -- a
    parser/security failure must still fail the job."""
    steps = workflow["jobs"]["manual-live-test"]["steps"]
    script_steps = [step for step in steps if "manual_live_source_test.py" in step.get("run", "")]
    assert len(script_steps) == 1
    assert "continue-on-error" not in script_steps[0]


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
        tmd_operation = "direct_cap"

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert "collection_run" not in report


def test_run_tmd_cap_rss_discovery_dry_run_never_touches_network() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "TMD_CAP")

    class Args:
        language = "primary"
        tmd_operation = "rss_discovery"

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert report["operation"] == "rss_discovery"
    assert "fetch" not in report
    assert "discovery" not in report
    assert "envelope_classification" not in report


# --- WO-006 Scope E/G: candidate_cap_validation dry run (zero DNS/network) --


def test_run_tmd_candidate_cap_validation_dry_run_derives_url_with_zero_network() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "TMD_CAP")

    class Args:
        language = "primary"
        tmd_operation = "candidate_cap_validation"
        candidate_filename = "CAPTMD20260723155032_2.xml"
        candidate_evidence_run_id = "30028391246"
        candidate_item_index = "0"

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert report["operation"] == "candidate_cap_validation"
    assert (
        report["request_url"] == "https://www.tmd.go.th/uploads/CAP/en/CAPTMD20260723155032_2.xml"
    )
    assert "candidate_validation" not in report
    assert "errors" not in report


def test_run_tmd_candidate_cap_validation_dry_run_rejects_a_bad_filename() -> None:
    registry = load_registry()
    contract = source_by_id(registry, "TMD_CAP")

    class Args:
        language = "primary"
        tmd_operation = "candidate_cap_validation"
        candidate_filename = "../etc/passwd"
        candidate_evidence_run_id = "1"
        candidate_item_index = "0"

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["mode"] == "dry_run"
    assert report["error_code"] == "CandidateReferenceError"
    assert report["error_category"] == "validation"
    assert "request_url" not in report


def test_run_tmd_candidate_cap_validation_dry_run_rejects_a_blank_item_index() -> None:
    # Simulates an unset GitHub Actions workflow_dispatch string input.
    registry = load_registry()
    contract = source_by_id(registry, "TMD_CAP")

    class Args:
        language = "primary"
        tmd_operation = "candidate_cap_validation"
        candidate_filename = "CAPTMD20260723155032_2.xml"
        candidate_evidence_run_id = "30028391246"
        candidate_item_index = ""

    report = run_tmd_cap(Args(), contract, dry_run=True)
    assert report["error_code"] == "CandidateReferenceError"
    assert report["error_category"] == "validation"


# --- WO-006 Scope E/G: candidate_cap_validation live mode (fakes only) ------


def test_main_candidate_cap_validation_succeeds_and_minimizes_the_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "30028391246",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 0
    validation = report["candidate_validation"]
    assert validation["http_status"] == 200
    assert validation["envelope_classification"]["envelope_kind"] == "cap_alert"
    assert validation["connected_ip_matches_selected"] is True
    assert validation["cap_identifier_length"] == len("synthetic-tmd-cap-0001")
    assert "cap_identifier" not in validation
    report_text = json.dumps(report)
    # The raw CAP identifier and every piece of free-text CAP content must
    # never appear anywhere in the final sanitized report.
    for canary in (
        "synthetic-tmd-cap-0001",
        "Synthetic severe thunderstorm warning",
        "Synthetic hazard description",
        "Synthetic instruction text",
        "https://example.test/synthetic-warning-0001",
        "synthetic-contact@example.test",
        "Synthetic Test Province",
        "15.0,100.0",
    ):
        assert canary not in report_text


def test_main_candidate_cap_validation_rejects_a_non_cap_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (RSS_FIXTURES / "same_host_link.xml").read_bytes()
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/xml"})
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    validation = report["candidate_validation"]
    assert validation["error_code"] == "CandidateEnvelopeMismatchError"
    assert validation["error_category"] == "parse"


def test_main_candidate_cap_validation_rejects_dtd_xxe(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "dtd_entity_attack.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    validation = report["candidate_validation"]
    assert validation["error_category"] == "security"
    assert "/etc/passwd" not in json.dumps(report)


def test_main_candidate_cap_validation_rejects_missing_identifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "missing_identifier.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    validation = report["candidate_validation"]
    assert validation["error_code"] == "MalformedCapAlertError"
    assert validation["error_category"] == "parse"
    assert validation["cap_identifier_length"] is None


def test_main_candidate_cap_validation_unexpected_content_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = b"<html><body>not xml</body></html>"
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/html"})
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    assert report["candidate_validation"]["error_category"] == "content_type"


def test_main_candidate_cap_validation_response_too_large(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from collectors.adapters.tmd_cap import CANDIDATE_MAX_RESPONSE_BYTES

    body = b"x" * (CANDIDATE_MAX_RESPONSE_BYTES + 1)
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    assert report["candidate_validation"]["error_category"] == "security"


def test_main_candidate_cap_validation_304_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _install_fake_tmd_adapter(monkeypatch, body=b"", status=304, headers={"etag": '"same"'})
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    validation = report["candidate_validation"]
    assert validation["error_code"] == "UnexpectedNotModifiedError"
    assert validation["http_status"] == 304


def test_main_candidate_cap_validation_never_fetches_more_than_one_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    fake_http = _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    assert fake_http.pinned_call_count == 1
    assert fake_http.call_count == 1


def test_main_candidate_cap_validation_dns_failure_never_reaches_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _raise_dns(hostname, port):
        raise DnsResolutionError("simulated resolver failure")

    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    fake_http = _install_fake_tmd_adapter(
        monkeypatch,
        body=body,
        headers={"content-type": "application/cap+xml"},
        resolve_pinned=_raise_dns,
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    assert report["candidate_validation"]["error_code"] == "DnsResolutionError"
    assert report["candidate_validation"]["error_category"] == "security"
    assert fake_http.pinned_call_count == 0


def test_main_candidate_cap_validation_connected_ip_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch,
        body=body,
        headers={"content-type": "application/cap+xml"},
        connected_ip_override="10.0.0.99",
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert exit_code == 1
    validation = report["candidate_validation"]
    assert validation["error_code"] == "PinnedConnectionError"
    assert validation["connected_ip_matches_selected"] is False


def test_main_candidate_cap_validation_never_creates_a_staging_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert "staging_sample" not in report
    assert "collection_run" not in report


def test_main_candidate_cap_validation_leaves_source_state_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    body = (CAP_FIXTURES / "valid_bilingual_alert.xml").read_bytes()
    _install_fake_tmd_adapter(
        monkeypatch, body=body, headers={"content-type": "application/cap+xml"}
    )
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)

    main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "false",
            "--tmd-operation",
            "candidate_cap_validation",
            "--candidate-filename",
            "CAPTMD20260723155032_2.xml",
            "--candidate-evidence-run-id",
            "1",
            "--candidate-item-index",
            "0",
        ]
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["contract_state"]["enabled"] is False
    assert report["contract_state"]["machine_readable_status"] == "unverified"
    assert report["contract_state"]["licence_status"] == "pending_review"


# --- _classify_error_category: stable vocabulary for sanitized diagnostics --


@pytest.mark.parametrize(
    ("exc", "expected_category"),
    [
        (SystemExit("bad range"), "validation"),
        (CapSecurityError("boom"), "security"),
        (EnvelopeSecurityError("boom"), "security"),
        (RssSecurityError("boom"), "security"),
        (MalformedCapAlertError("boom"), "parse"),
        (NotAnRssEnvelopeError("boom"), "parse"),
        (EnvelopeParseError("boom"), "parse"),
        (RssParseError("boom"), "parse"),
        (UnexpectedContentTypeError("boom"), "content_type"),
        (ValueError("boom"), "validation"),
        (RuntimeError("boom"), "unexpected"),
        (CandidateReferenceError("boom"), "validation"),
        (CandidateEnvelopeMismatchError("boom"), "parse"),
        (CandidateUnexpectedStatusError("boom"), "unexpected"),
        (DnsResolutionError("boom"), "security"),
        (NonGlobalAddressError("boom"), "security"),
        (PinnedRedirectError("boom"), "security"),
        (PinnedTlsError("boom"), "security"),
        (PinnedConnectionError("boom"), "security"),
    ],
)
def test_classify_error_category_maps_known_exception_types(exc, expected_category) -> None:
    assert _classify_error_category(exc) == expected_category


# --- main(): failure path still produces a sanitized report + non-zero exit -


def test_main_produces_sanitized_error_report_for_an_out_of_bound_gdacs_date_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    exit_code = main(
        [
            "--source",
            "gdacs",
            "--dry-run",
            "true",
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2026-12-31",
        ]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_category"] == "validation"
    assert report["errors"]
    assert report["forbidden_path_check"] == "clean"
    assert report["contract_state"]["enabled"] is False


def test_main_produces_sanitized_error_report_for_an_unknown_tmd_language_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unexpected exception raised before an adapter's own try/except
    (here, resolve_endpoint's ValueError for an unknown alternate-endpoint
    label) must still produce a sanitized report and a non-zero exit --
    never a crash with no artifact."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "true",
            "--language",
            "unknown_language_label",
        ]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_code"] == "ValueError"
    assert report["error_category"] == "validation"
    assert report["operation"] == "direct_cap"
    assert report["forbidden_path_check"] == "clean"


def test_main_succeeds_for_a_valid_dry_run_and_leaves_forbidden_paths_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    exit_code = main(
        [
            "--source",
            "tmd_cap",
            "--dry-run",
            "true",
            "--tmd-operation",
            "rss_discovery",
        ]
    )
    assert exit_code == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["mode"] == "dry_run"
    assert report["forbidden_path_check"] == "clean"


# --- main(): end-to-end structured reports for adapter-handled failures ----
# Review round 1, finding 4: these exercise the actual paths TmdCapAdapter
# catches internally (collect()/discover_rss()), not just exceptions that
# escape to main()'s own try/except -- each must produce a sanitized
# report, return non-zero, retain the forbidden-path result, and carry the
# correct structured error_category.


def test_main_direct_cap_receiving_rss_produces_structured_parse_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The exact WO-003 failure: a direct-CAP fetch that receives an RSS
    envelope. collect() catches MalformedCapAlertError itself and never
    lets it escape to main() -- the structured category and the envelope
    classification must still surface in the report."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    _install_fake_tmd_adapter(
        monkeypatch,
        body=(RSS_FIXTURES / "same_host_link.xml").read_bytes(),
        headers={"content-type": "text/xml"},
    )
    exit_code = main(["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "direct_cap"])
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_code"] == "MalformedCapAlertError"
    assert report["error_category"] == "parse"
    assert report["envelope_classification"]["envelope_kind"] == "rss"
    assert report["forbidden_path_check"] == "clean"


def test_main_rss_discovery_dtd_xxe_produces_structured_security_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    _install_fake_tmd_adapter(
        monkeypatch,
        body=(CAP_FIXTURES / "dtd_entity_attack.xml").read_bytes(),
        headers={"content-type": "application/xml"},
    )
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_category"] == "security"
    assert "EnvelopeSecurityError" in report["error_code"]
    assert report["forbidden_path_check"] == "clean"


def test_main_rss_discovery_malformed_xml_produces_structured_parse_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    _install_fake_tmd_adapter(
        monkeypatch,
        body=b"<rss><channel><title>unterminated",
        headers={"content-type": "text/xml"},
    )
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_category"] == "parse"
    assert "EnvelopeParseError" in report["error_code"]
    assert "unterminated" not in json.dumps(report)
    assert report["forbidden_path_check"] == "clean"


def test_main_unexpected_content_type_produces_structured_content_type_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    _install_fake_tmd_adapter(
        monkeypatch,
        body=b"<html><body>Not Found</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )
    exit_code = main(["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "direct_cap"])
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_category"] == "content_type"
    assert report["error_code"] == "UnexpectedContentTypeError"
    assert report["forbidden_path_check"] == "clean"


def test_main_response_too_large_produces_structured_security_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 2, finding 3: a real ResponseTooLargeError (the same
    exception ResilientHttpClient itself raises for a real oversized
    response) must be classified security, not unexpected, in the final
    report."""
    from collectors.http_client import ResponseTooLargeError

    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    fake_http = _install_fake_tmd_adapter(
        monkeypatch,
        body=(RSS_FIXTURES / "same_host_link.xml").read_bytes(),
        headers={"content-type": "text/xml"},
    )
    fake_http.raise_on_get_no_redirect = ResponseTooLargeError("oversized response")
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_code"] == "ResponseTooLargeError"
    assert report["error_category"] == "security"
    assert report["forbidden_path_check"] == "clean"


def test_main_rss_discovery_never_leaks_url_credentials_in_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 2, finding 2: end-to-end proof that embedded
    username/password never survive into the serialized report JSON, for
    both the discovery-parser-level redaction and the report-level second
    line of defense."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    body = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <link>https://canaryuser:canarysecret@feed.example.test/warnings/item-1</link>
      <guid isPermaLink="true">https://canaryuser:canarysecret@feed.example.test/warnings/item-1</guid>
    </item>
  </channel>
</rss>"""
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/xml"})
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 0
    report_text = (tmp_path / "report.json").read_text()
    assert "canaryuser" not in report_text
    assert "canarysecret" not in report_text
    report = json.loads(report_text)
    # The fixture's host (feed.example.test) differs from the TMD
    # contract's real requested endpoint host (www.tmd.go.th), so these
    # land in cross_host_urls -- the credentials-redaction assertions
    # above are this test's actual point; this just confirms candidates
    # were produced at all.
    assert report["discovery"]["cross_host_urls"]


def test_main_rss_discovery_never_leaks_malformed_credential_like_url_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 3, finding 2: a malformed (not well-formed) URL value
    that happens to contain credential-shaped text -- e.g. a single-slash
    "https:/user:pass@host" form with no parsed authority component --
    must never survive into the report, even though the producer-level
    redact_url_userinfo cannot reliably strip it (there is no parsed
    netloc to strip from for a value that never parsed as having one)."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    body = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <link>https:/malformeduser:malformedsecret@feed.example.test/path</link>
    </item>
  </channel>
</rss>"""
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/xml"})
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 0
    report_text = (tmp_path / "report.json").read_text()
    assert "malformeduser" not in report_text
    assert "malformedsecret" not in report_text
    report = json.loads(report_text)
    assert report["discovery"]["malformed_urls"]
    assert report["discovery"]["malformed_urls"][0].startswith("<malformed value:")


def test_main_rss_discovery_never_leaks_malformed_non_http_credential_like_url_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 3, finding 2: the non-HTTP-scheme variant -- a value
    with no scheme separator recognized as an authority component at all
    -- must also never survive into the report."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    body = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <link>nonhttpmalformeduser:nonhttpmalformedsecret@feed.example.test/path</link>
    </item>
  </channel>
</rss>"""
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/xml"})
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 0
    report_text = (tmp_path / "report.json").read_text()
    assert "nonhttpmalformeduser" not in report_text
    assert "nonhttpmalformedsecret" not in report_text
    report = json.loads(report_text)
    assert report["discovery"]["malformed_urls"]
    assert report["discovery"]["malformed_urls"][0].startswith("<malformed value:")


def test_main_rss_discovery_never_leaks_malformed_credential_bearing_guid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 4: a guid that starts with 'https://' but has an
    invalid IPv6 authority (urlsplit/urlparse raise ValueError) must not
    survive into the report, even though it passes the guid retention
    gate's startswith check."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    body = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <guid isPermaLink="true">https://guidcanaryuser:guidcanarysecret@[bad</guid>
    </item>
  </channel>
</rss>"""
    _install_fake_tmd_adapter(monkeypatch, body=body, headers={"content-type": "text/xml"})
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 0
    report_text = (tmp_path / "report.json").read_text()
    assert "guidcanaryuser" not in report_text
    assert "guidcanarysecret" not in report_text
    report = json.loads(report_text)
    assert report["discovery"]["malformed_urls"]
    assert report["discovery"]["malformed_urls"][0].startswith("<malformed value:")


def test_main_rss_discovery_304_is_a_non_zero_structured_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review round 3, finding 1: end-to-end proof that an uncacheable 304
    in discovery mode produces a non-zero exit and a structured failure
    report, not a quiet success with null classification/discovery."""
    monkeypatch.setattr(manual_live_source_test, "OUTPUT_DIR", tmp_path)
    _install_fake_tmd_adapter(monkeypatch, body=b"", status=304, headers={"etag": '"same"'})
    exit_code = main(
        ["--source", "tmd_cap", "--dry-run", "false", "--tmd-operation", "rss_discovery"]
    )
    assert exit_code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error_code"] == "UnexpectedNotModifiedError"
    assert report["error_category"] == "unexpected"
    assert report["envelope_classification"] is None
    assert report["discovery"] is None
    assert report["forbidden_path_check"] == "clean"


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
