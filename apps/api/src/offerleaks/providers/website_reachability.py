"""Website-reachability signal behind a `WebsiteReachabilityProvider`
interface (M7: Company Signal & Reputation) -- same provider-abstraction
pattern as the other M7/M6 external calls, even though this one talks to
an arbitrary company website rather than a fixed vendor API.

That "arbitrary URL, server-initiated request" shape is exactly an SSRF
risk (M7 §15 calls this out explicitly), so this module's job is as much
about *refusing* to make certain requests as it is about making them:
only `http`/`https` on their default ports are ever allowed, a literal
IP host is refused outright (domains only), and every resolved address
is checked against private/loopback/link-local/reserved ranges.

**IP pinning, not just pre-connect validation.** A hostname is resolved
and validated once, and the connection is made directly to that specific
validated address (with the original hostname preserved via the `Host`
header and TLS SNI) -- never re-resolved by the HTTP client itself.
Validating a hostname and then handing that same hostname to the client
to resolve *again* at connect time leaves a DNS-rebinding window (a
malicious domain with a very short TTL could return a public IP to the
validation step and a private one moments later to the actual
connection); pinning the literal validated address closes that gap.
Redirects are not auto-followed -- each hop is independently resolved,
validated, and pinned the same way.
"""

import ipaddress
import socket
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from offerleaks.core.config import Settings
from offerleaks.models.company import ProviderCheckOutcome
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError

_MAX_REDIRECTS = 3


class WebsiteReachabilityPermanentError(PermanentProviderError):
    pass


class WebsiteReachabilityTransientError(TransientProviderError):
    pass


class WebsiteReachabilityBlockedError(PermanentProviderError):
    """The target resolved to a non-public address (or an unsupported
    scheme/port) -- refused outright, never attempted. Treated by the
    caller as "insufficient evidence," not as a transient failure to
    retry."""


class WebsiteReachabilityResult:
    __slots__ = ("reachable", "outcome")

    def __init__(self, *, reachable: bool | None, outcome: ProviderCheckOutcome) -> None:
        self.reachable = reachable
        self.outcome = outcome


class WebsiteReachabilityProvider(Protocol):
    async def check(self, *, domain: str) -> WebsiteReachabilityResult: ...


def _resolve_pinned_address(host: str) -> str | None:
    """Resolves `host` and returns a single public, routable address to
    pin the actual connection to -- or `None` if resolution fails, or if
    *any* resolved address is private/loopback/link-local/multicast/
    reserved/unspecified (a mixed result fails the whole host closed;
    one safe-looking answer among several unsafe ones is not safe).
    Deliberately returns exactly the address that gets connected to,
    rather than a boolean, so validation and connection can never
    diverge -- see this module's docstring.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None

    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        return None

    public_addresses: list[str] = []
    for raw_address in addresses:
        try:
            addr = ipaddress.ip_address(raw_address)
        except ValueError:
            return None
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return None
        public_addresses.append(raw_address)

    return public_addresses[0] if public_addresses else None


class _PinnedRequest:
    """A validated, safe-to-send request: the literal address to connect
    to, plus the original hostname preserved for `Host`/SNI."""

    __slots__ = ("url", "hostname")

    def __init__(self, *, url: str, hostname: str) -> None:
        self.url = url
        self.hostname = hostname


def _build_pinned_request(url: str) -> "_PinnedRequest | None":
    """Returns a `_PinnedRequest` built against a validated, pinned
    address if `url` is safe to request, else `None`. Only bare
    `http`/`https` on their default ports, with a hostname (never a
    literal IP -- that's exactly how a naive SSRF filter gets bypassed)
    that resolves to a single, public, routable address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.hostname:
        return None
    if parts.port is not None and parts.port not in (80, 443):
        return None
    try:
        ipaddress.ip_address(parts.hostname)
        return None  # literal IP host -- refused, domains only
    except ValueError:
        pass

    pinned_address = _resolve_pinned_address(parts.hostname)
    if pinned_address is None:
        return None

    netloc = f"[{pinned_address}]" if ":" in pinned_address else pinned_address
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    pinned_url = urlunsplit(
        (parts.scheme, netloc, parts.path or "/", parts.query, parts.fragment)
    )
    return _PinnedRequest(url=pinned_url, hostname=parts.hostname)


class HttpxWebsiteReachabilityProvider:
    def __init__(self, settings: Settings, *, verify: bool = True) -> None:
        self._timeout = settings.website_reachability_timeout_seconds
        # `verify` is a testability seam only -- production always uses
        # the default `True` (real certificate validation; a company
        # site presenting an invalid/self-signed certificate is exactly
        # the kind of thing this check should NOT silently wave through
        # as "reachable"). Tests use `verify=False` against a throwaway
        # self-signed local server so the real request/redirect/
        # HEAD-fallback mechanics can be exercised without a real
        # publicly-trusted certificate.
        self._verify = verify

    async def check(self, *, domain: str) -> WebsiteReachabilityResult:
        url = f"https://{domain}"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, verify=self._verify
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    pinned = _build_pinned_request(url)
                    if pinned is None:
                        return WebsiteReachabilityResult(
                            reachable=None, outcome=ProviderCheckOutcome.MALFORMED_RESPONSE
                        )

                    # `Host` covers plain HTTP virtual hosting; `sni_hostname`
                    # covers TLS SNI/certificate validation for HTTPS --
                    # both point at the *original* hostname even though the
                    # connection itself goes to the pinned literal address.
                    pinned_headers = {"Host": pinned.hostname}
                    pinned_extensions = {"sni_hostname": pinned.hostname}
                    try:
                        response = await client.head(
                            pinned.url, headers=pinned_headers, extensions=pinned_extensions
                        )
                        # Some servers don't support HEAD cleanly (405/501) --
                        # fall back to a lightweight GET rather than
                        # reporting an honest server as unreachable.
                        if response.status_code in (405, 501):
                            response = await client.get(
                                pinned.url, headers=pinned_headers, extensions=pinned_extensions
                            )
                    except httpx.TimeoutException:
                        return WebsiteReachabilityResult(
                            reachable=None, outcome=ProviderCheckOutcome.TIMEOUT
                        )
                    except httpx.HTTPError:
                        return WebsiteReachabilityResult(
                            reachable=None, outcome=ProviderCheckOutcome.UNAVAILABLE
                        )

                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            break
                        # Resolve the redirect target against the
                        # *original* hostname, not the pinned-IP URL we
                        # actually sent -- otherwise a relative Location
                        # would resolve against a bare IP with no
                        # meaningful path/host semantics.
                        current_parts = urlsplit(url)
                        original_url = urlunsplit(
                            current_parts._replace(path=current_parts.path or "/")
                        )
                        url = str(httpx.URL(original_url).join(location))
                        continue

                    # Any real HTTP response (including 4xx from the
                    # server itself) means the site is up and answering
                    # -- reachability is about the server responding at
                    # all, not about it returning 200.
                    return WebsiteReachabilityResult(
                        reachable=True, outcome=ProviderCheckOutcome.OK
                    )

                # Exhausted the redirect budget without landing on a
                # final response -- insufficient evidence, not a
                # fabricated negative.
                return WebsiteReachabilityResult(
                    reachable=None, outcome=ProviderCheckOutcome.MALFORMED_RESPONSE
                )
        except Exception:
            # Defensive: any unexpected client-level error (DNS failure
            # mid-request, connection reset, etc.) degrades to
            # "insufficient evidence," never to a false "not reachable."
            return WebsiteReachabilityResult(
                reachable=None, outcome=ProviderCheckOutcome.UNAVAILABLE
            )
