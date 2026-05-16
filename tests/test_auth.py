import base64

import pytest
from fastapi.testclient import TestClient

from brain.api import create_app
from brain.auth import (
    COOKIE_NAME,
    SessionStore,
    hash_password,
    verify_password,
    _check_basic_header,
)


# ---------- unit tests for the primitives ----------

def test_hash_password_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("$2b$")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False
    assert verify_password("", h) is False


def test_verify_password_rejects_empty_hash():
    assert verify_password("anything", "") is False


def test_verify_password_handles_long_password():
    # bcrypt truncates at 72 bytes — make sure we don't crash on long input.
    h = hash_password("a" * 200)
    assert verify_password("a" * 200, h) is True


def test_check_basic_header_happy_path():
    h = hash_password("pw")
    creds = base64.b64encode(b"user:pw").decode()
    assert _check_basic_header(f"Basic {creds}", "user", h) is True


def test_check_basic_header_rejects_bad_username():
    h = hash_password("pw")
    creds = base64.b64encode(b"other:pw").decode()
    assert _check_basic_header(f"Basic {creds}", "user", h) is False


def test_check_basic_header_rejects_bad_password():
    h = hash_password("pw")
    creds = base64.b64encode(b"user:wrong").decode()
    assert _check_basic_header(f"Basic {creds}", "user", h) is False


def test_check_basic_header_rejects_malformed():
    h = hash_password("pw")
    assert _check_basic_header("", "user", h) is False
    assert _check_basic_header("Bearer x", "user", h) is False
    assert _check_basic_header("Basic not-base64!!", "user", h) is False
    assert _check_basic_header("Basic " + base64.b64encode(b"nocolon").decode(), "user", h) is False


def test_session_store_create_and_validate():
    s = SessionStore()
    token = s.create()
    assert s.is_valid(token) is True
    assert s.is_valid(None) is False
    assert s.is_valid("garbage") is False


def test_session_store_expiry():
    s = SessionStore()
    token = s.create()
    s.force_expire(token)
    assert s.is_valid(token) is False


# ---------- middleware integration ----------

@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "alice")
    monkeypatch.setenv("APP_PASSWORD_HASH", hash_password("secret"))
    app = create_app(db_path=str(tmp_path / "brain.json"))
    with TestClient(app) as c:
        yield c


def test_request_without_credentials_returns_401(auth_client):
    r = auth_client.get("/api/graph")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


def test_request_with_wrong_password_returns_401(auth_client):
    r = auth_client.get("/api/graph", auth=("alice", "nope"))
    assert r.status_code == 401


def test_request_with_wrong_username_returns_401(auth_client):
    r = auth_client.get("/api/graph", auth=("eve", "secret"))
    assert r.status_code == 401


def test_correct_basic_auth_returns_200_and_sets_cookie(auth_client):
    r = auth_client.get("/api/graph", auth=("alice", "secret"))
    assert r.status_code == 200
    assert COOKIE_NAME in r.cookies
    # httponly, samesite=strict expected in the header
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    # Plain HTTP test → no Secure flag
    assert "secure" not in set_cookie


def test_cookie_admits_subsequent_requests_without_basic(auth_client):
    r1 = auth_client.get("/api/graph", auth=("alice", "secret"))
    assert r1.status_code == 200
    # TestClient persists cookies on the session; clear basic auth
    r2 = auth_client.get("/api/graph")
    assert r2.status_code == 200


def test_static_index_is_also_protected(auth_client):
    r = auth_client.get("/")
    assert r.status_code == 401
    r2 = auth_client.get("/", auth=("alice", "secret"))
    assert r2.status_code == 200


def test_expired_session_cookie_returns_401(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "alice")
    monkeypatch.setenv("APP_PASSWORD_HASH", hash_password("secret"))
    app = create_app(db_path=str(tmp_path / "brain.json"))
    with TestClient(app) as c:
        # Mint a session
        r = c.get("/api/graph", auth=("alice", "secret"))
        token = r.cookies.get(COOKIE_NAME)
        assert token

        # Expire it server-side
        # (state is stored on the app via the same SessionStore the middleware uses)
        sessions = None
        for mw in app.user_middleware:
            if mw.cls.__name__ == "BasicAuthMiddleware":
                sessions = mw.kwargs["sessions"]
                break
        assert sessions is not None
        sessions.force_expire(token)

        r2 = c.get("/api/graph")  # cookie still present in jar
        assert r2.status_code == 401


def test_websocket_without_cookie_is_rejected(auth_client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with auth_client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_websocket_with_cookie_connects(auth_client):
    auth_client.get("/api/graph", auth=("alice", "secret"))  # mint cookie
    with auth_client.websocket_connect("/ws") as ws:
        # Trigger a broadcast by creating a node, then read the event.
        r = auth_client.post(
            "/api/nodes",
            json={"type": "task", "title": "ws-test", "status": "active"},
        )
        assert r.status_code == 200
        msg = ws.receive_json()
        assert msg == {"type": "graph_changed"}


def test_auth_disabled_when_env_unset(tmp_path):
    app = create_app(db_path=str(tmp_path / "brain.json"))
    with TestClient(app) as c:
        # No credentials anywhere — request still succeeds because middleware
        # was never installed.
        r = c.get("/api/graph")
        assert r.status_code == 200


def test_auth_disabled_when_only_username_set(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "alice")
    # APP_PASSWORD_HASH intentionally missing
    app = create_app(db_path=str(tmp_path / "brain.json"))
    with TestClient(app) as c:
        r = c.get("/api/graph")
        assert r.status_code == 200


def test_allowed_hosts_rejects_bad_host(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "brain.example.com")
    app = create_app(db_path=str(tmp_path / "brain.json"))
    with TestClient(app, base_url="http://evil.example.com") as c:
        r = c.get("/api/graph")
        assert r.status_code == 400  # TrustedHostMiddleware → 400 "Invalid host header"


def test_storage_path_env_used(tmp_path, monkeypatch):
    custom = tmp_path / "custom_brain.json"
    monkeypatch.setenv("STORAGE_PATH", str(custom))
    app = create_app()
    with TestClient(app) as c:
        c.post("/api/nodes", json={"type": "task", "title": "persisted"})
    assert custom.exists()
    assert "persisted" in custom.read_text()
