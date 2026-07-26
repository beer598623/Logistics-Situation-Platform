"""End-to-end Source Health positive path, from real collection-run
manifests through the production build path to the Dashboard
(WO-010-R4 §8).

Every prior positive-path test either called individual functions directly
or fabricated a Source Health snapshot by hand. Neither proves that a real
collection-run manifest, read from disk by ``collectors.collection_runs``,
actually flows through ``collectors.source_health.evaluate_registry_health``,
``scripts/build_analysis.py``'s production ``main()``, and
``scripts/build_dashboard.py`` and comes out the other end agreeing with
itself -- Source Health, capability coverage, the situation banner's own
counts and the published current series must all describe the same thing.
This test builds a full temporary copy of the committed repository, injects
a real source contract, a schema-valid successful collection-run manifest
and qualifying observations, and runs the *actual* production scripts
against it. Nothing here fabricates a Source Health snapshot directly.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import collectors.collection_runs as collection_runs_module  # noqa: E402
import scripts.build_analysis as build_analysis  # noqa: E402
import scripts.build_dashboard as build_dashboard  # noqa: E402
from tests.positive_path import live_trade_series, manual_notice_evidence  # noqa: E402

E2E_SOURCE = "TEST_E2E_TRADE_SOURCE"
AS_OF = "2026-07-24T00:00:00Z"
AS_OF_DT = datetime(2026, 7, 24, tzinfo=UTC)


def _e2e_source(**overrides):
    source = {
        "id": E2E_SOURCE,
        "name": "E2E test trade publisher",
        "owner": "Test",
        "source_class": "official",
        "access_method": "download",
        "format": "csv",
        "machine_readable_status": "verified",
        "licence_status": "reviewed",
        "endpoint": "https://example.org/e2e.csv",
        "landing_url": "https://example.org/e2e",
        "enabled": True,
        "required_for_publication": False,
        "max_stale_minutes": 105120,
        "expected_cadence_minutes": 44640,
        "purposes": ["thailand_trade_indicator"],
        "known_limitations": ["Test source."],
        "qualification": {
            "access_cost": "free",
            "paywall_status": "none",
            "reuse_status": "permitted_with_attribution",
            "redistribution_status": "permitted",
            "publication_use": "raw_values_permitted",
            "publication_cadence": "monthly",
            "observed_freshness": "2026-07-20",
            "logistics_role": ["thailand_trade_flow"],
            "prototype_eligibility": "eligible",
            "rate_limit": "60 requests per hour",
        },
        "enablement": {"blockers": [], "schedule_justified": True},
    }
    source.update(overrides)
    return source


def _e2e_registry(**source_overrides):
    return {
        "version": "0.8",
        "policy": "free_sources_only",
        "last_reviewed_at": "2026-07-24",
        "sources": [_e2e_source(**source_overrides)],
    }


def _run(*, completed_at: str, status: str = "success", records_emitted=26, run_suffix="001"):
    stamp = completed_at.replace("-", "").replace(":", "").replace("Z", "Z")
    return {
        "run_id": f"COL-{stamp[:8]}T{stamp[9:15]}Z-{E2E_SOURCE}",
        "source_id": E2E_SOURCE,
        "started_at": completed_at,
        "completed_at": completed_at,
        "status": status,
        "workflow_sha": "a" * 40,
        # Matches live_trade_observation's own default parser_version
        # (tests/positive_path.py), so WO-010-R5 §1's acquisition-binding
        # check does not reject an otherwise-correctly-bound record over an
        # incidental version-string mismatch between two independent fixtures.
        "adapter_version": "test_v1",
        "request_url": "https://example.org/e2e.csv",
        "response_url": "https://example.org/e2e.csv",
        "content_type": "text/csv",
        "http_status": 200 if status in {"success", "not_modified"} else 502,
        "etag": None,
        "last_modified": None,
        "content_sha256": "b" * 64,
        "records_received": records_emitted,
        "records_emitted": records_emitted if status in {"success", "not_modified"} else None,
        "records_rejected": 0,
        "data_cutoff_at": completed_at,
        "warnings": [],
        "errors": [] if status in {"success", "not_modified"} else ["simulated adapter failure"],
    }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _copy_repo(tmp_path) -> Path:
    temp_root = tmp_path / "repo"
    shutil.copytree(ROOT / "data", temp_root / "data")
    shutil.copytree(ROOT / "innovation", temp_root / "innovation")
    (temp_root / "config").mkdir()
    # WO-010-R5 §8: each of these tests builds a fresh repository injecting
    # its own data at the committed default as-of time; without removing the
    # real committed Build Context copied above, that would collide with the
    # new "reused build_context_id with changed input_hashes" check -- these
    # tests are simulating a first build, not a rebuild of the real one.
    shutil.rmtree(temp_root / "data" / "build_context", ignore_errors=True)
    return temp_root


def _patch_build_scripts(monkeypatch, temp_root: Path, *, registry: dict) -> None:
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
    monkeypatch.setattr(build_analysis, "load_registry", lambda: registry)
    monkeypatch.setattr(
        collection_runs_module, "COLLECTION_RUNS_DIR", temp_root / "data" / "collection_runs"
    )
    monkeypatch.setattr(
        collection_runs_module,
        "MANUAL_REVIEW_EVENTS_DIR",
        temp_root / "data" / "collection_runs" / "manual",
    )
    monkeypatch.setattr(build_dashboard, "ROOT", temp_root)


def _run_build_analysis(monkeypatch, *, as_of: str = AS_OF) -> int:
    monkeypatch.setattr(sys, "argv", ["build_analysis.py", "--as-of", as_of])
    return build_analysis.main()


# ---------------------------------------------------------------------------
# §8 The principal end-to-end positive path
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_repo(tmp_path, monkeypatch):
    """A temporary repository with one qualifying source: an enabled
    contract, a schema-valid successful collection-run manifest dated at the
    as-of time, and 26 months of qualifying trade observations."""
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")

    run = _run(completed_at="2026-07-20T00:00:00Z")

    trade_path = temp_root / "data" / "observations" / "trade_observations.json"
    trade_payload = json.loads(trade_path.read_text(encoding="utf-8"))
    trade_payload["records"] = trade_payload["records"] + live_trade_series(
        periods=26,
        growth=0.02,
        series_id="th_export_value_neur",
        source_id=E2E_SOURCE,
        collection_run_id=run["run_id"],
    )
    _write_json(trade_path, trade_payload)

    _write_json(
        temp_root / "data" / "collection_runs" / f"{E2E_SOURCE}.json",
        {"version": "0.8", "source_id": E2E_SOURCE, "runs": [run]},
    )

    _patch_build_scripts(monkeypatch, temp_root, registry=registry)
    return temp_root


def test_the_production_build_reports_the_source_fresh(e2e_repo, monkeypatch):
    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (e2e_repo / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "fresh"
    assert source_status["overall_status"] == "sufficient"


def test_capability_coverage_agrees_with_source_health(e2e_repo, monkeypatch):
    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (e2e_repo / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    coverage = {item["capability"]: item for item in source_status["capabilities"]}
    assert coverage["thailand_trade_indicator"]["status"] == "sufficient"
    assert E2E_SOURCE in coverage["thailand_trade_indicator"]["supporting_sources"]


def test_the_situation_banner_counts_agree_with_what_was_built(e2e_repo, monkeypatch):
    assert _run_build_analysis(monkeypatch) == 0
    thailand = json.loads(
        (e2e_repo / "data" / "assessments" / "thailand_assessment.json").read_text(encoding="utf-8")
    )
    assert thailand["qualified_observation_count"] == 26
    assert thailand["evidence_coverage"] == "sufficient"

    payloads = build_dashboard.build_payloads()
    situation = payloads["thailand_situation.json"]
    assert situation["qualified_observation_count"] == thailand["qualified_observation_count"]
    assert "SUFFICIENT" in situation["live_coverage_statement"]
    assert "INSUFFICIENT" not in situation["live_coverage_statement"]


def test_the_published_series_agrees_with_source_health(e2e_repo, monkeypatch):
    """The Dashboard's own current trade series -- not a fabricated
    snapshot -- must show the value this same collection run produced."""
    assert _run_build_analysis(monkeypatch) == 0
    payloads = build_dashboard.build_payloads()
    trade = payloads["trade.json"]
    assert trade["current_lane_flows"] != []
    flow = trade["current_lane_flows"][0]["flows"][0]
    assert flow["source_id"] == E2E_SOURCE
    assert flow["current_value"] is not None
    assert flow["freshness"]["status"] == "fresh"

    build_status = payloads["build_status.json"]
    assert build_status["qualified_evidence"] is True
    assert build_status["live_coverage"] == "sufficient"


# ---------------------------------------------------------------------------
# §8 Additional Source Health edge cases
# ---------------------------------------------------------------------------


def test_a_successful_run_with_no_qualifying_observations_reports_no_data(tmp_path, monkeypatch):
    """The run succeeded, but nothing in the observation files actually
    qualifies (e.g. wrong dataset) -- Source Health must not read
    'a run happened' as 'evidence exists'."""
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    run = _run(completed_at="2026-07-20T00:00:00Z")
    _write_json(
        temp_root / "data" / "collection_runs" / f"{E2E_SOURCE}.json",
        {"version": "0.8", "source_id": E2E_SOURCE, "runs": [run]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "fresh"
    thailand = json.loads(
        (temp_root / "data" / "assessments" / "thailand_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    assert thailand["qualified_observation_count"] == 0


def test_a_qualifying_observation_with_no_run_manifest_is_not_silently_fresh(tmp_path, monkeypatch):
    """Qualifying data exists, but no collection-run manifest was ever
    written for its source -- WO-010-R4 §7/§8: a qualified observation
    cannot make Source Health fresh without its own recorded run.

    WO-010-R5 §1 goes further: the record itself is now excluded from
    current publication, not merely disconnected from a fresh Source Health
    reading. Before R5, this test asserted the opposite -- that the
    observation "still qualifies and is still counted" because "Source
    Health and the qualification filter are independent questions". That
    statement is superseded: a live_retrieved record with no matching
    persisted collection run does not qualify, full stop, because there is
    nothing that actually establishes the record was ever acquired.
    """
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    trade_path = temp_root / "data" / "observations" / "trade_observations.json"
    trade_payload = json.loads(trade_path.read_text(encoding="utf-8"))
    trade_payload["records"] = trade_payload["records"] + live_trade_series(
        periods=26,
        growth=0.02,
        series_id="th_export_value_neur",
        source_id=E2E_SOURCE,
        collection_run_id="COL-20260720T000000Z-TEST_E2E_TRADE_SOURCE",
    )
    _write_json(trade_path, trade_payload)
    # Deliberately no collection-run manifest written -- the collection_run_id
    # above names a run that will never resolve.
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "no_data"
    thailand = json.loads(
        (temp_root / "data" / "assessments" / "thailand_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    assert thailand["qualified_observation_count"] == 0


def test_a_latest_run_error_retains_the_earlier_success(tmp_path, monkeypatch):
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    success = _run(completed_at="2026-07-10T00:00:00Z")
    error = _run(completed_at="2026-07-23T00:00:00Z", status="error", records_emitted=None)
    _write_json(
        temp_root / "data" / "collection_runs" / f"{E2E_SOURCE}.json",
        {"version": "0.8", "source_id": E2E_SOURCE, "runs": [success, error]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "error"
    assert health["last_success_at"] == "2026-07-10T00:00:00Z"
    assert health["last_error"] == "simulated adapter failure"


def test_a_stale_run_reports_stale(tmp_path, monkeypatch):
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    # expected_cadence_minutes is 44640 (31 days); 60 days ago is well past
    # cadence but still inside max_stale_minutes (105120 minutes, ~73 days).
    run = _run(completed_at="2026-05-25T00:00:00Z")
    _write_json(
        temp_root / "data" / "collection_runs" / f"{E2E_SOURCE}.json",
        {"version": "0.8", "source_id": E2E_SOURCE, "runs": [run]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "stale"


def test_a_future_dated_run_relative_to_the_build_context_is_not_fresh(tmp_path, monkeypatch):
    temp_root = _copy_repo(tmp_path)
    registry = _e2e_registry()
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    future_run = _run(completed_at="2026-08-15T00:00:00Z")
    _write_json(
        temp_root / "data" / "collection_runs" / f"{E2E_SOURCE}.json",
        {"version": "0.8", "source_id": E2E_SOURCE, "runs": [future_run]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    # as-of is 2026-07-24, strictly before the run's completed_at.
    assert _run_build_analysis(monkeypatch, as_of=AS_OF) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[E2E_SOURCE]
    assert health["status"] == "no_data"
    assert health["last_success_at"] is None


# ---------------------------------------------------------------------------
# §8 Manual-review event edge cases
# ---------------------------------------------------------------------------


def _manual_source():
    return {
        "id": "TEST_E2E_MANUAL_SOURCE",
        "name": "E2E manual intake",
        "owner": "Test",
        "source_class": "manual_human_review",
        "access_method": "manual",
        "format": "manual",
        "machine_readable_status": "not_applicable",
        "licence_status": "reviewed",
        "endpoint": None,
        "enabled": False,
        "required_for_publication": False,
        "max_stale_minutes": 20160,
        "expected_cadence_minutes": None,
        "purposes": ["official_operational_notice"],
        "known_limitations": ["Bounded claim and link only."],
        "qualification": {
            "access_cost": "free",
            "paywall_status": "none",
            "reuse_status": "permitted_with_attribution",
            "redistribution_status": "link_only",
            "publication_use": "bounded_claim_and_link_only",
            "manual_intake_status": "allowed",
            "underlying_publisher_required": True,
            "publication_cadence": "irregular",
            "observed_freshness": "2026-07-20",
            "logistics_role": ["official_operational_notice"],
            "prototype_eligibility": "eligible",
            "rate_limit": None,
        },
        "enablement": {"blockers": [], "schedule_justified": False},
    }


def _manual_event(**overrides):
    event = {
        "event_id": "MAN-20260720T000000Z-TEST_E2E_MANUAL_SOURCE",
        "source_id": "TEST_E2E_MANUAL_SOURCE",
        "reviewed_at": "2026-07-20T00:00:00Z",
        "reviewer_record": "A. Reviewer",
        "status": "reviewed",
        "record_count": 1,
        "related_record_ids": ["EVD-E2E-1"],
        "data_cutoff_at": "2026-07-20T00:00:00Z",
        "bounded_content_confirmed": True,
        "underlying_publisher": "Example Port Authority",
        "content_sha256": None,
        "known_limitations": [],
    }
    event.update(overrides)
    return event


def _manual_evidence_record(**overrides):
    return manual_notice_evidence(
        evidence_id="EVD-E2E-1",
        event_id="EVT-20260720-900",
        source_id="TEST_E2E_MANUAL_SOURCE",
        manual_review_event_id="MAN-20260720T000000Z-TEST_E2E_MANUAL_SOURCE",
        **overrides,
    )


def test_a_valid_manual_review_event_makes_the_source_fresh(tmp_path, monkeypatch):
    temp_root = _copy_repo(tmp_path)
    registry = {
        "version": "0.8",
        "policy": "free_sources_only",
        "last_reviewed_at": "2026-07-24",
        "sources": [_manual_source()],
    }
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    _write_json(
        temp_root / "data" / "collection_runs" / "manual" / "TEST_E2E_MANUAL_SOURCE.json",
        {"version": "0.8", "source_id": "TEST_E2E_MANUAL_SOURCE", "events": [_manual_event()]},
    )
    # WO-010-R5 §1: a manual review event now needs a real, matching,
    # non-fixture, same-source evidence record actually listed in its own
    # related_record_ids -- both for the event to load at all (§2's
    # record-index check) and for the record it is the basis for to qualify
    # for current publication (§1's acquisition-binding check).
    evidence_path = temp_root / "data" / "events" / "event_evidence.json"
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_payload["evidence"] = evidence_payload["evidence"] + [_manual_evidence_record()]
    _write_json(evidence_path, evidence_payload)
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    assert _run_build_analysis(monkeypatch) == 0
    source_status = json.loads(
        (temp_root / "data" / "source_status" / "latest.json").read_text(encoding="utf-8")
    )
    health = {item["source_id"]: item for item in source_status["sources"]}[
        "TEST_E2E_MANUAL_SOURCE"
    ]
    assert health["status"] == "fresh"


def test_a_malformed_manual_review_event_fails_the_build_closed(tmp_path, monkeypatch):
    temp_root = _copy_repo(tmp_path)
    registry = {
        "version": "0.8",
        "policy": "free_sources_only",
        "last_reviewed_at": "2026-07-24",
        "sources": [_manual_source()],
    }
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    malformed = _manual_event()
    del malformed["record_count"]
    _write_json(
        temp_root / "data" / "collection_runs" / "manual" / "TEST_E2E_MANUAL_SOURCE.json",
        {"version": "0.8", "source_id": "TEST_E2E_MANUAL_SOURCE", "events": [malformed]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    with pytest.raises(ValueError, match="invalid manual review event"):
        _run_build_analysis(monkeypatch)


def test_a_manual_event_referencing_missing_evidence_fails_closed(tmp_path, monkeypatch):
    """WO-010-R5 §2 reverses the WO-010-R4 behaviour this test used to
    assert: a manual review event naming a record nobody can find no longer
    loads. The previous version of this test's docstring claimed that
    "the loader still accepts a well-formed event naming a record ID
    nothing else in this test's repository defines" and that this was
    "documented, not a silent gap" because cross-referencing belonged to
    ``analysis.review_package`` alone. That statement is superseded: the
    loader itself now receives the current record index
    (``collectors.collection_runs.load_manual_review_events``'s
    ``record_index`` parameter) and fails closed on exactly this case."""
    temp_root = _copy_repo(tmp_path)
    registry = {
        "version": "0.8",
        "policy": "free_sources_only",
        "last_reviewed_at": "2026-07-24",
        "sources": [_manual_source()],
    }
    (temp_root / "config" / "sources.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    orphaned = _manual_event(related_record_ids=["EVD-DOES-NOT-EXIST"])
    _write_json(
        temp_root / "data" / "collection_runs" / "manual" / "TEST_E2E_MANUAL_SOURCE.json",
        {"version": "0.8", "source_id": "TEST_E2E_MANUAL_SOURCE", "events": [orphaned]},
    )
    _patch_build_scripts(monkeypatch, temp_root, registry=registry)

    with pytest.raises(ValueError, match="does not exist in this build's record index"):
        _run_build_analysis(monkeypatch)
