"""Shared URL user-info redaction (WO-004 v0.2.1 review round 2, finding 2).

A URL string that legitimately belongs in a diagnostic report or discovery
result (an RSS ``<link>``/``<guid>``/``<enclosure>`` value, a request or
response URL) may still embed credentials via the deprecated
``user:password@host`` URL syntax. This module strips that user-info
component from any URL string before it is retained or serialized
anywhere -- scheme, host, port, path, query, and fragment are all
preserved; only the user-info component is ever removed. This is separate,
structural logic from ``_bounded_url``'s length cap in
``collectors/adapters/rss_discovery.py``: bounding limits size, this
prevents a specific class of sensitive content from being retained at all.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url_userinfo(value: str) -> str:
    """Return ``value`` with any embedded user-info stripped from its
    authority component.

    Values that are not a parseable absolute URL (no scheme/netloc, or a
    string ``urlsplit`` cannot parse at all) are returned unchanged --
    there is no authority component to redact user-info from in the first
    place, and such a value is not itself a credential-bearing URL.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if "@" not in parts.netloc:
        return value
    host_and_port = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, host_and_port, parts.path, parts.query, parts.fragment))
