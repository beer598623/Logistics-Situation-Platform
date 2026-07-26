"""Acquisition-binding validation for current records (WO-010-R5 §1, §3, §9).

A ``live_retrieved`` or ``human_reviewed_manual`` record's origin label is a
claim -- that a real acquisition event actually happened. These tests check
that the claim is verified against persisted collection-run manifests and
manual-review events, not merely trusted, and that a record whose claim
cannot be verified is excluded rather than published.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.provenance import (  # noqa: E402
    acquisition_binding_problems,
    build_acquisition_summary,
    build_record_index,
    source_health_publication_consistency_problems,
)
from tests.positive_path import (  # noqa: E402
    TEST_NOTICE_SOURCE,
    TEST_TRADE_SOURCE,
    live_trade_observation,
    manual_notice_evidence,
)

AS_OF = datetime(2026, 7, 24, tzinfo=UTC)

RUN_ID = "COL-20260720T000000Z-" + TEST_TRADE_SOURCE
EVENT_ID = "MAN-20260720T000000Z-" + TEST_NOTICE_SOURCE


def _run(**overrides):
    run = {
        "run_id": RUN_ID,
        "source_id": TEST_TRADE_SOURCE,
        "started_at": "2026-07-20T00:00:00Z",
        "completed_at": "2026-07-20T00:00:00Z",
        "status": "success",
        "adapter_version": "test_v1",
    }
    run.update(overrides)
    return run


def _event(**overrides):
    event = {
        "event_id": EVENT_ID,
        "source_id": TEST_NOTICE_SOURCE,
        "reviewed_at": "2026-07-20T00:00:00Z",
        "status": "reviewed",
        "related_record_ids": ["EVD-MANUAL-001"],
        "bounded_content_confirmed": True,
    }
    event.update(overrides)
    return event


# ---------------------------------------------------------------------------
# Positive path
# ---------------------------------------------------------------------------


def test_a_fully_bound_live_observation_has_no_binding_problems():
    record = live_trade_observation(period_key="2026-07", value=100.0, collection_run_id=RUN_ID)
    problems = acquisition_binding_problems(
        record,
        collection_runs_by_source={TEST_TRADE_SOURCE: [_run()]},
        as_of=AS_OF,
    )
    assert problems == []


def test_a_fully_bound_human_reviewed_notice_has_no_binding_problems():
    record = manual_notice_evidence(evidence_id="EVD-MANUAL-001", manual_review_event_id=EVENT_ID)
    problems = acquisition_binding_problems(
        record,
        manual_events_by_source={TEST_NOTICE_SOURCE: [_event()]},
        as_of=AS_OF,
    )
    assert problems == []


def test_a_fixture_record_is_exempt_from_acquisition_binding():
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        evidence_origin="synthetic_test_fixture",
        collection_run_id=None,
    )
    assert acquisition_binding_problems(record) == []


# ---------------------------------------------------------------------------
# Negative: live records (WO-010-R5 §1, §10)
# ---------------------------------------------------------------------------


def test_a_live_record_with_no_collection_run_binding_is_rejected():
    record = live_trade_observation(period_key="2026-07", value=100.0)
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [_run()]}, as_of=AS_OF
    )
    assert any("carries no collection_run_id" in item for item in problems), problems


def test_a_live_record_referencing_a_missing_run_is_rejected():
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id="COL-20260720T000000Z-NOPE"
    )
    problems = acquisition_binding_problems(
        record, collection_runs_by_source={TEST_TRADE_SOURCE: [_run()]}, as_of=AS_OF
    )
    assert any("matches no persisted collection run" in item for item in problems), problems


def test_a_live_record_referencing_a_failed_run_is_rejected():
    record = live_trade_observation(period_key="2026-07", value=100.0, collection_run_id=RUN_ID)
    problems = acquisition_binding_problems(
        record,
        collection_runs_by_source={TEST_TRADE_SOURCE: [_run(status="error")]},
        as_of=AS_OF,
    )
    assert any("not 'success' or 'not_modified'" in item for item in problems), problems


def test_a_live_record_referencing_another_sources_run_is_rejected():
    other_run_id = "COL-20260720T000000Z-SOME_OTHER_SOURCE"
    record = live_trade_observation(
        period_key="2026-07", value=100.0, collection_run_id=other_run_id
    )
    other_run = _run(run_id=other_run_id, source_id="SOME_OTHER_SOURCE")
    problems = acquisition_binding_problems(
        record,
        collection_runs_by_source={
            TEST_TRADE_SOURCE: [_run()],
            "SOME_OTHER_SOURCE": [other_run],
        },
        as_of=AS_OF,
    )
    assert any("matches no persisted collection run" in item for item in problems), problems


def test_no_index_supplied_fails_closed_for_a_live_record():
    record = live_trade_observation(period_key="2026-07", value=100.0, collection_run_id=RUN_ID)
    problems = acquisition_binding_problems(record)
    assert problems != []


def test_a_run_completed_after_as_of_is_rejected():
    record = live_trade_observation(
        period_key="2026-07",
        value=100.0,
        collection_run_id=RUN_ID,
        retrieved_at="2026-07-20T06:00:00Z",
    )
    future_run = _run(completed_at="2026-08-01T00:00:00Z")
    problems = acquisition_binding_problems(
        record,
        collection_runs_by_source={TEST_TRADE_SOURCE: [future_run]},
        as_of=AS_OF,
    )
    assert any("completed after this build's as-of time" in item for item in problems), problems


# ---------------------------------------------------------------------------
# Negative: manual records (WO-010-R5 §1, §10)
# ---------------------------------------------------------------------------


def test_a_manual_record_with_no_review_event_binding_is_rejected():
    record = manual_notice_evidence(evidence_id="EVD-MANUAL-001")
    problems = acquisition_binding_problems(
        record, manual_events_by_source={TEST_NOTICE_SOURCE: [_event()]}, as_of=AS_OF
    )
    assert any("carries no manual_review_event_id" in item for item in problems), problems


def test_a_manual_record_not_listed_in_the_events_related_record_ids_is_rejected():
    record = manual_notice_evidence(evidence_id="EVD-NOT-LISTED", manual_review_event_id=EVENT_ID)
    problems = acquisition_binding_problems(
        record, manual_events_by_source={TEST_NOTICE_SOURCE: [_event()]}, as_of=AS_OF
    )
    assert any("is not listed in manual review event" in item for item in problems), problems


def test_a_manual_record_bound_to_a_rejected_event_is_rejected():
    record = manual_notice_evidence(evidence_id="EVD-MANUAL-001", manual_review_event_id=EVENT_ID)
    problems = acquisition_binding_problems(
        record,
        manual_events_by_source={TEST_NOTICE_SOURCE: [_event(status="rejected")]},
        as_of=AS_OF,
    )
    assert any("not 'reviewed'" in item for item in problems), problems


# ---------------------------------------------------------------------------
# build_record_index (WO-010-R5 §2)
# ---------------------------------------------------------------------------


def test_build_record_index_covers_observations_and_evidence():
    observation = live_trade_observation(period_key="2026-07", value=100.0)
    evidence = manual_notice_evidence(evidence_id="EVD-MANUAL-001")
    index = build_record_index(
        observations={"trade_observations": [observation]}, evidence=[evidence]
    )
    assert observation["provenance"]["record_id"] in index
    assert "EVD-MANUAL-001" in index
    assert index["EVD-MANUAL-001"]["source_id"] == TEST_NOTICE_SOURCE
    assert index["EVD-MANUAL-001"]["is_fixture"] is False


# ---------------------------------------------------------------------------
# WO-010-R5 §3: Source Health / publication consistency
# ---------------------------------------------------------------------------


def test_a_live_record_from_a_no_data_source_is_flagged():
    record = live_trade_observation(period_key="2026-07", value=100.0)
    source_status = {"sources": [{"source_id": TEST_TRADE_SOURCE, "status": "no_data"}]}
    problems = source_health_publication_consistency_problems(source_status, [record])
    assert any("Source Health status is 'no_data'" in item for item in problems), problems


def test_a_live_record_from_a_disabled_source_is_flagged():
    record = live_trade_observation(period_key="2026-07", value=100.0)
    source_status = {"sources": [{"source_id": TEST_TRADE_SOURCE, "status": "disabled"}]}
    problems = source_health_publication_consistency_problems(source_status, [record])
    assert any("Source Health status is 'disabled'" in item for item in problems), problems


def test_a_live_record_from_a_fresh_source_is_not_flagged():
    record = live_trade_observation(period_key="2026-07", value=100.0)
    source_status = {"sources": [{"source_id": TEST_TRADE_SOURCE, "status": "fresh"}]}
    assert source_health_publication_consistency_problems(source_status, [record]) == []


def test_a_manual_record_is_never_flagged_by_this_check():
    """A manual intake's own health comes only from its recorded review
    event, never from a no_data/disabled snapshot -- this check is specific
    to automated, live_retrieved sources."""
    record = manual_notice_evidence(evidence_id="EVD-MANUAL-001")
    source_status = {"sources": [{"source_id": TEST_NOTICE_SOURCE, "status": "disabled"}]}
    assert source_health_publication_consistency_problems(source_status, [record]) == []


# ---------------------------------------------------------------------------
# WO-010-R5 §9: acquisition summary
# ---------------------------------------------------------------------------


def test_acquisition_summary_reports_a_qualifying_run_and_its_cutoff():
    record = live_trade_observation(period_key="2026-07", value=100.0, collection_run_id=RUN_ID)
    summary = build_acquisition_summary(
        observations={"trade_observations": [record]},
        collection_runs_by_source={TEST_TRADE_SOURCE: [_run()]},
        as_of=AS_OF,
    )
    assert summary["qualifying_collection_run_ids"] == [RUN_ID]
    assert summary["excluded_unbound_record_count"] == 0
    assert summary["latest_source_cutoff"] == "2026-07-20T00:00:00Z"
    assert summary["acquisition_health_limitations"] == []


def test_acquisition_summary_counts_an_excluded_unbound_record():
    record = live_trade_observation(period_key="2026-07", value=100.0)  # no collection_run_id
    summary = build_acquisition_summary(
        observations={"trade_observations": [record]},
        collection_runs_by_source={TEST_TRADE_SOURCE: [_run()]},
        as_of=AS_OF,
    )
    assert summary["qualifying_collection_run_ids"] == []
    assert summary["excluded_unbound_record_count"] == 1
    assert summary["latest_source_cutoff"] is None
    assert summary["acquisition_health_limitations"] != []


def test_acquisition_summary_of_nothing_is_an_honest_empty_summary():
    summary = build_acquisition_summary()
    assert summary == {
        "qualifying_collection_run_ids": [],
        "qualifying_manual_review_event_ids": [],
        "excluded_unbound_record_count": 0,
        "latest_source_cutoff": None,
        "acquisition_health_limitations": [],
    }
