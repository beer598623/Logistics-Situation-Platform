"""Discovery-only RSS 2.x envelope parser (Scope C/D, WO-004 v0.2.1).

Extracts only bounded, structural candidate-resource metadata from an RSS
2.x feed -- channel/item counts, per-item index, a URL-shaped ``guid``,
``link``, ``enclosure.url``/``enclosure.type``, a normalized publication
timestamp when parseable, and each URL's scheme/host/path. It never
retains full titles, descriptions, instruction text, HTML content, raw
XML, or a source's warning prose, and it never creates a staging record.
Every retained URL string also has any embedded user-info
(``user:password@host``) stripped via ``collectors.url_redaction`` before
it is bounded or stored -- a retained URL string must never carry
credentials (review round 2, finding 2).

SSRF / follow-link boundary: this module has no HTTP client, imports none,
and cannot reach the network under any input -- discovering a candidate
URL is structurally incapable of fetching it here. No candidate URL is
ever followed automatically; a future controlled fetch of a discovered
candidate requires a separate work order with host allowlisting, DNS/IP
protections, redirect policy, request-count bounds, and human approval.

Security posture mirrors ``collectors/adapters/cap.py`` and
``collectors/adapters/xml_envelope.py``: the response-size limit is
enforced before any parsing, ``defusedxml`` forbids DTD/entities/external
references, and no exception raised here ever includes the raw payload
text. Callers should run ``collectors.adapters.xml_envelope.classify_envelope``
first and only call into this module when the classified kind is
``"rss"`` -- this parser raises rather than silently reinterpreting a
non-RSS root.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from ..url_redaction import redact_url_userinfo

#: Bounded so an adversarial feed with an enormous item count cannot
#: inflate the discovery result or the eventual report artifact.
MAX_ITEMS = 50

#: A candidate URL string itself is structural (not free text), but its
#: length is still bounded defensively -- a query string could otherwise
#: be used to smuggle an arbitrarily large value into a report.
MAX_URL_LENGTH = 500

#: The root tag echoed in NotAnRssEnvelopeError's message is untrusted,
#: attacker-controlled XML-name/namespace text -- bounded independently of
#: the overall payload byte cap at the point the exception is raised, not
#: left to a downstream report-level sanitizer (review round 2, finding 4).
MAX_ROOT_NAME_LENGTH = 200

SAME_HOST = "same_host"
CROSS_HOST = "cross_host"
NON_HTTP = "non_http"
MALFORMED = "malformed"


class RssSecurityError(ValueError):
    """A payload was rejected before or during parsing for a security
    reason (oversized, DOCTYPE/DTD, external or internal entity). The
    message must never include the raw payload."""


class RssParseError(ValueError):
    """A payload is not well-formed XML at all (no DTD/entity/oversize
    involved). Kept distinct from ``RssSecurityError`` so a diagnostic
    report can categorize this as a parse failure rather than a security
    rejection. The message must never include the raw payload."""


class NotAnRssEnvelopeError(ValueError):
    """The root element is not ``<rss>``. Run
    ``collectors.adapters.xml_envelope.classify_envelope`` first and only
    call ``discover_rss_candidates`` when the classified kind is
    ``"rss"`` -- this parser must never reinterpret another envelope kind
    as RSS."""


def _bounded_url(value: str) -> str:
    if len(value) <= MAX_URL_LENGTH:
        return value
    omitted = len(value) - MAX_URL_LENGTH
    return value[:MAX_URL_LENGTH] + f"...(+{omitted} chars omitted)"


def _bounded_name(value: str) -> str:
    if len(value) <= MAX_ROOT_NAME_LENGTH:
        return value
    omitted = len(value) - MAX_ROOT_NAME_LENGTH
    return value[:MAX_ROOT_NAME_LENGTH] + f"...(+{omitted} chars omitted)"


def _classify_url(
    value: str, *, feed_host: str | None
) -> tuple[str, str | None, str | None, str | None]:
    """Return ``(group, scheme, host, path)`` for one candidate URL string.

    ``host`` is always ``urlparse(...).hostname`` -- never the raw
    ``netloc`` -- so embedded user-info (``user:pass@host``) is never
    exposed in a discovery result or report, and comparison against
    ``feed_host`` cannot be confused by it either. Host comparison and
    storage deliberately consider only the hostname component, ignoring
    any port: this is a discovery-only module that never connects to any
    candidate URL in this iteration, so a same-hostname/different-port
    candidate is grouped as ``same_host`` here. A future controlled fetch
    work order must treat host and port together as part of its own
    allowlist policy -- this grouping is not itself an authorization to
    connect to any port.
    """
    try:
        parsed = urlparse(value)
    except ValueError:
        return MALFORMED, None, None, None
    if not parsed.scheme or not parsed.hostname:
        return MALFORMED, None, None, None
    if parsed.scheme not in {"http", "https"}:
        return NON_HTTP, parsed.scheme, parsed.hostname, (parsed.path or None)
    if feed_host and parsed.hostname == feed_host.lower():
        return SAME_HOST, parsed.scheme, parsed.hostname, (parsed.path or None)
    return CROSS_HOST, parsed.scheme, parsed.hostname, (parsed.path or None)


def _parse_pub_date(raw: str | None) -> str | None:
    """Return a normalized ISO-8601 UTC timestamp if ``raw`` parses as an
    RFC 2822 pubDate, else None. An unparseable value is dropped entirely
    rather than retained as raw text."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True, frozen=True)
class RssUrlCandidate:
    item_index: int
    source_field: str  # "link" | "guid" | "enclosure"
    url: str
    scheme: str | None
    host: str | None
    path: str | None
    group: str
    media_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_index": self.item_index,
            "source_field": self.source_field,
            "url": self.url,
            "scheme": self.scheme,
            "host": self.host,
            "path": self.path,
            "group": self.group,
            "media_type": self.media_type,
        }


@dataclass(slots=True, frozen=True)
class RssDiscoveryResult:
    channel_item_count: int
    items_considered: int
    candidates: list[RssUrlCandidate]
    item_publication_times: dict[int, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_item_count": self.channel_item_count,
            "items_considered": self.items_considered,
            "same_host_urls": [c.url for c in self.candidates if c.group == SAME_HOST],
            "cross_host_urls": [c.url for c in self.candidates if c.group == CROSS_HOST],
            "non_http_values": [c.url for c in self.candidates if c.group == NON_HTTP],
            "malformed_urls": [c.url for c in self.candidates if c.group == MALFORMED],
            "candidate_media_types": sorted(
                {c.media_type for c in self.candidates if c.media_type}
            ),
            "candidates": [c.to_dict() for c in self.candidates],
            "item_publication_times": dict(self.item_publication_times),
        }


def discover_rss_candidates(
    payload: bytes, *, max_bytes: int, feed_host: str | None
) -> tuple[RssDiscoveryResult, list[str]]:
    """Parse an RSS 2.x envelope into discovery-only structural metadata.

    Raises ``RssSecurityError`` for an oversized or DTD/entity-bearing
    payload (before any parsing), ``RssParseError`` for ordinary malformed
    XML that raised no security concern, and ``NotAnRssEnvelopeError`` if
    the root element is not ``<rss>``. Never fetches any discovered URL --
    this module has no HTTP client at all.
    """
    if len(payload) > max_bytes:
        raise RssSecurityError(
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
        raise RssSecurityError(f"payload rejected: {type(exc).__name__}") from None
    except Exception as exc:  # noqa: BLE001 -- never echo the raw payload back
        # Not a DTD/entity/oversize security rejection (that's the branch
        # above) -- this is ordinary malformed XML, categorized separately
        # as a parse failure, not a security one.
        raise RssParseError(f"payload could not be parsed as XML: {type(exc).__name__}") from None

    if root.tag != "rss":
        raise NotAnRssEnvelopeError(
            f"root element is not <rss>, got {_bounded_name(str(root.tag))!r}"
        )

    warnings: list[str] = []
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    channel_item_count = len(items)
    if channel_item_count > MAX_ITEMS:
        warnings.append(
            f"channel has {channel_item_count} items; only the first {MAX_ITEMS} were considered"
        )
    considered = items[:MAX_ITEMS]

    candidates: list[RssUrlCandidate] = []
    item_publication_times: dict[int, str] = {}

    for index, item in enumerate(considered):
        link_el = item.find("link")
        if link_el is not None and link_el.text and link_el.text.strip():
            # redact_url_userinfo runs before _bounded_url so any embedded
            # credential is stripped before length truncation, not after
            # (review round 2, finding 2: a retained URL string must never
            # carry username/password, regardless of its length).
            url = _bounded_url(redact_url_userinfo(link_el.text.strip()))
            group, scheme, host, path = _classify_url(url, feed_host=feed_host)
            candidates.append(RssUrlCandidate(index, "link", url, scheme, host, path, group))

        guid_el = item.find("guid")
        if guid_el is not None and guid_el.text and guid_el.text.strip():
            guid_text = guid_el.text.strip()
            # A guid is retained only when its text is itself URL-shaped.
            # RSS's isPermaLink defaults to "true" when the attribute is
            # absent, but that attribute is only the *publisher's claim*
            # that the guid is a dereferenceable URL -- it is not proof,
            # and trusting it blindly would let arbitrary non-URL guid
            # text (an opaque message ID, or worse, warning prose) be
            # retained verbatim in a public diagnostic artifact. The
            # isPermaLink attribute is therefore never consulted here;
            # only the value's own shape decides retention.
            if guid_text.startswith(("http://", "https://")):
                url = _bounded_url(redact_url_userinfo(guid_text))
                group, scheme, host, path = _classify_url(url, feed_host=feed_host)
                candidates.append(RssUrlCandidate(index, "guid", url, scheme, host, path, group))

        enclosure_el = item.find("enclosure")
        if enclosure_el is not None:
            enclosure_url = enclosure_el.get("url")
            enclosure_type = enclosure_el.get("type")
            if enclosure_url:
                url = _bounded_url(redact_url_userinfo(enclosure_url.strip()))
                group, scheme, host, path = _classify_url(url, feed_host=feed_host)
                candidates.append(
                    RssUrlCandidate(
                        index,
                        "enclosure",
                        url,
                        scheme,
                        host,
                        path,
                        group,
                        media_type=(enclosure_type or "").strip()[:80] or None,
                    )
                )

        pub_date_el = item.find("pubDate")
        pub_date_iso = _parse_pub_date(pub_date_el.text if pub_date_el is not None else None)
        if pub_date_iso:
            item_publication_times[index] = pub_date_iso

    result = RssDiscoveryResult(
        channel_item_count=channel_item_count,
        items_considered=len(considered),
        candidates=candidates,
        item_publication_times=item_publication_times,
    )
    return result, warnings
