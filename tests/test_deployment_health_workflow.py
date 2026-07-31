"""WO-014: deployment liveness check and incident-recording wiring.

Does not fetch the live URL or call the GitHub API -- that needs live
network, which does not belong in the default (network-free) test run.
These tests check the structural wiring: the workflow runs daily with no
push/pull_request trigger, has issues:write permission, actually checks the
real published URL for the real content marker, and the failure/recovery
steps agree on the same issue title. They also cross-check the URL cited in
health-check.yml against the URL documented in
docs/deployment_verification.md, the way test_documentation_registry_coverage.py
cross-checks the source registry against its documentation.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_URL = "https://beer598623.github.io/Logistics-Situation-Platform/"
EXPECTED_CONTENT_MARKER = "Thailand Ocean Logistics Intelligence"


def _load_health_check_workflow() -> dict:
    text = (ROOT / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _triggers(workflow: dict) -> dict:
    # YAML parses a bare `on:` key as boolean True; PyYAML represents it either
    # way depending on quoting, so check whichever key resolves.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    return triggers


def test_health_check_runs_daily_with_no_push_or_pull_request_trigger() -> None:
    triggers = _triggers(_load_health_check_workflow())
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers

    cron = triggers["schedule"][0]["cron"]
    # A daily cron fixes hour and minute but leaves day-of-month, month and
    # day-of-week as "*"; a weekly one (the pre-WO-014 "17 0 * * 1") pins a
    # specific weekday in the fifth field.
    minute, hour, day_of_month, month, day_of_week = cron.split()
    assert day_of_month == "*"
    assert month == "*"
    assert day_of_week == "*"


def test_health_check_can_write_issues() -> None:
    workflow = _load_health_check_workflow()
    assert workflow["permissions"]["issues"] == "write"
    assert workflow["permissions"]["contents"] == "read"


def test_health_check_env_declares_the_real_published_url() -> None:
    workflow = _load_health_check_workflow()
    assert workflow["env"]["DEPLOYED_URL"] == EXPECTED_URL


def test_health_check_liveness_step_checks_status_and_content() -> None:
    text = (ROOT / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    assert "$DEPLOYED_URL" in text
    assert 'status" != "200"' in text
    assert EXPECTED_CONTENT_MARKER in text


def test_content_marker_is_actually_present_on_the_committed_page() -> None:
    """WO-020 / Issue #32-adjacent roadmap gap: the test above only checks
    that EXPECTED_CONTENT_MARKER appears in the workflow file's grep
    command -- never that the marker actually appears on the page it greps.
    A renamed <h1> (e.g. at Bundle 2, when "Ocean" stops being the whole
    scope) would silently break the daily liveness check in production with
    no CI warning, since nothing today ties the two together. index.html itself
    is hand-maintained, not generated -- scripts/build_dashboard.py only writes
    dashboard/public/data/ -- but it is committed, so this can check it
    directly like any other test here."""
    index_html = (ROOT / "dashboard" / "public" / "index.html").read_text(encoding="utf-8")
    assert EXPECTED_CONTENT_MARKER in index_html, (
        f"EXPECTED_CONTENT_MARKER {EXPECTED_CONTENT_MARKER!r} is not present in "
        "dashboard/public/index.html -- health-check.yml's daily liveness grep for this "
        "string would now fail against the real published page"
    )


def test_health_check_failure_and_recovery_steps_share_one_issue_title() -> None:
    workflow = _load_health_check_workflow()
    title = workflow["env"]["HEALTH_ISSUE_TITLE"]
    assert title

    text = (ROOT / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    # Both the failure-recording step and the recovery-closing step must key
    # off the same $HEALTH_ISSUE_TITLE env var, not a hardcoded duplicate
    # string that could drift out of sync with it.
    assert text.count("$HEALTH_ISSUE_TITLE") >= 2
    assert "if: failure()" in text
    assert "if: success()" in text


def test_health_check_issue_dedupe_excludes_pull_requests() -> None:
    """WO-021: GET /issues returns pull requests as well as issues. Without
    filtering, a PR that happened to carry $HEALTH_ISSUE_TITLE would be
    mistaken for the tracked issue by both the failure-recording lookup and
    the recovery-closing lookup, corrupting the dedupe. Both occurrences
    must exclude pull requests, not just one."""
    text = (ROOT / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    assert text.count("select(.pull_request == null)") >= 2


def test_deployment_verification_doc_cites_the_same_url_as_the_workflow() -> None:
    text = (ROOT / "docs" / "deployment_verification.md").read_text(encoding="utf-8")
    assert EXPECTED_URL in text
    assert "gh-pages" in text
    assert "deploy-pages@v5" in text


def test_operations_runbook_has_the_new_wo014_sections() -> None:
    text = (ROOT / "docs" / "operations_runbook.md").read_text(encoding="utf-8")
    assert re.search(r"^## \d+\. Backup and disaster recovery", text, re.MULTILINE)
    assert re.search(r"^## \d+\. Incident response", text, re.MULTILINE)
    assert "Rolling back the published Dashboard" in text


def test_operations_runbook_workflow_table_reflects_the_daily_cadence() -> None:
    text = (ROOT / "docs" / "operations_runbook.md").read_text(encoding="utf-8")
    assert "| `health-check.yml` | **daily**" in text
