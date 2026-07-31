"""Reproducibility of every generated artefact, and the no-network default.

Three generators (``ingest_fixtures``, ``build_events_from_cases``,
``build_analysis``) have a ``--check`` mode that regenerates in memory and
compares against what is committed; exercised directly below. If any of these
fail, the committed data no longer matches the inputs it claims to be derived
from. ``generate_synthetic_fixtures`` has no ``--check`` mode -- its
reproducibility is instead verified by
``test_regenerating_the_fixtures_is_a_no_op``, which byte-compares its output
before and after a fresh run. ``build_dashboard`` and ``build_warehouse`` are
not exercised by this file at all; ``build_dashboard``'s reproducibility is
enforced by CI's build-then-``git status --porcelain`` step (see
``docs/operations_runbook.md`` §1), and ``build_warehouse`` is not a generated
artefact this repository commits (its output is gitignored).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ground truth for which generators genuinely have a --check mode, kept in
# sync with the real code by test_check_flag_support_matches_what_the_docs_claim
# below (WO-025). Every doc that claims "every generator has --check" must
# name exactly these three.
CHECK_MODE_SCRIPTS = {"ingest_fixtures.py", "build_events_from_cases.py", "build_analysis.py"}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_regenerating_the_fixtures_is_a_no_op():
    """A reviewer must be able to confirm no fixture was hand-tuned."""
    before = {
        path: path.read_bytes()
        for path in sorted((ROOT / "tests/fixtures/csv_series").glob("*.csv"))
    }
    assert before, "fixture set must not be empty"
    result = run("scripts/generate_synthetic_fixtures.py")
    assert result.returncode == 0, result.stderr
    after = {path: path.read_bytes() for path in before}
    assert after == before


def test_observation_records_match_the_fixtures():
    result = run("scripts/ingest_fixtures.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_event_records_match_the_authored_cases():
    result = run("scripts/build_events_from_cases.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_derived_analysis_records_are_up_to_date():
    result = run("scripts/build_analysis.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def _scripts_declaring_a_check_argument() -> set[str]:
    """AST-parse scripts/*.py for a real ``add_argument("--check")`` call.

    Ground truth for what "has a --check mode" means, so documentation claims
    about it are bound to the real code rather than merely asserted (WO-025).
    """
    declaring: set[str] = set()
    for path in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "add_argument":
                continue
            if any(isinstance(arg, ast.Constant) and arg.value == "--check" for arg in node.args):
                declaring.add(path.name)
    return declaring


def test_check_flag_support_matches_what_the_docs_claim():
    """Regression guard for WO-025: exactly these three scripts have --check.

    docs/operations_runbook.md, docs/bundle1_architecture.md and
    docs/data_model_and_persistence.md all once claimed every generator has a
    --check mode; only three genuinely do. If a future change adds or removes
    --check support from any script in scripts/, this must fail until
    CHECK_MODE_SCRIPTS and the prose in those three docs are updated to match.
    """
    assert _scripts_declaring_a_check_argument() == CHECK_MODE_SCRIPTS


@pytest.mark.parametrize("script", ["build_dashboard.py", "generate_synthetic_fixtures.py"])
def test_generators_without_a_check_mode_reject_an_unrecognized_flag(script):
    """WO-025: these two scripts have no --check mode. Before this Work Order,
    both silently ignored an unrecognized flag and wrote files anyway (exit 0),
    so a maintainer following the "verify without writing" instruction got a
    false-clean result while the working tree was mutated. They must now fail
    fast instead.
    """
    result = run(f"scripts/{script}", "--check")
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


def test_validation_passes():
    result = run("scripts/validate.py")
    assert result.returncode == 0, result.stdout[-4000:]
    assert "Validation successful." in result.stdout


def test_collect_dry_run_reports_every_contract_without_network():
    result = run("scripts/collect.py", "--dry-run")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    # 17 registered sources, none enabled: a dry run enumerates every contract
    # without touching the network. R1 added PAT_STATISTICS and FBX_PUBLIC.
    assert payload["contracts"] == 17
    assert all(run_manifest["status"] == "dry_run" for run_manifest in payload["runs"])


def test_historical_validation_passes():
    result = run("scripts/run_historical_validation.py")
    assert result.returncode == 0, result.stdout[-4000:]
    assert "All historical validation expectations met." in result.stdout


# ---------------------------------------------------------------------------
# Fixture labelling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    ["indicator_observations", "trade_observations", "port_observations", "cost_observations"],
)
def test_every_fixture_derived_observation_is_labelled_synthetic(family):
    """Synthetic values must be unmistakable wherever they surface."""
    payload = json.loads((ROOT / f"data/observations/{family}.json").read_text(encoding="utf-8"))
    assert payload["records"]
    for record in payload["records"]:
        assert record["provenance"]["evidence_class"] == "synthetic_test_fixture"
        assert any(
            "synthetic test fixture" in limitation
            for limitation in record["provenance"]["known_limitations"]
        )


def test_historical_evidence_records_that_it_was_not_retrieved():
    evidence = json.loads((ROOT / "data/events/event_evidence.json").read_text(encoding="utf-8"))[
        "evidence"
    ]
    for item in evidence:
        assert item["raw_snapshot_path"] is None
        assert any("NOT retrieved under WO-010" in note for note in item["known_limitations"])


def test_no_source_is_enabled_and_every_candidate_records_its_blockers():
    import yaml

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    for source in registry["sources"]:
        assert source["enabled"] is False, source["id"]
        if source["id"] in {"TMD_CAP", "GDACS"}:
            continue
        assert source["enablement"]["blockers"], source["id"]


def test_tmd_and_gdacs_remain_disabled_and_unqualified_by_this_bundle():
    """WO-010 must not enable or modify either source's governance record."""
    import yaml

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    by_id = {source["id"]: source for source in registry["sources"]}
    for source_id in ("TMD_CAP", "GDACS"):
        assert by_id[source_id]["enabled"] is False
        assert "qualification" not in by_id[source_id]
        assert "enablement" not in by_id[source_id]


def test_no_paid_source_is_registered_or_required():
    import yaml

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    for source in registry["sources"]:
        qualification = source.get("qualification")
        if qualification:
            assert qualification["access_cost"] != "paid", source["id"]


# ---------------------------------------------------------------------------
# No network in the default path
# ---------------------------------------------------------------------------


def test_importing_every_adapter_opens_no_socket():
    """Import each module in a fresh interpreter with sockets disabled.

    A subprocess is used rather than ``importlib.reload`` so that this check
    cannot leave rebound module objects behind for other tests to trip over.
    """
    modules = [
        "collectors.adapters.csv_series",
        "collectors.adapters.notice_feed",
        "collectors.series_catalog",
        "analysis.indicators",
        "analysis.events",
        "analysis.assessments",
        "analysis.scenarios",
        "analysis.review_package",
        "analysis.reference",
        "analysis.warehouse",
    ]
    program = (
        "import socket, sys\n"
        "def forbidden(*a, **k):\n"
        "    raise SystemExit('network access attempted at import time')\n"
        "socket.socket.connect = forbidden\n"
        "socket.create_connection = forbidden\n"
        "import importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "print('ok')\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_the_full_build_chain_makes_no_network_request(monkeypatch, tmp_path):
    """validate, ingest and analysis must all run with sockets disabled."""
    import socket

    def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the build chain attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    from scripts import build_analysis, ingest_fixtures

    assert ingest_fixtures.collect()
    registry_free = build_analysis.load_observations()
    assert sum(len(records) for records in registry_free.values()) == 930
