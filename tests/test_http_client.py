from __future__ import annotations

import io
import urllib.request
from email.message import Message
from urllib.response import addinfourl

import pytest

from collectors import http_client
from collectors.http_client import (
    DiscoveryRedirectError,
    ResilientHttpClient,
    ResponseTooLargeError,
    _NoRedirectHandler,
)


class _FakeHTTPHandler(urllib.request.HTTPHandler):
    """A network-free stand-in for the real ``HTTPHandler``: it subclasses
    ``urllib.request.HTTPHandler`` (so ``urllib.request.build_opener``
    treats it as *the* HTTP handler and skips adding the real one) but its
    ``http_open`` fabricates a response entirely in memory instead of
    opening a socket. This exercises the *actual* urllib opener/handler
    dispatch machinery -- including ``HTTPErrorProcessor`` and
    ``HTTPRedirectHandler``'s real ``http_error_302``-family methods -- not
    just a hand-rolled mock of this repository's own code.
    """

    def __init__(self, script: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self.script = script
        self.requested_urls: list[str] = []

    def http_open(self, req):
        url = req.full_url
        self.requested_urls.append(url)
        status, headers, body = self.script[url]
        msg = Message()
        for key, value in headers.items():
            msg[key] = value
        resp = addinfourl(io.BytesIO(body), msg, url, status)
        resp.msg = "status text"
        resp.code = status
        return resp

    https_open = http_open


def _build_test_opener(script: dict[str, tuple[int, dict[str, str], bytes]]) -> tuple:
    fake = _FakeHTTPHandler(script)
    opener = urllib.request.build_opener(_NoRedirectHandler, fake)
    return opener, fake


# --- Transport-level: a redirect is refused before its target is requested --


def test_get_no_redirect_never_requests_the_redirect_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "http://start.example.test/rss"
    target_url = "http://target.example.test/rss"
    opener, fake = _build_test_opener(
        {start_url: (302, {"Location": target_url}, b"")},
    )
    monkeypatch.setattr(http_client, "_build_no_redirect_opener", lambda: opener)

    client = ResilientHttpClient()
    with pytest.raises(DiscoveryRedirectError):
        client.get_no_redirect(start_url, timeout_seconds=5, max_response_bytes=1_000_000)

    assert fake.requested_urls == [start_url]
    assert target_url not in fake.requested_urls


def test_get_no_redirect_error_never_echoes_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "http://start.example.test/rss"
    opener, _fake = _build_test_opener(
        {start_url: (302, {"Location": "http://target.example.test/"}, b"CANARY_BODY_TEXT")},
    )
    monkeypatch.setattr(http_client, "_build_no_redirect_opener", lambda: opener)

    client = ResilientHttpClient()
    with pytest.raises(DiscoveryRedirectError) as excinfo:
        client.get_no_redirect(start_url, timeout_seconds=5, max_response_bytes=1_000_000)
    assert "CANARY_BODY_TEXT" not in str(excinfo.value)


# --- Transport-level: a successful (non-redirected) response works normally --


def test_get_no_redirect_returns_a_successful_response_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "http://start.example.test/rss"
    body = b"<rss><channel></channel></rss>"
    opener, fake = _build_test_opener({url: (200, {"content-type": "text/xml"}, body)})
    monkeypatch.setattr(http_client, "_build_no_redirect_opener", lambda: opener)

    client = ResilientHttpClient()
    response = client.get_no_redirect(url, timeout_seconds=5, max_response_bytes=1_000_000)
    assert response.status == 200
    assert response.url == url
    assert response.body == body
    assert response.headers["content-type"] == "text/xml"
    assert fake.requested_urls == [url]


def test_get_no_redirect_handles_304_like_get_does(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "http://start.example.test/rss"
    opener, _fake = _build_test_opener({url: (304, {"etag": '"abc"'}, b"")})
    monkeypatch.setattr(http_client, "_build_no_redirect_opener", lambda: opener)

    client = ResilientHttpClient()
    response = client.get_no_redirect(url, timeout_seconds=5, max_response_bytes=1_000_000)
    assert response.status == 304
    assert response.headers["etag"] == '"abc"'
    assert response.body == b""


def test_get_no_redirect_still_enforces_the_response_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "http://start.example.test/rss"
    opener, _fake = _build_test_opener({url: (200, {}, b"x" * 100)})
    monkeypatch.setattr(http_client, "_build_no_redirect_opener", lambda: opener)

    client = ResilientHttpClient()
    with pytest.raises(ResponseTooLargeError):
        client.get_no_redirect(url, timeout_seconds=5, max_response_bytes=10)


# --- The real (non-test-double) redirect handler class, in isolation -------


def test_no_redirect_handler_raises_before_any_request_to_newurl() -> None:
    """A pure unit test of _NoRedirectHandler.redirect_request itself:
    proves it raises synchronously with no I/O of any kind, independent of
    the surrounding opener machinery tested above."""
    handler = _NoRedirectHandler()
    req = urllib.request.Request("http://start.example.test/")
    with pytest.raises(DiscoveryRedirectError) as excinfo:
        handler.redirect_request(req, None, 302, "Found", {}, "http://target.example.test/")
    assert "target.example.test" not in str(excinfo.value)
