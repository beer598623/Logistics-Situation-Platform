"""Shared, stable error classification for diagnostic reports (WO-004 v0.2.1
review round 1, finding 4).

A single place maps every exception type this repository's source-facing
code can raise to a stable ``(error_code, error_category)`` pair, so an
adapter (``collectors/adapters/tmd_cap.py``) and the manual-test script
(``scripts/manual_live_source_test.py``) agree on the same vocabulary
whether the failure was caught inside the adapter itself or escaped to the
script's own dispatch wrapper. ``error_code`` is always the exception's
class name; ``error_category`` is one of a small, stable set:
``validation`` / ``security`` / ``parse`` / ``content_type`` / ``unexpected``.

This module intentionally has no side effects and performs no I/O -- it is
pure classification logic, safe to import from both an adapter and a
script without creating a network- or filesystem-capable dependency.
"""

from __future__ import annotations

from .adapters.cap import CapSecurityError, MalformedCapAlertError
from .adapters.rss_discovery import NotAnRssEnvelopeError, RssParseError, RssSecurityError
from .adapters.xml_envelope import EnvelopeParseError, EnvelopeSecurityError
from .http_client import UnexpectedContentTypeError

_SECURITY_ERRORS = (CapSecurityError, EnvelopeSecurityError, RssSecurityError)
_PARSE_ERRORS = (
    MalformedCapAlertError,
    NotAnRssEnvelopeError,
    EnvelopeParseError,
    RssParseError,
)


def classify_error(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, error_category)`` for one exception.

    Best-effort only -- an unrecognized exception type still yields a
    result (category ``"unexpected"``), never a reason to skip producing a
    diagnostic report.
    """
    code = type(exc).__name__
    if isinstance(exc, SystemExit):
        return code, "validation"
    if isinstance(exc, _SECURITY_ERRORS):
        return code, "security"
    if isinstance(exc, _PARSE_ERRORS):
        return code, "parse"
    if isinstance(exc, UnexpectedContentTypeError):
        return code, "content_type"
    if isinstance(exc, ValueError):
        return code, "validation"
    return code, "unexpected"
