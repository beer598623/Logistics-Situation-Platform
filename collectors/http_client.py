"""Small standard-library HTTP client with bounded retries and provenance.

No credentials are supported in v0.1.2. Live adapters remain disabled until
source terms, endpoint behavior, and fixtures have been reviewed.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import random
import socket
import ssl
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


#: WO-006 Scope B: a candidate-only pinned-DNS transport, kept fully
#: separate from ``get()`` and ``get_no_redirect()`` above -- neither of
#: those methods exposes a DNS-resolution step at all (both delegate host
#: resolution entirely to urllib/urlopen internals), so this is new,
#: additional restriction, never a relaxation of either existing path.
class DnsResolutionError(RuntimeError):
    """Raised when DNS resolution for a pinned candidate hostname fails
    outright, or succeeds but returns no usable address at all."""


class NonGlobalAddressError(RuntimeError):
    """Raised when DNS resolution for a pinned candidate hostname returns
    at least one address that is not globally routable (private,
    loopback, link-local, multicast, reserved, unspecified, or otherwise
    non-global per :mod:`ipaddress`). The entire resolution is rejected --
    fail closed -- even if other addresses in the same answer are global;
    a partially non-global answer is itself treated as untrustworthy."""


class PinnedRedirectError(RuntimeError):
    """Raised when a DNS-pinned candidate fetch receives an HTTP 3xx
    response. This transport never constructs or sends a second request
    to a ``Location`` target -- the single physical request has already
    completed by the time this is raised, mirroring (but kept separate
    from) ``DiscoveryRedirectError`` above."""


class PinnedTlsError(RuntimeError):
    """Raised when the TLS handshake or hostname verification fails while
    connecting to a DNS-pinned candidate address. The message never
    includes certificate contents, only the sanitized exception class."""


class PinnedConnectionError(RuntimeError):
    """Raised when the direct socket connection to a DNS-pinned, already
    address-validated candidate IP fails for a reason other than TLS, or
    when the HTTP exchange over that connection fails at the protocol
    level."""


def _is_globally_routable(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Explicit, fail-closed address check for WO-006 Scope B step 2.

    Private, loopback, link-local, multicast, reserved, and unspecified
    addresses are all rejected by name, matching the issue's own
    enumeration; ``is_global`` is checked in addition (not instead) to
    catch any other special-purpose, non-global range not covered by the
    explicit checks above.
    """
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return bool(ip.is_global)


@dataclass(slots=True, frozen=True)
class PinnedResolution:
    selected_ip: str
    address_family: str  # "IPv4" or "IPv6"


def resolve_pinned_address(hostname: str, port: int) -> PinnedResolution:
    """Resolve ``hostname`` and deterministically select exactly one
    globally routable address (WO-006 Scope B steps 1-3).

    Fails closed -- raises rather than silently filtering -- if
    resolution is empty, or if *any* returned address is not globally
    routable, even when other addresses in the same answer are global.
    Selection among the addresses that survive is deterministic: sorted
    IPv4 first; IPv6 is only considered if no IPv4 address was returned.
    """
    try:
        addrinfo = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DnsResolutionError(f"DNS resolution failed for {hostname}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _socktype, _proto, _canonname, sockaddr in addrinfo:
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue

    if not addresses:
        raise DnsResolutionError(f"DNS resolution for {hostname} returned no usable address")

    if any(not _is_globally_routable(ip) for ip in addresses):
        raise NonGlobalAddressError(
            f"DNS resolution for {hostname} returned a non-globally-routable address; "
            "the entire resolution is rejected"
        )

    ipv4_addresses = sorted((ip for ip in addresses if ip.version == 4), key=int)
    if ipv4_addresses:
        return PinnedResolution(selected_ip=str(ipv4_addresses[0]), address_family="IPv4")

    ipv6_addresses = sorted((ip for ip in addresses if ip.version == 6), key=int)
    return PinnedResolution(selected_ip=str(ipv6_addresses[0]), address_family="IPv6")


#: Response headers are bounded independently of the response body cap --
#: a candidate response's headers are read into memory before the body
#: streaming/size check below even begins.
_MAX_PINNED_HEADER_BYTES = 65536


def _open_pinned_socket(
    selected_ip: str, port: int, verify_hostname: str, *, timeout_seconds: float
) -> ssl.SSLSocket:
    """Open a raw TCP connection to ``selected_ip`` -- never re-resolving
    ``verify_hostname`` -- and TLS-wrap it with SNI and certificate
    verification pinned to ``verify_hostname``. Factored out so tests can
    substitute an in-memory socket pair without opening a real connection
    or performing a real TLS handshake."""
    raw_sock = socket.create_connection((selected_ip, port), timeout=timeout_seconds)
    context = ssl.create_default_context()
    return context.wrap_socket(raw_sock, server_hostname=verify_hostname)


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
        """Candidate-only pinned transport (WO-006 Scope B).

        Makes exactly one physical HTTPS GET to ``selected_ip`` -- never
        performing a second DNS lookup of ``hostname`` -- while preserving
        TLS certificate verification and SNI for ``hostname`` and sending
        ``Host: hostname``. No retry loop, no redirect follow (a 3xx
        response raises ``PinnedRedirectError`` before any second request
        could be constructed), no environment proxy (this never goes
        through ``urllib``, which is the only thing in this module that
        consults ``HTTP_PROXY``/``HTTPS_PROXY``), no cookies, no
        authentication, no request body. Returns the response together
        with the IP address the socket actually connected to, so a caller
        can confirm it equals ``selected_ip``.

        Kept entirely separate from ``get()`` and ``get_no_redirect()``
        above: this method shares no connection-building code with either,
        so GDACS, direct-CAP, and RSS-discovery transport behavior is
        unaffected by this addition.
        """
        try:
            sock = _open_pinned_socket(selected_ip, port, hostname, timeout_seconds=timeout_seconds)
        except ssl.SSLError as exc:
            raise PinnedTlsError(
                f"TLS handshake or hostname verification failed for {hostname}"
            ) from exc
        except OSError as exc:
            raise PinnedConnectionError("connection to pinned candidate address failed") from exc

        connected_ip = sock.getpeername()[0]
        conn = http.client.HTTPConnection(selected_ip, port, timeout=timeout_seconds)
        conn.sock = sock
        try:
            request_headers = {
                "Host": hostname,
                "User-Agent": self.user_agent,
                "Accept": "*/*",
                "Connection": "close",
            }
            conn.request("GET", path, headers=request_headers)
            response = conn.getresponse()

            header_bytes = sum(len(name) + len(value) for name, value in response.getheaders())
            if header_bytes > _MAX_PINNED_HEADER_BYTES:
                raise ResponseTooLargeError(
                    f"Response headers from {hostname} exceeded {_MAX_PINNED_HEADER_BYTES} bytes"
                )

            # 304 is technically in the 3xx range but is not a redirect --
            # it carries no Location to follow and is a conditional-request
            # response, not a "go elsewhere" instruction. It is passed
            # through unmodified here, exactly like get()/get_no_redirect()
            # above; treating an *uncacheable* 304 as a structured failure
            # (no validator was ever sent) is the candidate-validation
            # adapter's responsibility, not this transport's.
            if response.status != 304 and 300 <= response.status < 400:
                raise PinnedRedirectError(
                    f"refused HTTP {response.status} redirect for pinned candidate fetch; "
                    "this transport never requests a Location target"
                )

            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise ResponseTooLargeError(
                    f"Response from {hostname} exceeded {max_response_bytes} bytes"
                )
            normalized_headers = {key.lower(): value for key, value in response.getheaders()}
            http_response = HttpResponse(
                url=f"https://{hostname}{path}",
                status=response.status,
                headers=normalized_headers,
                body=body,
                content_sha256=self.sha256(body),
            )
            return http_response, connected_ip
        except http.client.HTTPException as exc:
            raise PinnedConnectionError(
                f"HTTP protocol error fetching pinned candidate from {hostname}"
            ) from exc
        finally:
            conn.close()
