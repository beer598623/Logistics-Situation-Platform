"""Shared observation-record assembly.

Every adapter that produces a ``fact_*_observation`` record builds it through
this one helper, so provenance shape and missing-value semantics cannot drift
between sources. The helper is the single place that enforces the rule the
rest of the platform depends on: **a value exists only when
``value_status`` is ``available``**, and any other status forces the value to
``None``.

Assembling a record never infers impact, relevance or direction. Adapters
normalize; interpretation belongs to ``analysis/`` and to human review.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from analysis.provenance import FIXTURE_ORIGINS, SYNTHETIC_SOURCE_ID

#: Statuses that permit a non-null value. Exactly one, deliberately.
_AVAILABLE = "available"

_RECORD_ID_SEGMENT = re.compile(r"[^0-9A-Za-z_.:-]+")


class ObservationContractError(ValueError):
    """Raised when a caller tries to build a record that would violate the
    observation contract -- for example a non-null value on a missing
    observation. Adapters fail closed rather than emitting such a record."""


def slugify_series(value: str) -> str:
    """Normalize a series identifier to the schema's ``[a-z0-9_]+`` pattern."""
    lowered = re.sub(r"[^0-9a-z]+", "_", value.strip().lower())
    return lowered.strip("_")


def build_record_id(source_id: str, series_id: str, period_key: str) -> str:
    """Deterministic record ID: same source, series and period always yield
    the same ID, which is what makes re-collection an update rather than a
    duplicate."""
    return (
        f"OBS-{source_id}-{slugify_series(series_id)}-"
        f"{_RECORD_ID_SEGMENT.sub('-', period_key.strip())}"
    )


def content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def build_observation(
    *,
    source_id: str,
    series_id: str,
    period_key: str,
    value: float | None,
    value_status: str,
    unit: str | None,
    currency: str | None,
    period_start: str | None,
    period_end: str | None,
    period_type: str,
    parser_version: str,
    evidence_class: str,
    content_sha256: str,
    evidence_origin: str,
    retrieval_status: str,
    content_hash_scope: str,
    retrieved_at: str | None = None,
    intended_source_id: str | None = None,
    fixture_created_at: str | None = None,
    published_at: str | None = None,
    revised_at: str | None = None,
    revision_number: int = 0,
    source_record_id: str | None = None,
    source_revision: str | None = None,
    geography_id: str | None = None,
    country_id: str | None = None,
    transport_mode: str = "not_applicable",
    lane_id: str | None = None,
    node_id: str | None = None,
    known_limitations: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one observation record.

    Raises ``ObservationContractError`` when the value and the value status
    disagree. That is a hard failure rather than a silent correction: an
    adapter that thinks it has a value for a period the source did not
    publish has a bug, and quietly rewriting either field would hide it.

    Provenance is held to the same standard. A record whose origin is a
    fixture may not claim a real publisher as its source, and a record that
    retrieved nothing may not carry a retrieval time.
    """
    if value_status == _AVAILABLE and value is None:
        raise ObservationContractError(
            f"{series_id}/{period_key}: value_status is 'available' but no value was parsed"
        )
    if value_status != _AVAILABLE and value is not None:
        raise ObservationContractError(
            f"{series_id}/{period_key}: value_status is {value_status!r} but a value was "
            "supplied; a missing observation must never carry a number, including zero"
        )
    if value_status == _AVAILABLE and unit is None:
        raise ObservationContractError(
            f"{series_id}/{period_key}: an available value must record its unit"
        )

    if retrieval_status != "retrieved" and retrieved_at is not None:
        raise ObservationContractError(
            f"{series_id}/{period_key}: retrieval_status is {retrieval_status!r} but a "
            "retrieved_at timestamp was supplied; nothing was retrieved, so there is no "
            "retrieval time"
        )
    if retrieval_status == "retrieved" and retrieved_at is None:
        raise ObservationContractError(
            f"{series_id}/{period_key}: retrieval_status is 'retrieved' but no retrieved_at "
            "was supplied"
        )
    if evidence_origin in FIXTURE_ORIGINS:
        if source_id != SYNTHETIC_SOURCE_ID:
            raise ObservationContractError(
                f"{series_id}/{period_key}: a {evidence_origin} record must record source_id "
                f"{SYNTHETIC_SOURCE_ID!r}, not {source_id!r}; attributing generated content to "
                "a real publisher misstates its provenance"
            )
        if not intended_source_id:
            raise ObservationContractError(
                f"{series_id}/{period_key}: a fixture must record the intended_source_id it "
                "stands in for"
            )
    elif source_id == SYNTHETIC_SOURCE_ID:
        raise ObservationContractError(
            f"{series_id}/{period_key}: origin {evidence_origin!r} is publishable but the "
            "reserved synthetic source identifier was supplied"
        )

    record: dict[str, Any] = dict(extra or {})
    record["provenance"] = {
        "record_id": build_record_id(source_id, series_id, period_key),
        "source_id": source_id,
        "source_record_id": source_record_id,
        "evidence_origin": evidence_origin,
        "retrieval_status": retrieval_status,
        "content_hash_scope": content_hash_scope,
        "intended_source_id": intended_source_id,
        "fixture_created_at": fixture_created_at,
        "period_start": period_start,
        "period_end": period_end,
        "period_type": period_type,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "revised_at": revised_at,
        "revision_number": revision_number,
        "content_sha256": content_sha256,
        "parser_version": parser_version,
        "source_revision": source_revision,
        "evidence_class": evidence_class,
        "known_limitations": list(known_limitations),
    }
    record["measurement"] = {
        "value": value,
        "value_status": value_status,
        "unit": unit,
        "currency": currency,
    }
    record["placement"] = {
        "geography_id": geography_id,
        "country_id": country_id,
        "transport_mode": transport_mode,
        "lane_id": lane_id,
        "node_id": node_id,
    }
    return record


def deduplicate_observations(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse records that share a ``record_id``, keeping the highest
    revision.

    Two collections of the same period are the same observation, not two
    observations. A later revision supersedes an earlier one here; the full
    revision history is preserved separately by the warehouse.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record["provenance"]["record_id"]
        revision = int(record["provenance"].get("revision_number", 0))
        existing = by_id.get(record_id)
        if existing is None or revision >= int(existing["provenance"].get("revision_number", 0)):
            by_id[record_id] = dict(record)
    return [by_id[key] for key in sorted(by_id)]
