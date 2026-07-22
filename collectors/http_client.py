"""Small standard-library HTTP client with bounded retries and provenance.

No credentials are supported in v0.1.1. Live adapters remain disabled until
source terms, endpoint behavior, and fixtures have been reviewed.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
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


class ResilientHttpClient:
    def __init__(self, user_agent: str = "Logistics-Situation-Platform/0.1.1") -> None:
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
                with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                    body = response.read(max_response_bytes + 1)
                    if len(body) > max_response_bytes:
                        raise ResponseTooLargeError(
                            f"Response from {url} exceeded {max_response_bytes} bytes"
                        )
                    normalized_headers = {k.lower(): v for k, v in response.headers.items()}
                    return HttpResponse(
                        url=response.geturl(),
                        status=response.status,
                        headers=normalized_headers,
                        body=body,
                        content_sha256=self.sha256(body),
                    )
            except HTTPError as exc:
                if exc.code == 304:
                    return HttpResponse(
                        url=url,
                        status=304,
                        headers={},
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
