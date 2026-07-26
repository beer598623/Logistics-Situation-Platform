"""Validated loading of collection-run and manual-review history
(WO-010-R4 §7)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.provenance import compute_reviewed_record_set_hash  # noqa: E402
from collectors.collection_runs import load_collection_runs, load_manual_review_events  # noqa: E402
from tests.positive_path import TEST_NOTICE_SOURCE, TEST_REGISTRY  # noqa: E402

NOW = datetime(2026, 7, 24, tzinfo=UTC)

#: A placeholder hash. Valid for every test whose event either has no
#: related_record_ids (the hash check is skipped) or fails an earlier check
#: (the hash check is never reached) -- only a test asserting a clean load
#: with a non-empty related_record_ids needs to override it with a real
#: computed hash (WO-010-R6 §2).
_PLACEHOLDER_HASH = "0" * 64


def _event(**overrides):
    base = {
        "event_id": "MAN-20260101T000000Z-" + TEST_NOTICE_SOURCE,
        "source_id": TEST_NOTICE_SOURCE,
        "reviewed_at": "2026-01-01T00:00:00Z",
        "reviewer_record": "A. Reviewer",
        "status": "reviewed",
        "record_count": 1,
        "related_record_ids": ["EVD-1"],
        "data_cutoff_at": "2026-01-01T00:00:00Z",
        "bounded_content_confirmed": True,
        "underlying_publisher": "Example Port Authority",
        "content_sha256": None,
        "known_limitations": [],
        "reviewed_record_set_sha256": _PLACEHOLDER_HASH,
    }
    base.update(overrides)
    return base


def _write(directory: Path, filename: str, source_id: str, events: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps({"version": "0.8", "source_id": source_id, "events": events}, indent=2),
        encoding="utf-8",
    )
    return path


from tests.positive_path import TEST_TRADE_SOURCE  # noqa: E402, F811


def _run(**overrides):
    base = {
        "run_id": "COL-20260101T000000Z-" + TEST_TRADE_SOURCE,
        "source_id": TEST_TRADE_SOURCE,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:00Z",
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
        "data_cutoff_at": "2026-01-01T00:00:00Z",
        "warnings": [],
        "errors": [],
        "emitted_records": [
            {"record_id": "OBS-1", "source_record_id": None, "content_sha256": "a" * 64}
        ],
        "output_manifest_sha256": None,
        "supersedes_run_id": None,
    }
    base.update(overrides)
    return base


def _write_runs(directory: Path, filename: str, runs: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(json.dumps({"version": "0.8", "runs": runs}, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Collection runs: missing directory / basic pass-through
# ---------------------------------------------------------------------------


def test_a_missing_collection_runs_directory_returns_empty(tmp_path):
    assert load_collection_runs(tmp_path / "does-not-exist") == {}


def test_a_well_formed_run_with_a_matching_manifest_loads_cleanly(tmp_path):
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [_run()])
    loaded = load_collection_runs(tmp_path)
    assert loaded[TEST_TRADE_SOURCE][0]["run_id"] == "COL-20260101T000000Z-" + TEST_TRADE_SOURCE


# ---------------------------------------------------------------------------
# WO-010-R6 §1: collection-run output-manifest internal consistency
# ---------------------------------------------------------------------------


def test_a_not_modified_run_that_claims_emitted_records_is_rejected(tmp_path):
    _write_runs(
        tmp_path,
        f"{TEST_TRADE_SOURCE}.json",
        [
            _run(
                status="not_modified", supersedes_run_id="COL-20251201T000000Z-" + TEST_TRADE_SOURCE
            )
        ],
    )
    with pytest.raises(ValueError, match="must not claim newly emitted records"):
        load_collection_runs(tmp_path)


def test_a_records_emitted_count_that_disagrees_with_the_manifest_is_rejected(tmp_path):
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [_run(records_emitted=5)])
    with pytest.raises(ValueError, match="disagrees with the 1 entries"):
        load_collection_runs(tmp_path)


def test_a_declared_output_manifest_hash_that_disagrees_is_rejected(tmp_path):
    _write_runs(tmp_path, f"{TEST_TRADE_SOURCE}.json", [_run(output_manifest_sha256="f" * 64)])
    with pytest.raises(ValueError, match="disagrees with the computed hash"):
        load_collection_runs(tmp_path)


def test_a_correct_output_manifest_hash_loads_cleanly(tmp_path):
    from analysis.provenance import compute_output_manifest_hash

    emitted = [{"record_id": "OBS-1", "source_record_id": None, "content_sha256": "a" * 64}]
    _write_runs(
        tmp_path,
        f"{TEST_TRADE_SOURCE}.json",
        [
            _run(
                emitted_records=emitted,
                output_manifest_sha256=compute_output_manifest_hash(emitted),
            )
        ],
    )
    loaded = load_collection_runs(tmp_path)
    assert loaded[TEST_TRADE_SOURCE][0]["output_manifest_sha256"] == compute_output_manifest_hash(
        emitted
    )


def test_a_missing_manual_events_directory_returns_empty(tmp_path):
    assert load_manual_review_events(tmp_path / "does-not-exist") == {}


# ---------------------------------------------------------------------------
# Manual review events: schema validity
# ---------------------------------------------------------------------------


def test_a_well_formed_event_loads_and_groups_by_source(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    loaded = load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)
    assert [item["event_id"] for item in loaded[TEST_NOTICE_SOURCE]] == [
        "MAN-20260101T000000Z-" + TEST_NOTICE_SOURCE
    ]


def test_a_malformed_event_fails_the_whole_build(tmp_path):
    bad = _event()
    del bad["record_count"]
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [bad])
    with pytest.raises(ValueError, match="invalid manual review event"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_a_negative_record_count_fails_schema(tmp_path):
    bad = _event(record_count=-1)
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [bad])
    with pytest.raises(ValueError, match="invalid manual review event"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


# ---------------------------------------------------------------------------
# Manual review events: cross-checks beyond schema
# ---------------------------------------------------------------------------


def test_duplicate_event_ids_are_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event(), _event()])
    with pytest.raises(ValueError, match="duplicate manual review event_id"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_a_source_id_mismatched_with_the_filename_is_rejected(tmp_path):
    _write(tmp_path, "WRONG_FILENAME.json", TEST_NOTICE_SOURCE, [_event()])
    with pytest.raises(ValueError, match="does not match the containing filename"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_an_unknown_source_id_is_rejected(tmp_path):
    _write(
        tmp_path,
        "NOT_A_REAL_SOURCE.json",
        "NOT_A_REAL_SOURCE",
        [_event(event_id="MAN-20260101T000000Z-NOT_A_REAL_SOURCE", source_id="NOT_A_REAL_SOURCE")],
    )
    with pytest.raises(ValueError, match="not in the source registry"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_a_non_manual_intake_source_is_rejected(tmp_path):
    from tests.positive_path import TEST_TRADE_SOURCE

    _write(
        tmp_path,
        f"{TEST_TRADE_SOURCE}.json",
        TEST_TRADE_SOURCE,
        [_event(event_id="MAN-20260101T000000Z-" + TEST_TRADE_SOURCE, source_id=TEST_TRADE_SOURCE)],
    )
    with pytest.raises(ValueError, match="not an allowed manual-intake contract"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_a_missing_required_underlying_publisher_is_rejected(tmp_path):
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(underlying_publisher=None)],
    )
    with pytest.raises(ValueError, match="requires an underlying publisher"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_a_future_dated_review_is_rejected(tmp_path):
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(reviewed_at="2026-08-01T00:00:00Z")],
    )
    with pytest.raises(ValueError, match="later than this build's as-of time"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW)


def test_without_a_registry_or_now_only_schema_validity_is_checked(tmp_path):
    """The loader stays usable without a full Build Context (e.g. in an
    isolated schema test) -- registry and now are both optional."""
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(reviewed_at="2099-01-01T00:00:00Z", underlying_publisher=None)],
    )
    loaded = load_manual_review_events(tmp_path)
    assert loaded[TEST_NOTICE_SOURCE]


# ---------------------------------------------------------------------------
# WO-010-R5 §2: the record index reverses the accepted-orphan-reference
# behaviour -- every related_record_id must resolve to a real record.
# ---------------------------------------------------------------------------


def _record(record_id="EVD-1", **overrides):
    entry = {
        "record_id": record_id,
        "source_id": TEST_NOTICE_SOURCE,
        "is_fixture": False,
        "dataset": "current_publication",
        "timestamp": "2026-01-01T00:00:00Z",
        "evidence_origin": "human_reviewed_manual",
        "content_hash": "b" * 64,
        "event_id": "EVT-20260101-001",
    }
    entry.update(overrides)
    return entry


def test_a_related_record_id_that_does_not_exist_is_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    with pytest.raises(ValueError, match="does not exist in this build's record index"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index={})


def test_a_related_record_from_another_source_is_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    index = {"EVD-1": _record(source_id="SOME_OTHER_SOURCE")}
    with pytest.raises(ValueError, match="belongs to source 'SOME_OTHER_SOURCE'"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_related_record_that_is_a_fixture_is_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    index = {"EVD-1": _record(is_fixture=True)}
    with pytest.raises(ValueError, match="is a fixture record"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_related_record_that_is_historical_validation_is_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    index = {"EVD-1": _record(dataset="historical_validation")}
    with pytest.raises(ValueError, match="historical-validation record"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_related_record_dated_after_the_review_is_rejected(tmp_path):
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    index = {"EVD-1": _record(timestamp="2026-06-01T00:00:00Z")}
    with pytest.raises(ValueError, match="dated later than the review event"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_duplicate_related_record_ids_are_rejected(tmp_path):
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(related_record_ids=["EVD-1", "EVD-1"])],
    )
    index = {"EVD-1": _record()}
    with pytest.raises(ValueError, match="duplicate record ID"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_record_count_that_disagrees_with_valid_records_is_rejected(tmp_path):
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(record_count=2, related_record_ids=["EVD-1"])],
    )
    index = {"EVD-1": _record()}
    with pytest.raises(ValueError, match="disagrees with the 1 valid referenced record"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_reviewed_event_with_an_empty_record_set_is_rejected(tmp_path):
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(record_count=0, related_record_ids=[])],
    )
    with pytest.raises(ValueError, match="related_record_ids is empty"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index={})


def test_a_valid_related_record_loads_cleanly(tmp_path):
    index = {"EVD-1": _record()}
    expected_hash = compute_reviewed_record_set_hash(["EVD-1"], record_index=index)
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(reviewed_record_set_sha256=expected_hash)],
    )
    loaded = load_manual_review_events(
        tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index
    )
    assert loaded[TEST_NOTICE_SOURCE]


# ---------------------------------------------------------------------------
# WO-010-R6 §2: reviewed_record_set_sha256 recompute-and-compare
# ---------------------------------------------------------------------------


def test_a_reviewed_record_set_hash_that_disagrees_is_rejected(tmp_path):
    """The record still exists and every existence check passes, but the
    event's declared hash does not match what the current record set
    actually hashes to -- the drift an existence-only check cannot catch."""
    index = {"EVD-1": _record()}
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(reviewed_record_set_sha256=_PLACEHOLDER_HASH)],
    )
    with pytest.raises(ValueError, match="reviewed_record_set_sha256"):
        load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index)


def test_a_reviewed_record_set_hash_changes_when_a_records_content_changes(tmp_path):
    """Same record ID, source and dataset -- only the content hash differs --
    is still caught, because the summary hashed includes content_hash."""
    index = {"EVD-1": _record()}
    expected_hash = compute_reviewed_record_set_hash(["EVD-1"], record_index=index)
    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(reviewed_record_set_sha256=expected_hash)],
    )
    drifted_index = {"EVD-1": _record(content_hash="c" * 64)}
    with pytest.raises(ValueError, match="reviewed_record_set_sha256"):
        load_manual_review_events(
            tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=drifted_index
        )


def test_reviewed_record_set_hash_is_order_independent(tmp_path):
    """Canonical ordering: the same two records referenced in either order
    hash identically."""
    index = {"EVD-1": _record("EVD-1"), "EVD-2": _record("EVD-2")}
    forward = compute_reviewed_record_set_hash(["EVD-1", "EVD-2"], record_index=index)
    backward = compute_reviewed_record_set_hash(["EVD-2", "EVD-1"], record_index=index)
    assert forward == backward
    assert forward is not None


def test_a_superseded_event_is_not_the_latest_reviewed_event(tmp_path):
    """WO-010-R5 §2/§1: a superseded event does not make Source Health
    fresh. ``load_manual_review_events`` still loads a superseded event (its
    status is a fact about it, not a schema violation), but
    ``collectors.source_health._latest_reviewed_event`` only ever considers
    events with status 'reviewed' when computing freshness -- so a source
    whose only event is 'superseded' reports the same as one with none."""
    from collectors.source_health import evaluate_source_health

    _write(
        tmp_path,
        f"{TEST_NOTICE_SOURCE}.json",
        TEST_NOTICE_SOURCE,
        [_event(status="superseded", related_record_ids=[], record_count=0)],
    )
    loaded = load_manual_review_events(tmp_path, registry=TEST_REGISTRY, now=NOW, record_index={})
    contract = next(s for s in TEST_REGISTRY["sources"] if s["id"] == TEST_NOTICE_SOURCE)
    health = evaluate_source_health(
        contract, [], now=NOW, manual_review_events=loaded[TEST_NOTICE_SOURCE]
    )
    assert health.status == "disabled"
    assert health.last_success_at is None
