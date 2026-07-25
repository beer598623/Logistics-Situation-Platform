"""Record origin, retrieval status and the current-publication boundary.

WO-010 delivered a working engine on labelled fixtures. WO-010-R1 adds the
boundary that was missing: a fixture may exercise the engine, but it may never
appear as current Logistics intelligence.

Three orthogonal facts are recorded on every record, and none of them can be
inferred from another:

* **origin** — where the record came from. A synthetic fixture and a retrieved
  publisher response are different kinds of thing even when they carry the
  same numbers.
* **retrieval status** — whether anything was actually fetched. ``not_retrieved``
  forbids a ``retrieved_at`` timestamp, because a retrieval time on a record
  nothing was retrieved for is simply false.
* **dataset** — which publication surface the record belongs to. Only
  ``current_publication`` reaches the Dashboard's current-intelligence view.

The single rule the rest of the platform depends on:
:func:`qualifies_for_current_publication`. If it returns ``False``, the record
cannot contribute a direction, an active event, a chokepoint notice status, an
operational impact, or a freshness label anywhere in the current view.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Where a record came from.
LIVE_RETRIEVED = "live_retrieved"
HUMAN_REVIEWED_MANUAL = "human_reviewed_manual"
SYNTHETIC_TEST_FIXTURE = "synthetic_test_fixture"
HISTORICAL_VALIDATION_FIXTURE = "historical_validation_fixture"

EVIDENCE_ORIGINS = (
    LIVE_RETRIEVED,
    HUMAN_REVIEWED_MANUAL,
    SYNTHETIC_TEST_FIXTURE,
    HISTORICAL_VALIDATION_FIXTURE,
)

#: Origins that may carry current Logistics intelligence. Deliberately the two
#: origins where a human or a publisher actually stands behind the content.
PUBLISHABLE_ORIGINS = frozenset({LIVE_RETRIEVED, HUMAN_REVIEWED_MANUAL})

#: Origins that exist to exercise the engine and must stay out of the current
#: view entirely.
FIXTURE_ORIGINS = frozenset({SYNTHETIC_TEST_FIXTURE, HISTORICAL_VALIDATION_FIXTURE})

#: Whether anything was actually fetched from a publisher.
RETRIEVAL_STATUSES = ("retrieved", "not_retrieved", "retrieval_failed", "not_applicable")

#: What a content hash actually covers. A hash over this repository's own
#: authored text is not evidence about a publisher's response, and labelling it
#: as such was the defect R1 corrects.
CONTENT_HASH_SCOPES = ("source_response", "local_fixture_payload", "authored_claim_record")

#: Which publication surface a record belongs to.
CURRENT_PUBLICATION = "current_publication"
TECHNICAL_DEMO = "technical_demo"
HISTORICAL_VALIDATION = "historical_validation"

DATASETS = (CURRENT_PUBLICATION, TECHNICAL_DEMO, HISTORICAL_VALIDATION)

#: Reserved source identifier for records the platform generated itself. It is
#: deliberately NOT a registry entry: it is not a source, and giving it one
#: would be the same category error as attributing a fixture to a publisher.
SYNTHETIC_SOURCE_ID = "SYNTHETIC_FIXTURE"

#: Freshness statuses for records that are not live. Kept disjoint from the
#: real-world set (fresh / stale / very_stale) so a fixture can never be read
#: as a statement about how current a publisher's data is.
FIXTURE_NOT_LIVE = "fixture_not_live"
HISTORICAL_VALIDATION_FRESHNESS = "historical_validation"
FRESHNESS_NOT_APPLICABLE = "not_applicable"

NON_LIVE_FRESHNESS_STATUSES = frozenset(
    {FIXTURE_NOT_LIVE, HISTORICAL_VALIDATION_FRESHNESS, FRESHNESS_NOT_APPLICABLE}
)

#: Real-world freshness statuses. Reserved for records that were actually
#: retrieved or human-reviewed.
LIVE_FRESHNESS_STATUSES = frozenset({"fresh", "stale", "very_stale", "no_data", "error"})

_FRESHNESS_BY_ORIGIN = {
    SYNTHETIC_TEST_FIXTURE: FIXTURE_NOT_LIVE,
    HISTORICAL_VALIDATION_FIXTURE: HISTORICAL_VALIDATION_FRESHNESS,
}


def qualifies_for_current_publication(origin: str | None) -> bool:
    """Whether a record of this origin may carry current intelligence.

    The whole current-publication boundary reduces to this predicate, so there
    is exactly one place to read, test and change it.
    """
    return origin in PUBLISHABLE_ORIGINS


def is_fixture(origin: str | None) -> bool:
    return origin in FIXTURE_ORIGINS


def fixture_freshness_status(origin: str | None) -> str:
    """Non-live freshness label for a fixture origin.

    Returns ``not_applicable`` for anything else, so a caller that reaches
    here with a publishable origin gets an obviously wrong-looking label
    rather than a plausible-looking one.
    """
    return _FRESHNESS_BY_ORIGIN.get(str(origin), FRESHNESS_NOT_APPLICABLE)


def record_origin(record: Mapping[str, Any]) -> str | None:
    """Read the origin from an observation, evidence item or event.

    Observations carry it inside ``provenance``; evidence items and events
    carry it at the top level. Reading both here keeps every caller from
    having to know which shape it holds.
    """
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping) and "evidence_origin" in provenance:
        return provenance.get("evidence_origin")
    return record.get("evidence_origin")


def record_source_id(record: Mapping[str, Any]) -> str | None:
    """Read the source ID from a record of either shape.

    Source identity comes from the record's own provenance. Nothing in the
    platform maps a series name to a publisher through a side table any more:
    that is how a synthetic freight benchmark ended up attributed to a fuel
    publisher.
    """
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping) and "source_id" in provenance:
        return provenance.get("source_id")
    return record.get("source_id")


def record_intended_source_id(record: Mapping[str, Any]) -> str | None:
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping) and "intended_source_id" in provenance:
        return provenance.get("intended_source_id")
    return record.get("intended_source_id")


def effective_source_id(record: Mapping[str, Any]) -> str | None:
    """The registry source a record relates to, whether or not it came from it.

    For a live record this is its actual source. For a fixture it is the
    production candidate the fixture stands in for -- useful for looking up a
    freshness contract, and never a claim that the fixture came from there.
    """
    source_id = record_source_id(record)
    if source_id == SYNTHETIC_SOURCE_ID:
        return record_intended_source_id(record)
    return source_id


def publishable(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Filter to records that may carry current intelligence."""
    return [
        dict(record)
        for record in records
        if qualifies_for_current_publication(record_origin(record))
    ]


def dataset_of(record: Mapping[str, Any]) -> str | None:
    return record.get("dataset")


def in_dataset(records: Sequence[Mapping[str, Any]], dataset: str) -> list[dict[str, Any]]:
    return [dict(record) for record in records if dataset_of(record) == dataset]


def provenance_problems(record: Mapping[str, Any], *, label: str) -> list[str]:
    """Truthfulness checks that apply to any record carrying provenance.

    These are the checks that catch a record claiming more than it can
    support: a retrieval time on something nothing was retrieved for, a
    fixture attributed to a real publisher, or a hash of this repository's own
    text presented as evidence about a publisher's response.
    """
    problems: list[str] = []
    origin = record_origin(record)
    nested = record.get("provenance")
    provenance = nested if isinstance(nested, Mapping) else record
    retrieval_status = provenance.get("retrieval_status")
    retrieved_at = provenance.get("retrieved_at")
    source_id = record_source_id(record)
    intended = record_intended_source_id(record)
    hash_scope = provenance.get("content_hash_scope")

    if origin not in EVIDENCE_ORIGINS:
        problems.append(f"{label}: evidence_origin {origin!r} is not a recognised origin")
    if retrieval_status not in RETRIEVAL_STATUSES:
        problems.append(
            f"{label}: retrieval_status {retrieval_status!r} is not a recognised status"
        )

    if retrieval_status != "retrieved" and retrieved_at:
        problems.append(
            f"{label}: retrieval_status is {retrieval_status!r} but a retrieved_at timestamp "
            "is present; nothing was retrieved, so there is no retrieval time"
        )
    if retrieval_status == "retrieved" and not retrieved_at:
        problems.append(f"{label}: retrieval_status is 'retrieved' but no retrieved_at is recorded")

    if is_fixture(origin):
        if retrieval_status == "retrieved":
            problems.append(
                f"{label}: a {origin} record cannot be marked as retrieved from a publisher"
            )
        if source_id != SYNTHETIC_SOURCE_ID:
            problems.append(
                f"{label}: a {origin} record must record source_id "
                f"{SYNTHETIC_SOURCE_ID!r}, not {source_id!r}; attributing generated content "
                "to a real publisher misstates its provenance"
            )
        if not intended:
            problems.append(
                f"{label}: a fixture must record the intended_source_id it stands in for"
            )
        if hash_scope == "source_response":
            problems.append(
                f"{label}: content_hash_scope 'source_response' claims the hash covers a "
                "publisher response, but nothing was retrieved"
            )
    else:
        if source_id == SYNTHETIC_SOURCE_ID:
            problems.append(
                f"{label}: origin {origin!r} is publishable but source_id is the reserved "
                "synthetic identifier"
            )
        if hash_scope == "authored_claim_record":
            problems.append(
                f"{label}: a publishable record should hash the source response or payload, "
                "not this repository's authored claim text"
            )

    return problems
