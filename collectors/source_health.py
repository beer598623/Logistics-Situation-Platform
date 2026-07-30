"""Deterministic source-health and coverage evaluation.

This module turns a Source Contract (``config/sources.yaml``) and the latest
known Collection Run manifests for that source into a ``SourceHealth``
record, then rolls per-source health up into a purpose-aware coverage
snapshot. It performs no network access and does not infer operational
impact; it only reports whether intelligence inputs are fresh, stale, or
missing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .models import SourceHealth, SourceStatus

CoverageStatus = str  # "sufficient" | "limited" | "insufficient"

_SUCCESS_RUN_STATUSES = {"success", "not_modified"}


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _run_completed_at(run: Mapping[str, Any]) -> datetime | None:
    return _parse_timestamp(run.get("completed_at"))


def _latest_run(
    runs: Sequence[Mapping[str, Any]], *, now: datetime | None = None
) -> Mapping[str, Any] | None:
    """The most recent run, excluding any whose ``completed_at`` is later than
    ``now``.

    WO-010-R4 §6: without this exclusion, a future-dated run (a clock error,
    a bad backfill, or an as-of time explicitly set earlier than a run's
    timestamp) would make ``age_minutes`` negative in the freshness
    computation below -- and a negative age is trivially "fresh", so the
    source would be reported fresher than any real run could ever make it.
    A run this build's as-of time has not reached yet is treated exactly
    like a run that has not happened yet, because as of this build, it has
    not: it simply is not counted as the latest run at all.
    """
    dated = [(run, _run_completed_at(run)) for run in runs]
    dated = [pair for pair in dated if pair[1] is not None]
    if now is not None:
        dated = [pair for pair in dated if pair[1] <= now]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[1])[0]


def _latest_success_run(
    runs: Sequence[Mapping[str, Any]], *, now: datetime | None = None
) -> Mapping[str, Any] | None:
    successes = [run for run in runs if run.get("status") in _SUCCESS_RUN_STATUSES]
    return _latest_run(successes, now=now)


def _latest_reviewed_event(
    events: Sequence[Mapping[str, Any]], *, now: datetime | None = None
) -> Mapping[str, Any] | None:
    """The most recently reviewed event, excluding any future-dated one.

    Same reasoning as :func:`_latest_run`: a ``reviewed_at`` later than this
    build's as-of time must not be able to produce a negative age and read
    as fresher than any real review could make it.
    """
    reviewed = [event for event in events if event.get("status") == "reviewed"]
    dated = [(event, _parse_timestamp(event.get("reviewed_at"))) for event in reviewed]
    dated = [pair for pair in dated if pair[1] is not None]
    if now is not None:
        dated = [pair for pair in dated if pair[1] <= now]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[1])[0]


def _fresh_boundary_minutes(contract: Mapping[str, Any]) -> int:
    cadence = contract.get("expected_cadence_minutes")
    max_stale = int(contract["max_stale_minutes"])
    if isinstance(cadence, int) and cadence > 0:
        return cadence
    return max(1, max_stale // 2)


def _evaluate_manual_source_health(
    contract: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> SourceHealth:
    """Health for a manual-intake source, from recorded review events only.

    A manual-intake contract has no automated collection to be ``enabled``
    or ``disabled`` about; that flag exists in the registry to keep the
    schema uniform, but health here never consults it. Instead:

    * with no review event ever recorded, health matches the registry's own
      ``enabled: false`` starting state (``disabled``) rather than the
      generic ``no_data`` an automated source gets -- there is no automated
      "not yet run" to describe, only "this path has never been used";
    * the moment a human records a bounded transcription, health is
      computed entirely from that event's ``reviewed_at`` timestamp against
      this source's own freshness boundary, never from a collection-run
      manifest (this source has none) and never from the registry flag.

    This is what "manually reviewed intake receives health only through its
    recorded manual review event" means in practice: collection runs for
    this source_id, if any were ever mistakenly supplied, play no part.
    """
    source_id = str(contract["id"])
    max_stale_minutes = int(contract["max_stale_minutes"])
    required_for_publication = bool(contract.get("required_for_publication", False))

    latest = _latest_reviewed_event(events, now=now)
    if latest is None:
        return SourceHealth(
            source_id=source_id,
            status=SourceStatus.DISABLED,
            last_checked_at=None,
            last_success_at=None,
            last_error=None,
            item_count=None,
            required_for_publication=required_for_publication,
            max_stale_minutes=max_stale_minutes,
        )

    reviewed_at = _parse_timestamp(latest.get("reviewed_at"))
    age_minutes = (now - reviewed_at).total_seconds() / 60.0
    fresh_boundary = _fresh_boundary_minutes(contract)
    if age_minutes <= fresh_boundary:
        status = SourceStatus.FRESH
    elif age_minutes <= max_stale_minutes:
        status = SourceStatus.STALE
    else:
        status = SourceStatus.VERY_STALE

    return SourceHealth(
        source_id=source_id,
        status=status,
        last_checked_at=_to_iso(reviewed_at),
        last_success_at=_to_iso(reviewed_at),
        last_error=None,
        item_count=latest.get("record_count"),
        required_for_publication=required_for_publication,
        max_stale_minutes=max_stale_minutes,
    )


def evaluate_source_health(
    contract: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    manual_review_events: Sequence[Mapping[str, Any]] = (),
) -> SourceHealth:
    """Evaluate one source's health from its contract and known collection runs.

    ``runs`` is the full known history of Collection Run manifests for this
    source (may be empty). Missing data is never treated as zero: a source
    with no successful run ever recorded is reported as ``no_data``, and a
    source whose most recent run failed is reported as ``error`` even if it
    previously succeeded, preserving the earlier success time separately.

    A manual-intake source (``access_method: manual``) is routed to
    :func:`_evaluate_manual_source_health` instead: it has no automated runs
    to evaluate, and evaluating it as though it did would either wrongly
    treat "never enabled" the same as "never used" or require a fabricated
    collection-run manifest for something that makes no network request.
    """
    moment = now or datetime.now(UTC)
    source_id = str(contract["id"])
    max_stale_minutes = int(contract["max_stale_minutes"])
    required_for_publication = bool(contract.get("required_for_publication", False))

    if contract.get("access_method") == "manual":
        return _evaluate_manual_source_health(contract, manual_review_events, now=moment)

    latest = _latest_run(runs, now=moment)
    latest_success = _latest_success_run(runs, now=moment)

    last_checked_at = _run_completed_at(latest) if latest else None
    last_success_at = _run_completed_at(latest_success) if latest_success else None
    item_count = latest_success.get("records_emitted") if latest_success else None
    last_error: str | None = None
    if latest and latest.get("status") == "error":
        errors = latest.get("errors") or []
        last_error = errors[-1] if errors else "Source reported an error with no message."

    if not contract.get("enabled", False):
        status = SourceStatus.DISABLED
    elif latest is None:
        status = SourceStatus.NO_DATA
    elif latest.get("status") == "error":
        status = SourceStatus.ERROR
    elif last_success_at is None:
        status = SourceStatus.NO_DATA
    else:
        age_minutes = (moment - last_success_at).total_seconds() / 60.0
        fresh_boundary = _fresh_boundary_minutes(contract)
        if age_minutes <= fresh_boundary:
            status = SourceStatus.FRESH
        elif age_minutes <= max_stale_minutes:
            status = SourceStatus.STALE
        else:
            status = SourceStatus.VERY_STALE

    return SourceHealth(
        source_id=source_id,
        status=status,
        last_checked_at=_to_iso(last_checked_at) if last_checked_at else None,
        last_success_at=_to_iso(last_success_at) if last_success_at else None,
        last_error=last_error,
        item_count=item_count,
        required_for_publication=required_for_publication,
        max_stale_minutes=max_stale_minutes,
    )


@dataclass(slots=True)
class CapabilityCoverage:
    capability: str
    status: CoverageStatus
    supporting_sources: list[str]
    gap_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status,
            "supporting_sources": self.supporting_sources,
            "gap_reason": self.gap_reason,
        }


_LIVE_STATUSES = {SourceStatus.FRESH, SourceStatus.STALE}


def _required_source_gap(healths: Sequence[SourceHealth]) -> bool:
    """True when a source required for publication is not currently live.

    A required source that is stale-but-fresh-enough is fine (it is
    ``fresh``/``stale``, i.e. live); anything else — ``no_data``, ``error``,
    ``very_stale``, or even ``disabled`` — is a publication gap. This check
    must run before any "is something live?" check: a required source
    failing must never be papered over by an unrelated optional source that
    happens to be healthy.
    """
    return any(
        health.required_for_publication and health.status not in _LIVE_STATUSES
        for health in healths
    )


def _capability_coverage(
    capability: str,
    healths: Sequence[SourceHealth],
) -> CapabilityCoverage:
    """Roll up the sources backing one purpose/capability.

    A capability is only as good as the sources that actually back it: a
    source failing does not degrade capabilities it does not serve, and no
    source becomes publication-critical just because it is registered — only
    an explicit ``required_for_publication`` source gap can force
    ``insufficient``. That required-source check runs first, ahead of the
    "is anything live?" check, so a required source failing can never be
    hidden behind an unrelated optional source that happens to be fresh.
    Likewise, one disabled source sharing a capability with an enabled (even
    if degraded) source must not be reported as "nothing backs this
    capability" — that phrasing is reserved for when every supporting
    source is disabled.
    """
    supporting = [health.source_id for health in healths]

    if _required_source_gap(healths):
        return CapabilityCoverage(
            capability,
            "insufficient",
            supporting,
            f"A source required for publication is unavailable for {capability}.",
        )

    if any(health.status in _LIVE_STATUSES for health in healths):
        return CapabilityCoverage(capability, "sufficient", supporting, None)

    if healths and all(health.status == SourceStatus.DISABLED for health in healths):
        return CapabilityCoverage(
            capability,
            "insufficient",
            supporting,
            f"No enabled source currently backs {capability}.",
        )

    return CapabilityCoverage(
        capability,
        "limited",
        supporting,
        f"Sources backing {capability} are degraded or stale.",
    )


def _overall_status(
    coverages: Sequence[CapabilityCoverage], healths: Sequence[SourceHealth]
) -> str:
    if _required_source_gap(healths):
        return "insufficient"
    if not coverages:
        return "insufficient"
    if any(coverage.status == "insufficient" for coverage in coverages):
        return (
            "insufficient"
            if all(coverage.status == "insufficient" for coverage in coverages)
            else "limited"
        )
    if any(coverage.status == "limited" for coverage in coverages):
        return "limited"
    return "sufficient"


def evaluate_registry_health(
    registry: Mapping[str, Any],
    runs_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    now: datetime | None = None,
    manual_events_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate every source in a registry and produce a coverage snapshot.

    The result matches ``schemas/source_status.schema.json``: a per-source
    health list plus a purpose-aware ``capabilities`` breakdown and an
    ``overall_status`` that can only be ``sufficient`` when every capability
    required for publication is actually covered.

    ``runs_by_source`` and ``manual_events_by_source`` should come from
    ``collectors.collection_runs.load_collection_runs`` /
    ``load_manual_review_events`` in every production call -- an empty
    mapping passed here is indistinguishable from "we checked and found
    nothing" and from "nobody ever asked", and only the loader can tell
    those apart from what is actually persisted on disk.
    """
    moment = now or datetime.now(UTC)
    manual_events_by_source = manual_events_by_source or {}
    healths = [
        evaluate_source_health(
            source,
            runs_by_source.get(source["id"], ()),
            now=moment,
            manual_review_events=manual_events_by_source.get(source["id"], ()),
        )
        for source in registry.get("sources", [])
    ]
    health_by_id = {health.source_id: health for health in healths}

    capabilities: dict[str, list[SourceHealth]] = {}
    for source in registry.get("sources", []):
        health = health_by_id[source["id"]]
        for purpose in source.get("purposes", []):
            capabilities.setdefault(purpose, []).append(health)

    coverages = [
        _capability_coverage(capability, capability_healths)
        for capability, capability_healths in sorted(capabilities.items())
    ]
    overall_status = _overall_status(coverages, healths)

    # WO-010-R4 §9: ``insufficient`` must not read as "zero evidence" when
    # some source has actually collected records but a required capability
    # is still uncovered -- those are different operational states, and
    # collapsing them into one sentence hides whether anything has been
    # collected at all.
    if overall_status == "sufficient":
        coverage_message = (
            "Sufficient coverage: all tracked capabilities have fresh or stale source coverage."
        )
    elif overall_status == "limited":
        coverage_message = (
            "Limited coverage: some capabilities have degraded or incomplete source coverage."
        )
    elif any((health.item_count or 0) > 0 for health in healths):
        coverage_message = (
            "Partial evidence but insufficient required coverage: at least one source has "
            "collected records, but one or more capabilities required for publication are "
            "still not sufficiently covered."
        )
    else:
        coverage_message = (
            "Zero evidence: no source has collected any qualifying record, so one or more "
            "capabilities required for publication have no coverage at all."
        )

    return {
        "generated_at": _to_iso(moment),
        "overall_status": overall_status,
        "coverage_message": coverage_message,
        "sources": [health.to_dict() for health in healths],
        "capabilities": [coverage.to_dict() for coverage in coverages],
    }
