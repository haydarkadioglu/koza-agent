"""Tests for SSRF protection in the web skill without network access."""
import io
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from email.message import Message

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import web


def _addrinfo(ip: str, family: int | None = None):
    family = family or (socket.AF_INET6 if ":" in ip else socket.AF_INET)
    sockaddr = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 80)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


@pytest.fixture(autouse=True)
def fake_getaddrinfo(monkeypatch):
    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ip = web.ipaddress.ip_address(host)
        except ValueError:
            return [_addrinfo("93.184.216.34")]
        return [_addrinfo(str(ip), ip.version == 6 and socket.AF_INET6 or socket.AF_INET)]

    monkeypatch.setattr(web.socket, "getaddrinfo", getaddrinfo)


def test_is_safe_url_accepts_public_host():
    assert web.is_safe_url("https://example.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[fd00::1]/",
    ],
)
def test_is_safe_url_rejects_local_and_private_targets(url):
    assert not web.is_safe_url(url)


def test_is_safe_url_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            _addrinfo("93.184.216.34"),
            _addrinfo("127.0.0.1"),
        ],
    )
    assert not web.is_safe_url("https://example.com/")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com", "http:///path"])
def test_is_safe_url_rejects_non_http_or_hostless_urls(url):
    assert not web.is_safe_url(url)


def test_is_safe_url_rejects_dns_failure(monkeypatch):
    def fail_lookup(*args, **kwargs):
        raise socket.gaierror("lookup failed")

    monkeypatch.setattr(web.socket, "getaddrinfo", fail_lookup)
    assert not web.is_safe_url("https://example.com/")


@pytest.mark.parametrize(
    "ip",
    ["::ffff:127.0.0.1", "::ffff:169.254.169.254", "::1", "224.0.0.1"],
)
def test_is_blocked_ip_rejects_non_public_addresses(ip):
    assert web._is_blocked_ip(ip)


def test_is_blocked_ip_accepts_public_address():
    assert not web._is_blocked_ip("93.184.216.34")


def test_is_blocked_ip_rejects_wrong_types():
    assert web._is_blocked_ip(None)


def test_redirect_handler_rejects_blocked_location():
    handler = web._SafeRedirectHandler()
    request = urllib.request.Request("https://example.com/start")
    with pytest.raises(urllib.error.HTTPError, match="SSRF violation"):
        handler.redirect_request(
            request, io.BytesIO(), 302, "Found", {}, "http://169.254.169.254/"
        )


def test_redirect_handler_accepts_public_location():
    handler = web._SafeRedirectHandler()
    request = urllib.request.Request("https://example.com/start")
    redirected = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", {}, "https://example.org/next"
    )
    assert redirected.full_url == "https://example.org/next"


def test_pinned_connection_rechecks_address_before_opening_socket(monkeypatch):
    # The connect-time resolver, not the earlier URL check, must refuse a rebinding answer.
    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [_addrinfo("127.0.0.1")],
    )

    def unexpected_socket(*args, **kwargs):
        pytest.fail("blocked address must not open a socket")

    monkeypatch.setattr(web.socket, "create_connection", unexpected_socket)
    connection = web._PinnedHTTPConnection("rebind.example", 80)
    with pytest.raises(web.BlockedTargetError, match="SSRF violation"):
        connection.connect()


def test_pinned_connection_dials_the_validated_address(monkeypatch):
    dialed = []

    def fake_create_connection(address, timeout=None, source_address=None):
        dialed.append(address)
        return object()

    monkeypatch.setattr(
        web.socket, "getaddrinfo", lambda *args, **kwargs: [_addrinfo("93.184.216.34")]
    )
    monkeypatch.setattr(web.socket, "create_connection", fake_create_connection)
    connection = web._PinnedHTTPConnection("example.com", 80)

    assert connection._create_pinned_socket() is not None
    assert dialed == [("93.184.216.34", 80)]


def test_pinned_https_handler_forwards_context():
    """Python 3.14 dropped HTTPSHandler._check_hostname; https_open must not read it."""
    handler = web._PinnedHTTPSHandler(context=ssl.create_default_context())
    recorded = {}
    sentinel = object()

    def fake_do_open(http_class, req, **kwargs):
        recorded["class"] = http_class
        recorded["kwargs"] = kwargs
        return sentinel

    handler.do_open = fake_do_open
    assert handler.https_open(urllib.request.Request("https://example.com/")) is sentinel
    assert recorded["class"] is web._PinnedHTTPSConnection
    assert isinstance(recorded["kwargs"]["context"], ssl.SSLContext)


def test_local_proxy_host_is_dialed_without_pinning(monkeypatch):
    """A configured local proxy is the trusted egress, not the SSRF target."""
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    dialed = []

    class _FakeSocket:
        def setsockopt(self, *args):
            pass

    def fake_create_connection(address, timeout=None, source_address=None, **kwargs):
        dialed.append(address)
        return _FakeSocket()

    monkeypatch.setattr(web.socket, "create_connection", fake_create_connection)
    connection = web._PinnedHTTPConnection("127.0.0.1", 7890)
    connection.connect()

    assert dialed == [("127.0.0.1", 7890)]


def test_fetch_url_returns_existing_blocked_url_error():
    assert (
        web.fetch_url("http://169.254.169.254/")
        == "ERROR: URL is blocked by security policy (SSRF Guard)."
    )


def test_safe_opener_preserves_user_agent_and_response_interface(monkeypatch):
    request_headers = {}

    class FakeResponse:
        status = 200
        code = 200
        reason = "OK"

        def __init__(self):
            self.headers = Message()
            self.headers["Content-Type"] = "text/plain"
            self.msg = self.headers

        def read(self):
            return b"response body"

        def info(self):
            return self.headers

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()

    class FakeConnection:
        sock = None

        def __init__(self, host, timeout=None):
            pass

        def set_debuglevel(self, level):
            pass

        def request(self, method, url, body=None, headers=None, **kwargs):
            request_headers.update(headers or {})

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(web, "_PinnedHTTPConnection", FakeConnection)
    request = urllib.request.Request(
        "http://example.com/",
        headers={"User-Agent": "KozaAgentTest/1.0"},
    )
    with web._SAFE_OPENER.open(request, timeout=15) as response:
        assert response.headers["Content-Type"] == "text/plain"
        assert response.read() == b"response body"

    assert request_headers["User-Agent"] == "KozaAgentTest/1.0"
