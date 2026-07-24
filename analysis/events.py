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
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collectors.url_redaction import redact_url_userinfo

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
