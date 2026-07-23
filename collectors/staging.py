"""Shared staging-record assembly (schemas/staging_record.schema.json).

Both the GDACS adapter (``collectors/adapters/gdacs.py``) and the generic
CAP 1.2 / TMD adapters (``collectors/adapters/cap.py``,
``collectors/adapters/tmd_cap.py``) build their normalized output through
this single helper so every staging record carries the same provenance
shape regardless of source. Building a staging record never infers
operational logistics impact and never assigns a ``canonical_event_id`` —
identity resolution belongs to a later, human-reviewed promotion step that
is out of scope for this pilot; a staging record only carries the
controlled ``candidate_identity_inputs`` a future promotion step would pass
to ``collectors.event_identity.resolve_event_identity``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_staging_record(
    *,
    source_id: str,
    retrieved_at: str,
    content_sha256: str,
    parser_version: str,
    source_external_id: str | None,
    source_revision: str | None,
    source_publication_time: str | None,
    title: str,
    source_url: str | None,
    primary_category: str,
    geography: Sequence[str],
    transport_modes: Sequence[str] = (),
    segments: Sequence[str] = (),
    event_date: str | None = None,
    publication_date: str | None = None,
    source_signal: Mapping[str, Any] | None = None,
    field_mapping_notes: Sequence[str] = (),
    warnings: Sequence[str] = (),
    known_limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble one staging record matching ``staging_record.schema.json``.

    ``source_signal`` must only ever carry source-native hazard/context
    classifications (a GDACS alert level, a CAP severity/certainty/urgency
    triple); callers must never place a platform impact-severity value
    there.
    """
    record: dict[str, Any] = {
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "content_sha256": content_sha256,
        "parser_version": parser_version,
        "source_external_id": source_external_id,
        "source_revision": source_revision,
        "source_publication_time": source_publication_time,
        "title": title,
        "source_url": source_url,
        "candidate_identity_inputs": {
            "primary_category": primary_category,
            "geography": list(geography),
            "transport_modes": list(transport_modes),
            "segments": list(segments),
            "event_date": event_date,
            "publication_date": publication_date,
        },
        "field_mapping_notes": list(field_mapping_notes),
        "warnings": list(warnings),
        "known_limitations": list(known_limitations),
    }
    if source_signal:
        record["source_signal"] = dict(source_signal)
    return record
