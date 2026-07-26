"""Reproducible build context: the single as-of time every current build shares.

WO-010 through R3 pinned "now" to a permanent hard-coded ``DATA_CUTOFF``
constant, for every build, current or demonstration alike. A demonstration
build genuinely should stay pinned: it exercises the engine against fixtures
dated to a fixed point, and re-dating it on every run would make it
non-reproducible for no benefit. A *current* build is different -- its "now"
is supposed to advance as the platform is actually operated -- and a
permanent constant meant nothing in the code would ever notice that it
never did.

WO-010-R4 §6 replaces that constant, for the current-publication dataset
only, with a **Build Context**: a small record resolved once per build
(:func:`resolve_current_as_of`), assembled into a persisted, schema-validated
artifact (:func:`build_context_record`, ``schemas/build_context.schema.json``),
and checked against fail-closed rules (:func:`context_problems`) before
anything downstream trusts it.

``scripts/build_analysis.py`` is the only writer of the current build's
context file. ``scripts/build_dashboard.py`` and ``scripts/
build_review_package.py`` are read-only consumers of that same file -- "the
same as-of time drives Analysis, Source Health, the review package and the
Dashboard" is guaranteed by there being exactly one place that resolves it,
not by convention across three separately-invoked scripts.

Technical-demo and historical-validation builds are untouched: they keep
using the permanently pinned :data:`DEMO_AS_OF` this module also exposes,
because WO-010-R4 explicitly permits (and this platform's own reproducibility
tests require) those two datasets to stay dated to a fixed point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .provenance import CURRENT_PUBLICATION, HISTORICAL_VALIDATION, TECHNICAL_DEMO

#: The committed, reproducible as-of time a current build falls back to when
#: no ``--as-of`` is given and no prior context exists to carry forward. Not
#: a permanent pin -- :func:`resolve_current_as_of` only returns this as a
#: last resort -- but it is exactly what keeps a bare ``python scripts/
#: build_analysis.py`` and CI byte-reproducible, which is the "explicitly
#: committed test/demo context" WO-010-R4 §6 requires CI to use.
DEFAULT_CURRENT_AS_OF_ISO = "2026-07-24T00:00:00Z"

#: The permanently pinned as-of time for technical-demo and
#: historical-validation builds. These describe fixed fixtures at a fixed
#: point and are never meant to advance with the wall clock.
DEMO_AS_OF = datetime(2026, 7, 24, tzinfo=UTC)
DEMO_AS_OF_ISO = DEMO_AS_OF.isoformat().replace("+00:00", "Z")

METHODOLOGY_VERSION = "0.8"

DATASETS = (CURRENT_PUBLICATION, TECHNICAL_DEMO, HISTORICAL_VALIDATION)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, defaulting a naive one to UTC.

    The one timestamp parser every module in this package should share --
    previously duplicated, slightly differently, in half a dozen places.
    """
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def resolve_current_as_of(
    cli_value: str | None,
    *,
    previous_context: Mapping[str, Any] | None = None,
) -> datetime:
    """The as-of time this current build should use.

    Precedence, checked in order:

    1. An explicit ``--as-of`` always wins -- a human said what "now" is for
       this build, and nothing overrides that.
    2. The previously committed context's own as-of time carries forward. A
       rebuild given no new instruction should not silently jump to a
       different notion of "now" than the last one actually published.
    3. The committed default (:data:`DEFAULT_CURRENT_AS_OF_ISO`) keeps a bare
       invocation, and CI, reproducible.
    """
    if cli_value:
        return parse_timestamp(cli_value)
    if previous_context is not None and previous_context.get("dataset") == CURRENT_PUBLICATION:
        as_of = previous_context.get("as_of_time")
        if as_of:
            return parse_timestamp(as_of)
    return parse_timestamp(DEFAULT_CURRENT_AS_OF_ISO)


def build_context_record(
    *,
    dataset: str,
    as_of: datetime,
    source_cutoff: datetime | None = None,
    generated_at: datetime | None = None,
    latest_collection_run_at: datetime | None = None,
    latest_manual_review_at: datetime | None = None,
    methodology_version: str = METHODOLOGY_VERSION,
    input_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble one Build Context record.

    ``build_context_id`` is derived from the dataset and the as-of time, not
    randomly generated: rebuilding at the same as-of time for the same
    dataset must always produce the same ID, or a build artifact whose own
    identity changes on every rebuild would defeat the "diff and see nothing
    moved" property the rest of this platform relies on.
    """
    moment = generated_at or datetime.now(UTC)
    stamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    return {
        "build_context_id": f"BCTX-{dataset.upper()}-{stamp}",
        "dataset": dataset,
        "as_of_time": to_iso(as_of),
        "source_cutoff": to_iso(source_cutoff or as_of),
        "generated_at": to_iso(moment),
        "latest_included_collection_run_at": (
            to_iso(latest_collection_run_at) if latest_collection_run_at else None
        ),
        "latest_included_manual_review_at": (
            to_iso(latest_manual_review_at) if latest_manual_review_at else None
        ),
        "methodology_version": methodology_version,
        "input_hashes": dict(input_hashes or {}),
    }


def context_problems(
    context: Mapping[str, Any],
    *,
    previous_context: Mapping[str, Any] | None = None,
) -> list[str]:
    """Fail-closed checks on a freshly built context, before it is trusted.

    Two regressions are refused here:

    * ``as_of_time`` later than ``generated_at`` -- a build cannot be "as of"
      a moment after it was itself produced.
    * for the current-publication dataset, an ``as_of_time`` older than a
      previously committed context's own ``as_of_time`` -- rebuilding with an
      earlier as-of than what was already published as current would mean
      the new build knows about *less* evidence than the platform already
      told readers it had, which is exactly "an as-of time older than
      included current evidence" and is refused rather than silently
      accepted. Passing an explicit ``--as-of`` at or after the previous
      value supersedes it intentionally and is not a regression.
    """
    problems: list[str] = []
    dataset = context.get("dataset")
    if dataset not in DATASETS:
        problems.append(
            f"build context dataset {dataset!r} is not a recognised publication surface"
        )
        return problems

    as_of = parse_timestamp(context["as_of_time"])
    generated_at = parse_timestamp(context["generated_at"])
    if as_of > generated_at:
        problems.append("as_of_time is later than generated_at, which is not yet possible")

    if (
        dataset == CURRENT_PUBLICATION
        and previous_context is not None
        and previous_context.get("dataset") == CURRENT_PUBLICATION
    ):
        previous_as_of = parse_timestamp(previous_context["as_of_time"])
        if as_of < previous_as_of:
            problems.append(
                f"as_of_time {context['as_of_time']!r} regresses behind the previously "
                f"committed context's as_of_time {previous_context['as_of_time']!r}; pass an "
                "explicit --as-of at or after the previous value to supersede it intentionally"
            )

    return problems


def exclude_future_dated(
    records: Sequence[Any],
    *,
    as_of: datetime,
    timestamp_of: Callable[[Any], str | None],
) -> tuple[list[Any], list[Any]]:
    """Split ``records`` into ``(included, excluded_as_future_dated)``.

    A record with no discoverable timestamp is included -- the absence of a
    timestamp is not evidence the record is from the future. A record whose
    own timestamp is later than the build's as-of time is excluded: it is
    never published as though it were already known "as of" a moment before
    it existed (WO-010-R4 §6, "current records later than the context
    cutoff are excluded").
    """
    included: list[Any] = []
    excluded: list[Any] = []
    for record in records:
        raw = timestamp_of(record)
        timestamp = parse_timestamp(raw) if raw else None
        if timestamp is not None and timestamp > as_of:
            excluded.append(record)
        else:
            included.append(record)
    return included, excluded


def latest_timestamp(
    records: Sequence[Any],
    *,
    timestamp_of: Callable[[Any], str | None],
) -> datetime | None:
    """The latest parseable timestamp among ``records``, or ``None``."""
    timestamps = [timestamp_of(record) for record in records]
    parsed = [parse_timestamp(value) for value in timestamps if value]
    return max(parsed) if parsed else None
