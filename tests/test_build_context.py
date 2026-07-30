"""The reproducible current Build Context (WO-010-R4 §6)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.build_context import (  # noqa: E402
    DEFAULT_CURRENT_AS_OF_ISO,
    build_context_record,
    context_problems,
    exclude_future_dated,
    latest_timestamp,
    resolve_current_as_of,
)
from analysis.contracts import schema_errors  # noqa: E402
from analysis.provenance import CURRENT_PUBLICATION, TECHNICAL_DEMO  # noqa: E402

# ---------------------------------------------------------------------------
# Resolution precedence
# ---------------------------------------------------------------------------


def test_an_explicit_as_of_always_wins():
    resolved = resolve_current_as_of(
        "2027-01-01T00:00:00Z",
        previous_context={"dataset": CURRENT_PUBLICATION, "as_of_time": "2026-08-01T00:00:00Z"},
    )
    assert resolved == datetime(2027, 1, 1, tzinfo=UTC)


def test_no_explicit_value_carries_forward_the_previous_context():
    resolved = resolve_current_as_of(
        None,
        previous_context={"dataset": CURRENT_PUBLICATION, "as_of_time": "2026-08-01T00:00:00Z"},
    )
    assert resolved == datetime(2026, 8, 1, tzinfo=UTC)


def test_a_demo_previous_context_is_not_carried_forward_for_current():
    resolved = resolve_current_as_of(
        None, previous_context={"dataset": TECHNICAL_DEMO, "as_of_time": "2026-08-01T00:00:00Z"}
    )
    assert resolved == datetime.fromisoformat(DEFAULT_CURRENT_AS_OF_ISO.replace("Z", "+00:00"))


def test_with_nothing_at_all_the_committed_default_is_used():
    resolved = resolve_current_as_of(None, previous_context=None)
    assert resolved == datetime.fromisoformat(DEFAULT_CURRENT_AS_OF_ISO.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Assembly and schema
# ---------------------------------------------------------------------------


def test_the_context_record_is_deterministic_for_the_same_inputs():
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    generated = datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
    first = build_context_record(dataset=CURRENT_PUBLICATION, as_of=as_of, generated_at=generated)
    second = build_context_record(dataset=CURRENT_PUBLICATION, as_of=as_of, generated_at=generated)
    assert first == second
    assert first["build_context_id"] == "BCTX-CURRENT_PUBLICATION-20260801T000000Z"


def test_the_context_record_satisfies_its_own_schema():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        latest_collection_run_at=datetime(2026, 7, 30, tzinfo=UTC),
        latest_manual_review_at=None,
        input_hashes={"trade_observations": "a" * 64},
    )
    assert schema_errors(context, "build_context.schema.json") == []


# ---------------------------------------------------------------------------
# Fail-closed checks
# ---------------------------------------------------------------------------


def test_a_context_generated_before_its_own_as_of_time_is_rejected():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    problems = context_problems(context)
    assert any("later than generated_at" in item for item in problems), problems


def test_a_regressed_as_of_time_is_rejected():
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 8, 1, tzinfo=UTC)
    )
    regressed = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 7, 25, tzinfo=UTC)
    )
    problems = context_problems(regressed, previous_context=previous)
    assert any("regresses behind" in item for item in problems), problems


def test_an_equal_or_advancing_as_of_time_is_not_a_regression():
    generated = datetime(2026, 8, 3, tzinfo=UTC)
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 8, 1, tzinfo=UTC), generated_at=generated
    )
    same = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 8, 1, tzinfo=UTC), generated_at=generated
    )
    later = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 8, 2, tzinfo=UTC), generated_at=generated
    )
    assert context_problems(same, previous_context=previous) == []
    assert context_problems(later, previous_context=previous) == []


def test_a_demo_context_never_regression_checks_against_a_current_previous():
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=datetime(2026, 8, 1, tzinfo=UTC)
    )
    demo = build_context_record(dataset=TECHNICAL_DEMO, as_of=datetime(2020, 1, 1, tzinfo=UTC))
    assert context_problems(demo, previous_context=previous) == []


def test_an_unrecognised_dataset_is_rejected():
    context = build_context_record(
        dataset="not_a_real_dataset", as_of=datetime(2026, 8, 1, tzinfo=UTC)
    )
    problems = context_problems(context)
    assert any("not a recognised publication surface" in item for item in problems), problems


# ---------------------------------------------------------------------------
# Future-dated record exclusion
# ---------------------------------------------------------------------------


def test_future_dated_records_are_excluded_not_published():
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    records = [
        {"id": "past", "published_at": "2026-07-30T00:00:00Z"},
        {"id": "future", "published_at": "2026-08-05T00:00:00Z"},
        {"id": "undated"},
    ]
    included, excluded = exclude_future_dated(
        records, as_of=as_of, timestamp_of=lambda r: r.get("published_at")
    )
    assert {item["id"] for item in included} == {"past", "undated"}
    assert {item["id"] for item in excluded} == {"future"}


def test_latest_timestamp_ignores_undated_records():
    records = [
        {"id": "a", "published_at": "2026-07-20T00:00:00Z"},
        {"id": "b"},
        {"id": "c", "published_at": "2026-07-25T00:00:00Z"},
    ]
    latest = latest_timestamp(records, timestamp_of=lambda r: r.get("published_at"))
    assert latest == datetime(2026, 7, 25, tzinfo=UTC)


def test_latest_timestamp_of_nothing_is_none():
    assert latest_timestamp([], timestamp_of=lambda r: None) is None


# ---------------------------------------------------------------------------
# WO-010-R5 §8: source_cutoff and generated_at semantics
# ---------------------------------------------------------------------------


def test_source_cutoff_is_null_when_not_given():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert context["source_cutoff"] is None
    assert schema_errors(context, "build_context.schema.json") == []


def test_generated_at_defaults_to_as_of_not_the_wall_clock():
    """Never observed 'now' implicitly: with no explicit generated_at, the
    record uses as_of_time itself rather than a fresh datetime.now() call,
    which would make the committed artifact non-reproducible."""
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    first = build_context_record(dataset=CURRENT_PUBLICATION, as_of=as_of)
    second = build_context_record(dataset=CURRENT_PUBLICATION, as_of=as_of)
    assert first == second
    assert first["generated_at"] == first["as_of_time"]


def test_a_non_null_source_cutoff_with_zero_included_evidence_is_rejected():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_cutoff=datetime(2026, 7, 30, tzinfo=UTC),
        # Neither latest_collection_run_at nor latest_manual_review_at set.
    )
    problems = context_problems(context)
    assert any("source_cutoff is set but neither" in item for item in problems), problems


def test_source_cutoff_later_than_as_of_is_rejected():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        generated_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_cutoff=datetime(2026, 8, 2, tzinfo=UTC),
        latest_collection_run_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    problems = context_problems(context)
    assert any("source_cutoff is later than as_of_time" in item for item in problems), problems


def test_a_latest_included_run_after_as_of_is_rejected():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        generated_at=datetime(2026, 8, 5, tzinfo=UTC),
        latest_collection_run_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    problems = context_problems(context)
    assert any(
        "latest_included_collection_run_at is later than as_of_time" in item for item in problems
    ), problems


def test_generated_at_before_the_latest_included_run_is_rejected():
    context = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=datetime(2026, 8, 5, tzinfo=UTC),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        latest_collection_run_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    problems = context_problems(context)
    assert any(
        "generated_at is earlier than latest_included_collection_run_at" in item
        for item in problems
    ), problems


def test_a_reused_context_id_with_changed_input_hashes_is_rejected():
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=as_of,
        generated_at=as_of,
        input_hashes={"trade_observations": "a" * 64},
    )
    rebuilt = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=as_of,
        generated_at=as_of,
        input_hashes={"trade_observations": "b" * 64},
    )
    problems = context_problems(rebuilt, previous_context=previous)
    assert any("input_hashes differ" in item for item in problems), problems


def test_a_reused_context_id_with_identical_input_hashes_is_not_a_regression():
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    hashes = {"trade_observations": "a" * 64}
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=as_of, generated_at=as_of, input_hashes=hashes
    )
    rebuilt = build_context_record(
        dataset=CURRENT_PUBLICATION, as_of=as_of, generated_at=as_of, input_hashes=hashes
    )
    assert context_problems(rebuilt, previous_context=previous) == []


def test_a_rebuild_with_identical_inputs_reuses_the_persisted_generated_at():
    """WO-010-R5 §8 positive path: scripts/build_analysis.py's own logic
    (reproduced here at the level this module actually controls) -- reusing
    a previously-committed context's generated_at when the build_context_id
    and input_hashes are unchanged, rather than overwriting it with a new
    instant, is what keeps a bare rebuild byte-identical without pretending
    the record was generated at its own as-of time."""
    as_of = datetime(2026, 8, 1, tzinfo=UTC)
    original_generated_at = datetime(2026, 8, 1, 3, 30, tzinfo=UTC)
    hashes = {"trade_observations": "a" * 64}
    previous = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=as_of,
        generated_at=original_generated_at,
        input_hashes=hashes,
    )

    prospective_id = f"BCTX-{CURRENT_PUBLICATION.upper()}-{as_of:%Y%m%dT%H%M%SZ}"
    if (
        previous.get("build_context_id") == prospective_id
        and previous.get("input_hashes") == hashes
    ):
        reused_generated_at = datetime.fromisoformat(
            previous["generated_at"].replace("Z", "+00:00")
        )
    else:
        reused_generated_at = datetime(2099, 1, 1, tzinfo=UTC)  # would prove the reuse failed

    rebuilt = build_context_record(
        dataset=CURRENT_PUBLICATION,
        as_of=as_of,
        generated_at=reused_generated_at,
        input_hashes=hashes,
    )
    assert rebuilt == previous
    assert rebuilt["generated_at"] == "2026-08-01T03:30:00Z"
