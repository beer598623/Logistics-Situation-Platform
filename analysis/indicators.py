"""Time-series derivation for Logistics indicators.

The single governing rule in this module: **a missing observation is never a
zero**. Every derivation that cannot be computed because an input period is
missing, suppressed, unpublished or failed to retrieve returns ``None`` and
records the reason, and every count of "how many periods did this actually
use" is reported alongside the result so a reader can see how thin the
evidence is.

The module is source-agnostic and mode-agnostic: it takes observation
records in the shape defined by ``schemas/observation_common.schema.json``
and knows nothing about Ocean, ports, or Thailand.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

#: Number of periods in the trailing average the platform publishes. Three is
#: short enough to stay responsive on a monthly series and long enough to
#: damp a single revision.
ROLLING_WINDOW = 3


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@dataclass(slots=True, frozen=True)
class SeriesPoint:
    """One period of a series, including periods with no usable value."""

    period_start: str | None
    period_end: str | None
    period_type: str
    value: float | None
    value_status: str
    unit: str | None
    currency: str | None
    published_at: str | None
    retrieved_at: str
    revised_at: str | None
    revision_number: int
    evidence_class: str
    record_id: str
    source_id: str

    @property
    def is_available(self) -> bool:
        return self.value_status == "available" and self.value is not None

    @property
    def end_date(self) -> date | None:
        return _parse_date(self.period_end)


@dataclass(slots=True)
class Freshness:
    status: str
    as_of: str | None
    age_days: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SeriesDerivation:
    """Derived readings for one series, with explicit gap accounting."""

    series_id: str
    unit: str | None
    currency: str | None
    period_type: str
    current_value: float | None
    current_period: str | None
    previous_period_change: float | None
    previous_period_change_pct: float | None
    month_over_month_pct: float | None
    year_over_year_pct: float | None
    rolling_average: float | None
    rolling_window_used: int
    baseline_definition: str | None
    deviation_from_baseline: float | None
    freshness: Freshness
    revision_status: str
    periods_total: int
    periods_available: int
    periods_missing: int
    missing_periods: list[str] = field(default_factory=list)
    evidence_classes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["freshness"] = self.freshness.to_dict()
        return data


def to_points(observations: Iterable[Mapping[str, Any]]) -> list[SeriesPoint]:
    """Convert raw observation records into ordered series points.

    Records with no ``period_end`` cannot be ordered and are dropped, but the
    caller sees that through ``periods_total`` in the derivation rather than
    through a silent shortening of the series.
    """
    points: list[SeriesPoint] = []
    for record in observations:
        provenance = record["provenance"]
        measurement = record["measurement"]
        points.append(
            SeriesPoint(
                period_start=provenance.get("period_start"),
                period_end=provenance.get("period_end"),
                period_type=provenance.get("period_type", "month"),
                value=measurement.get("value"),
                value_status=measurement.get("value_status", "missing"),
                unit=measurement.get("unit"),
                currency=measurement.get("currency"),
                published_at=provenance.get("published_at"),
                retrieved_at=provenance["retrieved_at"],
                revised_at=provenance.get("revised_at"),
                revision_number=int(provenance.get("revision_number", 0)),
                evidence_class=provenance["evidence_class"],
                record_id=provenance["record_id"],
                source_id=provenance["source_id"],
            )
        )
    return sorted(
        (point for point in points if point.end_date is not None),
        key=lambda point: point.end_date,  # type: ignore[arg-type,return-value]
    )


def _pct_change(current: float, previous: float) -> float | None:
    """Percentage change, or ``None`` when the basis is zero.

    A zero basis makes percentage change undefined rather than infinite, and
    undefined must surface as a gap, not as a very large number.
    """
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def _months_between(later: date, earlier: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _find_offset_point(
    points: Sequence[SeriesPoint],
    current: SeriesPoint,
    *,
    months: int,
) -> SeriesPoint | None:
    """Find the available point exactly ``months`` before ``current``.

    Exactness matters: substituting "the nearest earlier period we happen to
    have" would silently compare a January reading against an October one and
    label the result a year-over-year change.
    """
    current_end = current.end_date
    if current_end is None:
        return None
    for point in points:
        end = point.end_date
        if end is None or not point.is_available:
            continue
        if _months_between(current_end, end) == months:
            return point
    return None


def evaluate_freshness(
    latest_point: SeriesPoint | None,
    *,
    max_stale_minutes: int,
    expected_cadence_minutes: int | None = None,
    now: datetime | None = None,
) -> Freshness:
    """Classify series freshness using the same boundaries as source health.

    A series with no usable point at all is ``no_data`` -- never ``fresh``
    with a zero age.
    """
    moment = now or datetime.now(UTC)
    if latest_point is None:
        return Freshness(status="no_data", as_of=None, age_days=None)

    reference = _parse_timestamp(latest_point.published_at) or _parse_timestamp(
        latest_point.retrieved_at
    )
    if reference is None:
        return Freshness(status="no_data", as_of=None, age_days=None)

    age_minutes = (moment - reference).total_seconds() / 60.0
    age_days = round(age_minutes / 1440.0, 2)
    fresh_boundary = (
        expected_cadence_minutes
        if isinstance(expected_cadence_minutes, int) and expected_cadence_minutes > 0
        else max(1, max_stale_minutes // 2)
    )
    if age_minutes <= fresh_boundary:
        status = "fresh"
    elif age_minutes <= max_stale_minutes:
        status = "stale"
    else:
        status = "very_stale"
    return Freshness(
        status=status,
        as_of=reference.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        age_days=age_days,
    )


def derive_series(
    series_id: str,
    observations: Iterable[Mapping[str, Any]],
    *,
    baseline_definition: str | None = None,
    baseline_value: float | None = None,
    max_stale_minutes: int = 52560,
    expected_cadence_minutes: int | None = None,
    now: datetime | None = None,
) -> SeriesDerivation:
    """Derive the published readings for one series.

    Deviation from baseline is computed only when the caller supplies an
    explicit ``baseline_definition``. A series whose baseline is undefined
    gets ``deviation_from_baseline=None`` and a recorded limitation, because
    a deviation against an unstated baseline is not interpretable.
    """
    points = to_points(observations)
    available = [point for point in points if point.is_available]
    missing = [point for point in points if not point.is_available]
    limitations: list[str] = []

    current = available[-1] if available else None
    current_value = current.value if current else None

    previous_change: float | None = None
    previous_change_pct: float | None = None
    if current is not None and len(available) >= 2:
        previous = available[-2]
        assert previous.value is not None  # guaranteed by is_available
        assert current.value is not None
        previous_change = current.value - previous.value
        previous_change_pct = _pct_change(current.value, previous.value)
        if previous_change_pct is None:
            limitations.append(
                "Previous-period percentage change is undefined because the earlier "
                "value is zero; the absolute change is reported instead."
            )
    elif current is not None:
        limitations.append(
            "Only one usable observation exists, so no period-over-period change can "
            "be computed. This is a data gap, not an unchanged series."
        )

    mom_pct: float | None = None
    yoy_pct: float | None = None
    if current is not None and current.period_type == "month":
        prior_month = _find_offset_point(available, current, months=1)
        if prior_month is not None and prior_month.value:
            assert current.value is not None
            mom_pct = _pct_change(current.value, prior_month.value)
        elif prior_month is None:
            limitations.append(
                "Month-over-month change is unavailable because the immediately "
                "preceding month has no usable observation."
            )
        prior_year = _find_offset_point(available, current, months=12)
        if prior_year is not None and prior_year.value:
            assert current.value is not None
            yoy_pct = _pct_change(current.value, prior_year.value)
        elif prior_year is None:
            limitations.append(
                "Year-over-year change is unavailable because the same period one "
                "year earlier has no usable observation."
            )
    elif current is not None:
        mom_pct = previous_change_pct
        limitations.append(
            f"Series period type is '{current.period_type}', not 'month'; the "
            "period-over-period change is reported in place of a calendar "
            "month-over-month change."
        )

    window = available[-ROLLING_WINDOW:]
    rolling_average: float | None = None
    if len(window) == ROLLING_WINDOW:
        rolling_average = sum(point.value for point in window) / ROLLING_WINDOW  # type: ignore[misc]
    elif window:
        limitations.append(
            f"Rolling average needs {ROLLING_WINDOW} usable observations but only "
            f"{len(window)} are available; no rolling average is published."
        )

    deviation: float | None = None
    if baseline_definition is None:
        if current is not None:
            limitations.append(
                "No baseline is defined for this series, so no deviation from baseline "
                "is published."
            )
    elif current is not None and baseline_value is not None:
        assert current.value is not None
        deviation = current.value - baseline_value

    revision_status = "unknown"
    if current is not None:
        if current.revised_at or current.revision_number > 0:
            revision_status = "revised"
        else:
            revision_status = "original"

    if missing:
        limitations.append(
            f"{len(missing)} of {len(points)} periods have no usable value and are "
            "excluded from every derivation; they are not treated as zero."
        )

    return SeriesDerivation(
        series_id=series_id,
        unit=current.unit if current else next((p.unit for p in points), None),
        currency=current.currency if current else next((p.currency for p in points), None),
        period_type=current.period_type if current else "month",
        current_value=current_value,
        current_period=current.period_end if current else None,
        previous_period_change=previous_change,
        previous_period_change_pct=previous_change_pct,
        month_over_month_pct=mom_pct,
        year_over_year_pct=yoy_pct,
        rolling_average=rolling_average,
        rolling_window_used=len(window) if len(window) == ROLLING_WINDOW else 0,
        baseline_definition=baseline_definition,
        deviation_from_baseline=deviation,
        freshness=evaluate_freshness(
            current,
            max_stale_minutes=max_stale_minutes,
            expected_cadence_minutes=expected_cadence_minutes,
            now=now,
        ),
        revision_status=revision_status,
        periods_total=len(points),
        periods_available=len(available),
        periods_missing=len(missing),
        missing_periods=[point.period_end for point in missing if point.period_end],
        evidence_classes=sorted({point.evidence_class for point in points}),
        limitations=limitations,
    )


def change_for_basis(derivation: SeriesDerivation, basis: str) -> tuple[float | None, int]:
    """Return the change value a threshold rule's basis needs, plus the
    number of observations that were actually available to compute it."""
    if basis == "previous_period":
        return derivation.previous_period_change_pct, derivation.periods_available
    if basis == "month_over_month":
        return derivation.month_over_month_pct, derivation.periods_available
    if basis == "year_over_year":
        return derivation.year_over_year_pct, derivation.periods_available
    if basis == "absolute_deviation":
        return derivation.deviation_from_baseline, derivation.periods_available
    raise ValueError(f"Unknown threshold basis: {basis}")
