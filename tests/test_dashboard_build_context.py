"""The Dashboard reads the shared Build Context, not its own pinned time
(WO-010-R4 §6)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_dashboard as build_dashboard  # noqa: E402


@pytest.fixture
def temp_repo(tmp_path):
    temp_root = tmp_path / "repo"
    shutil.copytree(ROOT / "data", temp_root / "data")
    shutil.copytree(ROOT / "innovation", temp_root / "innovation")
    (temp_root / "config").mkdir()
    shutil.copy(ROOT / "config" / "sources.yaml", temp_root / "config" / "sources.yaml")
    return temp_root


def test_missing_build_context_fails_closed(tmp_path, monkeypatch, temp_repo):
    (temp_repo / "data" / "build_context" / "current.json").unlink()
    monkeypatch.setattr(build_dashboard, "ROOT", temp_repo)
    with pytest.raises(SystemExit, match="No Build Context found"):
        build_dashboard.build_payloads()


def test_the_dashboard_reflects_a_custom_context_as_of_time(monkeypatch, temp_repo):
    context_path = temp_repo / "data" / "build_context" / "current.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["as_of_time"] = "2026-09-01T00:00:00Z"
    context["generated_at"] = "2026-09-01T00:00:00Z"
    context_path.write_text(json.dumps(context, indent=2), encoding="utf-8")

    monkeypatch.setattr(build_dashboard, "ROOT", temp_repo)
    payloads = build_dashboard.build_payloads()
    assert payloads["thailand_situation.json"]["generated_at"] == "2026-09-01T00:00:00Z"
    assert payloads["build_status.json"]["built_at"] == "2026-09-01T00:00:00Z"
