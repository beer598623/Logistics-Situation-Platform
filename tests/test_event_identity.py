from __future__ import annotations

from datetime import UTC, datetime

from collectors.event_identity import compute_event_fingerprint, resolve_event_identity

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
    known = [
        {
            "source_id": "GDACS",
            "external_event_id": "EQ-99",
            "event_fingerprint": first.event_fingerprint,
            "canonical_event_id": first.canonical_event_id,
            "first_seen_at": first.first_seen_at,
            "last_changed_at": first.last_changed_at,
            "content_signature": "signature-1",
            "supersedes": [],
        }
    ]
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
    known = [
        {
            "source_id": None,
            "external_event_id": None,
            "event_fingerprint": first.event_fingerprint,
            "canonical_event_id": first.canonical_event_id,
            "first_seen_at": first.first_seen_at,
            "last_changed_at": first.last_changed_at,
            "content_signature": "signature-1",
            "supersedes": [],
        }
    ]
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


def _as_known(
    identity, *, content_signature: str = "signature-1", source_id=None, external_event_id=None
) -> dict:
    return {
        "source_id": source_id,
        "external_event_id": external_event_id,
        "event_fingerprint": identity.event_fingerprint,
        "canonical_event_id": identity.canonical_event_id,
        "first_seen_at": identity.first_seen_at,
        "last_changed_at": identity.last_changed_at,
        "content_signature": content_signature,
        "supersedes": identity.supersedes,
    }
