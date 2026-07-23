"""Deterministic event identity and lifecycle metadata.

Identity is derived only from controlled, structured fields (source ID,
external event ID, category, geography, event-date bucket, transport mode,
and segment). Title wording and generated summaries never participate in
identity, so rewording a headline cannot change which event a record
belongs to. No similarity or clustering heuristic runs here: this module
never automatically merges two distinct canonical events. It only detects
an exact external-ID match or an exact controlled-fingerprint match; any
weaker relationship is left to a human reviewer via ``merge_suggested``.

Callers must persist every field of ``EventIdentity.to_dict()`` — including
``content_signature`` — back into the candidate/reviewed record and pass it
back in on the next ``known_events`` lookup. ``last_changed_at`` and the
event-date-promotion rule below only work across a real JSON round trip
because the previous ``content_signature`` and ``event_date`` are read back
from storage, not recomputed from data that was never saved.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_WHITESPACE = re.compile(r"\s+")

CANONICAL_EVENT_ID_PATTERN = re.compile(r"^CEVT-[0-9a-f]{16}$")
EVENT_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")

MERGE_STATUSES = (
    "unmatched",
    "matched_external_id",
    "matched_fingerprint",
    "merge_suggested",
    "merged_approved",
    "split_required",
)


def _normalize_token(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip().lower())


def _normalize_list(values: Sequence[str]) -> list[str]:
    return sorted({_normalize_token(value) for value in values if value})


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def compute_event_fingerprint(
    *,
    primary_category: str,
    geography: Sequence[str],
    event_date: str | None,
    publication_date: str,
    transport_modes: Sequence[str],
    segments: Sequence[str],
) -> str:
    """Derive a reproducible fingerprint from controlled fields only.

    The event-date bucket falls back to the publication date when no
    event date is known yet, so early candidates fingerprint consistently
    with the later reviewed record describing the same event.
    """
    controlled = {
        "category": _normalize_token(primary_category),
        "geography": _normalize_list(geography),
        "date_bucket": event_date or publication_date,
        "modes": _normalize_list(transport_modes),
        "segments": _normalize_list(segments),
    }
    canonical_json = json.dumps(controlled, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_canonical_event_id(
    *,
    source_id: str | None,
    external_event_id: str | None,
    fingerprint: str,
) -> str:
    """Derive a stable canonical ID, preferring source_id + external_event_id."""
    if source_id and external_event_id:
        basis = f"ext:{source_id}:{external_event_id}"
    else:
        basis = f"fp:{fingerprint}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"CEVT-{digest}"


def compute_content_signature(*, title: str, text_fields: Sequence[str]) -> str:
    """Hash the free-text content that indicates a real, human-visible change.

    This is deliberately separate from ``compute_event_fingerprint``: the
    signature is allowed (expected) to change when wording changes — that is
    what drives ``last_changed_at`` — while the fingerprint, which drives
    identity, never does. Callers decide which text fields feed this (e.g. a
    candidate's ``title`` + ``raw_claims``, or a reviewed event's ``title`` +
    ``verified_facts`` + ``reported_claims``); volatile fields such as
    ``retrieved_at``/``last_verified_at`` must never be included, or every
    re-observation would look like a content change. Only the resulting hash
    is persisted (``content_signature``, ``^[0-9a-f]{64}$``), so storage
    format never leaks which fields were hashed.
    """
    payload = json.dumps(
        {"title": title, "text_fields": list(text_fields)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True, frozen=True)
class EventIdentity:
    canonical_event_id: str
    event_fingerprint: str
    merge_status: str
    first_seen_at: str
    last_seen_at: str
    last_changed_at: str
    supersedes: list[str]
    content_signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_event_id": self.canonical_event_id,
            "event_fingerprint": self.event_fingerprint,
            "merge_status": self.merge_status,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "last_changed_at": self.last_changed_at,
            "supersedes": self.supersedes,
            "content_signature": self.content_signature,
        }


def _find_by_external_id(
    known_events: Sequence[Mapping[str, Any]],
    source_id: str,
    external_event_id: str,
) -> Mapping[str, Any] | None:
    for event in known_events:
        if (
            event.get("source_id") == source_id
            and event.get("external_event_id") == external_event_id
        ):
            return event
    return None


def _find_by_fingerprint(
    known_events: Sequence[Mapping[str, Any]],
    fingerprint: str,
) -> Mapping[str, Any] | None:
    for event in known_events:
        if event.get("event_fingerprint") == fingerprint:
            return event
    return None


_UNKNOWN = object()


def _find_by_provisional_fingerprint(
    known_events: Sequence[Mapping[str, Any]],
    provisional_fingerprint: str,
) -> Mapping[str, Any] | None:
    """Match a known record that fingerprinted before its event date was known.

    Only records whose *own persisted* ``event_date`` is ``None`` are
    eligible: that is the only reliable signal that their stored
    ``event_fingerprint`` was itself built from the publication-date
    fallback bucket rather than a real, independently-known event date. A
    known record with a real (even if coincidentally identical) event date
    must never match here — that is exactly the "different date bucket"
    case that must stay unmatched, and is why callers that omit
    ``event_date`` from a known-event dict are treated as ineligible rather
    than as an unknown date.
    """
    for event in known_events:
        if event.get("event_date", _UNKNOWN) is not None:
            continue
        if event.get("event_fingerprint") == provisional_fingerprint:
            return event
    return None


def resolve_event_identity(
    *,
    source_id: str | None,
    external_event_id: str | None,
    primary_category: str,
    geography: Sequence[str],
    event_date: str | None,
    publication_date: str,
    transport_modes: Sequence[str],
    segments: Sequence[str],
    content_signature: str,
    known_events: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> EventIdentity:
    """Resolve stable identity and lifecycle metadata for one candidate/event.

    ``known_events`` is prior candidate/reviewed records read back from
    storage, each carrying the full persisted identity: ``source_id``,
    ``external_event_id``, ``event_date``, ``event_fingerprint``,
    ``canonical_event_id``, ``first_seen_at``, ``last_changed_at``,
    ``content_signature``, ``supersedes``. All of these must be the actual
    values last written by ``EventIdentity.to_dict()`` (plus the record's own
    ``event_date``) — this function does not itself persist anything, so a
    caller that fails to round-trip a field (most importantly
    ``content_signature`` and ``event_date``) will get a less precise
    ``last_changed_at`` or identity-promotion result, not a crash.

    Matching tries, in order: (1) same ``source_id`` + ``external_event_id``;
    (2) same fingerprint; (3) only when this observation's ``event_date`` is
    newly known and no known record fingerprint-matches directly, a known
    record whose own ``event_date`` was still ``None`` when it was stored,
    re-fingerprinted with the publication-date fallback bucket it would have
    used at that time — this lets a candidate observed before its event date
    was known keep its canonical ID once the date resolves, without ever
    matching a record that already had a real (if coincidentally identical)
    event date. A different mode, geography, category, or a date bucket that
    was already known changes the fingerprint and therefore can never match
    an unrelated event.
    """
    moment = now or datetime.now(UTC)
    now_iso = _to_iso(moment)
    fingerprint = compute_event_fingerprint(
        primary_category=primary_category,
        geography=geography,
        event_date=event_date,
        publication_date=publication_date,
        transport_modes=transport_modes,
        segments=segments,
    )

    match: Mapping[str, Any] | None = None
    merge_status = "unmatched"
    if source_id and external_event_id:
        match = _find_by_external_id(known_events, source_id, external_event_id)
        if match is not None:
            merge_status = "matched_external_id"
    if match is None:
        match = _find_by_fingerprint(known_events, fingerprint)
        if match is not None:
            merge_status = "matched_fingerprint"
    if match is None and event_date is not None:
        provisional_fingerprint = compute_event_fingerprint(
            primary_category=primary_category,
            geography=geography,
            event_date=None,
            publication_date=publication_date,
            transport_modes=transport_modes,
            segments=segments,
        )
        match = _find_by_provisional_fingerprint(known_events, provisional_fingerprint)
        if match is not None:
            merge_status = "matched_fingerprint"

    if match is None:
        canonical_event_id = compute_canonical_event_id(
            source_id=source_id,
            external_event_id=external_event_id,
            fingerprint=fingerprint,
        )
        return EventIdentity(
            canonical_event_id=canonical_event_id,
            event_fingerprint=fingerprint,
            merge_status="unmatched",
            first_seen_at=now_iso,
            last_seen_at=now_iso,
            last_changed_at=now_iso,
            supersedes=[],
            content_signature=content_signature,
        )

    changed = match.get("content_signature") != content_signature
    first_seen_at = match.get("first_seen_at") or now_iso
    last_changed_at = now_iso if changed else match.get("last_changed_at") or first_seen_at
    return EventIdentity(
        canonical_event_id=str(match["canonical_event_id"]),
        event_fingerprint=fingerprint,
        merge_status=merge_status,
        first_seen_at=first_seen_at,
        last_seen_at=now_iso,
        last_changed_at=last_changed_at,
        supersedes=list(match.get("supersedes", [])),
        content_signature=content_signature,
    )
