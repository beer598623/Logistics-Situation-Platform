"""WO-015: cross-workflow action-pin and trigger-safety consistency.

Nothing here was previously machine-checked -- the six workflow files
happened to agree on shared-action versions by discipline, not by an
enforced test, and a partial Dependabot merge nearly reintroduced exactly
the version split this test now catches (see Issue #28 / #2). Likewise,
``manual-live-source-test.yml`` already has a test asserting it carries no
``schedule``/``push``/``pull_request`` trigger; ``collect.yml`` carries the
same documented guarantee (``docs/operations_runbook.md`` §3) but had no
equivalent test.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

_USES_PATTERN = re.compile(
    r"^\s*uses:\s*['\"]?(?P<action>[\w./-]+)@(?P<version>[\w.-]+)['\"]?\s*(#.*)?$"
)


def _iter_workflow_files() -> list[Path]:
    # GitHub Actions honours both .yml and .yaml workflow files.
    paths = sorted(set(WORKFLOWS_DIR.glob("*.yml")) | set(WORKFLOWS_DIR.glob("*.yaml")))
    assert paths, f"expected at least one workflow file under {WORKFLOWS_DIR}"
    return paths


def _load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # YAML parses a bare `on:` key as boolean True; PyYAML represents it either
    # way depending on quoting, so check whichever key resolves.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    return triggers


def test_every_shared_action_pins_the_same_version_across_workflows() -> None:
    """A regex scan, not a YAML-structure walk: `uses:` can appear at any step
    nesting depth, and a version string is what we actually care about, not
    which job/step it's attached to."""
    versions_by_action: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for path in _iter_workflow_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _USES_PATTERN.match(line)
            if not match:
                continue
            action = match.group("action")
            version = match.group("version")
            versions_by_action[action][version].append(path.name)

    inconsistent = {
        action: dict(by_version)
        for action, by_version in versions_by_action.items()
        if len(by_version) > 1
    }
    assert not inconsistent, (
        "these actions are pinned to more than one version across workflow files "
        f"(action -> {{version: [files]}}): {inconsistent}"
    )


def test_every_shared_action_actually_appears_more_than_once() -> None:
    """Guards the previous test against becoming vacuous: if every action only
    ever appears in one workflow file, the consistency check above would pass
    trivially without ever comparing anything."""
    occurrences: dict[str, int] = defaultdict(int)
    for path in _iter_workflow_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _USES_PATTERN.match(line)
            if match:
                occurrences[match.group("action")] += 1

    shared = {action: count for action, count in occurrences.items() if count > 1}
    assert shared, "expected at least one action reused across multiple workflow steps"
    assert shared.get("actions/checkout", 0) > 1
    assert shared.get("actions/setup-python", 0) > 1
    assert shared.get("actions/upload-artifact", 0) > 1


def test_collect_workflow_has_no_schedule_or_push_trigger() -> None:
    triggers = _triggers(_load_workflow(WORKFLOWS_DIR / "collect.yml"))
    assert set(triggers) == {"workflow_dispatch"}
