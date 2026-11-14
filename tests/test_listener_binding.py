import http.server
import io
import json
import urllib.error
import urllib.request

import pytest

from skills import devops
from skills.sync import server

# ── Sync server ───────────────────────────────────────────────────────────────

def _get_status(port: int, token: str | None) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/sync/status")
    if token is not None:
        req.add_header("X-Koza-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_sync_server_refuses_to_start_without_token(tmp_path):
    assert server.start_sync_server(str(tmp_path / "k.db"), "") is False
    assert server.start_sync_server(str(tmp_path / "k.db"), "   ") is False
    assert server.is_running() is False
    assert server.get_bind_host() == ""


def test_sync_server_binds_loopback_and_enforces_token(tmp_path):
    assert server.start_sync_server(str(tmp_path / "k.db"), "s3cret", port=0) is True
    try:
        host, port = server._server_instance.server_address[:2]
        assert host == "127.0.0.1"
        assert server.get_bind_host() == "127.0.0.1"

        code, body = _get_status(port, None)
        assert code == 401
        assert body == {"error": "unauthorized"}

        code, _ = _get_status(port, "wrong")
        assert code == 401

        code, body = _get_status(port, "s3cret")
        assert code == 200
        assert body["status"] == "ok"
        assert body["bind_host"] == "127.0.0.1"
    finally:
        server.stop_sync_server()
    assert server.is_running() is False


class _FakeRequest:
    def __init__(self, headers: dict):
        self.headers = headers


def test_sync_auth_fails_closed_and_compares_exactly(monkeypatch):
    monkeypatch.setattr(server, "_token", "")
    assert server._SyncHandler._auth(_FakeRequest({})) is False
    assert server._SyncHandler._auth(_FakeRequest({"X-Koza-Token": ""})) is False

    monkeypatch.setattr(server, "_token", "s3cret")
    assert server._SyncHandler._auth(_FakeRequest({"X-Koza-Token": "s3cret"})) is True
    assert server._SyncHandler._auth(_FakeRequest({"X-Koza-Token": "nope"})) is False
    assert server._SyncHandler._auth(_FakeRequest({"X-Koza-Token": "s3cret-but-longer"})) is False
    assert server._SyncHandler._auth(_FakeRequest({})) is False


# ── Webhook listener ──────────────────────────────────────────────────────────

class _FakeServer:
    """Stands in for HTTPServer: records the bind address and runs a callback
    in place of handle_request() so nothing listens or blocks."""

    def __init__(self, address, handler_cls, on_request=None):
        self.address = address
        self.handler_cls = handler_cls
        self.on_request = on_request
        self.timeout = None
        self.closed = False

    def handle_request(self):
        if self.on_request:
            self.on_request(self.handler_cls)

    def server_close(self):
        self.closed = True


def _install_fake_server(monkeypatch, on_request=None) -> list:
    created: list[_FakeServer] = []

    def factory(address, handler_cls):
        srv = _FakeServer(address, handler_cls, on_request)
        created.append(srv)
        return srv

    monkeypatch.setattr(http.server, "HTTPServer", factory)
    return created


def _drive(handler_cls, method: str, headers: dict, body: bytes = b"") -> dict:
    """Run one handler method on a real Handler instance with recorded I/O."""
    h = handler_cls.__new__(handler_cls)
    h.headers = headers
    h.path = "/hook"
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    sent: dict = {"codes": []}
    h.send_response = lambda code, message=None: sent["codes"].append(code)
    h.send_error = lambda code, message=None, explain=None: sent["codes"].append(code)
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda: None
    getattr(h, f"do_{method}")()
    sent["body"] = h.wfile.getvalue()
    return sent


def test_webhook_refuses_non_loopback_without_token(monkeypatch):
    def boom(*args, **kwargs):
        pytest.fail("HTTPServer must not be constructed")

    monkeypatch.setattr(http.server, "HTTPServer", boom)
    result = devops.webhook_listen(host="0.0.0.0")
    assert result.startswith("ERROR:")
    assert "0.0.0.0" in result


def test_webhook_binds_loopback_by_default(monkeypatch):
    created = _install_fake_server(monkeypatch)
    result = devops.webhook_listen(timeout=1)
    assert len(created) == 1
    assert created[0].address == ("127.0.0.1", 9988)
    assert created[0].closed is True
    assert result == "No webhook received within timeout."


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_webhook_rejects_missing_or_wrong_token(monkeypatch, method):
    seen: list[dict] = []

    def on_request(handler_cls):
        seen.append(_drive(handler_cls, method, {}, b"{}"))
        seen.append(_drive(handler_cls, method, {"X-Koza-Token": "wrong", "Content-Length": "2"}, b"{}"))

    _install_fake_server(monkeypatch, on_request)
    result = devops.webhook_listen(token="s3cret", timeout=1)

    assert [s["codes"] for s in seen] == [[401], [401]]
    assert all(s["body"] == b"unauthorized" for s in seen)
    assert result == "No webhook received within timeout."


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_webhook_accepts_correct_token(monkeypatch, method):
    seen: list[dict] = []

    def on_request(handler_cls):
        seen.append(_drive(handler_cls, method,
                           {"X-Koza-Token": "s3cret", "Content-Length": "11"}, b'{"ok": true}'))

    _install_fake_server(monkeypatch, on_request)
    result = devops.webhook_listen(token="s3cret", timeout=1)

    assert seen[0]["codes"] == [200]
    assert result.startswith("Webhook received:")
    assert f'"method": "{method}"' in result


def test_webhook_rejects_oversized_body(monkeypatch):
    seen: list[dict] = []

    def on_request(handler_cls):
        seen.append(_drive(handler_cls, "POST", {"Content-Length": str(1_000_001)}, b"x"))

    _install_fake_server(monkeypatch, on_request)
    result = devops.webhook_listen(timeout=1)

    assert seen[0]["codes"] == [413]
    assert result == "No webhook received within timeout."


def test_webhook_rejects_malformed_content_length(monkeypatch):
    seen: list[dict] = []

    def on_request(handler_cls):
        seen.append(_drive(handler_cls, "POST", {"Content-Length": "not-a-number"}, b"x"))

    _install_fake_server(monkeypatch, on_request)
    result = devops.webhook_listen(timeout=1)

    assert seen[0]["codes"] == [400]
    assert result == "No webhook received within timeout."


def test_default_config_binds_sync_to_loopback():
    from config import default_config

    assert default_config()["multi_host"]["sync_bind_host"] == "127.0.0.1"
