"""Deterministic event identity and lifecycle metadata.

Identity is derived only from controlled, structured fields (source ID,
external event ID, category, geography, event-date bucket, transport mode,
and segment). Title wording and generated summaries never participate in
identity, so rewording a headline cannot change which event a record
belongs to.

No similarity, clustering, or AI-based deduplication runs here, and no code
path in this module ever *automatically* merges two canonical events that
matching found to be merely similar — that kind of semantic merge is
impossible by construction, because it is simply not implemented. Matching
itself, however, is exact-field matching: two genuinely distinct real-world
incidents that happen to share the same category, geography, date bucket,
transport mode, and segment are indistinguishable by these controlled
fields alone and will resolve to the same canonical event. That
controlled-field collision is a known limitation of deterministic
fingerprinting, not a bug; see ``resolve_event_identity`` for how a source
ID narrows this, and rely on `merge_suggested`/`split_required` plus human
review for cases this module cannot tell apart on its own.

Callers must persist every field of ``EventIdentity.to_dict()`` — including
``content_signature`` and ``identity_date_bucket`` — back into the
candidate/reviewed record and pass it back in on the next ``known_events``
lookup. ``last_changed_at`` and the event-date-promotion rule below only
work across a real JSON round trip because the previous
``content_signature`` and ``identity_date_bucket`` are read back from
storage, not recomputed from data that was never saved.
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


def compute_event_fingerprint_from_bucket(
    *,
    primary_category: str,
    geography: Sequence[str],
    date_bucket: str,
    transport_modes: Sequence[str],
    segments: Sequence[str],
) -> str:
    """Derive a reproducible fingerprint from controlled fields plus an
    explicit, already-resolved date bucket.

    This is the primitive both ``compute_event_fingerprint`` (today's best
    known date) and the event-date-promotion lookup (a known record's own
    frozen ``identity_date_bucket``) build on, so both paths hash controlled
    fields identically.
    """
    controlled = {
        "category": _normalize_token(primary_category),
        "geography": _normalize_list(geography),
        "date_bucket": date_bucket,
        "modes": _normalize_list(transport_modes),
        "segments": _normalize_list(segments),
    }
    canonical_json = json.dumps(controlled, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


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

    The event-date bucket falls back to the publication date when no event
    date is known yet. This computes the fingerprint for *this observation
    as given*; it does not know about any previously frozen
    ``identity_date_bucket`` — that promotion logic lives in
    ``resolve_event_identity``, which is what makes identity survive a
    later publication-date change once the real event date is known.
    """
    return compute_event_fingerprint_from_bucket(
        primary_category=primary_category,
        geography=geography,
        date_bucket=event_date or publication_date,
        transport_modes=transport_modes,
        segments=segments,
    )


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

    This is deliberately separate from the fingerprint functions above: the
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


def event_date_from_candidate(candidate: Mapping[str, Any]) -> str | None:
    """Read the identity date from a stored candidate record.

    Candidates carry it under ``event_date`` (nullable — see
    ``schemas/candidate_event.schema.json``). This accessor exists so every
    caller reads the field the same, explicit way rather than re-deriving
    the key name inline.
    """
    return candidate.get("event_date")


def event_date_from_reviewed_event(event: Mapping[str, Any]) -> str | None:
    """Read the identity date from a stored reviewed event record.

    Reviewed events carry the same concept under ``event_start`` (nullable
    — see ``schemas/reviewed_event.schema.json``), not ``event_date``. No
    separate schema field was added for this; this accessor is the single
    place that encodes the field-name mapping between the two record
    shapes, so a caller promoting a candidate into a reviewed event (or
    building a ``known_events`` entry from either) never has to remember
    which schema uses which name.
    """
    return event.get("event_start")


def known_event_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``resolve_event_identity`` ``known_events`` entry from a
    stored candidate record, explicitly mapping its ``event_date`` field."""
    return {
        "source_id": candidate.get("source_id"),
        "external_event_id": candidate.get("external_event_id"),
        "event_date": event_date_from_candidate(candidate),
        "event_fingerprint": candidate.get("event_fingerprint"),
        "canonical_event_id": candidate.get("canonical_event_id"),
        "identity_date_bucket": candidate.get("identity_date_bucket"),
        "first_seen_at": candidate.get("first_seen_at"),
        "last_changed_at": candidate.get("last_changed_at"),
        "content_signature": candidate.get("content_signature"),
        "supersedes": candidate.get("supersedes", []),
    }


def known_event_from_reviewed_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``resolve_event_identity`` ``known_events`` entry from a
    stored reviewed event record, explicitly mapping its ``event_start``
    field to the ``event_date`` key ``resolve_event_identity`` expects."""
    return {
        "source_id": event.get("source_id"),
        "external_event_id": event.get("external_event_id"),
        "event_date": event_date_from_reviewed_event(event),
        "event_fingerprint": event.get("event_fingerprint"),
        "canonical_event_id": event.get("canonical_event_id"),
        "identity_date_bucket": event.get("identity_date_bucket"),
        "first_seen_at": event.get("first_seen_at"),
        "last_changed_at": event.get("last_changed_at"),
        "content_signature": event.get("content_signature"),
        "supersedes": event.get("supersedes", []),
    }


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
    identity_date_bucket: str

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
            "identity_date_bucket": self.identity_date_bucket,
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


def _find_by_frozen_bucket(
    known_events: Sequence[Mapping[str, Any]],
    *,
    primary_category: str,
    geography: Sequence[str],
    transport_modes: Sequence[str],
    segments: Sequence[str],
) -> Mapping[str, Any] | None:
    """Match a known record via its own frozen ``identity_date_bucket``.

    This is what makes event-date promotion survive a publication-date
    change between observations: instead of recomputing a "provisional"
    fingerprint from *this* observation's ``publication_date`` (which may
    have drifted since the record was first stored), this re-derives the
    known record's own fingerprint from controlled fields it already has —
    this observation's category/geography/modes/segments plus the known
    record's own persisted ``identity_date_bucket`` — and compares that
    against the value the known record actually stored. Neither this
    observation's ``event_date`` nor its ``publication_date`` factor into
    the comparison at all.

    Only records whose *own persisted* ``event_date`` is ``None`` are
    eligible: that is the only reliable signal that the record's identity
    was ever established without a real, independently-known event date. A
    known record with a real (even if coincidentally identical) event date
    must never match here — that is exactly the "different date bucket"
    case that must stay unmatched. A known-event dict that omits the
    ``event_date`` key entirely, or that has no persisted
    ``identity_date_bucket``, is conservatively ineligible rather than
    treated as "unknown".
    """
    for event in known_events:
        if event.get("event_date", _UNKNOWN) is not None:
            continue
        bucket = event.get("identity_date_bucket")
        if not bucket:
            continue
        provisional = compute_event_fingerprint_from_bucket(
            primary_category=primary_category,
            geography=geography,
            date_bucket=bucket,
            transport_modes=transport_modes,
            segments=segments,
        )
        if event.get("event_fingerprint") == provisional:
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
    storage — build each entry with ``known_event_from_candidate`` or
    ``known_event_from_reviewed_event`` so the ``event_date`` key is mapped
    correctly, rather than constructing the dict by hand. Every value must
    be the actual value last written by ``EventIdentity.to_dict()`` (plus
    the record's own identity date under the ``event_date`` key) — this
    function does not itself persist anything, so a caller that fails to
    round-trip a field (most importantly ``content_signature`` and
    ``identity_date_bucket``) will get a less precise ``last_changed_at`` or
    identity-promotion result, not a crash.

    Matching tries, in order:

    1. Same ``source_id`` + ``external_event_id`` (``matched_external_id``).
    2. Same fingerprint, computed from this observation's own fields as
       given (``matched_fingerprint``).
    3. A known record whose own ``event_date`` was ``None`` when it was
       stored, matched via its frozen ``identity_date_bucket`` rather than
       anything about this observation's date fields (see
       ``_find_by_frozen_bucket``) — this is what lets a candidate observed
       before its event date was known keep its canonical ID once the date
       resolves, *even if publication_date also changed* between the two
       observations, without ever matching a record that already had a
       real (if coincidentally identical) event date.

    A different mode, geography, category, or a date bucket that was
    already known on both sides changes the fingerprint and therefore
    prevents an accidental match. This is exact-field matching, not
    semantic matching: it cannot and does not distinguish two genuinely
    different real-world events that happen to share identical controlled
    fields (see the module docstring's "known limitation" note).

    Once a match is found (or a new record is created), the returned
    ``identity_date_bucket`` freezes to ``event_date`` if it is now known,
    otherwise to whatever bucket was already frozen on the matched record,
    otherwise to this observation's ``publication_date``. The returned
    ``event_fingerprint`` is always recomputed from that resolved bucket, so
    it stays internally consistent with what gets persisted.
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
    if match is None:
        match = _find_by_frozen_bucket(
            known_events,
            primary_category=primary_category,
            geography=geography,
            transport_modes=transport_modes,
            segments=segments,
        )
        if match is not None:
            merge_status = "matched_fingerprint"

    if match is None:
        identity_date_bucket = event_date or publication_date
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
            identity_date_bucket=identity_date_bucket,
        )

    prior_bucket = match.get("identity_date_bucket") or match.get("event_date")
    identity_date_bucket = event_date or prior_bucket or publication_date
    resolved_fingerprint = compute_event_fingerprint_from_bucket(
        primary_category=primary_category,
        geography=geography,
        date_bucket=identity_date_bucket,
        transport_modes=transport_modes,
        segments=segments,
    )

    changed = match.get("content_signature") != content_signature
    first_seen_at = match.get("first_seen_at") or now_iso
    last_changed_at = now_iso if changed else match.get("last_changed_at") or first_seen_at
    return EventIdentity(
        canonical_event_id=str(match["canonical_event_id"]),
        event_fingerprint=resolved_fingerprint,
        merge_status=merge_status,
        first_seen_at=first_seen_at,
        last_seen_at=now_iso,
        last_changed_at=last_changed_at,
        supersedes=list(match.get("supersedes", [])),
        content_signature=content_signature,
        identity_date_bucket=identity_date_bucket,
    )
