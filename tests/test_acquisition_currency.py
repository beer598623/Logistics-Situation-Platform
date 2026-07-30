"""Approval-time acquisition-state revalidation (WO-010-R6 §4, §10).

``analysis.review_package.acquisition_currency_problems`` is the check
``scripts/review_decision.py`` runs against acquisition state reloaded fresh
from disk, immediately before an approval decision -- never against the
state that existed when the package was built. These tests exercise it
directly: per-ID status/existence checks (already present before this work
order) and the new whole-state ``acquisition_state_sha256`` comparison,
which catches drift that per-ID checks alone cannot (a manifest's output
list changed, a record-set hash changed, a timestamp moved) even when every
individually-cited ID still resolves and still shows an acceptable status.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.review_package import acquisition_currency_problems  # noqa: E402
from collectors.collection_runs import _acquisition_state_hash  # noqa: E402

RUN_ID = "COL-20260720T000000Z-TEST_SOURCE"
EVENT_ID = "MAN-20260720T000000Z-TEST_MANUAL_SOURCE"


def _run(**overrides):
    run = {
        "run_id": RUN_ID,
        "source_id": "TEST_SOURCE",
        "status": "success",
        "completed_at": "2026-07-20T00:00:00Z",
        "adapter_version": "test_v1",
        "output_manifest_sha256": "a" * 64,
        "supersedes_run_id": None,
    }
    run.update(overrides)
    return run


def _event(**overrides):
    event = {
        "event_id": EVENT_ID,
        "source_id": "TEST_MANUAL_SOURCE",
        "status": "reviewed",
        "reviewed_at": "2026-07-20T00:00:00Z",
        "reviewed_record_set_sha256": "b" * 64,
    }
    event.update(overrides)
    return event


def _package(**overrides):
    summary = {
        "qualifying_collection_run_ids": [RUN_ID],
        "qualifying_manual_review_event_ids": [EVENT_ID],
        "excluded_unbound_record_count": 0,
        "latest_source_cutoff": "2026-07-20T00:00:00Z",
        "acquisition_health_limitations": [],
        "collection_run_manifest_hashes": {RUN_ID: "a" * 64},
        "manual_review_record_set_hashes": {EVENT_ID: "b" * 64},
        "included_current_record_ids": ["OBS-1"],
        "acquisition_state_sha256": _acquisition_state_hash(
            {"TEST_SOURCE": [_run()]}, {"TEST_MANUAL_SOURCE": [_event()]}
        ),
    }
    summary.update(overrides)
    return {"dataset": "current_publication", "acquisition_summary": summary}


# ---------------------------------------------------------------------------
# Per-ID existence/status checks (pre-existing, now directly tested)
# ---------------------------------------------------------------------------


def test_a_disappeared_collection_run_is_rejected():
    package = _package()
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event()]},
    )
    assert any("no longer exists" in item and RUN_ID in item for item in problems), problems


def test_a_collection_run_whose_status_changed_is_rejected():
    package = _package()
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [_run(status="error")]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event()]},
    )
    assert any("status has changed" in item and RUN_ID in item for item in problems), problems


def test_a_manual_event_whose_status_changed_is_rejected():
    package = _package()
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [_run()]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event(status="superseded")]},
    )
    assert any("status has changed" in item and EVENT_ID in item for item in problems), problems


# ---------------------------------------------------------------------------
# WO-010-R6 §4: whole-state acquisition_state_sha256 comparison
# ---------------------------------------------------------------------------


def test_matching_acquisition_state_hash_has_no_problems():
    package = _package()
    current_hash = _acquisition_state_hash(
        {"TEST_SOURCE": [_run()]}, {"TEST_MANUAL_SOURCE": [_event()]}
    )
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [_run()]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event()]},
        current_acquisition_state_sha256=current_hash,
    )
    assert problems == []


def test_a_changed_output_manifest_hash_is_rejected_even_though_ids_and_statuses_are_unchanged():
    """The run's own id and status are identical -- only its
    output_manifest_sha256 changed (its manifest was corrected). Per-ID
    existence/status checks alone would miss this; the whole-state hash
    comparison catches it."""
    package = _package()
    drifted_run = _run(output_manifest_sha256="f" * 64)
    current_hash = _acquisition_state_hash(
        {"TEST_SOURCE": [drifted_run]}, {"TEST_MANUAL_SOURCE": [_event()]}
    )
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [drifted_run]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event()]},
        current_acquisition_state_sha256=current_hash,
    )
    assert any("acquisition_state_sha256" in item for item in problems), problems


def test_a_changed_record_set_hash_is_rejected_even_with_unchanged_ids_and_statuses():
    package = _package()
    drifted_event = _event(reviewed_record_set_sha256="c" * 64)
    current_hash = _acquisition_state_hash(
        {"TEST_SOURCE": [_run()]}, {"TEST_MANUAL_SOURCE": [drifted_event]}
    )
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [_run()]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [drifted_event]},
        current_acquisition_state_sha256=current_hash,
    )
    assert any("acquisition_state_sha256" in item for item in problems), problems


def test_no_current_hash_supplied_skips_the_whole_state_comparison():
    """Backward-compatible: a caller that does not pass
    current_acquisition_state_sha256 still gets the per-ID checks, not a
    spurious whole-state mismatch."""
    package = _package()
    problems = acquisition_currency_problems(
        package,
        collection_runs_by_source={"TEST_SOURCE": [_run()]},
        manual_events_by_source={"TEST_MANUAL_SOURCE": [_event()]},
    )
    assert problems == []
