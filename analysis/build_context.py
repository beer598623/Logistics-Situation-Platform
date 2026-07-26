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

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
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


#: File suffixes excluded from a directory hash: generated database and
#: temporary files, never a genuine build input (WO-010-R6 §5).
_EXCLUDED_DIRECTORY_SUFFIXES = frozenset({".duckdb", ".duckdb.wal", ".tmp"})


def hash_directory(path: Path) -> str | None:
    """One deterministic digest over every hashable file under ``path``
    (WO-010-R6 §5).

    Used where a Build Context input is a directory of files (collection-run
    manifests, manual-review events, reference dimensions) rather than a
    single file. Files are visited in sorted relative-path order so the
    result never depends on filesystem iteration order; both the relative
    path and the file's bytes feed the hash, so a rename and a content
    change are both visible, and two directories with the same files in a
    different layout still hash identically only if every relative path
    matches too. Generated database files and temporary files are excluded
    -- they are build *output*, not input. Returns ``None`` when the
    directory does not exist or contains no hashable files, the same
    "nothing to hash" signal a missing single input file already gives.
    """
    if not path.exists():
        return None
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and not any(candidate.name.endswith(suffix) for suffix in _EXCLUDED_DIRECTORY_SUFFIXES)
    )
    if not files:
        return None
    digest = hashlib.sha256()
    for file_path in files:
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


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


#: Valid values for ``generation_time_basis`` (WO-010-R6 §7).
OBSERVED_BUILD_TIME = "observed_build_time"
PERSISTED_REBUILD_TIME = "persisted_rebuild_time"
LEGACY_MIGRATED = "legacy_migrated"

GENERATION_TIME_BASES = (OBSERVED_BUILD_TIME, PERSISTED_REBUILD_TIME, LEGACY_MIGRATED)


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
    generation_time_basis: str = OBSERVED_BUILD_TIME,
) -> dict[str, Any]:
    """Assemble one Build Context record.

    ``build_context_id`` is derived from the dataset and the as-of time, not
    randomly generated: rebuilding at the same as-of time for the same
    dataset must always produce the same ID, or a build artifact whose own
    identity changes on every rebuild would defeat the "diff and see nothing
    moved" property the rest of this platform relies on.

    WO-010-R5 §8: ``source_cutoff`` is taken exactly as given -- ``None``
    stays ``None`` in the record rather than silently defaulting to
    ``as_of``. ``as_of_time`` is the analytical cutoff this build was told to
    describe; ``source_cutoff`` is the latest evidence this build actually
    found, and a caller with zero included evidence must be able to say so
    honestly rather than being forced into a value that overstates what was
    found. ``generated_at`` is likewise taken exactly as given -- the caller
    (never this function) decides whether that is a freshly observed instant
    or a reused, previously persisted one; ``datetime.now(UTC)`` here would
    silently reintroduce the wall-clock dependency the caller is responsible
    for avoiding.
    """
    stamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    return {
        "build_context_id": f"BCTX-{dataset.upper()}-{stamp}",
        "dataset": dataset,
        "as_of_time": to_iso(as_of),
        "source_cutoff": to_iso(source_cutoff) if source_cutoff is not None else None,
        "generated_at": to_iso(generated_at) if generated_at is not None else to_iso(as_of),
        "latest_included_collection_run_at": (
            to_iso(latest_collection_run_at) if latest_collection_run_at else None
        ),
        "latest_included_manual_review_at": (
            to_iso(latest_manual_review_at) if latest_manual_review_at else None
        ),
        "methodology_version": methodology_version,
        "input_hashes": dict(input_hashes or {}),
        "generation_time_basis": generation_time_basis,
    }


def context_problems(
    context: Mapping[str, Any],
    *,
    previous_context: Mapping[str, Any] | None = None,
    legacy_migration: bool = False,
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

    WO-010-R5 §8 adds:

    * ``source_cutoff`` later than ``as_of_time`` -- evidence cannot be
      known to exist after the analytical moment it is being cited to
      support.
    * ``generated_at`` earlier than ``latest_included_collection_run_at`` or
      ``latest_included_manual_review_at`` -- a context cannot have been
      written before the acquisition event it includes happened.
    * either latest-included timestamp later than ``as_of_time`` -- would
      mean a run or review this build treated as included was, in fact,
      from after the moment it is being included "as of".
    * a non-null ``source_cutoff`` when neither latest-included timestamp is
      set -- a source cutoff must trace back to at least one included
      acquisition event; one that does not is not honestly derived.
    * the same ``build_context_id`` as ``previous_context`` but different
      ``input_hashes`` -- an identity implying "the same, reproducible
      context" while the underlying data actually changed. Suppressed when
      ``legacy_migration`` is true (WO-010-R6 §7): the one-time upgrade of a
      pre-R6 context (no ``generation_time_basis`` at all) to hash
      additional acquisition/reference inputs legitimately changes
      ``input_hashes`` under an unchanged ``build_context_id``, without the
      underlying data itself having changed -- that is the migration the
      work order asks for, not the drift this rule otherwise catches.
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

    basis = context.get("generation_time_basis")
    if basis not in GENERATION_TIME_BASES:
        problems.append(f"generation_time_basis {basis!r} is not a recognised value")

    source_cutoff_raw = context.get("source_cutoff")
    source_cutoff = parse_timestamp(source_cutoff_raw) if source_cutoff_raw else None
    if source_cutoff is not None and source_cutoff > as_of:
        problems.append("source_cutoff is later than as_of_time, which cannot be honestly cited")

    latest_run_raw = context.get("latest_included_collection_run_at")
    latest_run = parse_timestamp(latest_run_raw) if latest_run_raw else None
    latest_review_raw = context.get("latest_included_manual_review_at")
    latest_review = parse_timestamp(latest_review_raw) if latest_review_raw else None

    for label, value in (
        ("latest_included_collection_run_at", latest_run),
        ("latest_included_manual_review_at", latest_review),
    ):
        if value is not None and value > as_of:
            problems.append(f"{label} is later than as_of_time")
        if value is not None and value > generated_at:
            problems.append(f"generated_at is earlier than {label}, which is not yet possible")

    if source_cutoff is not None and latest_run is None and latest_review is None:
        problems.append(
            "source_cutoff is set but neither latest_included_collection_run_at nor "
            "latest_included_manual_review_at is; a source cutoff must trace back to at "
            "least one included acquisition event"
        )

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

    if (
        not legacy_migration
        and previous_context is not None
        and previous_context.get("build_context_id") == context.get("build_context_id")
        and previous_context.get("input_hashes") != context.get("input_hashes")
    ):
        problems.append(
            f"build_context_id {context.get('build_context_id')!r} is unchanged from the "
            "previous context but input_hashes differ; the same context ID must not describe "
            "two different sets of underlying data"
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
