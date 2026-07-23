"""Shared test fixtures. Nothing here performs network access."""

from __future__ import annotations

from dataclasses import dataclass, field

from collectors.http_client import HttpResponse, ResilientHttpClient


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
        if len(self.body) > max_response_bytes:
            raise RuntimeError("fake response exceeds max_response_bytes")
        return HttpResponse(
            url=self.response_url or url,
            status=self.status,
            headers=dict(self.headers),
            body=self.body,
            content_sha256=ResilientHttpClient.sha256(self.body),
        )
