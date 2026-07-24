from __future__ import annotations

import io
import socket
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


class _FakeSocket:
    """A fully in-memory stand-in for a connected socket -- zero
    ``socket()``, ``bind()``, ``listen()``, ``accept()``, or
    ``create_connection()`` calls anywhere (ChatGPT review round 1,
    finding 1: CI must be completely network-free, including loopback).

    Implements just enough of the socket interface for
    ``http.client.HTTPConnection``/``HTTPResponse`` to drive a full
    request/response cycle against it: ``sendall`` records every byte
    the real transport code would have put on the wire (so a test can
    assert on the exact request, or assert nothing was ever sent),
    ``makefile`` hands back an in-memory reader over the canned response,
    and ``getpeername`` reports a fixed, test-supplied peer address.
    """

    def __init__(self, response_bytes: bytes, peer_ip: str = "8.8.8.10") -> None:
        self._rfile = io.BytesIO(response_bytes)
        self._peer_ip = peer_ip
        self.sent = b""
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, mode: str = "r", *args, **kwargs):  # noqa: ARG002
        if "r" in mode:
            return self._rfile
        return io.BytesIO()

    def settimeout(self, timeout: float | None) -> None:  # noqa: ARG002
        pass

    def close(self) -> None:
        self.closed = True

    def getpeername(self) -> tuple[str, int]:
        return (self._peer_ip, 443)


def _install_fake_pinned_socket(
    monkeypatch: pytest.MonkeyPatch, response_bytes: bytes, *, peer_ip: str = "8.8.8.10"
) -> _FakeSocket:
    fake_socket = _FakeSocket(response_bytes, peer_ip=peer_ip)
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )
    return fake_socket


def test_get_pinned_candidate_sends_host_header_for_hostname_not_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    fake_socket = _install_fake_pinned_socket(monkeypatch, response, peer_ip="8.8.8.10")

    client = ResilientHttpClient()
    http_response, connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )

    assert http_response.status == 200
    assert http_response.body == b"BODY"
    assert connected_ip == "8.8.8.10"
    request_text = fake_socket.sent.decode("latin-1")
    assert "Host: www.tmd.go.th\r\n" in request_text
    assert "GET /uploads/CAP/en/CAPTMD20260723155032_2.xml HTTP/1.1" in request_text


def test_get_pinned_candidate_rejects_a_3xx_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = b"HTTP/1.1 302 Found\r\nLocation: https://evil.test/x\r\n\r\n"
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    with pytest.raises(PinnedRedirectError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "evil.test" not in str(excinfo.value)


def test_get_pinned_candidate_passes_through_a_304_unmodified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Transport-level pass-through only -- treating a 304 as a structured
    # failure is the candidate-validation *adapter*'s job (mirroring
    # get_no_redirect()'s own division of responsibility), not this
    # transport's.
    response = b'HTTP/1.1 304 Not Modified\r\nETag: "abc"\r\n\r\n'
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    assert http_response.status == 304


def test_get_pinned_candidate_enforces_the_response_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * 1000
    response = b"HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\n\r\n" + body
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    with pytest.raises(ResponseTooLargeError):
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=10,
        )


def test_get_pinned_candidate_only_ever_makes_one_physical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    fake_socket = _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    # No retry parameter exists on get_pinned_candidate at all -- this
    # counts the literal "GET " request lines that ever reached the wire
    # to prove that structural absence actually holds at runtime.
    assert fake_socket.sent.count(b"GET ") == 1


def test_get_pinned_candidate_never_opens_a_real_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """ChatGPT review round 1, finding 1: an explicit guard proving the
    candidate transport tests above never fall back to a real socket --
    ``socket.socket``/``socket.create_connection`` are made to explode if
    called, and the fake-socket-based request/response cycle still
    succeeds without tripping either guard."""
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    _install_fake_pinned_socket(monkeypatch, response)

    def _explode(*args, **kwargs):
        raise AssertionError("a real socket was opened during a candidate transport test")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(socket, "create_connection", _explode)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    assert http_response.status == 200


def test_get_pinned_candidate_fails_closed_before_sending_on_peer_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ChatGPT review round 1, finding 2: if the opened socket's peer does
    not match the DNS-validated ``selected_ip``, the request must never be
    sent at all -- not merely fail closed after the fact. Asserts zero
    bytes ever reached ``sendall`` on the fake peer socket."""
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    fake_socket = _install_fake_pinned_socket(monkeypatch, response, peer_ip="8.8.8.99")

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
    assert fake_socket.sent == b""
    assert fake_socket.closed is True


def test_get_pinned_candidate_wraps_a_getpeername_failure_and_closes_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ChatGPT review round 2, finding 2: sock.getpeername() executes
    after TLS wrapping but before the try/finally that owns conn.close().
    A failure there must still be classified as PinnedConnectionError
    (not escape as an unclassified OSError) and must still close the
    socket -- proven with a fake socket whose getpeername() itself
    raises."""

    class _GetpeernameRaisesSocket:
        def __init__(self) -> None:
            self.closed = False
            self.sent = b""

        def sendall(self, data: bytes) -> None:
            self.sent += data

        def makefile(self, mode: str = "r", *args, **kwargs):  # noqa: ARG002
            return io.BytesIO()

        def settimeout(self, timeout: float | None) -> None:  # noqa: ARG002
            pass

        def close(self) -> None:
            self.closed = True

        def getpeername(self):
            raise OSError("simulated getpeername failure")

    fake_socket = _GetpeernameRaisesSocket()
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )

    client = ResilientHttpClient()
    with pytest.raises(PinnedConnectionError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "simulated getpeername failure" not in str(excinfo.value)
    assert fake_socket.sent == b""
    assert fake_socket.closed is True


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


# --- ChatGPT review round 2, finding 3: post-handshake failure paths -------


class _FaultySocket:
    """A fake, fully in-memory socket whose read/write side can be made
    to fail at a specific point (request write, header parsing, or body
    read) for exercising ``get_pinned_candidate``'s post-handshake error
    taxonomy -- zero real sockets involved."""

    def __init__(
        self,
        *,
        send_exc: Exception | None = None,
        makefile_result=None,
        peer_ip: str = "8.8.8.10",
    ) -> None:
        self._send_exc = send_exc
        self._makefile_result = makefile_result
        self._peer_ip = peer_ip
        self.sent = b""
        self.closed = False

    def sendall(self, data: bytes) -> None:
        if self._send_exc is not None:
            raise self._send_exc
        self.sent += data

    def makefile(self, mode: str = "r", *args, **kwargs):  # noqa: ARG002
        if "r" in mode and self._makefile_result is not None:
            return self._makefile_result
        return io.BytesIO()

    def settimeout(self, timeout: float | None) -> None:  # noqa: ARG002
        pass

    def close(self) -> None:
        self.closed = True

    def getpeername(self) -> tuple[str, int]:
        return (self._peer_ip, 443)


class _RaisingFile:
    """Serves ``header_bytes`` via ``readline()`` (so status-line/header
    parsing can succeed normally up to some point) and raises ``exc``
    once ``fail_on_read`` says to -- either from the next ``readline()``
    call (simulating a header-parsing failure) or from ``read()``
    (simulating a body-read failure)."""

    def __init__(self, header_bytes: bytes, exc: Exception, *, fail_on_readline: bool) -> None:
        self._reader = io.BytesIO(header_bytes)
        self._exc = exc
        self._fail_on_readline = fail_on_readline

    def readline(self, limit: int = -1) -> bytes:
        if self._fail_on_readline:
            raise self._exc
        return self._reader.readline(limit)

    def read(self, *args, **kwargs) -> bytes:
        if not self._fail_on_readline:
            raise self._exc
        return self._reader.read(*args, **kwargs)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_get_pinned_candidate_wraps_a_request_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = _FaultySocket(send_exc=OSError("simulated write failure"))
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )

    client = ResilientHttpClient()
    with pytest.raises(PinnedConnectionError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "simulated write failure" not in str(excinfo.value)
    assert fake_socket.closed is True


def test_get_pinned_candidate_wraps_a_response_header_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faulty_file = _RaisingFile(b"", OSError("simulated reset"), fail_on_readline=True)
    fake_socket = _FaultySocket(makefile_result=faulty_file)
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )

    client = ResilientHttpClient()
    with pytest.raises(PinnedConnectionError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "simulated reset" not in str(excinfo.value)
    assert fake_socket.closed is True


def test_get_pinned_candidate_wraps_a_response_body_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    header_bytes = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\n"
    faulty_file = _RaisingFile(
        header_bytes, OSError("simulated body reset"), fail_on_readline=False
    )
    fake_socket = _FaultySocket(makefile_result=faulty_file)
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )

    client = ResilientHttpClient()
    with pytest.raises(PinnedConnectionError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "simulated body reset" not in str(excinfo.value)
    assert fake_socket.closed is True


def test_get_pinned_candidate_wraps_a_post_handshake_tls_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssl

    header_bytes = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\n"
    faulty_file = _RaisingFile(
        header_bytes, ssl.SSLError("simulated TLS read failure"), fail_on_readline=False
    )
    fake_socket = _FaultySocket(makefile_result=faulty_file)
    monkeypatch.setattr(
        http_client,
        "_open_pinned_socket",
        lambda selected_ip, port, verify_hostname, *, timeout_seconds: fake_socket,
    )

    client = ResilientHttpClient()
    with pytest.raises(PinnedTlsError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    assert "simulated TLS read failure" not in str(excinfo.value)
    assert fake_socket.closed is True


# --- ChatGPT review round 2, finding 4: aggregate header cap enforced ------
# --- while headers are being streamed, not only after the fact ------------


def test_get_pinned_candidate_accepts_headers_just_under_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Few, large header values rather than many small ones -- http.client
    # itself refuses more than 100 headers per response regardless of
    # this transport's own byte cap, so the line count here must stay
    # well under that unrelated built-in limit.
    filler_value = "x" * 900
    header_lines = []
    total = 0
    i = 0
    prefix = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n"
    total += len(prefix)
    while total < http_client._MAX_PINNED_HEADER_BYTES - 2000:
        line = f"X-Filler-{i}: {filler_value}\r\n".encode()
        header_lines.append(line)
        total += len(line)
        i += 1
    response = prefix + b"".join(header_lines) + b"\r\nBODY"
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    assert http_response.status == 200
    assert http_response.body == b"BODY"


def test_get_pinned_candidate_rejects_headers_over_the_cap_before_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary_body = b"CANARY_BODY_MUST_NEVER_BE_READ"
    filler_value = "x" * 1000
    header_lines = []
    total = 0
    i = 0
    prefix = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n"
    total += len(prefix)
    while total <= http_client._MAX_PINNED_HEADER_BYTES:
        line = f"X-Filler-{i}: {filler_value}\r\n".encode()
        header_lines.append(line)
        total += len(line)
        i += 1
    response = prefix + b"".join(header_lines) + b"\r\n" + canary_body
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    with pytest.raises(ResponseTooLargeError) as excinfo:
        client.get_pinned_candidate(
            hostname="www.tmd.go.th",
            port=443,
            path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
            selected_ip="8.8.8.10",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
        )
    # The oversized header block is rejected before the body is ever read.
    assert canary_body not in str(excinfo.value).encode()


def test_bounded_header_file_stops_counting_once_headers_are_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test of _BoundedHeaderFile in isolation: a body far larger
    than the header cap must still be readable once the blank line
    terminating the header block has been seen -- the cap applies only
    to the header-parsing phase, never to the body."""
    body = b"x" * (http_client._MAX_PINNED_HEADER_BYTES * 2)
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\n" + body
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=len(body) + 1,
    )
    assert http_response.body == body


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


def test_get_pinned_candidate_ignores_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """This transport never touches ``urllib.request`` -- the only thing in
    this module that consults ``HTTP_PROXY``/``HTTPS_PROXY`` -- so
    deliberately-broken proxy env vars must have zero effect on the pinned
    candidate fetch."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:9")
    response = b"HTTP/1.1 200 OK\r\nContent-Type: application/cap+xml\r\n\r\nBODY"
    _install_fake_pinned_socket(monkeypatch, response)

    client = ResilientHttpClient()
    http_response, _connected_ip = client.get_pinned_candidate(
        hostname="www.tmd.go.th",
        port=443,
        path="/uploads/CAP/en/CAPTMD20260723155032_2.xml",
        selected_ip="8.8.8.10",
        timeout_seconds=5,
        max_response_bytes=1_000_000,
    )
    assert http_response.status == 200
