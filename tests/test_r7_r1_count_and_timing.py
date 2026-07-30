"""Manifest count and retrieval-time fail-closed correction (WO-010-R7-R1).

R7 introduced the status-dependent manifest contract, the confirming/
governing run split, and exact record/run agreement -- but left three real
gaps: ``records_emitted`` was never actually constrained per status (a
``success`` run with a ``null`` count silently skipped the count-agreement
check; a ``not_modified`` run could carry a ``null`` count; ``error``/
``disabled``/``dry_run`` had no convention at all); no run's own
``started_at``..``completed_at`` interval was ever validated; and the
retrieval-timing checks inside the acquisition-binding boundary itself
silently skipped whenever a value was missing (rather than failing closed),
and outright crashed with an uncaught ``ValueError`` on a malformed
``retrieved_at`` instead of returning a validation problem. These tests
close those gaps and lock in what R7 already got right but never tested
directly (a chain hop that would let a governing run complete after its own
confirming run; a record retrieved after the build's as-of time).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.contracts import schema_errors  # noqa: E402
from analysis.provenance import (  # noqa: E402
    acquisition_binding_problems,
    collection_run_problems,
    compute_output_manifest_hash,
    resolve_governing_run,
)
from collectors.collection_runs import load_collection_runs  # noqa: E402
from tests.positive_path import TEST_TRADE_SOURCE, live_trade_observation  # noqa: E402

RECORD_ID = f"OBS-{TEST_TRADE_SOURCE}-th_export_value_neur-2026-07"
RECORD_CONTENT_HASH = "a" * 64


def _run(**overrides):
    run = {
        "run_id": "COL-20260720T000000Z-" + TEST_TRADE_SOURCE,
        "source_id": TEST_TRADE_SOURCE,
        "started_at": "2026-07-20T00:00:00Z",
        "completed_at": "2026-07-20T23:59:59Z",
        "status": "success",
        "workflow_sha": None,
        "adapter_version": "test_v1",
        "request_url": None,
        "response_url": None,
        "content_type": None,
        "http_status": None,
        "etag": None,
        "last_modified": None,
        "content_sha256": None,
        "records_received": 1,
        "records_emitted": 1,
        "records_rejected": 0,
        "data_cutoff_at": "2026-07-20T00:00:00Z",
        "warnings": [],
        "errors": [],
        "emitted_records": [
            {
                "record_id": RECORD_ID,
                "source_record_id": None,
                "content_sha256": RECORD_CONTENT_HASH,
            }
        ],
        "output_manifest_sha256": None,
        "supersedes_run_id": None,
    }
    run.update(overrides)
    if run.get("status") == "success" and "output_manifest_sha256" not in overrides:
        run["output_manifest_sha256"] = compute_output_manifest_hash(run.get("emitted_records"))
    return run


def _write_runs(directory: Path, filename: str, runs: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(json.dumps({"version": "0.8", "runs": runs}, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# A. Status-dependent counts -- negative, via load_collection_runs (schema +
#    semantic layers both exercised).
# ---------------------------------------------------------------------------


def test_a_success_run_with_a_null_records_emitted_count_is_rejected(tmp_path):
    run = _run(records_emitted=None)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_not_modified_run_with_a_null_records_emitted_count_is_rejected(tmp_path):
    prior = _run()
    not_modified = _run(
        run_id="COL-20260721T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-21T00:00:00Z",
        completed_at="2026-07-21T23:59:59Z",
        status="not_modified",
        emitted_records=[],
        records_emitted=None,
        output_manifest_sha256=None,
        supersedes_run_id=prior["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [prior, not_modified])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_not_modified_run_with_a_positive_records_emitted_count_is_rejected(tmp_path):
    prior = _run()
    not_modified = _run(
        run_id="COL-20260721T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-21T00:00:00Z",
        completed_at="2026-07-21T23:59:59Z",
        status="not_modified",
        emitted_records=[],
        records_emitted=7,
        output_manifest_sha256=None,
        supersedes_run_id=prior["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [prior, not_modified])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_an_error_run_with_a_positive_records_emitted_count_is_rejected(tmp_path):
    run = _run(
        status="error",
        emitted_records=None,
        records_emitted=3,
        output_manifest_sha256=None,
        supersedes_run_id=None,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_dry_run_with_a_zero_records_emitted_count_is_rejected(tmp_path):
    # WO-010-R7-R1: the documented convention for error/disabled/dry_run is
    # null, never 0 -- 0 is reserved for a success run whose manifest
    # genuinely has zero entries.
    run = _run(
        status="dry_run",
        emitted_records=None,
        records_emitted=0,
        output_manifest_sha256=None,
        supersedes_run_id=None,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_disabled_run_with_a_records_emitted_count_is_rejected(tmp_path):
    run = _run(
        status="disabled",
        emitted_records=None,
        records_emitted=1,
        output_manifest_sha256=None,
        supersedes_run_id=None,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# B. Universal manifest field presence -- negative.
# ---------------------------------------------------------------------------


def test_an_error_run_missing_the_output_manifest_fields_entirely_is_rejected(tmp_path):
    run = _run(
        status="error", emitted_records=None, records_emitted=None, output_manifest_sha256=None
    )
    del run["emitted_records"]
    del run["output_manifest_sha256"]
    del run["supersedes_run_id"]
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_success_run_missing_supersedes_run_id_is_rejected(tmp_path):
    run = _run()
    del run["supersedes_run_id"]
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# C. Status-dependent counts -- positive.
# ---------------------------------------------------------------------------


def test_a_not_modified_run_with_a_zero_count_and_a_valid_chain_loads_cleanly(tmp_path):
    prior = _run()
    not_modified = _run(
        run_id="COL-20260721T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-21T00:00:00Z",
        completed_at="2026-07-21T23:59:59Z",
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        output_manifest_sha256=None,
        supersedes_run_id=prior["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [prior, not_modified])
    loaded = load_collection_runs(tmp_path)
    stored = {run["run_id"]: run for run in loaded[TEST_TRADE_SOURCE]}
    _confirming, governing, _chain, problems = resolve_governing_run(
        stored[not_modified["run_id"]],
        runs_by_id={run["run_id"]: run for run in loaded[TEST_TRADE_SOURCE]},
    )
    assert problems == []
    assert governing["run_id"] == prior["run_id"]


def test_an_error_run_with_a_null_count_and_no_manifest_loads_cleanly(tmp_path):
    run = _run(
        status="error",
        emitted_records=None,
        records_emitted=None,
        output_manifest_sha256=None,
        supersedes_run_id=None,
        errors=["simulated adapter failure"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    loaded = load_collection_runs(tmp_path)
    stored = loaded[TEST_TRADE_SOURCE][0]
    assert stored["records_emitted"] is None
    assert stored["emitted_records"] is None


def test_a_zero_output_success_run_records_a_zero_count(tmp_path):
    run = _run(emitted_records=[], records_emitted=0)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    loaded = load_collection_runs(tmp_path)
    stored = loaded[TEST_TRADE_SOURCE][0]
    assert stored["records_emitted"] == 0
    assert stored["emitted_records"] == []
    assert stored["output_manifest_sha256"] == compute_output_manifest_hash([])


# ---------------------------------------------------------------------------
# D. Run timing -- negative.
# ---------------------------------------------------------------------------


def test_a_run_that_completes_before_it_started_is_rejected(tmp_path):
    run = _run(started_at="2026-07-20T23:00:00Z", completed_at="2026-07-20T01:00:00Z")
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="cannot complete before it started"):
        load_collection_runs(tmp_path)


def test_a_run_with_a_malformed_started_at_fails_closed_with_a_validation_message(tmp_path):
    run = _run(started_at="not-a-timestamp")
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    # Must fail with the semantic validation message, not an uncaught
    # "Invalid isoformat string" traceback from datetime.fromisoformat.
    with pytest.raises(ValueError, match="records no valid started_at"):
        load_collection_runs(tmp_path)


def test_a_run_with_a_missing_completed_at_is_rejected(tmp_path):
    # Already satisfied by the top-level `required` list; locked here.
    run = _run()
    del run["completed_at"]
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_supersedes_chain_hop_with_an_inverted_interval_is_rejected(tmp_path):
    prior = _run(started_at="2026-07-20T23:00:00Z", completed_at="2026-07-20T01:00:00Z")
    not_modified = _run(
        run_id="COL-20260721T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-21T00:00:00Z",
        completed_at="2026-07-21T23:59:59Z",
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        output_manifest_sha256=None,
        supersedes_run_id=prior["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [prior, not_modified])
    with pytest.raises(ValueError, match="cannot complete before it started"):
        load_collection_runs(tmp_path)


def test_resolve_governing_run_rejects_a_governing_run_with_an_inverted_interval():
    run = _run(started_at="2026-07-20T23:59:59Z", completed_at="2026-07-20T00:00:00Z")
    _confirming, governing, _chain, problems = resolve_governing_run(
        run, runs_by_id={run["run_id"]: run}
    )
    assert governing is None
    assert any("inverted" in problem for problem in problems), problems


def test_a_supersedes_chain_whose_prior_run_completes_later_is_rejected():
    # Already correctly rejected by R7's pairwise chronology check; locked
    # here with no production change.
    prior = _run(
        run_id="COL-20260722T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-22T00:00:00Z",
        completed_at="2026-07-22T23:59:59Z",
    )
    not_modified = _run(
        run_id="COL-20260721T000000Z-" + TEST_TRADE_SOURCE,
        started_at="2026-07-21T00:00:00Z",
        completed_at="2026-07-21T23:59:59Z",
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        output_manifest_sha256=None,
        supersedes_run_id=prior["run_id"],
    )
    runs_by_id = {prior["run_id"]: prior, not_modified["run_id"]: not_modified}
    _confirming, governing, _chain, problems = resolve_governing_run(
        not_modified, runs_by_id=runs_by_id
    )
    assert governing is None
    assert any("is not chronological" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# E. Live-record retrieval timing -- negative, at the acquisition-binding
#    boundary (analysis.provenance.acquisition_binding_problems), not only
#    repository-level validation.
# ---------------------------------------------------------------------------


def test_a_live_record_with_a_non_retrieved_retrieval_status_is_rejected_at_the_binding_boundary():
    run = _run()
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        collection_run_id=run["run_id"],
        retrieval_status="retrieval_failed",
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}
    )
    assert any("retrieval_status" in item and "not 'retrieved'" in item for item in problems), (
        problems
    )


def test_a_live_record_with_a_null_retrieved_at_is_rejected_at_the_binding_boundary():
    run = _run()
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=run["run_id"], retrieved_at=None
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}
    )
    assert any("no valid retrieved_at" in item for item in problems), problems


def test_a_live_record_with_a_malformed_retrieved_at_fails_closed_rather_than_raising():
    run = _run()
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        collection_run_id=run["run_id"],
        retrieved_at="not-a-timestamp",
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}
    )
    assert any("no valid retrieved_at" in item for item in problems), problems


def test_a_governing_run_with_no_started_at_cannot_back_a_live_record():
    run = _run()
    del run["started_at"]
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=run["run_id"]
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}
    )
    # Caught by resolve_governing_run's own per-hop interval check before
    # resolve_live_record_binding's governing-interval check is even
    # reached -- both are independently fail-closed (WO-010-R7-R1).
    assert any(
        "missing, malformed or inverted started_at..completed_at interval" in item
        for item in problems
    ), problems


def test_a_live_record_retrieved_after_the_builds_as_of_time_is_rejected():
    from datetime import UTC, datetime

    run = _run(started_at="2026-07-20T00:00:00Z", completed_at="2026-07-20T02:00:00Z")
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        collection_run_id=run["run_id"],
        retrieved_at="2026-07-20T04:00:00Z",
    )
    as_of = datetime(2026, 7, 20, 3, 0, tzinfo=UTC)
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}, as_of=as_of
    )
    assert any("retrieved_at is after this build's as-of time" in item for item in problems), (
        problems
    )


# ---------------------------------------------------------------------------
# F. Positive end-to-end: the new checks do not over-reject a clean binding.
# ---------------------------------------------------------------------------


def test_a_fully_bound_live_record_with_valid_retrieval_timing_still_binds_cleanly():
    run = _run()
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=run["run_id"]
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}
    )
    assert problems == []


# ---------------------------------------------------------------------------
# G. collection_run_problems direct unit coverage (defense-in-depth: these
#    invariants hold even for a caller that bypasses schema validation).
# ---------------------------------------------------------------------------


def test_collection_run_problems_rejects_a_success_run_with_a_null_count():
    run = _run(records_emitted=None)
    problems = collection_run_problems(run)
    assert any("must record an integer count" in problem for problem in problems), problems


def test_collection_run_problems_rejects_a_not_modified_run_with_a_null_count():
    run = _run(
        status="not_modified", emitted_records=[], records_emitted=None, output_manifest_sha256=None
    )
    problems = collection_run_problems(run)
    assert any("must record exactly 0" in problem for problem in problems), problems


def test_collection_run_problems_rejects_an_inverted_interval():
    run = _run(started_at="2026-07-21T00:00:00Z", completed_at="2026-07-20T00:00:00Z")
    problems = collection_run_problems(run)
    assert any("cannot complete before it started" in problem for problem in problems), problems


def test_collection_run_problems_accepts_a_fully_valid_success_run():
    run = _run()
    assert collection_run_problems(run) == []


# ---------------------------------------------------------------------------
# H. Schema alignment: retrieval_status <-> retrieved_at is now structural
#    on both observation and event-evidence records, not only prose.
# ---------------------------------------------------------------------------


def test_a_retrieved_observation_with_a_null_retrieved_at_fails_its_schema():
    record = live_trade_observation(period_key="2026-07", value=100.0)
    record["provenance"]["retrieved_at"] = None
    errors = schema_errors(record, "trade_observation.schema.json")
    assert errors, "expected a schema error for retrieval_status=retrieved with a null retrieved_at"


def test_a_not_retrieved_observation_with_a_retrieved_at_fails_its_schema():
    record = live_trade_observation(
        period_key="2026-07", value=100.0, retrieval_status="not_retrieved", retrieved_at=None
    )
    record["provenance"]["retrieved_at"] = "2026-07-20T06:00:00Z"
    errors = schema_errors(record, "trade_observation.schema.json")
    assert errors, (
        "expected a schema error for retrieval_status=not_retrieved with a non-null retrieved_at"
    )


def test_a_retrieved_event_evidence_with_a_null_retrieved_at_fails_its_schema():
    evidence = _event_evidence(retrieval_status="retrieved", retrieved_at=None)
    errors = schema_errors(evidence, "event_evidence.schema.json")
    assert errors, "expected a schema error for retrieval_status=retrieved with a null retrieved_at"


def test_a_not_applicable_event_evidence_with_a_retrieved_at_fails_its_schema():
    evidence = _event_evidence(
        retrieval_status="not_applicable", retrieved_at="2026-07-20T06:00:00Z"
    )
    errors = schema_errors(evidence, "event_evidence.schema.json")
    assert errors, (
        "expected a schema error for retrieval_status=not_applicable with a non-null retrieved_at"
    )


def test_a_retrieved_observation_with_a_valid_retrieved_at_is_not_rejected_by_the_new_rule():
    # Isolates the new allOf rule from the pre-existing, unrelated
    # partner_scope mismatch in tests.positive_path.live_trade_observation
    # (it defaults to 'region_group', not one of the schema's enum values,
    # and is out of WO-010-R7-R1's narrow scope to fix): assert only that no
    # error mentions retrieved_at or retrieval_status.
    record = live_trade_observation(period_key="2026-07", value=100.0)
    errors = schema_errors(record, "trade_observation.schema.json")
    assert not any("retrieved_at" in error or "retrieval_status" in error for error in errors), (
        errors
    )


def _event_evidence(*, retrieval_status: str, retrieved_at: str | None) -> dict:
    return {
        "evidence_id": "EVD-TEST-001",
        "event_id": "EVT-20260720-001",
        "source_id": "TEST_SOURCE",
        "source_name": "Test source",
        "source_class": "official",
        "source_url": "https://example.org/notice",
        "source_record_id": None,
        "claim": "A test claim.",
        "claim_type": "official_notice",
        "evidence_role": "confirming",
        "relation": "supports",
        "strength": "A",
        "scope_supported": "facility",
        "event_date": "2026-07-20",
        "publication_date": "2026-07-20",
        "content_sha256": "a" * 64,
        "parser_version": "test_v1",
        "licence_status": "reviewed",
        "known_limitations": [],
        "evidence_origin": "live_retrieved",
        "retrieval_status": retrieval_status,
        "content_hash_scope": "source_response",
        "retrieved_at": retrieved_at,
        "strength_basis": "verified",
        "dataset": "current_publication",
    }
