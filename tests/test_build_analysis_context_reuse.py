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

import collectors.collection_runs as collection_runs_module  # noqa: E402
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
    monkeypatch.setattr(
        collection_runs_module, "COLLECTION_RUNS_DIR", temp_root / "data" / "collection_runs"
    )
    monkeypatch.setattr(
        collection_runs_module,
        "MANUAL_REVIEW_EVENTS_DIR",
        temp_root / "data" / "collection_runs" / "manual",
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

    # WO-010-R6 §7: generation_time_basis legitimately differs -- the first
    # build observed a fresh instant, the second reused it -- while
    # generated_at itself, the property under test, stays byte-identical.
    assert {k: v for k, v in first.items() if k != "generation_time_basis"} == {
        k: v for k, v in second.items() if k != "generation_time_basis"
    }
    assert second["generated_at"] == first["generated_at"]
    assert first["generation_time_basis"] == "observed_build_time"
    assert second["generation_time_basis"] == "persisted_rebuild_time"


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


# ---------------------------------------------------------------------------
# WO-010-R6 §7: legacy generated_at migration
# ---------------------------------------------------------------------------


def test_a_pre_r6_context_with_no_generation_time_basis_is_migrated_once(monkeypatch, temp_repo):
    """A committed context predating WO-010-R6 (no generation_time_basis at
    all, generated_at produced under the old generated_at = as_of_time
    rule) is migrated exactly once: a truthful wall-clock instant is
    observed now, tagged 'legacy_migrated', and reused verbatim on every
    subsequent identical rebuild."""
    _patch(monkeypatch, temp_repo)
    context_path = temp_repo / "data" / "build_context" / "current.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_context = {
        "build_context_id": "BCTX-CURRENT_PUBLICATION-20260715T000000Z",
        "dataset": "current_publication",
        "as_of_time": "2026-07-15T00:00:00Z",
        "source_cutoff": None,
        # The legacy bug this migration corrects: generated_at was copied
        # from as_of_time rather than truthfully observed.
        "generated_at": "2026-07-15T00:00:00Z",
        "latest_included_collection_run_at": None,
        "latest_included_manual_review_at": None,
        "methodology_version": "0.8",
        "input_hashes": {},
        # No generation_time_basis key at all -- the migration trigger.
    }
    context_path.write_text(json.dumps(legacy_context, indent=2), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    migrated = json.loads(context_path.read_text(encoding="utf-8"))

    assert migrated["build_context_id"] == legacy_context["build_context_id"]
    assert migrated["generation_time_basis"] == "legacy_migrated"
    # A truthful migration timestamp was observed now -- not silently kept
    # equal to the legacy (incorrect) as_of_time-derived value.
    assert migrated["generated_at"] != legacy_context["generated_at"]

    # A second, identical rebuild reuses the newly persisted truthful
    # timestamp -- the migration is a one-time event, not repeated forever.
    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    rebuilt = json.loads(context_path.read_text(encoding="utf-8"))
    assert rebuilt["generated_at"] == migrated["generated_at"]
    assert rebuilt["generation_time_basis"] == "persisted_rebuild_time"


# ---------------------------------------------------------------------------
# WO-010-R6 §5: collection-run/manual-review files are hashed build inputs
# ---------------------------------------------------------------------------


def test_a_changed_collection_run_file_changes_the_build_context_input_hash(monkeypatch, temp_repo):
    _patch(monkeypatch, temp_repo)
    context_path = temp_repo / "data" / "build_context" / "current.json"

    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-15T00:00:00Z"])
    assert build_analysis.main() == 0
    first = json.loads(context_path.read_text(encoding="utf-8"))

    collection_runs_dir = temp_repo / "data" / "collection_runs"
    collection_runs_dir.mkdir(parents=True, exist_ok=True)
    (collection_runs_dir / "SOME_SOURCE.json").write_text(
        json.dumps({"version": "0.8", "source_id": "SOME_SOURCE", "runs": []}), encoding="utf-8"
    )

    # A new --as-of, matching the intended workflow: new acquisition data
    # arriving is a reason to advance the build, not to silently rewrite an
    # already-committed context_id's inputs out from under it (that specific
    # regression -- the same context_id describing two different acquisition
    # states -- is refused by analysis.build_context.context_problems).
    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", "2026-07-20T00:00:00Z"])
    assert build_analysis.main() == 0
    second = json.loads(context_path.read_text(encoding="utf-8"))

    assert (
        second["input_hashes"]["collection_run_manifests"]
        != first["input_hashes"]["collection_run_manifests"]
    )
    # Nothing else about the build inputs moved.
    assert (
        second["input_hashes"]["manual_review_events"]
        == first["input_hashes"]["manual_review_events"]
    )
