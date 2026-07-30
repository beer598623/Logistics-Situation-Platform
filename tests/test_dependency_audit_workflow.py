"""WO-013: dependency vulnerability scanning is wired up and stays offline-by-default.

Does not invoke ``pip-audit`` itself -- that needs a live query against a public
vulnerability database, which does not belong in the default (network-free)
test run. These tests check the structural wiring instead: the scheduled
workflow exists and carries no push/pull_request trigger, the per-PR step is
present, and every pin file agrees on ``duckdb``'s version.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_workflow(name: str) -> dict:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _triggers(workflow: dict) -> dict:
    # YAML parses a bare `on:` key as boolean True; PyYAML represents it either
    # way depending on quoting, so check whichever key resolves.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    return triggers


def test_dependency_audit_workflow_runs_on_a_schedule_only() -> None:
    triggers = _triggers(_load_workflow("dependency-audit.yml"))
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers


def test_dependency_audit_workflow_reads_the_committed_lock_file() -> None:
    text = (ROOT / ".github" / "workflows" / "dependency-audit.yml").read_text(encoding="utf-8")
    assert "pip-audit -r requirements.lock" in text


def test_dependency_audit_workflow_is_read_only() -> None:
    workflow = _load_workflow("dependency-audit.yml")
    assert workflow["permissions"] == {"contents": "read"}


def test_validate_pr_workflow_runs_the_same_audit_per_pull_request() -> None:
    text = (ROOT / ".github" / "workflows" / "validate-pr.yml").read_text(encoding="utf-8")
    assert "pip-audit -r requirements.lock" in text
    assert "pip-audit-report" in text


def test_pip_audit_version_matches_between_dev_requirements_and_ci_install() -> None:
    dev_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    match = re.search(r"^pip-audit==([\w.]+)$", dev_requirements, re.MULTILINE)
    assert match, "expected a pinned pip-audit== line in requirements-dev.txt"
    dev_version = match.group(1)

    ci_text = (ROOT / ".github" / "workflows" / "validate-pr.yml").read_text(encoding="utf-8")
    assert f"pip-audit=={dev_version}" in ci_text

    weekly_text = (ROOT / ".github" / "workflows" / "dependency-audit.yml").read_text(
        encoding="utf-8"
    )
    assert f"pip-audit=={dev_version}" in weekly_text


def test_duckdb_pin_is_identical_across_every_pin_file() -> None:
    def duckdb_version(text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.MULTILINE)
        assert match, f"expected to find a duckdb pin matching {pattern!r}"
        return match.group(1)

    requirements_txt = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    requirements_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    versions = {
        duckdb_version(requirements_txt, r"^duckdb==([\w.]+)$"),
        duckdb_version(requirements_lock, r"^duckdb==([\w.]+)$"),
        duckdb_version(pyproject, r'"duckdb==([\w.]+)"'),
    }
    assert len(versions) == 1, f"duckdb pin disagrees across files: {versions}"
