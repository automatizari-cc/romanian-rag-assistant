from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.main import app


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    auth_mod.reset_rate_limiter()


def _mock_signin(monkeypatch, *, status_code: int = 200, body: dict | None = None) -> list[dict]:
    """Replace httpx.AsyncClient.post with a stub; return the captured call list."""
    captured: list[dict] = []
    response_body = body if body is not None else {"token": "test-jwt-abc", "id": 1}

    class StubResponse:
        def __init__(self, sc: int, payload: dict) -> None:
            self.status_code = sc
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class StubAsyncClient:
        def __init__(self, *_a, **_kw) -> None: ...
        async def __aenter__(self) -> StubAsyncClient: return self
        async def __aexit__(self, *_a) -> None: return None
        async def post(self, path: str, *, json: dict, headers: dict) -> StubResponse:
            captured.append({"path": path, "json": json, "headers": headers})
            return StubResponse(status_code, response_body)

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", StubAsyncClient)
    return captured


# ─── Input validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_email", [
    "not-an-email",
    "@missing-local.com",
    "missing-at.com",
    "double@@dot.com",
    "spaces in@local.com",
    "a@b",          # tld too short
    "x" * 250 + "@x.ro",  # over 254 chars
    "ab",           # under 3 chars
    "user@host\x00evil.com",  # NUL byte
])
def test_login_rejects_bad_email(bad_email: str, monkeypatch) -> None:
    _mock_signin(monkeypatch)
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": bad_email, "password": "correctHorse9"})
        assert r.status_code == 422, (bad_email, r.status_code, r.text)


@pytest.mark.parametrize("bad_password", [
    "short",                # < 8
    "a" * 7,                # < 8
    "a" * 257,              # > 256
    "good\x00pass1",        # NUL byte
    "good\x07pass1",        # BEL
    "good\x1bpass1",        # ESC
    "good\x7fpass1",        # DEL
])
def test_login_rejects_bad_password(bad_password: str, monkeypatch) -> None:
    _mock_signin(monkeypatch)
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": bad_password})
        assert r.status_code == 422, (bad_password, r.status_code, r.text)


def test_login_lowercases_and_strips_email(monkeypatch) -> None:
    captured = _mock_signin(monkeypatch)
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "  USer@Example.RO  ", "password": "goodpass1"})
        assert r.status_code == 200
        assert captured[0]["json"]["email"] == "user@example.ro"


# ─── Happy path & cookie ─────────────────────────────────────────────────────


def test_login_success_sets_token_cookie_and_returns_redirect(monkeypatch) -> None:
    _mock_signin(monkeypatch)
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "goodpass1"})
        assert r.status_code == 200
        assert r.json() == {"redirect": "/", "token": "test-jwt-abc"}
        cookie = r.cookies.get("token")
        assert cookie == "test-jwt-abc"
        # Check Set-Cookie attributes
        set_cookie_header = r.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie_header
        assert "Secure" in set_cookie_header
        assert "samesite=strict" in set_cookie_header.lower()


# ─── Upstream errors ─────────────────────────────────────────────────────────


def test_login_upstream_401_returns_invalid_credentials(monkeypatch) -> None:
    _mock_signin(monkeypatch, status_code=401, body={"detail": "Wrong password"})
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "wrongpass1"})
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid credentials"


def test_login_upstream_500_returns_502(monkeypatch) -> None:
    _mock_signin(monkeypatch, status_code=500, body={"detail": "boom"})
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "goodpass1"})
        assert r.status_code == 502


def test_login_upstream_unreachable_returns_502(monkeypatch) -> None:
    class StubAsyncClient:
        def __init__(self, *_a, **_kw) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): return None
        async def post(self, *_a, **_kw):
            raise httpx.ConnectError("nope")

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", StubAsyncClient)
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "goodpass1"})
        assert r.status_code == 502
        assert r.json()["detail"] == "auth backend unreachable"


def test_login_missing_token_in_response_returns_502(monkeypatch) -> None:
    _mock_signin(monkeypatch, body={"id": 1})  # no token key
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "goodpass1"})
        assert r.status_code == 502


# ─── Rate limit ──────────────────────────────────────────────────────────────


def test_login_rate_limited_after_n_attempts(monkeypatch) -> None:
    # Rate limit triggers regardless of upstream outcome — count is per-IP.
    _mock_signin(monkeypatch, status_code=401, body={"detail": "nope"})
    with TestClient(app) as c:
        for _ in range(auth_mod.RL_MAX_ATTEMPTS):
            r = c.post("/auth/login", json={"email": "user@example.ro", "password": "wrongpass1"})
            assert r.status_code == 401

        # Next attempt is rate-limited regardless of credentials.
        r = c.post("/auth/login", json={"email": "user@example.ro", "password": "wrongpass1"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert int(r.headers["Retry-After"]) >= 1
