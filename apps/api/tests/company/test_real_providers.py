"""Tests for the *real* provider implementations (as opposed to the
fakes used elsewhere) -- `HttpxWebsiteReachabilityProvider`'s SSRF
refusal and IP-pinned request mechanics, and
`RDAPDomainAgeProvider._extract_registration_date`'s RDAP-payload
parsing. Runs a real local HTTP server on loopback for the reachability
mechanics test (redirect handling, HEAD->GET fallback) -- SSRF
protection is proven by the fact that this same loopback address is
*refused* by the unmocked code path, then deliberately bypassed only at
the resolution step to test the request mechanics in isolation.
"""

import datetime as dt
import http.server
import ssl
import threading
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from offerleaks.core.config import get_settings
from offerleaks.models.company import ProviderCheckOutcome
from offerleaks.providers.domain_age import RDAPDomainAgeProvider
from offerleaks.providers.website_reachability import (
    HttpxWebsiteReachabilityProvider,
    _resolve_pinned_address,
)


def _self_signed_ssl_context() -> ssl.SSLContext:
    """A throwaway self-signed cert/key pair, purely so the mechanics
    tests below can run a real local HTTPS server without a publicly-
    trusted certificate -- the provider under test still performs real
    certificate validation in production (`verify=True` by default);
    these tests explicitly opt out of that via `verify=False`, which
    exists on the provider purely as a testability seam."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "pinned-test.invalid")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5))
        .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("pinned-test.invalid")]), False)
        .sign(key, hashes.SHA256())
    )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=_write_pem(cert.public_bytes(serialization.Encoding.PEM)),
        keyfile=_write_pem(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        ),
    )
    return context


def _write_pem(data: bytes) -> str:
    import tempfile

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    handle.write(data)
    handle.flush()
    return handle.name


class _OKHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 - quiet test output
        pass


class _RedirectThenOKHandler(http.server.BaseHTTPRequestHandler):
    hit_paths: list[str] = []

    def do_HEAD(self):
        _RedirectThenOKHandler.hit_paths.append(self.path)
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/landed")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class _HeadUnsupportedHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(405)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _serve(handler_cls) -> http.server.HTTPServer:
    # Bound explicitly to the HTTPS default port: `_build_pinned_request`
    # deliberately only allows the default 80/443 ports (part of the
    # SSRF surface reduction), so a real end-to-end test of `check()`
    # has to run its throwaway server there too, not on an arbitrary
    # port. Running as root in this sandbox makes binding low ports
    # possible; `allow_reuse_address` (on by default for
    # `http.server.HTTPServer`) lets successive tests rebind quickly.
    server = http.server.HTTPServer(("127.0.0.1", 443), handler_cls)
    server.socket = _self_signed_ssl_context().wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# --- SSRF refusal (real, unmocked resolution path) ---


def test_resolve_pinned_address_refuses_loopback():
    assert _resolve_pinned_address("localhost") is None
    assert _resolve_pinned_address("127.0.0.1") is None


def test_resolve_pinned_address_refuses_unresolvable_host():
    assert _resolve_pinned_address("this-domain-does-not-exist-offerleaks-test.invalid") is None


async def test_check_refuses_a_domain_that_resolves_to_loopback():
    provider = HttpxWebsiteReachabilityProvider(get_settings())
    result = await provider.check(domain="localhost")
    assert result.reachable is None
    assert result.outcome == ProviderCheckOutcome.MALFORMED_RESPONSE


# --- Request mechanics, against a real local server (SSRF check bypassed
#     only at the resolution step, via monkeypatch, purely to isolate
#     "does the pinned request/redirect/fallback logic work") ---


async def test_check_reports_reachable_for_a_real_responding_server(monkeypatch):
    server = _serve(_OKHandler)
    try:
        monkeypatch.setattr(
            "offerleaks.providers.website_reachability._resolve_pinned_address",
            lambda host: "127.0.0.1",
        )
        provider = HttpxWebsiteReachabilityProvider(get_settings(), verify=False)
        result = await provider.check(domain="pinned-test.invalid")
    finally:
        server.shutdown()
        server.server_close()

    assert result.reachable is True
    assert result.outcome == ProviderCheckOutcome.OK


async def test_check_follows_a_redirect_and_reports_the_final_hop(monkeypatch):
    _RedirectThenOKHandler.hit_paths = []
    server = _serve(_RedirectThenOKHandler)
    try:
        monkeypatch.setattr(
            "offerleaks.providers.website_reachability._resolve_pinned_address",
            lambda host: "127.0.0.1",
        )
        provider = HttpxWebsiteReachabilityProvider(get_settings(), verify=False)
        result = await provider.check(domain="pinned-test.invalid")
    finally:
        server.shutdown()
        server.server_close()

    assert result.reachable is True
    assert result.outcome == ProviderCheckOutcome.OK
    assert _RedirectThenOKHandler.hit_paths == ["/", "/landed"]


async def test_check_falls_back_to_get_when_head_is_unsupported(monkeypatch):
    server = _serve(_HeadUnsupportedHandler)
    try:
        monkeypatch.setattr(
            "offerleaks.providers.website_reachability._resolve_pinned_address",
            lambda host: "127.0.0.1",
        )
        provider = HttpxWebsiteReachabilityProvider(get_settings(), verify=False)
        result = await provider.check(domain="pinned-test.invalid")
    finally:
        server.shutdown()
        server.server_close()

    assert result.reachable is True
    assert result.outcome == ProviderCheckOutcome.OK


# --- RDAP payload parsing (unit-level, no live network) ---


def test_rdap_extracts_registration_date_from_events():
    payload = {
        "events": [
            {"eventAction": "last changed", "eventDate": "2024-01-01T00:00:00Z"},
            {"eventAction": "registration", "eventDate": "2010-05-06T12:00:00Z"},
        ]
    }
    extracted = RDAPDomainAgeProvider._extract_registration_date(payload)
    assert extracted == datetime(2010, 5, 6, 12, 0, 0, tzinfo=UTC)


def test_rdap_returns_none_when_no_registration_event_present():
    payload = {"events": [{"eventAction": "last changed", "eventDate": "2024-01-01T00:00:00Z"}]}
    assert RDAPDomainAgeProvider._extract_registration_date(payload) is None


def test_rdap_returns_none_for_malformed_payload():
    assert RDAPDomainAgeProvider._extract_registration_date({"nonsense": True}) is None
    assert RDAPDomainAgeProvider._extract_registration_date(None) is None
    assert RDAPDomainAgeProvider._extract_registration_date("not a dict") is None
