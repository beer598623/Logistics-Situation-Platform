"""Reproducibility of every generated artefact, and the no-network default.

Each generator has a ``--check`` mode that regenerates in memory and compares
against what is committed. If any of these fail, the committed data no longer
matches the inputs it claims to be derived from.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


def test_validation_passes():
    result = run("scripts/validate.py")
    assert result.returncode == 0, result.stdout[-4000:]
    assert "Validation successful." in result.stdout


def test_collect_dry_run_reports_every_contract_without_network():
    result = run("scripts/collect.py", "--dry-run")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["contracts"] == 15
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
