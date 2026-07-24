"""Bounded official-notice and news-discovery adapter.

Two intake paths share this module because they share every safety property
and differ only in what the resulting evidence is allowed to do:

* **Official notice** (port authority, canal authority, carrier advisory).
  Produces ``evidence_role='confirming'`` evidence. It establishes the notice
  that was published -- not that any particular lane, service or organization
  was affected.
* **News discovery**. Produces ``evidence_role='discovery_only'`` evidence,
  which ``analysis.events`` will refuse to accept as the sole support for a
  material impact conclusion.

Safety properties, all inherited from the repository's existing hardened
discovery model rather than reinvented:

* The adapter parses bytes it is handed and never fetches anything.
* A link found in a feed is **recorded, never followed**. There is no code
  path here that turns a discovered URL into a request.
* Titles and summaries are truncated to a documented bound, so no full
  article body can enter the repository. Full copyrighted text is never
  stored or republished.
* User-info is stripped from every retained URL.
* Malformed entries fail the parse rather than yielding partial records.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from defusedxml import ElementTree as DefusedElementTree

from ..observations import content_hash
from ..url_redaction import redact_url_userinfo

#: Maximum retained length of a notice or headline title.
MAX_TITLE_LENGTH = 300

#: Maximum retained length of a claim/summary. Matches the 600-character
#: bound in schemas/event_evidence.schema.json so the adapter cannot emit a
#: record the contract would reject.
MAX_CLAIM_LENGTH = 600

#: Maximum entries accepted from one payload.
MAX_ENTRIES = 200

#: Maximum payload size the parser will accept.
MAX_BYTES = 10_000_000

ALLOWED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/json",
)

_RSS_ITEM_PATH = "./channel/item"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class NoticeFeedError(ValueError):
    """Raised when a payload does not match the declared notice contract.

    Messages never include entry content, only structural detail.
    """


@dataclass(slots=True, frozen=True)
class NoticeSpec:
    """Metadata describing how one feed's entries should be recorded."""

    source_id: str
    source_name: str
    source_class: str
    parser_version: str
    #: ``official_notice`` entries can confirm; ``discovery`` entries cannot.
    intake_kind: str
    licence_status: str = "pending_review"
    redistribution_status: str = "link_only"
    known_limitations: tuple[str, ...] = ()

    @property
    def evidence_role(self) -> str:
        return "confirming" if self.intake_kind == "official_notice" else "discovery_only"

    @property
    def claim_type(self) -> str:
        return "official_notice" if self.intake_kind == "official_notice" else "discovery_lead"

    @property
    def strength(self) -> str:
        # An official notice from the operating authority is primary-grade
        # evidence of the notice. A discovery lead is not primary evidence of
        # anything and is graded accordingly.
        return "A" if self.intake_kind == "official_notice" else "D"


def _truncate(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _parse_publication_date(value: str | None) -> str | None:
    """Best-effort ISO date from a feed timestamp, or ``None``.

    Returning ``None`` for an unrecognised format is correct: an invented
    publication date would corrupt both clustering and freshness.
    """
    if not value:
        return None
    text = value.strip()
    for parser in (
        lambda raw: date.fromisoformat(raw[:10]),
        lambda raw: datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %z").date(),
        lambda raw: datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z").date(),
    ):
        try:
            return parser(text).isoformat()
        except (ValueError, TypeError):
            continue
    return None


def _entry_fields(element: Any) -> tuple[str, str, str | None, str | None, str | None]:
    """Extract ``(title, summary, link, guid, published)`` from one entry."""
    if element.tag == f"{_ATOM_NS}entry":
        title = (element.findtext(f"{_ATOM_NS}title") or "").strip()
        summary = (
            element.findtext(f"{_ATOM_NS}summary")
            or element.findtext(f"{_ATOM_NS}content")
            or ""
        ).strip()
        link_element = element.find(f"{_ATOM_NS}link")
        link = link_element.get("href") if link_element is not None else None
        guid = (element.findtext(f"{_ATOM_NS}id") or "").strip() or None
        published = (
            element.findtext(f"{_ATOM_NS}published")
            or element.findtext(f"{_ATOM_NS}updated")
            or None
        )
        return title, summary, link, guid, published

    title = (element.findtext("title") or "").strip()
    summary = (element.findtext("description") or "").strip()
    link = (element.findtext("link") or "").strip() or None
    guid = (element.findtext("guid") or "").strip() or None
    published = element.findtext("pubDate")
    return title, summary, link, guid, published


def parse_notice_feed(
    payload: bytes,
    spec: NoticeSpec,
    *,
    retrieved_at: str,
    max_entries: int = MAX_ENTRIES,
    max_bytes: int = MAX_BYTES,
) -> list[dict[str, Any]]:
    """Parse an RSS or Atom payload into bounded notice records.

    The returned records are *intake* records, not events. Promotion to an
    event, and any relevance or impact judgement, happens later under human
    review.
    """
    if len(payload) > max_bytes:
        raise NoticeFeedError(
            f"payload is {len(payload)} bytes, above the {max_bytes}-byte parser bound"
        )

    try:
        root = DefusedElementTree.fromstring(payload)
    except Exception as exc:  # defusedxml raises several distinct types
        raise NoticeFeedError(f"payload is not well-formed XML: {type(exc).__name__}") from exc

    entries = root.findall(_RSS_ITEM_PATH)
    if not entries:
        entries = root.findall(f"{_ATOM_NS}entry")
    if not entries:
        raise NoticeFeedError(
            "payload contains no RSS <item> or Atom <entry> elements; the envelope is not "
            "a notice feed"
        )
    if len(entries) > max_entries:
        raise NoticeFeedError(
            f"payload contains {len(entries)} entries, above the {max_entries}-entry bound"
        )

    records: list[dict[str, Any]] = []
    for index, element in enumerate(entries):
        title, summary, link, guid, published = _entry_fields(element)
        if not title:
            raise NoticeFeedError(f"entry {index} has no title; the entry is not usable")

        canonical_link = redact_url_userinfo(link) if link else None
        record = {
            "source_id": spec.source_id,
            "source_name": spec.source_name,
            "source_class": spec.source_class,
            "intake_kind": spec.intake_kind,
            "evidence_role": spec.evidence_role,
            "claim_type": spec.claim_type,
            "strength": spec.strength,
            "title": _truncate(title, MAX_TITLE_LENGTH),
            "claim": _truncate(summary or title, MAX_CLAIM_LENGTH),
            # Recorded for provenance and clustering only. Nothing in this
            # module or its callers ever requests this URL.
            "source_url": canonical_link,
            "source_record_id": guid or canonical_link,
            "publication_date": _parse_publication_date(published),
            "retrieved_at": retrieved_at,
            "parser_version": spec.parser_version,
            "licence_status": spec.licence_status,
            "redistribution_status": spec.redistribution_status,
            "raw_snapshot_path": None,
            "content_sha256": content_hash(spec.source_id, title, summary, str(canonical_link)),
            "known_limitations": list(spec.known_limitations),
        }
        records.append(record)

    return records


def build_manual_intake_record(
    *,
    publisher: str,
    source_class: str,
    notice_reference: str,
    landing_url: str,
    publication_date: str,
    claim: str,
    recorded_at: str,
    known_limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Record one human-reviewed official notice.

    This is the bounded manual path used when a publisher offers no
    machine-readable feed. It makes no network request. The claim is capped
    at the same bound as the automated path, so the manual route cannot be
    used to smuggle a full article into the repository.
    """
    if not notice_reference.strip():
        raise NoticeFeedError("a manual intake record requires the publisher's notice reference")
    if not claim.strip():
        raise NoticeFeedError("a manual intake record requires a claim")

    bounded_claim = _truncate(claim, MAX_CLAIM_LENGTH)
    return {
        "source_id": "MANUAL_NOTICE_INTAKE",
        "source_name": publisher,
        "source_class": source_class,
        "intake_kind": "official_notice",
        "evidence_role": "confirming",
        "claim_type": "official_notice",
        "strength": "A",
        "title": _truncate(f"{publisher} notice {notice_reference}", MAX_TITLE_LENGTH),
        "claim": bounded_claim,
        "source_url": redact_url_userinfo(landing_url),
        "source_record_id": notice_reference.strip(),
        "publication_date": _parse_publication_date(publication_date),
        "retrieved_at": recorded_at,
        "parser_version": "manual_notice_v1",
        "licence_status": "reviewed",
        "redistribution_status": "link_only",
        "raw_snapshot_path": None,
        "content_sha256": content_hash(publisher, notice_reference, bounded_claim),
        "known_limitations": [
            "Recorded by a human from the publisher's own page; no automated retrieval "
            "was performed and no full notice text is stored.",
            *known_limitations,
        ],
    }


def to_event_evidence(
    record: Mapping[str, Any],
    *,
    evidence_id: str,
    event_id: str,
    relation: str = "supports",
    scope_supported: str = "node",
    event_date: str | None = None,
) -> dict[str, Any]:
    """Promote one intake record to an ``event_evidence`` record.

    Promotion preserves ``evidence_role`` verbatim. A discovery lead stays a
    discovery lead after promotion -- that is the whole point of carrying the
    role through the intake layer.
    """
    return {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "source_id": record["source_id"],
        "source_name": record["source_name"],
        "source_class": record["source_class"],
        "source_url": record.get("source_url"),
        "source_record_id": record.get("source_record_id"),
        "claim": record["claim"],
        "claim_type": record["claim_type"],
        "evidence_role": record["evidence_role"],
        "relation": relation,
        "strength": record["strength"],
        "scope_supported": scope_supported,
        "event_date": event_date,
        "publication_date": record.get("publication_date"),
        "retrieved_at": record["retrieved_at"],
        "revised_at": None,
        "content_sha256": record["content_sha256"],
        "parser_version": record["parser_version"],
        "source_revision": None,
        "licence_status": record["licence_status"],
        "redistribution_status": record.get("redistribution_status", "unknown"),
        "raw_snapshot_path": None,
        "known_limitations": list(record.get("known_limitations", [])),
    }
