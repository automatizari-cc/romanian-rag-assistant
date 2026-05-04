from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app import url_fetch
from app.config import settings
from app.main import app
from app.url_fetch import FetchError, _resolve_and_check, _validate_url

SECRET = "test-secret-please-change-me"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "WEBUI_SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))


def _tok() -> str:
    return jwt.encode({"id": "user-1"}, SECRET, algorithm="HS256")


# ─── _validate_url ───────────────────────────────────────────────────────────


def test_validate_url_accepts_https() -> None:
    assert _validate_url("https://example.com/page") == "example.com"


def test_validate_url_accepts_http() -> None:
    assert _validate_url("http://example.com") == "example.com"


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com",
    "gopher://example.com",
    "javascript:alert(1)",
    "//example.com",  # no scheme
    "",
    "   ",
])
def test_validate_url_rejects_bad_scheme(bad: str) -> None:
    with pytest.raises(FetchError):
        _validate_url(bad)


def test_validate_url_rejects_userinfo() -> None:
    with pytest.raises(FetchError):
        _validate_url("https://user:pass@example.com/")


def test_validate_url_rejects_empty_host() -> None:
    with pytest.raises(FetchError):
        _validate_url("https:///path")


# ─── _resolve_and_check ──────────────────────────────────────────────────────


def _patch_resolver(monkeypatch, ips: list[str]) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(0, 0, 0, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(url_fetch.socket, "getaddrinfo", fake_getaddrinfo)


def test_resolve_accepts_public_ipv4(monkeypatch) -> None:
    _patch_resolver(monkeypatch, ["93.184.216.34"])  # example.com
    _resolve_and_check("example.com")  # no raise


@pytest.mark.parametrize("private_ip", [
    "127.0.0.1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",   # AWS/GCP metadata
    "0.0.0.0",
    "::1",
    "fc00::1",
    "fe80::1",
])
def test_resolve_rejects_private_ip(monkeypatch, private_ip: str) -> None:
    _patch_resolver(monkeypatch, [private_ip])
    with pytest.raises(FetchError, match="internă"):
        _resolve_and_check("evil.example.com")


def test_resolve_rejects_mixed_public_and_private(monkeypatch) -> None:
    # Defense against round-robin DNS that returns both a public and a private IP.
    _patch_resolver(monkeypatch, ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(FetchError, match="internă"):
        _resolve_and_check("example.com")


def test_resolve_rejects_ip_literal_private() -> None:
    with pytest.raises(FetchError, match="internă"):
        _resolve_and_check("127.0.0.1")


def test_resolve_rejects_unresolvable(monkeypatch) -> None:
    import socket as _socket

    def boom(*a, **kw):
        raise _socket.gaierror("nope")

    monkeypatch.setattr(url_fetch.socket, "getaddrinfo", boom)
    with pytest.raises(FetchError, match="rezolvat"):
        _resolve_and_check("does-not-exist.invalid")


# ─── /kb/url route (with fetch_url monkeypatched) ────────────────────────────


def _patch_pipeline(monkeypatch, *, upserted: int = 2) -> dict:
    captured: dict = {}

    async def fake_ensure_collection() -> None:
        captured["ensure"] = True

    async def fake_embed_batch(chunks: list[str]) -> list[list[float]]:
        captured["chunks"] = chunks
        return [[0.0] * settings.QDRANT_VECTOR_SIZE for _ in chunks]

    async def fake_upsert_chunks(vectors, payloads) -> int:
        captured["payloads"] = payloads
        return upserted

    monkeypatch.setattr(main_mod, "ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(main_mod, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(main_mod, "upsert_chunks", fake_upsert_chunks)
    return captured


def _patch_fetch(monkeypatch, *, body: bytes, ct: str = "text/html") -> None:
    async def fake_fetch(url: str, *, max_bytes: int, **kw):
        return ct, body

    monkeypatch.setattr(main_mod, "fetch_url", fake_fetch)


def test_kb_url_happy_path(monkeypatch, tmp_path) -> None:
    captured = _patch_pipeline(monkeypatch)
    body = (
        b"<html><body><h1>Salut</h1>"
        b"<p>Acesta este un text romanesc dintr-o pagina web.</p>"
        b"</body></html>"
    )
    _patch_fetch(monkeypatch, body=body)
    with TestClient(app) as c:
        r = c.post(
            "/kb/url",
            json={"url": "https://example.ro/articol"},
            cookies={"token": _tok()},
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["chunks"] == 2
    assert j["source"] == "https://example.ro/articol"
    assert main_mod._UUID_RE.match(j["doc_id"])
    payloads = captured["payloads"]
    assert all(p["doc_id"] == j["doc_id"] for p in payloads)
    assert all(p["filename"] == "https://example.ro/articol" for p in payloads)
    assert (tmp_path / j["doc_id"] / "source.html").exists()


def test_kb_url_requires_auth(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    _patch_fetch(monkeypatch, body=b"<html>x</html>")
    with TestClient(app) as c:
        r = c.post("/kb/url", json={"url": "https://example.ro/"})
    assert r.status_code == 401


def test_kb_url_propagates_fetch_error_as_400(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)

    async def fake_fetch(url, *, max_bytes, **kw):
        raise FetchError("Adresă internă/privată refuzată.")

    monkeypatch.setattr(main_mod, "fetch_url", fake_fetch)
    with TestClient(app) as c:
        r = c.post(
            "/kb/url",
            json={"url": "http://10.0.0.1/"},
            cookies={"token": _tok()},
        )
    assert r.status_code == 400
    assert "internă" in r.json()["detail"]


def test_kb_url_rejects_empty_body(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    _patch_fetch(monkeypatch, body=b"")
    with TestClient(app) as c:
        r = c.post(
            "/kb/url",
            json={"url": "https://example.ro/"},
            cookies={"token": _tok()},
        )
    assert r.status_code == 400


def test_kb_url_rejects_no_extractable_text(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    _patch_fetch(monkeypatch, body=b"<html><script>x</script></html>")
    with TestClient(app) as c:
        r = c.post(
            "/kb/url",
            json={"url": "https://example.ro/"},
            cookies={"token": _tok()},
        )
    assert r.status_code == 422
