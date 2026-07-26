"""Collection-manifest contract and approval-state hash closure
(WO-010-R7).

R6 introduced the output manifest, the confirming/governing run split, and
a package-wide acquisition-state hash. These tests close the remaining gaps
R7 identifies: the manifest is mandatory (not merely present) for a
successful run; run and record identity is globally unambiguous, not just
locally consistent; a not_modified chain must actually resolve to a valid,
chronological, single-source successful run; a record must agree with its
*governing* run exactly, including retrieval timing; and the acquisition-
state hash is a full-document digest that changes on any material field,
never optional on a current package.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.provenance import (  # noqa: E402
    acquisition_binding_problems,
    compute_output_manifest_hash,
    resolve_governing_run,
)
from collectors.collection_runs import (  # noqa: E402
    EMPTY_ACQUISITION_STATE_SHA256,
    _acquisition_state_hash,
    load_collection_runs,
)
from tests.positive_path import TEST_TRADE_SOURCE, live_trade_observation  # noqa: E402

AS_OF = datetime(2026, 7, 24, tzinfo=UTC)
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


def _write_runs(
    directory: Path, filename: str, runs: list[dict], *, source_id: str | None = None
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    document = {"version": "0.8", "runs": runs}
    if source_id is not None:
        document["source_id"] = source_id
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# §1 Negative: success run with an incomplete/missing manifest
# ---------------------------------------------------------------------------


def test_a_success_run_with_emitted_records_and_a_null_manifest_hash_is_rejected(tmp_path):
    run = _run(output_manifest_sha256=None)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


def test_a_success_run_with_a_missing_output_manifest_hash_field_is_rejected(tmp_path):
    run = _run()
    del run["output_manifest_sha256"]
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="invalid collection run manifest"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# §1 Positive: zero-output success
# ---------------------------------------------------------------------------


def test_a_zero_output_success_run_with_a_valid_empty_manifest_hash_loads_cleanly(tmp_path):
    run = _run(emitted_records=[], records_emitted=0)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    loaded = load_collection_runs(tmp_path)
    stored = loaded[TEST_TRADE_SOURCE][0]
    assert stored["emitted_records"] == []
    assert stored["output_manifest_sha256"] == compute_output_manifest_hash([])
    assert stored["output_manifest_sha256"] is not None


# ---------------------------------------------------------------------------
# §2 Negative: global run identity
# ---------------------------------------------------------------------------


def test_a_duplicate_run_id_across_two_files_is_rejected(tmp_path):
    # Two entries sharing one run_id within a single, correctly named
    # source file -- "run_id appears more than once anywhere" is checked
    # before the filename/source-id agreement checks, so this isolates the
    # duplicate-ID rejection without also tripping a filename mismatch.
    run_a = _run(source_id=TEST_TRADE_SOURCE)
    run_b = _run(source_id=TEST_TRADE_SOURCE)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run_a, run_b])
    with pytest.raises(ValueError, match="duplicate run_id"):
        load_collection_runs(tmp_path)


def test_a_run_source_id_mismatched_with_its_filename_is_rejected(tmp_path):
    run = _run()
    _write_runs(tmp_path, "WRONG_FILENAME.json", [run])
    with pytest.raises(ValueError, match="does not match the containing filename"):
        load_collection_runs(tmp_path)


def test_a_document_level_source_id_disagreeing_with_its_runs_is_rejected(tmp_path):
    run = _run()
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run], source_id="SOME_OTHER_SOURCE")
    with pytest.raises(ValueError, match="document-level source_id"):
        load_collection_runs(tmp_path)


def test_a_run_id_source_suffix_disagreeing_with_source_id_is_rejected(tmp_path):
    run = _run(run_id="COL-20260720T000000Z-WRONG_SUFFIX", source_id=TEST_TRADE_SOURCE)
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="does not match the containing filename|source suffix"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# §3 Negative: output-manifest identity
# ---------------------------------------------------------------------------


def test_a_duplicate_emitted_record_id_is_rejected(tmp_path):
    run = _run(
        emitted_records=[
            {"record_id": RECORD_ID, "source_record_id": None, "content_sha256": "a" * 64},
            {"record_id": RECORD_ID, "source_record_id": None, "content_sha256": "a" * 64},
        ],
        records_emitted=2,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="more than once"):
        load_collection_runs(tmp_path)


def test_a_duplicate_emitted_record_id_with_differing_hashes_is_rejected(tmp_path):
    run = _run(
        emitted_records=[
            {"record_id": RECORD_ID, "source_record_id": None, "content_sha256": "a" * 64},
            {"record_id": RECORD_ID, "source_record_id": None, "content_sha256": "b" * 64},
        ],
        records_emitted=2,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run])
    with pytest.raises(ValueError, match="disagreeing content_sha256"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# §4 Negative: not_modified chain resolution
# ---------------------------------------------------------------------------


def test_a_not_modified_chain_terminating_at_error_is_rejected(tmp_path):
    error_run = _run(
        run_id="COL-20260701T000000Z-" + TEST_TRADE_SOURCE,
        status="error",
        emitted_records=None,
        records_emitted=None,
        output_manifest_sha256=None,
    )
    not_modified = _run(
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        supersedes_run_id=error_run["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [error_run, not_modified])
    with pytest.raises(ValueError, match="not 'success'"):
        load_collection_runs(tmp_path)


def test_a_not_modified_chain_terminating_at_dry_run_is_rejected(tmp_path):
    dry_run = _run(
        run_id="COL-20260701T000000Z-" + TEST_TRADE_SOURCE,
        status="dry_run",
        emitted_records=None,
        records_emitted=None,
        output_manifest_sha256=None,
    )
    not_modified = _run(
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        supersedes_run_id=dry_run["run_id"],
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [dry_run, not_modified])
    with pytest.raises(ValueError, match="not 'success'"):
        load_collection_runs(tmp_path)


def test_a_cross_source_supersedes_chain_is_rejected(tmp_path):
    other_run = _run(run_id="COL-20260701T000000Z-OTHER_SOURCE", source_id="OTHER_SOURCE")
    not_modified = _run(
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        supersedes_run_id=other_run["run_id"],
    )
    _write_runs(tmp_path, "OTHER_SOURCE.json", [other_run])
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [not_modified])
    with pytest.raises(ValueError, match="crosses source boundaries"):
        load_collection_runs(tmp_path)


def test_a_cyclic_supersedes_chain_is_rejected(tmp_path):
    run_a_id = "COL-20260701T000000Z-" + TEST_TRADE_SOURCE
    run_b_id = "COL-20260702T000000Z-" + TEST_TRADE_SOURCE
    run_a = _run(
        run_id=run_a_id,
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        supersedes_run_id=run_b_id,
        output_manifest_sha256=None,
    )
    run_b = _run(
        run_id=run_b_id,
        status="not_modified",
        emitted_records=[],
        records_emitted=0,
        supersedes_run_id=run_a_id,
        output_manifest_sha256=None,
    )
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [run_a, run_b])
    with pytest.raises(ValueError, match="cycle"):
        load_collection_runs(tmp_path)


# ---------------------------------------------------------------------------
# §5 Negative: exact record/run agreement
# ---------------------------------------------------------------------------


def test_a_null_record_source_record_id_does_not_match_a_non_null_manifest_value():
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=_run()["run_id"]
    )
    assert record["provenance"]["source_record_id"] is None
    run = _run(
        emitted_records=[
            {
                "record_id": RECORD_ID,
                "source_record_id": "REAL-ID",
                "content_sha256": RECORD_CONTENT_HASH,
            }
        ]
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}, as_of=AS_OF
    )
    assert any("source_record_id" in item and "disagrees" in item for item in problems), problems


def test_retrieval_time_outside_the_governing_runs_interval_is_rejected():
    run = _run(started_at="2026-07-20T00:00:00Z", completed_at="2026-07-20T01:00:00Z")
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        collection_run_id=run["run_id"],
        retrieved_at="2026-07-20T12:00:00Z",
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [run]}, as_of=AS_OF
    )
    assert any("falls outside governing collection run" in item for item in problems), problems


def test_parser_version_matching_the_confirming_run_but_not_the_governing_run_is_rejected():
    """A not_modified run's own adapter_version describes the confirmation
    attempt, not the parser that actually produced the record -- agreement
    must be checked against the *governing* run."""
    governing = _run(
        run_id="COL-20260701T000000Z-" + TEST_TRADE_SOURCE,
        adapter_version="original_parser_v1",
    )
    confirming = _run(
        status="not_modified",
        emitted_records=[],
        supersedes_run_id=governing["run_id"],
        adapter_version="test_v1",  # matches the record's own parser_version
    )
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=confirming["run_id"]
    )
    assert record["provenance"]["parser_version"] == "test_v1"
    problems = acquisition_binding_problems(
        record,
        collection_runs_by_source={TEST_TRADE_SOURCE: [governing, confirming]},
        as_of=AS_OF,
    )
    assert any(
        "parser_version" in item and "governing collection run" in item for item in problems
    ), problems


# ---------------------------------------------------------------------------
# §6 Full acquisition-state hash: deterministic and fully field-sensitive
# ---------------------------------------------------------------------------


def test_the_acquisition_state_hash_is_independent_of_iteration_order():
    run_a = _run(run_id="COL-20260701T000000Z-" + TEST_TRADE_SOURCE)
    run_b = _run(run_id="COL-20260702T000000Z-" + TEST_TRADE_SOURCE)
    forward = _acquisition_state_hash({TEST_TRADE_SOURCE: [run_a, run_b]}, {})
    backward = _acquisition_state_hash({TEST_TRADE_SOURCE: [run_b, run_a]}, {})
    assert forward == backward


def test_the_acquisition_state_hash_changes_when_a_field_outside_r6s_selected_set_changes():
    """WO-010-R6's hash only covered a hand-picked subset of fields (status,
    completed_at, adapter_version, output_manifest_sha256,
    supersedes_run_id). A change to a field outside that set -- here,
    content_sha256, the raw response hash -- left R6's hash unchanged even
    though the acquisition state genuinely had. The R7 full-document digest
    must not have this blind spot."""
    base = _run(content_sha256="c" * 64)
    drifted = _run(content_sha256="d" * 64)
    base_hash = _acquisition_state_hash({TEST_TRADE_SOURCE: [base]}, {})
    drifted_hash = _acquisition_state_hash({TEST_TRADE_SOURCE: [drifted]}, {})
    assert base_hash != drifted_hash


def test_the_empty_acquisition_state_hash_is_a_real_deterministic_sha256():
    assert EMPTY_ACQUISITION_STATE_SHA256 == _acquisition_state_hash({}, {})
    assert len(EMPTY_ACQUISITION_STATE_SHA256) == 64


# ---------------------------------------------------------------------------
# §7 Negative/positive: fail-closed missing acquisition-state hash
# ---------------------------------------------------------------------------


def test_a_current_package_with_a_null_acquisition_state_hash_is_rejected():
    from analysis.review_package import acquisition_currency_problems

    package = {
        "dataset": "current_publication",
        "acquisition_summary": {"acquisition_state_sha256": None},
    }
    problems = acquisition_currency_problems(package)
    assert any("missing or null" in item for item in problems), problems


def test_a_technical_demo_package_carries_the_deterministic_empty_state_hash():
    import scripts.build_review_package as build_review_package

    package = build_review_package.build("PKG-20260724-900", surface="technical_demo")
    assert package["acquisition_summary"]["acquisition_state_sha256"] == (
        EMPTY_ACQUISITION_STATE_SHA256
    )


# ---------------------------------------------------------------------------
# resolve_governing_run: direct unit coverage of the chain walker
# ---------------------------------------------------------------------------


def test_resolve_governing_run_returns_the_run_itself_when_already_successful():
    run = _run()
    confirming, governing, chain, problems = resolve_governing_run(
        run, runs_by_id={run["run_id"]: run}
    )
    assert problems == []
    assert confirming is run
    assert governing is run
    assert chain == [run["run_id"]]
