from __future__ import annotations

import io
import socket
import threading
import urllib.request
from email.message import Message
from urllib.response import addinfourl

import pytest

from collectors import http_client
from collectors.http_client import (
    DiscoveryRedirectError,
    DnsResolutionError,
    NonGlobalAddressError,
    PinnedConnectionError,
    PinnedRedirectError,
    PinnedTlsError,
    ResilientHttpClient,
    ResponseTooLargeError,
    _NoRedirectHandler,
    resolve_pinned_address,
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


# --- WO-006 Scope B/G: resolve_pinned_address (DNS-pinning, fail-closed) ----


def _fake_getaddrinfo(answers: list[tuple[int, str]]):
    """Build a network-free stand-in for ``socket.getaddrinfo`` returning
    ``(family, ip)`` pairs shaped like real ``getaddrinfo`` tuples --
    ``resolve_pinned_address`` only ever reads ``sockaddr[0]``, so the
    other tuple fields are filler."""

    def _fake(host, port, *args, **kwargs):  # noqa: ARG001
        return [(family, 1, 6, "", (ip, port)) for family, ip in answers]

    return _fake


def test_resolve_pinned_address_fails_closed_on_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args, **kwargs):
        raise OSError("simulated resolver failure")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(DnsResolutionError):
        resolve_pinned_address("www.tmd.go.th", 443)


def test_resolve_pinned_address_fails_closed_on_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo([]))
    with pytest.raises(DnsResolutionError):
        resolve_pinned_address("www.tmd.go.th", 443)


@pytest.mark.parametrize(
    "non_global_ip",
    [
        "10.0.0.5",  # private (RFC 1918)
        "127.0.0.1",  # loopback
        "169.254.1.1",  # link-local
        "224.0.0.1",  # multicast
        "192.0.0.1",  # IETF protocol assignments (reserved-ish, non-global)
        "0.0.0.0",  # noqa: S104 -- test data (unspecified address), not a real bind
    ],
)
def test_resolve_pinned_address_rejects_any_non_global_answer(
    monkeypatch: pytest.MonkeyPatch, non_global_ip: str
) -> None:
    # A mixed answer (one legitimate global address, one non-global one) is
    # rejected in its entirety -- fail closed, never silently filtered.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo([(socket.AF_INET, "8.8.8.10"), (socket.AF_INET, non_global_ip)]),
    )
    with pytest.raises(NonGlobalAddressError):
        resolve_pinned_address("www.tmd.go.th", 443)


def test_resolve_pinned_address_selects_lowest_ipv4_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            [
                (socket.AF_INET, "8.8.8.50"),
                (socket.AF_INET, "8.8.8.9"),
                (socket.AF_INET, "8.8.8.100"),
            ]
        ),
    )
    resolution = resolve_pinned_address("www.tmd.go.th", 443)
    assert resolution.selected_ip == "8.8.8.9"
    assert resolution.address_family == "IPv4"


def test_resolve_pinned_address_falls_back_to_ipv6_only_when_no_ipv4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            [
                (socket.AF_INET6, "2001:4860:4860::20"),
                (socket.AF_INET6, "2001:4860:4860::5"),
            ]
        ),
    )
    resolution = resolve_pinned_address("www.tmd.go.th", 443)
    assert resolution.selected_ip == "2001:4860:4860::5"
    assert resolution.address_family == "IPv6"


def test_resolve_pinned_address_prefers_ipv4_over_coexisting_ipv6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            [
                (socket.AF_INET6, "2001:4860:4860::5"),
                (socket.AF_INET, "8.8.8.9"),
            ]
        ),
    )
    resolution = resolve_pinned_address("www.tmd.go.th", 443)
    assert resolution.selected_ip == "8.8.8.9"
    assert resolution.address_family == "IPv4"


# --- WO-006 Scope B/G: get_pinned_candidate (pinned transport) -------------


class _LoopbackHttpServer:
    """A minimal, single-request HTTP server on 127.0.0.1 -- no TLS, no
    external network access. Used together with monkeypatching
    ``http_client._open_pinned_socket`` (the one factored-out extension
    point ``get_pinned_candidate`` uses to obtain its connected socket) so
    ``get_pinned_candidate``'s own HTTP-protocol handling (Host header,
    header/body bounds, redirect/304 handling) is exercised through the
    real ``http.client`` request/response machinery, without ever
    performing a real TLS handshake or leaving loopback."""

    def __init__(self, response_bytes: bytes) -> None:
        self._response = response_bytes
        self.received_request: bytes = b""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self.accept_count = 0
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _addr = self._sock.accept()
        self.accept_count += 1
        conn.settimeout(5)
        try:
            self.received_request = conn.recv(65536)
        except OSError:
            self.received_request = b""
        try:
            conn.sendall(self._response)
        except OSError:
            pass
        conn.close()

    def connect_client(self, timeout_seconds: float = 5) -> socket.socket:
        return socket.create_connection(("127.0.0.1", self.port), timeout=timeout_seconds)

    def join(self, timeout: float = 5) -> None:
        self._thread.join(timeout=timeout)
        self._sock.close()


def _install_loopback_server(
    monkeypatch: pytest.MonkeyPatch, response_bytes: bytes
) -> _LoopbackHttpServer:
    server = _LoopbackHttpServer(response_bytes)
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: server.connect_client(
            timeout_seconds
        ),
    )
    return server


def test_get_pinned_candidate_sends_host_header_for_hostname_not_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    server = _install_loopback_server(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="127.0.0.1",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    server.join()

    assert http_response.status == 200
    assert http_response.body == b"BODY"
    assert connected_ip == "127.0.0.1"
    assert server.accept_count == 1
    request_text = server.received_request.decode("latin-1")
    assert "Host: www.tmd.go.th\r\n" in request_text
    assert "GET /uploads/CAP/en/CAPTMD20260723155032_2.xml HTTP/1.1" in request_text


def test_get_pinned_candidate_rejects_a_3xx_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = b"HTTP/1.1 302 Found\r\nLocation: https://evil.test/x\r\n\r\n"
    server = _install_loopback_server(monkeypatch, response)

    client = ResilientHttpClient()
    with pytest.raises(PinnedRedirectError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="127.0.0.1",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    server.join()
    assert "evil.test" not in str(excinfo.value)


def test_get_pinned_candidate_passes_through_a_304_unmodified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Transport-level pass-through only -- treating a 304 as a structured
    # failure is the candidate-validation *adapter*'s job (mirroring
    # get_no_redirect()'s own division of responsibility), not this
    # transport's.
    response = b'HTTP/1.1 304 Not Modified\r\nETag: "abc"\r\n\r\n'
    server = _install_loopback_server(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="127.0.0.1",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    server.join()
    assert http_response.status == 304


def test_get_pinned_candidate_enforces_the_response_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * 1000
    response = b"HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\n\r\n" + body
    server = _install_loopback_server(monkeypatch, response)

    client = ResilientHttpClient()
    with pytest.raises(ResponseTooLargeError):
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="127.0.0.1",
            timeout_seconds=5,
            max_response_bytes=10,
        )
    server.join()


def test_get_pinned_candidate_only_ever_makes_one_physical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    server = _install_loopback_server(monkeypatch, response)

    client = ResilientHttpClient()
    client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="127.0.0.1",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    server.join()
    assert server.accept_count == 1


def test_get_pinned_candidate_wraps_a_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_connection_error(selected_ip, port, verify_hostname, *, timeout_seconds):
        raise OSError("simulated connection refused")

    monkeypatch.setattr(http_client, "_open_pinned_socket", _raise_connection_error)

    client = ResilientHttpClient()
    with pytest.raises(PinnedConnectionError):
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )


def test_get_pinned_candidate_wraps_a_tls_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import ssl

    def _raise_tls_error(selected_ip, port, verify_hostname, *, timeout_seconds):
        raise ssl.SSLError("simulated certificate verify failed")

    monkeypatch.setattr(http_client, "_open_pinned_socket", _raise_tls_error)

    client = ResilientHttpClient()
    with pytest.raises(PinnedTlsError):
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )


def test_open_pinned_socket_verifies_the_hostname_not_the_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test of ``_open_pinned_socket`` in isolation: proves the TLS
    context is asked to verify ``server_hostname=verify_hostname`` (the
    fixed policy hostname), never the IP address used to physically
    connect. No real TLS handshake or socket is used -- both
    ``socket.create_connection`` and the SSL context are monkeypatched."""

    calls: dict[str, object] = {}

    class _FakeContext:
        def wrap_socket(self, sock, *, server_hostname):
            calls["sock"] = sock
            calls["server_hostname"] = server_hostname
            return "WRAPPED_SOCKET"

    fake_raw_sock = object()
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: fake_raw_sock)
    monkeypatch.setattr(http_client.ssl, "create_default_context", lambda: _FakeContext())

    result = http_client._open_pinned_socket("8.8.8.10", 443, "www.tmd.go.th", timeout_seconds=5)
    assert result == "WRAPPED_SOCKET"
    assert calls["sock"] is fake_raw_sock
    assert calls["server_hostname"] == "www.tmd.go.th"
