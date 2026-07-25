"""Event lifecycle, clustering, and transmission-chain logic.

Three rules from the scope document are enforced here as code rather than as
guidance:

1. An external driver stays contextual until a Logistics transmission
   mechanism is stated. Completeness is computed from the chain's links, not
   asserted by the author.
2. A discovery source may detect a lead but may never be the sole evidence
   for a material impact conclusion.
3. Unrelated events must not merge merely because they concern the same
   country or the same conflict. Clustering therefore requires a shared
   record, a shared canonical URL, or a combination of type, date, geography
   and either operator identity or controlled title similarity -- never
   geography alone.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collectors.url_redaction import redact_url_userinfo

from .provenance import (
    CURRENT_PUBLICATION,
    PUBLISH_BOUNDED_CLAIM,
    dataset_of,
    qualifies_for_current_publication,
)

#: Query parameters stripped when canonicalizing a URL for clustering. These
#: are campaign/tracking parameters that vary between syndicated copies of
#: the same notice and would otherwise defeat duplicate detection.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "source",
    }
)

#: Tokens removed before title comparison. Deliberately short and generic:
#: an aggressive stopword list would make unrelated titles look similar.
_TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "by",
        "from",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "has",
        "have",
        "after",
        "amid",
        "over",
        "update",
        "news",
    }
)

#: Minimum controlled title similarity for the type/date/geography clustering
#: rule. Set high enough that two different incidents of the same type in the
#: same place on the same day do not merge on a couple of shared words.
TITLE_SIMILARITY_THRESHOLD = 0.6

_NON_WORD = re.compile(r"[^0-9a-z]+")

#: The links of the required reasoning chain, in order.
CHAIN_LINKS = (
    "external_driver",
    "operational_change",
    "logistics_mechanism",
    "observable_indicator",
    "outcome",
)

#: Links required for a chain to count as complete, per event class. A direct
#: operational event needs no upstream external driver -- it *is* the
#: operational change -- so requiring one would force authors to invent a
#: cause. A discovery lead has no established chain at all by definition.
_REQUIRED_LINKS: dict[str, tuple[str, ...]] = {
    "external_driver": CHAIN_LINKS,
    "direct_operational_event": (
        "operational_change",
        "logistics_mechanism",
        "observable_indicator",
        "outcome",
    ),
    "discovery_lead": (),
}

#: Impact statuses that constitute a material conclusion about impact.
MATERIAL_IMPACT_STATUSES = frozenset({"observed", "potential"})

#: Severities that may never be published without an explicit human-review
#: record.
HUMAN_REVIEW_SEVERITIES = frozenset({"high", "critical"})

#: Returned wherever the evidence does not support a direction. Named rather
#: than inlined so no caller can substitute "stable" for "we did not look".
INSUFFICIENT = "insufficient_evidence"


def canonicalize_url(url: str | None) -> str | None:
    """Return a stable canonical form of a URL for clustering.

    Scheme and host are lower-cased, user-info is stripped, the default port
    is removed, tracking parameters are dropped, remaining parameters are
    sorted, a trailing slash is removed, and the fragment is discarded. A
    value that does not parse as an absolute URL returns ``None`` rather than
    a half-normalized string that could collide with an unrelated event.
    """
    if not url:
        return None
    try:
        parts = urlsplit(redact_url_userinfo(url.strip()))
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None

    host = parts.hostname or ""
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    default_port = {"http": 80, "https": 443}.get(parts.scheme.lower())
    netloc = host if port in (None, default_port) else f"{host}:{port}"

    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_PARAMS
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def normalize_title(title: str) -> str:
    """Lower-case, strip punctuation and generic words, collapse whitespace."""
    lowered = _NON_WORD.sub(" ", title.lower())
    tokens = [token for token in lowered.split() if token and token not in _TITLE_STOPWORDS]
    return " ".join(tokens)


def title_similarity(left: str, right: str) -> float:
    """Deterministic Jaccard similarity over normalized title tokens."""
    left_tokens = set(normalize_title(left).split())
    right_tokens = set(normalize_title(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(intersection) / len(union)


def cluster_key(event: Mapping[str, Any]) -> str:
    """Deterministic clustering key over controlled fields only.

    Geography is included as a sorted list, but the key is never used on its
    own to merge: ``should_cluster`` still requires event type and date to
    match too.
    """
    payload = "|".join(
        [
            str(event.get("event_type", "")),
            str(event.get("event_date") or ""),
            ",".join(sorted(event.get("geography_ids", []))),
            str(event.get("operator_or_entity") or ""),
            normalize_title(str(event.get("title", ""))),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cluster_id_from_key(key: str) -> str:
    return f"CLU-{key[:16]}"


@dataclass(slots=True, frozen=True)
class ClusterDecision:
    should_merge: bool
    rule: str
    detail: str


def should_cluster(left: Mapping[str, Any], right: Mapping[str, Any]) -> ClusterDecision:
    """Decide whether two events are the same underlying event.

    The rules are applied in order of decreasing strength. The final rule is
    the only fuzzy one, and it still requires a matching event type, a
    matching event date, and overlapping geography before similarity is even
    considered.
    """
    left_source = left.get("source_id")
    right_source = right.get("source_id")
    left_record = left.get("source_record_id")
    right_record = right.get("source_record_id")
    if left_source and left_source == right_source and left_record and left_record == right_record:
        return ClusterDecision(True, "same_source_record", f"{left_source}:{left_record}")

    left_url = canonicalize_url(left.get("canonical_source_url"))
    right_url = canonicalize_url(right.get("canonical_source_url"))
    if left_url and left_url == right_url:
        return ClusterDecision(True, "same_canonical_url", left_url)

    same_type = left.get("event_type") and left.get("event_type") == right.get("event_type")
    same_date = left.get("event_date") and left.get("event_date") == right.get("event_date")
    shared_geography = set(left.get("geography_ids", [])) & set(right.get("geography_ids", []))
    if not (same_type and same_date and shared_geography):
        return ClusterDecision(
            False,
            "insufficient_common_attributes",
            "event type, event date and shared geography are all required before "
            "similarity is considered",
        )

    left_entity = left.get("operator_or_entity")
    right_entity = right.get("operator_or_entity")
    if left_entity and left_entity == right_entity:
        return ClusterDecision(True, "same_entity_type_date_geography", str(left_entity))

    similarity = title_similarity(str(left.get("title", "")), str(right.get("title", "")))
    if similarity >= TITLE_SIMILARITY_THRESHOLD:
        return ClusterDecision(
            True,
            "title_similarity_with_type_date_geography",
            f"similarity={similarity:.2f}",
        )
    return ClusterDecision(
        False,
        "title_similarity_below_threshold",
        f"similarity={similarity:.2f} < {TITLE_SIMILARITY_THRESHOLD}",
    )


def evaluate_transmission_chain(
    event_class: str,
    chain: Mapping[str, Any],
) -> tuple[str, list[str]]:
    """Compute chain completeness and the list of missing links.

    Returns ``('not_applicable', [])`` for a discovery lead: a lead is not
    an incomplete conclusion, it is not yet a conclusion at all.
    """
    required = _REQUIRED_LINKS.get(event_class)
    if required is None:
        raise ValueError(f"Unknown event class: {event_class}")
    if not required:
        return "not_applicable", []
    missing = [link for link in required if not chain.get(link)]
    return ("complete" if not missing else "incomplete"), missing


def external_driver_admission(event: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether an external driver may contribute to an impact conclusion.

    An external driver with an incomplete chain is admitted to the Dashboard
    as *context*, which is different from being excluded. What it may not do
    is carry a Logistics impact conclusion.
    """
    if event.get("event_class") != "external_driver":
        return True, "Not an external driver; admission rule does not apply."
    completeness, missing = evaluate_transmission_chain(
        "external_driver", event.get("transmission_chain", {})
    )
    if completeness == "complete":
        return True, "Transmission chain is complete."
    return False, (
        "External driver remains contextual: the transmission chain is missing "
        f"{', '.join(missing)}."
    )


def has_non_discovery_evidence(evidence_items: Sequence[Mapping[str, Any]]) -> bool:
    """True when at least one evidence item is not discovery-only."""
    return any(item.get("evidence_role") != "discovery_only" for item in evidence_items)


def validate_event(
    event: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Semantic checks for one event, beyond JSON Schema validity.

    Returns a list of human-readable problems; an empty list means the event
    satisfies every rule this module enforces.
    """
    problems: list[str] = []
    event_id = event.get("event_id", "<unknown>")

    known_ids = set(evidence_by_id)
    unknown = [eid for eid in event.get("evidence_ids", []) if eid not in known_ids]
    if unknown:
        problems.append(f"{event_id}: references unknown evidence IDs {sorted(unknown)}")

    evidence_items = [
        evidence_by_id[eid] for eid in event.get("evidence_ids", []) if eid in known_ids
    ]

    declared_completeness = event.get("transmission_chain", {}).get("completeness")
    computed, missing = evaluate_transmission_chain(
        str(event.get("event_class")), event.get("transmission_chain", {})
    )
    if declared_completeness != computed:
        problems.append(
            f"{event_id}: transmission_chain.completeness is {declared_completeness!r} but the "
            f"chain's links compute to {computed!r} (missing: {missing or 'none'})"
        )

    material_areas = [
        impact
        for impact in event.get("impact_assessments", [])
        if impact.get("status") in MATERIAL_IMPACT_STATUSES and impact.get("severity") != "none"
    ]

    if material_areas and computed == "incomplete":
        problems.append(
            f"{event_id}: claims a material impact while its transmission chain is "
            f"incomplete (missing: {', '.join(missing)})"
        )

    if material_areas and not has_non_discovery_evidence(evidence_items):
        problems.append(
            f"{event_id}: material impact is supported only by discovery-only evidence; "
            "a discovery source may detect a lead but may never be the sole evidence for "
            "a material impact conclusion"
        )

    for impact in event.get("impact_assessments", []):
        area = impact.get("area")
        if impact.get("status") == "no_material" and not event.get("negative_operational_evidence"):
            problems.append(
                f"{event_id}/{area}: status 'no_material' requires negative operational "
                "evidence from an actual assessment; it must not be used where impact was "
                "simply not assessed"
            )
        if (
            impact.get("status") in MATERIAL_IMPACT_STATUSES
            and impact.get("severity") != "none"
            and not impact.get("transmission_mechanism")
        ):
            problems.append(f"{event_id}/{area}: material impact has no transmission mechanism")
        if impact.get("severity") in HUMAN_REVIEW_SEVERITIES and impact.get(
            "evidence_strength"
        ) not in {"A", "B"}:
            problems.append(
                f"{event_id}/{area}: {impact.get('severity')} severity requires primary-grade "
                "evidence (A or B)"
            )
        unknown_impact_evidence = set(impact.get("evidence_ids", [])) - known_ids
        if unknown_impact_evidence:
            problems.append(
                f"{event_id}/{area}: references unknown evidence IDs "
                f"{sorted(unknown_impact_evidence)}"
            )

    highest = max(
        (impact.get("severity", "none") for impact in event.get("impact_assessments", [])),
        key=lambda severity: ["none", "low", "moderate", "high", "critical"].index(severity),
        default="none",
    )
    human_review = event.get("human_review", {})
    if highest in HUMAN_REVIEW_SEVERITIES:
        if not human_review.get("required"):
            problems.append(
                f"{event_id}: {highest} severity requires human_review.required to be true"
            )
        if human_review.get("status") != "approved" and event.get("publication_status") == (
            "Main dashboard"
        ):
            problems.append(
                f"{event_id}: {highest} severity cannot be published to the main dashboard "
                f"without an approved human-review record (status is "
                f"{human_review.get('status')!r})"
            )

    if event.get("lifecycle_status") == "closed" and not event.get("closure_basis"):
        problems.append(f"{event_id}: a closed event must record a closure basis")

    if event.get("thailand_relevance") != "none_established" and not event.get(
        "thailand_relevance_basis"
    ):
        problems.append(f"{event_id}: Thailand relevance is asserted without a recorded basis")

    admitted, reason = external_driver_admission(event)
    if not admitted and material_areas:
        problems.append(f"{event_id}: {reason}")

    # WO-010-R1: a fixture cannot become current intelligence by carrying a
    # confident-looking lifecycle status.
    fixture_backed = evidence_items and not any(
        qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
        for item in evidence_items
    )
    if dataset_of(event) == CURRENT_PUBLICATION and fixture_backed:
        problems.append(
            f"{event_id}: belongs to the current-publication dataset but is supported only "
            "by fixture evidence; a fixture cannot establish a current condition"
        )
    if (
        fixture_backed
        and event.get("lifecycle_status") == "verified_event"
        and (dataset_of(event) == CURRENT_PUBLICATION)
    ):
        problems.append(
            f"{event_id}: a fixture-backed event cannot independently reach lifecycle "
            "status 'verified_event' in the current event store"
        )
    if event.get("active_as_of") and not event.get("active_basis"):
        problems.append(
            f"{event_id}: records an active-as-of time with no basis; an assertion of "
            "activity with nothing behind it is not publishable"
        )

    for conflict in event.get("conflicting_evidence", []):
        unknown_conflict = set(conflict.get("evidence_ids", [])) - known_ids
        if unknown_conflict:
            problems.append(
                f"{event_id}: conflicting evidence references unknown IDs "
                f"{sorted(unknown_conflict)}"
            )

    computed_key = cluster_key(
        {
            "event_type": event.get("event_type"),
            "event_date": event.get("event_date"),
            "geography_ids": event.get("geography_ids", []),
            "operator_or_entity": event.get("operator_or_entity"),
            "title": event.get("title", ""),
        }
    )
    declared_key = event.get("clustering", {}).get("cluster_key")
    if declared_key != computed_key:
        problems.append(
            f"{event_id}: clustering.cluster_key does not match the deterministic key "
            "computed from the event's controlled fields"
        )

    return problems


# ---------------------------------------------------------------------------
# Current-publication filtering (WO-010-R1)
# ---------------------------------------------------------------------------

#: Lifecycle statuses that describe an event that is still running. A closed
#: event, an event whose evidence was insufficient, and a bare discovery lead
#: are all excluded: none of them is an active operational event.
ACTIVE_LIFECYCLE_STATUSES = frozenset(
    {"reported_event", "verified_event", "operational_impact_observed", "monitoring"}
)

#: How stale a confirmation of activity may be before the event stops counting
#: as active. An event nobody has re-confirmed for a quarter is not evidence of
#: a current condition, whatever its lifecycle field says.
ACTIVE_CONFIRMATION_WINDOW_DAYS = 90


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass(slots=True, frozen=True)
class ActivityDecision:
    """Whether an event may be published as active, and why not if not."""

    is_active: bool
    reason: str


def is_active_at(
    event: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    cutoff: datetime,
    registry: Mapping[str, Any] | None = None,
    window_days: int = ACTIVE_CONFIRMATION_WINDOW_DAYS,
) -> ActivityDecision:
    """Decide whether an event counts as active at ``cutoff``.

    Every condition must hold. The default answer is **not active**, which is
    the WO-010-R1 correction: previously a historical case with a null
    ``event_end_date`` stayed "active" forever simply because nothing had
    marked it finished.
    """
    if dataset_of(event) != CURRENT_PUBLICATION:
        return ActivityDecision(
            False,
            f"event belongs to the {dataset_of(event)!r} dataset, not the current "
            "publication dataset",
        )

    if event.get("lifecycle_status") not in ACTIVE_LIFECYCLE_STATUSES:
        return ActivityDecision(
            False, f"lifecycle status {event.get('lifecycle_status')!r} is not an active status"
        )

    if event.get("closure_basis"):
        return ActivityDecision(False, "the event records a closure basis")

    end_date = _as_date(event.get("event_end_date"))
    if end_date is not None and end_date < cutoff.date():
        return ActivityDecision(False, f"the event ended on {end_date.isoformat()}")

    supporting = [
        evidence_by_id[eid] for eid in event.get("evidence_ids", []) if eid in evidence_by_id
    ]
    if not any(
        qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
        for item in supporting
    ):
        return ActivityDecision(
            False,
            "no qualified current-publication evidence supports this event; fixture or "
            "demonstration evidence cannot establish a current condition",
        )

    active_as_of = _as_datetime(event.get("active_as_of"))
    if active_as_of is None or not event.get("active_basis"):
        return ActivityDecision(
            False,
            "the event records no active-as-of confirmation and basis; a null event end "
            "date is not itself evidence that the event is still running",
        )

    age_days = (cutoff - active_as_of).total_seconds() / 86400.0
    if age_days > window_days:
        return ActivityDecision(
            False,
            f"activity was last confirmed {age_days:.0f} days before the cutoff, beyond the "
            f"{window_days}-day confirmation window",
        )
    if age_days < 0:
        return ActivityDecision(
            False, "activity is confirmed only for a time after the data cutoff"
        )

    return ActivityDecision(True, f"activity confirmed at {event['active_as_of']}")


def event_qualifies_for_current_publication(
    event: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    registry: Mapping[str, Any] | None = None,
) -> bool:
    """Whether an event may appear in the current view at all.

    An event carries no origin of its own -- it is an assembled record, not a
    retrieved one -- so its qualification is read from the two things that do
    carry origin: the dataset it was built for, and the evidence standing
    behind it. An event assembled from fixtures is a fixture, whatever its
    lifecycle status says.

    This is weaker than :func:`is_active_at`, which additionally requires a
    dated confirmation that the event is still running.
    """
    if dataset_of(event) != CURRENT_PUBLICATION:
        return False
    return any(
        qualifies_for_current_publication(
            evidence_by_id[eid], registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
        for eid in event.get("evidence_ids", [])
        if eid in evidence_by_id
    )


def active_events(
    events: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    cutoff: datetime,
    registry: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every event that may be published as active at ``cutoff``.

    Nothing here special-cases the empty case. With no qualified evidence the
    filter simply matches nothing and the result is empty, which is why the
    current lists cannot be quietly hard-coded to `[]`.
    """
    return [
        dict(event)
        for event in events
        if is_active_at(event, evidence_by_id, cutoff=cutoff, registry=registry).is_active
    ]


# ---------------------------------------------------------------------------
# Event-derived domain direction (WO-010-R1)
# ---------------------------------------------------------------------------


def has_negative_operational_evidence(
    event: Mapping[str, Any],
    areas: Sequence[str],
) -> bool:
    """Whether an event carries explicit negative operational evidence for
    these domains.

    A negative conclusion is a finding, not a default. It requires the event
    to record ``negative_operational_evidence`` **and** to have actually
    assessed one of the relevant areas to ``no_material``.
    """
    if not event.get("negative_operational_evidence"):
        return False
    return any(
        impact["area"] in areas and impact.get("status") == "no_material"
        for impact in event.get("impact_assessments", [])
    )


def event_domain_direction(
    lane_id: str,
    events: Sequence[Mapping[str, Any]],
    areas: Sequence[str],
) -> tuple[str, list[str], list[str], list[str]]:
    """Direction for an event-driven domain, with the evidence behind it.

    Returns ``(direction, event_ids, evidence_ids, limitations)``.

    The governing rule, corrected by WO-010-R1: **the absence of an adverse
    record is not evidence of calm.** A domain nobody assessed returns
    ``insufficient_evidence``. ``stable`` is reserved for the case where an
    event actually recorded negative operational evidence covering these
    areas -- a finding that conditions were checked and found normal.
    """
    relevant = [
        event
        for event in events
        if any(entry["lane_id"] == lane_id for entry in event.get("lane_relevance", []))
    ]
    if not relevant:
        return (
            INSUFFICIENT,
            [],
            [],
            [
                "No event of any class is recorded against this lane, which is an absence "
                "of evidence rather than evidence of normal operation."
            ],
        )

    event_ids = sorted({event["event_id"] for event in relevant})

    if all(event["event_class"] == "discovery_lead" for event in relevant):
        return (
            INSUFFICIENT,
            event_ids,
            [],
            [
                "Only discovery-class leads are recorded against this lane; a lead cannot "
                "support a direction."
            ],
        )

    adverse_evidence: list[str] = []
    for event in relevant:
        for impact in event.get("impact_assessments", []):
            if (
                impact["area"] in areas
                and impact.get("status") in MATERIAL_IMPACT_STATUSES
                and impact.get("severity") != "none"
            ):
                adverse_evidence.extend(impact.get("evidence_ids", []))
    if adverse_evidence:
        return (
            "deteriorating",
            event_ids,
            sorted(set(adverse_evidence)),
            [
                "Direction reflects observed or potential impact recorded against this lane; "
                "it is not a measurement of current operating conditions."
            ],
        )

    negative_evidence: list[str] = []
    for event in relevant:
        if not has_negative_operational_evidence(event, areas):
            continue
        for impact in event.get("impact_assessments", []):
            if impact["area"] in areas and impact.get("status") == "no_material":
                negative_evidence.extend(impact.get("evidence_ids", []))
    if negative_evidence:
        return (
            "stable",
            event_ids,
            sorted(set(negative_evidence)),
            [
                "Direction rests on explicit negative operational evidence: an event was "
                "assessed for these areas and found no material effect. It covers only the "
                "geography, lane and period that evidence covers."
            ],
        )

    return (
        INSUFFICIENT,
        event_ids,
        [],
        [
            "Events are recorded against this lane but none assessed these areas against "
            "negative operational evidence. The absence of an adverse record is not "
            "evidence that conditions are normal."
        ],
    )
