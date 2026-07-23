from __future__ import annotations

import json
from datetime import UTC, datetime

from collectors.event_identity import (
    compute_content_signature,
    compute_event_fingerprint,
    event_date_from_candidate,
    event_date_from_reviewed_event,
    known_event_from_candidate,
    known_event_from_reviewed_event,
    resolve_event_identity,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)

BASE_FIELDS = dict(
    primary_category="maritime_port",
    geography=["Singapore", "Pasir Panjang"],
    event_date="2024-06-14",
    publication_date="2024-06-14",
    transport_modes=["maritime"],
    segments=["container"],
)


def _resolve(known_events=(), **overrides):
    fields = {**BASE_FIELDS, **overrides}
    return resolve_event_identity(
        source_id=fields.pop("source_id", None),
        external_event_id=fields.pop("external_event_id", None),
        content_signature=fields.pop("content_signature", "signature-1"),
        known_events=known_events,
        now=fields.pop("now", NOW),
        **fields,
    )


def test_same_external_id_resolves_to_same_canonical_event() -> None:
    first = _resolve(source_id="GDACS", external_event_id="EQ-99")
    known = [_as_known(first, source_id="GDACS", external_event_id="EQ-99")]
    second = _resolve(
        source_id="GDACS",
        external_event_id="EQ-99",
        primary_category="a completely different category",
        known_events=known,
    )
    assert second.canonical_event_id == first.canonical_event_id
    assert second.merge_status == "matched_external_id"
    assert second.first_seen_at == first.first_seen_at


def test_same_controlled_fingerprint_resolves_deterministically() -> None:
    fingerprint_a = compute_event_fingerprint(**BASE_FIELDS)
    fingerprint_b = compute_event_fingerprint(**BASE_FIELDS)
    assert fingerprint_a == fingerprint_b

    first = _resolve()
    known = [_as_known(first)]
    second = _resolve(known_events=known)
    assert second.canonical_event_id == first.canonical_event_id
    assert second.merge_status == "matched_fingerprint"


def test_different_mode_prevents_unsafe_merge() -> None:
    reference = _resolve()
    known = [_as_known(reference)]
    other_mode = _resolve(transport_modes=["air"], known_events=known)
    assert other_mode.canonical_event_id != reference.canonical_event_id
    assert other_mode.merge_status == "unmatched"


def test_different_geography_prevents_unsafe_merge() -> None:
    reference = _resolve()
    known = [_as_known(reference)]
    other_geo = _resolve(geography=["Thailand", "Laem Chabang"], known_events=known)
    assert other_geo.canonical_event_id != reference.canonical_event_id
    assert other_geo.merge_status == "unmatched"


def test_different_category_prevents_unsafe_merge() -> None:
    reference = _resolve()
    known = [_as_known(reference)]
    other_category = _resolve(primary_category="air_cargo", known_events=known)
    assert other_category.canonical_event_id != reference.canonical_event_id
    assert other_category.merge_status == "unmatched"


def test_different_date_bucket_prevents_unsafe_merge() -> None:
    """The reference event's date was known from the start (not ``None``),
    so it must never match through the event-date-promotion fallback either
    — only a known record whose own persisted ``event_date`` is ``None`` is
    eligible for that fallback (see
    ``test_canonical_identity_preserved_when_event_date_resolves_from_unknown``
    below)."""
    reference = _resolve()
    known = [_as_known(reference)]
    other_date = _resolve(event_date="2024-07-01", known_events=known)
    assert other_date.canonical_event_id != reference.canonical_event_id
    assert other_date.merge_status == "unmatched"


def test_title_wording_change_does_not_change_event_identity() -> None:
    reference = _resolve(content_signature="Oil spill near Pasir Panjang Terminal")
    known = [_as_known(reference, content_signature="Oil spill near Pasir Panjang Terminal")]
    reworded = _resolve(
        content_signature="Pasir Panjang oil spill - operations reported unaffected",
        known_events=known,
    )
    assert reworded.canonical_event_id == reference.canonical_event_id
    assert reworded.event_fingerprint == reference.event_fingerprint
    assert reworded.merge_status == "matched_fingerprint"
    # Content did change (title reworded), so last_changed_at should advance,
    # while identity and first_seen_at remain stable.
    assert reworded.first_seen_at == reference.first_seen_at


def test_unmatched_new_event_gets_empty_supersedes_and_self_consistent_timestamps() -> None:
    identity = _resolve()
    assert identity.merge_status == "unmatched"
    assert identity.supersedes == []
    assert identity.first_seen_at == identity.last_seen_at == identity.last_changed_at


def test_canonical_identity_preserved_when_event_date_resolves_from_unknown() -> None:
    """Regression for review finding #4.

    A candidate first observed with ``event_date=None`` (bucket falls back
    to ``publication_date``) must keep its canonical ID once the real event
    date becomes known, even though the fingerprint itself changes to the
    more precise, date-based value.
    """
    first = _resolve(event_date=None)
    known = [_as_known(first, event_date=None)]

    later = _resolve(event_date="2024-06-20", known_events=known)
    assert later.canonical_event_id == first.canonical_event_id
    assert later.merge_status == "matched_fingerprint"
    assert later.event_fingerprint != first.event_fingerprint


def test_event_date_promotion_ignores_known_records_with_a_real_date() -> None:
    """A known record that already had a real event date must never be
    reachable through the unknown-to-known promotion fallback, even if its
    fingerprint would coincidentally match the provisional (publication-date)
    bucket — that would resurrect the exact "different date bucket" merge
    the fingerprint is designed to prevent."""
    reference = _resolve(event_date="2024-06-14", publication_date="2024-06-14")
    known = [_as_known(reference, event_date="2024-06-14")]

    other = _resolve(event_date="2024-07-01", publication_date="2024-06-14", known_events=known)
    assert other.canonical_event_id != reference.canonical_event_id
    assert other.merge_status == "unmatched"


def test_known_event_missing_event_date_key_is_conservatively_ineligible() -> None:
    """A stored record that omits ``event_date`` altogether (e.g. an older
    record migrated before this field existed) must not be treated as
    "unknown date" by default — the promotion fallback only fires when a
    record explicitly persisted ``event_date: null``."""
    first = _resolve(event_date=None)
    known = [_as_known(first, event_date=None)]
    del known[0]["event_date"]

    later = _resolve(event_date="2024-06-20", known_events=known)
    assert later.canonical_event_id != first.canonical_event_id
    assert later.merge_status == "unmatched"


def test_identity_survives_event_date_and_publication_date_both_changing() -> None:
    """Round-2 regression: the event-date-promotion fallback must not depend
    on this observation retaining the original publication date.

    First observation: ``event_date=None``, ``publication_date=D1``. Later
    observation: ``event_date`` now a real date, and ``publication_date`` has
    also drifted to D2 (e.g. a source revision or a reviewed record with its
    own publication context). ``canonical_event_id`` must stay stable because
    matching now happens through the known record's own frozen
    ``identity_date_bucket`` (D1), never through this observation's
    ``publication_date``.
    """
    first = _resolve(event_date=None, publication_date="2024-06-01")
    known = [_as_known(first, event_date=None)]

    later = _resolve(
        event_date="2024-06-20",
        publication_date="2024-07-15",  # D1 ("2024-06-01") -> D2, deliberately different
        known_events=known,
    )
    assert later.canonical_event_id == first.canonical_event_id
    assert later.merge_status == "matched_fingerprint"
    assert later.identity_date_bucket == "2024-06-20"


def test_event_date_accessors_map_candidate_and_reviewed_fields_explicitly() -> None:
    """Regression for review finding #3: the candidate/reviewed field-name
    mapping (``event_date`` vs ``event_start``) must be explicit and tested,
    not just documented in prose."""
    candidate = {"event_date": "2024-06-14", "other_field": "x"}
    reviewed = {"event_start": "2024-06-14", "other_field": "x"}
    assert event_date_from_candidate(candidate) == "2024-06-14"
    assert event_date_from_reviewed_event(reviewed) == "2024-06-14"

    assert event_date_from_candidate({"event_date": None}) is None
    assert event_date_from_reviewed_event({"event_start": None}) is None


def test_known_event_builders_map_event_date_field_explicitly() -> None:
    first = _resolve(event_date=None)
    candidate_record = first.to_dict() | {
        "source_id": None,
        "external_event_id": None,
        "event_date": None,
    }
    known_from_candidate = known_event_from_candidate(candidate_record)
    assert known_from_candidate["event_date"] is None
    assert known_from_candidate["identity_date_bucket"] == first.identity_date_bucket
    assert known_from_candidate["canonical_event_id"] == first.canonical_event_id

    reviewed_record = first.to_dict() | {
        "source_id": None,
        "external_event_id": None,
        "event_start": None,
    }
    known_from_reviewed = known_event_from_reviewed_event(reviewed_record)
    assert known_from_reviewed["event_date"] is None
    assert known_from_reviewed["identity_date_bucket"] == first.identity_date_bucket

    # A promotion lookup must work identically regardless of which builder
    # produced the known_events entry, since both map to the same shape.
    later = _resolve(event_date="2024-06-20", known_events=[known_from_reviewed])
    assert later.canonical_event_id == first.canonical_event_id
    assert later.merge_status == "matched_fingerprint"


def test_content_signature_is_stable_across_a_json_round_trip_when_unchanged() -> None:
    """Regression for review finding #3.

    ``last_changed_at`` must only be recomputed from a *persisted*
    ``content_signature`` read back through an actual JSON round trip, not
    from an in-memory value that a real pipeline would never have.
    """
    signature = compute_content_signature(
        title="Oil spill near Pasir Panjang Terminal", text_fields=["claim a", "claim b"]
    )
    first = _resolve(content_signature=signature)
    stored = json.loads(json.dumps(_as_known(first)))

    same_signature = compute_content_signature(
        title="Oil spill near Pasir Panjang Terminal", text_fields=["claim a", "claim b"]
    )
    second = _resolve(content_signature=same_signature, known_events=[stored])

    assert same_signature == signature
    assert second.canonical_event_id == first.canonical_event_id
    assert second.last_changed_at == first.last_changed_at
    assert second.content_signature == signature


def test_content_signature_round_trip_detects_a_real_change() -> None:
    original_signature = compute_content_signature(
        title="Oil spill near Pasir Panjang Terminal", text_fields=["claim a"]
    )
    first = _resolve(content_signature=original_signature, now=NOW)
    stored = json.loads(json.dumps(_as_known(first)))

    changed_signature = compute_content_signature(
        title="Pasir Panjang oil spill - operations reported unaffected",
        text_fields=["claim a", "claim b (new)"],
    )
    later = datetime(2026, 7, 23, tzinfo=UTC)
    second = _resolve(content_signature=changed_signature, known_events=[stored], now=later)

    assert changed_signature != original_signature
    assert second.canonical_event_id == first.canonical_event_id
    assert second.first_seen_at == first.first_seen_at
    assert second.last_changed_at != first.last_changed_at
    assert second.content_signature == changed_signature


def _as_known(
    identity,
    *,
    content_signature: str | None = None,
    source_id=None,
    external_event_id=None,
    event_date: str | None = "2024-06-14",
) -> dict:
    return {
        "source_id": source_id,
        "external_event_id": external_event_id,
        "event_date": event_date,
        "event_fingerprint": identity.event_fingerprint,
        "canonical_event_id": identity.canonical_event_id,
        "identity_date_bucket": identity.identity_date_bucket,
        "first_seen_at": identity.first_seen_at,
        "last_changed_at": identity.last_changed_at,
        "content_signature": (
            content_signature if content_signature is not None else identity.content_signature
        ),
        "supersedes": identity.supersedes,
    }
