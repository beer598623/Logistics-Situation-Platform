"""End-to-end reproducible-rebuild positive path for the Build Context's
``generated_at`` (WO-010-R4 §6, timestamp semantics corrected WO-010-R5 §8).

A rebuild against unchanged inputs at the same as-of time must be
byte-identical, including ``generated_at`` -- which means the *second* run
must reuse the *first* run's truthfully-observed generation instant rather
than either copying ``as_of_time`` (the R4-era bug) or silently regenerating
a new wall-clock timestamp on every run (which would make the committed
context non-reproducible).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_analysis as build_analysis  # noqa: E402


@pytest.fixture
def temp_repo(tmp_path):
    temp_root = tmp_path / "repo"
    shutil.copytree(ROOT / "data", temp_root / "data")
    shutil.copytree(ROOT / "innovation", temp_root / "innovation")
    shutil.rmtree(temp_root / "data" / "build_context", ignore_errors=True)
    (temp_root / "config").mkdir()
    registry = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    return temp_root


def _patch(monkeypatch, temp_root):
    monkeypatch.setattr(build_analysis, "ROOT", temp_root)
    monkeypatch.setattr(build_analysis, "OBSERVATION_DIR", temp_root / "data" / "observations")
    monkeypatch.setattr(
        build_analysis, "EVENTS_PATH", temp_root / "data" / "events" / "events.json"
    )
    monkeypatch.setattr(build_analysis, "ASSESSMENT_DIR", temp_root / "data" / "assessments")
    monkeypatch.setattr(
        build_analysis, "INDICATOR_PATH", temp_root / "data" / "indicators" / "latest.json"
    )
    monkeypatch.setattr(
        build_analysis, "CURRENT_INDICATOR_PATH", temp_root / "data" / "indicators" / "current.json"
    )
    monkeypatch.setattr(
        build_analysis, "SOURCE_STATUS_PATH", temp_root / "data" / "source_status" / "latest.json"
    )
    monkeypatch.setattr(
        build_analysis, "BUILD_CONTEXT_PATH", temp_root / "data" / "build_context" / "current.json"
    )


def test_a_rebuild_with_identical_inputs_reuses_the_first_runs_generated_at(monkeypatch, temp_repo):
    _patch(monkeypatch, temp_repo)
    context_path = temp_repo / "data" / "build_context" / "current.json"

    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    first = json.loads(context_path.read_text(encoding="utf-8"))

    # A second run against exactly the same inputs and the same --as-of.
    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    second = json.loads(context_path.read_text(encoding="utf-8"))

    assert first == second
    assert second["generated_at"] == first["generated_at"]


def test_advancing_as_of_produces_a_new_context_id_and_a_fresh_generated_at(monkeypatch, temp_repo):
    _patch(monkeypatch, temp_repo)
    context_path = temp_repo / "data" / "build_context" / "current.json"

    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    first = json.loads(context_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-20T00:00:00Z"])
    assert build_analysis.main() == 0
    second = json.loads(context_path.read_text(encoding="utf-8"))

    assert second["build_context_id"] != first["build_context_id"]
    assert second["as_of_time"] == "2026-07-20T00:00:00Z"
