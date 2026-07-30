"""WO-012: OSS hygiene files exist and stay internally consistent.

These are documentation/repo-metadata files with no runtime behavior, so the
tests only check for presence, non-emptiness, and the few cross-references
that are cheap to keep honest (the CHANGELOG's latest version against
pyproject.toml, and that the security contact path actually needs no
credential this repository doesn't have).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    path = ROOT / relative_path
    assert path.is_file(), f"expected {relative_path} to exist"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"expected {relative_path} to be non-empty"
    return text


def test_root_governance_files_exist_and_are_non_empty() -> None:
    for relative_path in ("SECURITY.md", "CONTRIBUTING.md", "CODEOWNERS", "CHANGELOG.md"):
        _read(relative_path)


def test_github_templates_exist_and_are_non_empty() -> None:
    _read(".github/PULL_REQUEST_TEMPLATE.md")
    _read(".github/ISSUE_TEMPLATE/work_order.md")
    _read(".github/ISSUE_TEMPLATE/config.yml")


def test_security_policy_uses_a_credential_free_disclosure_channel() -> None:
    text = _read("SECURITY.md")
    assert "security/advisories/new" in text
    assert "No credential exists in this repository" in text


def test_security_policy_names_the_actual_live_network_surfaces() -> None:
    text = _read("SECURITY.md")
    assert "collectors/http_client.py" in text
    assert "manual-live-source-test.yml" in text


def test_contributing_documents_the_work_order_process() -> None:
    text = _read("CONTRIBUTING.md")
    assert "one GitHub Issue" in text or "one Issue" in text
    assert "AGENTS.md" in text
    assert "config/sources.yaml" in text


def test_changelog_latest_dated_version_matches_pyproject() -> None:
    changelog = _read("CHANGELOG.md")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]

    assert "## [Unreleased]" in changelog
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    assert match, "expected at least one dated version header in CHANGELOG.md"
    assert match.group(1) == project_version, (
        f"CHANGELOG's latest dated version ({match.group(1)}) does not match "
        f"pyproject.toml's version ({project_version})"
    )
