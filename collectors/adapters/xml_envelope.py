"""Generic, hardened XML-envelope classifier (Scope B, WO-004 v0.2.1).

Inspects a bounded XML response and returns structural metadata only --
root local name, root namespace, a classified envelope kind, content byte
length, and the content SHA-256 supplied by the HTTP layer. This module
never reinterprets one envelope kind as another (an RSS feed is never
treated as a CAP alert, and vice versa) and never creates a staging
record; it exists purely so a caller can decide, before any
profile-specific parsing, what kind of document it actually received.

Security posture mirrors ``collectors/adapters/cap.py``:

- The response-size limit is enforced *before* any parsing is attempted.
- ``defusedxml`` rejects any ``<!DOCTYPE ...>``, external entity, or
  internal entity-expansion ("billion laughs") attempt.
- No exception raised here ever includes the raw payload text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

#: Kept identical to collectors/adapters/cap.py's constant so both modules
#: agree on what counts as a CAP 1.2 alert -- this classifier does not
#: import from cap.py (to keep the two parsers fully independent code
#: paths, per Scope A), but the value itself must not drift.
CAP_NAMESPACE_1_2 = "urn:oasis:names:tc:emergency:cap:1.2"
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"

CAP_ALERT = "cap_alert"
RSS = "rss"
ATOM = "atom"
OTHER_XML = "other_xml"

#: Root local-name/namespace strings are structural, but still bounded
#: independently of the overall payload byte cap -- an XML document's root
#: tag can itself carry an attacker-controlled string up to that cap's
#: size, and this classifier must never surface an unbounded raw value in
#: its own returned classification, regardless of what a downstream
#: report-level sanitizer would later do (review round 2, finding 4: bound
#: untrusted root metadata at the parser boundary itself). This is the
#: retained prefix length, not a strict total-length cap: a longer value
#: keeps its first MAX_ROOT_NAME_LENGTH characters plus a bounded
#: "...(+N chars omitted)" marker appended.
MAX_ROOT_NAME_LENGTH = 200


def _bounded_name(value: str | None) -> str | None:
    if value is None or len(value) <= MAX_ROOT_NAME_LENGTH:
        return value
    omitted = len(value) - MAX_ROOT_NAME_LENGTH
    return value[:MAX_ROOT_NAME_LENGTH] + f"...(+{omitted} chars omitted)"


class EnvelopeSecurityError(ValueError):
    """A payload was rejected before or during classification for a
    security reason (oversized, DOCTYPE/DTD, external or internal entity).
    The message must never include the raw payload."""


class EnvelopeParseError(ValueError):
    """A payload is not well-formed XML at all (no DTD/entity/oversize
    involved -- ``defusedxml`` never flagged a security concern; the
    document simply does not parse). Kept distinct from
    ``EnvelopeSecurityError`` so a diagnostic report can categorize this as
    a parse failure rather than a security rejection. The message must
    never include the raw payload."""


@dataclass(slots=True, frozen=True)
class EnvelopeClassification:
    """Structural metadata only -- never full content, never a decision
    about whether the document is usable by any specific profile parser.
    ``root_local_name``/``root_namespace`` are bounded to
    ``MAX_ROOT_NAME_LENGTH`` before this dataclass is even constructed."""

    root_local_name: str | None
    root_namespace: str | None
    envelope_kind: str
    content_length: int
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_local_name": self.root_local_name,
            "root_namespace": self.root_namespace,
            "envelope_kind": self.envelope_kind,
            "content_length": self.content_length,
            "content_sha256": self.content_sha256,
        }


def classify_envelope(
    payload: bytes, *, max_bytes: int, content_sha256: str
) -> EnvelopeClassification:
    """Classify a bounded XML payload's root element structurally.

    Raises ``EnvelopeSecurityError`` for an oversized payload (checked
    before any parsing) or a DTD/entity rejection during the hardened parse,
    and ``EnvelopeParseError`` for ordinary malformed (not well-formed) XML
    that raised no security concern. Never creates a staging record and
    never treats the classified kind as authorization to parse it with a
    different profile's parser -- the caller decides what to do with the
    classification.
    """
    if len(payload) > max_bytes:
        raise EnvelopeSecurityError(
            f"payload of {len(payload)} bytes exceeds the {max_bytes}-byte "
            "limit; rejected before parsing"
        )

    try:
        root = DefusedET.fromstring(
            payload,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        raise EnvelopeSecurityError(f"payload rejected: {type(exc).__name__}") from None
    except Exception as exc:  # noqa: BLE001 -- never echo the raw payload back
        # Not a DTD/entity/oversize security rejection (that's the branch
        # above) -- this is ordinary malformed XML (e.g. a ParseError), so
        # it is categorized separately as a parse failure, not a security
        # one.
        raise EnvelopeParseError(
            f"payload could not be parsed as XML: {type(exc).__name__}"
        ) from None

    tag = root.tag
    if isinstance(tag, str) and tag.startswith("{"):
        namespace, _, local_name = tag[1:].partition("}")
    else:
        namespace, local_name = None, (tag if isinstance(tag, str) else None)

    if namespace == CAP_NAMESPACE_1_2 and local_name == "alert":
        kind = CAP_ALERT
    elif namespace is None and local_name == "rss":
        kind = RSS
    elif namespace == ATOM_NAMESPACE and local_name == "feed":
        kind = ATOM
    else:
        kind = OTHER_XML

    return EnvelopeClassification(
        root_local_name=_bounded_name(local_name),
        root_namespace=_bounded_name(namespace),
        envelope_kind=kind,
        content_length=len(payload),
        content_sha256=content_sha256,
    )
