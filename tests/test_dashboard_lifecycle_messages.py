"""WO-010-R4 §9: dynamic lifecycle-message unit tests.

``scripts.build_dashboard._events_current_statement`` and
``_current_notice_statement`` compute a distinct sentence for each stage of
a progressively narrowing pipeline (current-dataset records -> qualified
records -> active/notice-attached records). These tests exercise every
stage directly against the pure functions, without needing a full repo
build, since each function only inspects the lists it is handed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_dashboard as build_dashboard  # noqa: E402


def _event(event_class: str = "direct_operational_event") -> dict:
    return {"event_class": event_class}


# ---------------------------------------------------------------------------
# Events: 6 states
# ---------------------------------------------------------------------------


def test_no_current_event_records():
    message = build_dashboard._events_current_statement([], [], [])
    assert "No current event records exist" in message


def test_current_records_exist_but_none_qualify():
    message = build_dashboard._events_current_statement([_event()], [], [])
    assert "none qualifies for current publication" in message


def test_qualified_current_events_exist_but_none_active():
    qualified = [_event("direct_operational_event")]
    message = build_dashboard._events_current_statement(qualified, qualified, [])
    assert "none is confirmed active" in message


def test_discovery_leads_exist_without_confirmation():
    qualified = [_event("discovery_lead"), _event("discovery_lead")]
    message = build_dashboard._events_current_statement(qualified, qualified, [])
    assert "qualified discovery lead(s) exist without confirmation" in message


def test_active_operational_events_exist():
    active = [_event("direct_operational_event"), _event("external_driver")]
    message = build_dashboard._events_current_statement(active, active, active)
    assert "including at least one direct operational event" in message


def test_only_contextual_external_drivers_exist():
    active = [_event("external_driver")]
    message = build_dashboard._events_current_statement(active, active, active)
    assert "only contextual external drivers" in message
    assert "no direct operational event is currently active" in message


def test_qualified_but_inactive_events_are_never_folded_into_every_stored_event_is_historical():
    # A mixed-class qualified-but-inactive set must use the "none active"
    # sentence, never the "no current event records" sentence reserved for
    # a genuinely empty current dataset.
    qualified = [_event("direct_operational_event"), _event("external_driver")]
    message = build_dashboard._events_current_statement(qualified, qualified, [])
    assert "No current event records exist" not in message
    assert "none is confirmed active" in message


# ---------------------------------------------------------------------------
# Notices: 4 states
# ---------------------------------------------------------------------------


def _notice(event_id: str = "EVT-1") -> dict:
    return {"event_id": event_id}


def test_no_current_notice_record():
    message = build_dashboard._current_notice_statement([], [], [])
    assert "No current notice record exists" in message


def test_notice_exists_but_not_qualified():
    message = build_dashboard._current_notice_statement([_notice()], [], [])
    assert "none qualifies for current publication" in message


def test_qualified_notice_exists_but_event_inactive():
    qualified = [_notice()]
    message = build_dashboard._current_notice_statement(qualified, qualified, [])
    assert "event(s) they reference are not currently active" in message


def test_qualified_active_notice_exists():
    active = [_notice()]
    message = build_dashboard._current_notice_statement(active, active, active)
    assert "qualified operational notice(s) are recorded below" in message
