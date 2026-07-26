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

from collectors.collection_runs import load_collection_runs, load_manual_review_events  # noqa: E402
from tests.positive_path import TEST_NOTICE_SOURCE, TEST_REGISTRY  # noqa: E402

NOW = datetime(2026, 7, 24, tzinfo=UTC)


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


# ---------------------------------------------------------------------------
# Collection runs: missing directory / basic pass-through
# ---------------------------------------------------------------------------


def test_a_missing_collection_runs_directory_returns_empty(tmp_path):
    assert load_collection_runs(tmp_path / "does-not-exist") == {}


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
    _write(tmp_path, f"{TEST_NOTICE_SOURCE}.json", TEST_NOTICE_SOURCE, [_event()])
    index = {"EVD-1": _record()}
    loaded = load_manual_review_events(
        tmp_path, registry=TEST_REGISTRY, now=NOW, record_index=index
    )
    assert loaded[TEST_NOTICE_SOURCE]


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
