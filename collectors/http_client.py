"""Small standard-library HTTP client with bounded retries and provenance.

No credentials are supported in v0.1.2. Live adapters remain disabled until
source terms, endpoint behavior, and fixtures have been reviewed.
"""

from __future__ import annotations

import hashlib
import random
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(slots=True, frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    content_sha256: str


class ResponseTooLargeError(RuntimeError):
    """Raised when a response exceeds the source contract limit."""


class UnexpectedContentTypeError(RuntimeError):
    """Raised when a response's Content-Type does not match a source's
    documented allowlist (e.g. an HTML error/login page returned in place of
    JSON or XML data). Callers should treat this the same as any other
    fetch failure -- the body must not be parsed."""


class DiscoveryRedirectError(RuntimeError):
    """Raised by ``ResilientHttpClient.get_no_redirect`` when the response
    was an HTTP redirect (3xx). Discovery mode (WO-004 review round 2,
    finding 1) makes at most one physical request to the configured
    endpoint and must never request a redirect's ``Location`` target --
    this is enforced at the transport layer, before any such request could
    be made, not merely by capping retry attempts. The message carries only
    the rejected status code, never response body content."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rejects every HTTP redirect instead of the default urllib behavior
    of transparently following it. ``redirect_request`` is urllib's own
    extension point for this -- raising here happens before urllib would
    otherwise construct and send a second request to ``newurl``."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        raise DiscoveryRedirectError(
            f"refused to follow HTTP {code} redirect; discovery mode makes at "
            "most one request to the configured endpoint and never requests "
            "a redirect target"
        )


def _build_no_redirect_opener() -> urllib.request.OpenerDirector:
    """Factored out of ``get_no_redirect`` so tests can substitute a fully
    in-memory opener (a fake protocol handler alongside this same
    ``_NoRedirectHandler``) without touching production networking code or
    opening a real socket."""
    return urllib.request.build_opener(_NoRedirectHandler)


def validate_content_type(
    headers: Mapping[str, str], allowed_media_types: Sequence[str]
) -> tuple[str | None, str | None]:
    """Check a response's Content-Type header against an allowlist.

    Returns ``(content_type, warning)``. Content-Type parameters (e.g.
    ``; charset=utf-8``) are ignored for the comparison. A missing
    Content-Type header is not fatal -- some sources omit it -- but is
    surfaced as a warning since it could not be validated. A *present but
    unexpected* Content-Type (for example ``text/html``, typically an error
    or login page rather than real data) raises
    ``UnexpectedContentTypeError`` so the caller never parses the body.
    """
    content_type = headers.get("content-type")
    if not content_type:
        return None, "Content-Type header was not present; content type could not be validated"
    base_type = content_type.split(";", 1)[0].strip().lower()
    if base_type not in {media_type.lower() for media_type in allowed_media_types}:
        raise UnexpectedContentTypeError(
            f"unexpected Content-Type {content_type!r}; expected one of "
            f"{sorted(allowed_media_types)}"
        )
    return content_type, None


class ResilientHttpClient:
    def __init__(self, user_agent: str = "Logistics-Situation-Platform/0.1.2") -> None:
        self.user_agent = user_agent

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        attempts: int = 3,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("Only HTTP and HTTPS source endpoints are permitted")

        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            request_headers.update(headers)
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                request = Request(url, headers=request_headers, method="GET")
                with urlopen(request, timeout=timeout_seconds) as response:
                    body = response.read(max_response_bytes + 1)
                    if len(body) > max_response_bytes:
                        raise ResponseTooLargeError(
                            f"Response from {url} exceeded {max_response_bytes} bytes"
                        )
                    normalized_headers = {
                        key.lower(): value for key, value in response.headers.items()
                    }
                    return HttpResponse(
                        url=response.geturl(),
                        status=response.status,
                        headers=normalized_headers,
                        body=body,
                        content_sha256=self.sha256(body),
                    )
            except HTTPError as exc:
                if exc.code == 304:
                    not_modified_headers = {
                        key.lower(): value for key, value in (exc.headers or {}).items()
                    }
                    return HttpResponse(
                        url=url,
                        status=304,
                        headers=not_modified_headers,
                        body=b"",
                        content_sha256=self.sha256(b""),
                    )
                last_error = exc
                if 400 <= exc.code < 500 and exc.code not in {408, 429}:
                    raise
            except (URLError, TimeoutError, ResponseTooLargeError) as exc:
                last_error = exc
                if isinstance(exc, ResponseTooLargeError):
                    raise

            if attempt < attempts:
                delay = min(30.0, (2 ** (attempt - 1)) + random.uniform(0.0, 0.5))
                time.sleep(delay)

        raise RuntimeError(f"GET failed after {attempts} attempts: {url}") from last_error

    def get_no_redirect(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Discovery-only fetch (WO-004 review round 2, finding 1): exactly
        one physical HTTP request, no retry loop, and no redirect ever
        followed. A 3xx response raises ``DiscoveryRedirectError`` -- via
        ``_NoRedirectHandler.redirect_request`` -- before urllib would
        otherwise construct and send a request to the redirect's
        ``Location`` target. This is a stronger, transport-level guarantee
        than merely capping a retry count: even a single ``attempts=1``
        call to ``get()`` would still transparently follow a redirect to
        another host (or a private address), since retry count and
        redirect-following are unrelated urllib behaviors.

        Used only by ``TmdCapAdapter.discover_rss()``. GDACS and
        direct-CAP collection (``get()``, above) are unaffected and keep
        following redirects and retrying exactly as before this method was
        added.
        """
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("Only HTTP and HTTPS source endpoints are permitted")

        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            request_headers.update(headers)
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified

        opener = _build_no_redirect_opener()
        request = Request(url, headers=request_headers, method="GET")
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise ResponseTooLargeError(
                        f"Response from {url} exceeded {max_response_bytes} bytes"
                    )
                normalized_headers = {key.lower(): value for key, value in response.headers.items()}
                return HttpResponse(
                    url=response.geturl(),
                    status=response.status,
                    headers=normalized_headers,
                    body=body,
                    content_sha256=self.sha256(body),
                )
        except HTTPError as exc:
            if exc.code == 304:
                not_modified_headers = {
                    key.lower(): value for key, value in (exc.headers or {}).items()
                }
                return HttpResponse(
                    url=url,
                    status=304,
                    headers=not_modified_headers,
                    body=b"",
                    content_sha256=self.sha256(b""),
                )
            raise
