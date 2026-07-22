from __future__ import annotations

from datetime import UTC, datetime, timedelta

from collectors.source_health import evaluate_registry_health, evaluate_source_health

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


def _contract(**overrides: object) -> dict:
    base = {
        "id": "TEST_SRC",
        "enabled": True,
        "expected_cadence_minutes": 60,
        "max_stale_minutes": 180,
        "required_for_publication": False,
        "purposes": ["hazard_detection"],
    }
    base.update(overrides)
    return base


def _run(minutes_ago: int, status: str = "success", **overrides: object) -> dict:
    completed = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    run = {
        "source_id": "TEST_SRC",
        "status": status,
        "completed_at": completed,
        "records_emitted": 3,
        "errors": [],
    }
    run.update(overrides)
    return run


def test_fresh_source_within_cadence() -> None:
    health = evaluate_source_health(_contract(), [_run(10)], now=NOW)
    assert health.status == "fresh"
    assert health.item_count == 3


def test_stale_source_past_cadence_within_max_stale() -> None:
    health = evaluate_source_health(_contract(), [_run(120)], now=NOW)
    assert health.status == "stale"


def test_very_stale_source_past_max_stale() -> None:
    health = evaluate_source_health(_contract(), [_run(400)], now=NOW)
    assert health.status == "very_stale"


def test_no_data_when_no_run_ever_recorded() -> None:
    health = evaluate_source_health(_contract(), [], now=NOW)
    assert health.status == "no_data"
    assert health.item_count is None
    assert health.last_checked_at is None
    assert health.last_success_at is None


def test_disabled_source_stays_disabled_even_with_runs() -> None:
    health = evaluate_source_health(_contract(enabled=False), [_run(5)], now=NOW)
    assert health.status == "disabled"


def test_error_is_distinguished_from_no_data() -> None:
    health = evaluate_source_health(
        _contract(), [_run(5, status="error", errors=["timeout"], records_emitted=None)], now=NOW
    )
    assert health.status == "error"
    assert health.status != "no_data"
    assert health.last_error == "timeout"


def test_error_preserves_prior_success_time_separately_from_check_time() -> None:
    success = _run(500)
    error = _run(1, status="error", errors=["connection reset"], records_emitted=None)
    health = evaluate_source_health(_contract(), [success, error], now=NOW)
    assert health.status == "error"
    assert health.last_success_at is not None
    assert health.last_checked_at is not None
    assert health.last_success_at != health.last_checked_at


def test_no_data_is_never_reported_as_zero_item_count() -> None:
    health = evaluate_source_health(_contract(), [], now=NOW)
    assert health.item_count is None
    assert health.item_count != 0

    error_health = evaluate_source_health(
        _contract(), [_run(1, status="error", errors=["boom"], records_emitted=None)], now=NOW
    )
    assert error_health.item_count is None
    assert error_health.item_count != 0


def test_coverage_sufficient_when_a_live_source_backs_the_capability() -> None:
    registry = {"sources": [_contract()]}
    snapshot = evaluate_registry_health(registry, {"TEST_SRC": [_run(10)]}, now=NOW)
    assert snapshot["overall_status"] == "sufficient"
    capability = next(c for c in snapshot["capabilities"] if c["capability"] == "hazard_detection")
    assert capability["status"] == "sufficient"


def test_coverage_degrades_to_limited_when_source_goes_very_stale() -> None:
    registry = {"sources": [_contract()]}
    snapshot = evaluate_registry_health(registry, {"TEST_SRC": [_run(400)]}, now=NOW)
    assert snapshot["overall_status"] == "limited"
    capability = next(c for c in snapshot["capabilities"] if c["capability"] == "hazard_detection")
    assert capability["status"] == "limited"


def test_coverage_is_insufficient_when_a_required_source_has_no_data() -> None:
    registry = {"sources": [_contract(required_for_publication=True)]}
    snapshot = evaluate_registry_health(registry, {}, now=NOW)
    assert snapshot["overall_status"] == "insufficient"
    capability = next(c for c in snapshot["capabilities"] if c["capability"] == "hazard_detection")
    assert capability["status"] == "insufficient"


def test_a_failing_source_only_affects_capabilities_it_backs() -> None:
    registry = {
        "sources": [
            _contract(id="DOWN_SRC", purposes=["hazard_detection"], required_for_publication=True),
            _contract(id="UP_SRC", purposes=["cost_context"]),
        ]
    }
    snapshot = evaluate_registry_health(registry, {"UP_SRC": [_run(5)]}, now=NOW)
    hazard = next(c for c in snapshot["capabilities"] if c["capability"] == "hazard_detection")
    cost = next(c for c in snapshot["capabilities"] if c["capability"] == "cost_context")
    assert hazard["status"] == "insufficient"
    assert cost["status"] == "sufficient"
    # A required source failing overall must not be masked as sufficient.
    assert snapshot["overall_status"] != "sufficient"


def test_registered_but_disabled_source_is_not_publication_critical_by_default() -> None:
    registry = {"sources": [_contract(enabled=False, required_for_publication=False)]}
    snapshot = evaluate_registry_health(registry, {}, now=NOW)
    # Existing disabled sources stay disabled and do not force insufficient
    # for capabilities nobody has declared required, but the capability
    # itself has no live coverage.
    source = snapshot["sources"][0]
    assert source["status"] == "disabled"
