"""Shared test fixtures. Nothing here performs network access."""

from __future__ import annotations

from dataclasses import dataclass, field

from collectors.http_client import (
    HttpResponse,
    PinnedConnectionError,
    PinnedResolution,
    ResilientHttpClient,
    ResponseTooLargeError,
)


@dataclass
class FakeHttpClient:
    """Stand-in for ResilientHttpClient that returns one canned response.

    Used to exercise an adapter's full ``collect()`` pipeline (request ->
    fetch -> parse -> normalize -> CollectionResult) without opening a
    socket. Every test that uses this fixture is exercising deterministic,
    in-memory behavior only.
    """

    body: bytes
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    response_url: str | None = None
    call_count: int = field(default=0, init=False)
    last_attempts: int | None = field(default=None, init=False)
    no_redirect_call_count: int = field(default=0, init=False)
    raise_on_get_no_redirect: Exception | None = None
    #: WO-006 Scope B/G: fake for the DNS-pinned candidate transport.
    #: ``pinned_call_count`` and ``last_pinned_selected_ip`` let a test
    #: assert exactly one physical candidate fetch occurred and which IP
    #: it was given. ``raise_on_get_pinned_candidate`` simulates a
    #: transport-level failure (DNS/TLS/connection/redirect) without
    #: exercising real sockets -- see ``tests/test_http_client.py`` for
    #: the transport-level tests that do exercise the real pinning code.
    #: ``connected_ip_override``, when set to a value different from the
    #: ``selected_ip`` a test passes in, makes this fake mirror the real
    #: transport's fail-closed peer-pin check (ChatGPT review round 1,
    #: finding 2): it raises ``PinnedConnectionError`` itself, before
    #: "sending" anything, rather than returning a mismatched IP for the
    #: adapter to catch after the fact.
    pinned_call_count: int = field(default=0, init=False)
    last_pinned_selected_ip: str | None = field(default=None, init=False)
    raise_on_get_pinned_candidate: Exception | None = None
    connected_ip_override: str | None = None

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        attempts: int = 3,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        self.call_count += 1
        self.last_attempts = attempts
        if len(self.body) > max_response_bytes:
            raise ResponseTooLargeError("fake response exceeds max_response_bytes")
        return HttpResponse(
            url=self.response_url or url,
            status=self.status,
            headers=dict(self.headers),
            body=self.body,
            content_sha256=ResilientHttpClient.sha256(self.body),
        )

    def get_no_redirect(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        """Mirrors ``ResilientHttpClient.get_no_redirect`` -- no ``attempts``
        parameter exists here either, since discovery mode never retries.
        ``raise_on_get_no_redirect`` lets a test simulate a rejected
        redirect (or any other transport-level failure) without exercising
        the real urllib opener machinery -- see ``tests/test_http_client.py``
        for the transport-level test that does exercise it directly."""
        self.call_count += 1
        self.no_redirect_call_count += 1
        if self.raise_on_get_no_redirect is not None:
            raise self.raise_on_get_no_redirect
        if len(self.body) > max_response_bytes:
            raise ResponseTooLargeError("fake response exceeds max_response_bytes")
        return HttpResponse(
            url=self.response_url or url,
            status=self.status,
            headers=dict(self.headers),
            body=self.body,
            content_sha256=ResilientHttpClient.sha256(self.body),
        )

    def get_pinned_candidate(
        self,
        *,
        hostname: str,
        port: int,
        path: str,
        selected_ip: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> tuple[HttpResponse, str]:
        """Mirrors ``ResilientHttpClient.get_pinned_candidate`` -- no DNS
        lookup or socket is ever touched. Echoes ``selected_ip`` back as
        the connected IP, matching what the real transport guarantees by
        construction, unless ``connected_ip_override`` simulates a
        mismatch (see that field's docstring above)."""
        self.call_count += 1
        self.pinned_call_count += 1
        self.last_pinned_selected_ip = selected_ip
        if self.raise_on_get_pinned_candidate is not None:
            raise self.raise_on_get_pinned_candidate
        connected_ip = self.connected_ip_override or selected_ip
        if connected_ip != selected_ip:
            raise PinnedConnectionError(
                "connected IP did not match the DNS-validated selected IP; "
                "refusing to send the candidate request"
            )
        if len(self.body) > max_response_bytes:
            raise ResponseTooLargeError("fake response exceeds max_response_bytes")
        response = HttpResponse(
            url=self.response_url or f"https://{hostname}{path}",
            status=self.status,
            headers=dict(self.headers),
            body=self.body,
            content_sha256=ResilientHttpClient.sha256(self.body),
        )
        return response, connected_ip


def fake_resolve_pinned(selected_ip: str = "203.0.113.10", address_family: str = "IPv4"):
    """Build an injectable, network-free stand-in for
    ``collectors.http_client.resolve_pinned_address`` -- returns a fixed,
    RFC 5737 documentation-range address rather than doing any real DNS
    resolution. Pass the returned callable as
    ``TmdCapAdapter(..., resolve_pinned=...)``."""

    def _resolve(hostname: str, port: int) -> PinnedResolution:  # noqa: ARG001
        return PinnedResolution(selected_ip=selected_ip, address_family=address_family)

    return _resolve
