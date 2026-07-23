from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate import source_status_checks  # noqa: E402


def _status(overall: str, sources: list[dict], capabilities: list[dict]) -> dict:
    return {"overall_status": overall, "sources": sources, "capabilities": capabilities}


def test_sufficient_capability_with_degraded_required_source_is_rejected() -> None:
    """Regression for review finding #1, checked at the validation layer too:
    a capability cannot be reported ``sufficient`` while one of its
    ``required_for_publication`` supporting sources is not fresh/stale."""
    status = _status(
        overall="sufficient",
        sources=[
            {
                "source_id": "A",
                "status": "fresh",
                "required_for_publication": False,
                "item_count": 1,
            },
            {
                "source_id": "B",
                "status": "no_data",
                "required_for_publication": True,
                "item_count": None,
            },
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "sufficient",
                "supporting_sources": ["A", "B"],
                "gap_reason": None,
            }
        ],
    )
    problems = source_status_checks(status)
    assert any("degraded required supporting source" in problem for problem in problems)
    assert any("must force overall_status to insufficient" in problem for problem in problems)


def test_overall_sufficient_with_required_gap_is_rejected() -> None:
    """Round-2 regression: a degraded required source must force
    ``overall_status == "insufficient"``, so ``sufficient`` is rejected."""
    status = _status(
        overall="sufficient",
        sources=[
            {
                "source_id": "B",
                "status": "no_data",
                "required_for_publication": True,
                "item_count": None,
            }
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "insufficient",
                "supporting_sources": ["B"],
                "gap_reason": "x",
            }
        ],
    )
    problems = source_status_checks(status)
    assert any(
        "must force overall_status to insufficient" in problem and "'sufficient'" in problem
        for problem in problems
    )


def test_overall_limited_with_required_gap_is_rejected() -> None:
    """Round-2 regression for review finding #1: a hand-edited or stale
    snapshot with a degraded required source and ``overall_status: limited``
    must also be rejected, not just ``sufficient`` — ``_overall_status`` can
    only ever produce ``insufficient`` when a required source has a gap, so
    ``limited`` in that situation cannot have come from the canonical
    evaluator and must fail validation too."""
    status = _status(
        overall="limited",
        sources=[
            {
                "source_id": "B",
                "status": "very_stale",
                "required_for_publication": True,
                "item_count": 1,
            }
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "insufficient",
                "supporting_sources": ["B"],
                "gap_reason": "x",
            }
        ],
    )
    problems = source_status_checks(status)
    assert any(
        "must force overall_status to insufficient" in problem and "'limited'" in problem
        for problem in problems
    )


def test_degraded_required_source_must_make_capability_insufficient() -> None:
    status = _status(
        overall="limited",
        sources=[
            {
                "source_id": "B",
                "status": "error",
                "required_for_publication": True,
                "item_count": None,
            }
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "limited",
                "supporting_sources": ["B"],
                "gap_reason": "x",
            }
        ],
    )
    problems = source_status_checks(status)
    assert any("must make coverage insufficient" in problem for problem in problems)


def test_healthy_required_source_passes_cleanly() -> None:
    status = _status(
        overall="sufficient",
        sources=[
            {"source_id": "A", "status": "fresh", "required_for_publication": True, "item_count": 2}
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "sufficient",
                "supporting_sources": ["A"],
                "gap_reason": None,
            }
        ],
    )
    assert source_status_checks(status) == []


def test_gap_never_reported_as_zero_item_count() -> None:
    status = _status(
        overall="insufficient",
        sources=[
            {
                "source_id": "A",
                "status": "no_data",
                "required_for_publication": False,
                "item_count": 0,
            }
        ],
        capabilities=[
            {
                "capability": "cap",
                "status": "insufficient",
                "supporting_sources": ["A"],
                "gap_reason": "x",
            }
        ],
    )
    problems = source_status_checks(status)
    assert any("must never be represented as zero items" in problem for problem in problems)
