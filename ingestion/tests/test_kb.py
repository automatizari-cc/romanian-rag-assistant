from __future__ import annotations

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app import main as main_mod
from app.config import settings
from app.main import app

SECRET = "test-secret-please-change-me"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEBUI_SECRET_KEY", SECRET)
    auth_mod.reset_rate_limiter()


def _make_token(payload: dict | None = None, *, secret: str = SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(payload or {"id": "user-1"}, secret, algorithm=algorithm)


# ─── verify_webui_jwt ────────────────────────────────────────────────────────


def test_verify_jwt_valid() -> None:
    claims = auth_mod.verify_webui_jwt(_make_token({"id": "abc"}), SECRET)
    assert claims == {"id": "abc"}


def test_verify_jwt_empty_token_raises_401() -> None:
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_webui_jwt("", SECRET)
    assert exc.value.status_code == 401


def test_verify_jwt_no_secret_configured_raises_500() -> None:
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_webui_jwt(_make_token(), "")
    assert exc.value.status_code == 500


def test_verify_jwt_wrong_secret_raises_401() -> None:
    tok = _make_token(secret="other-secret")
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_webui_jwt(tok, SECRET)
    assert exc.value.status_code == 401


def test_verify_jwt_tampered_raises_401() -> None:
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_webui_jwt(_make_token() + "x", SECRET)
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_other_algorithm() -> None:
    # Algorithm-confusion guard: HS512 token must not be accepted under HS256 verify.
    tok = jwt.encode({"id": "abc"}, SECRET, algorithm="HS512")
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_webui_jwt(tok, SECRET)
    assert exc.value.status_code == 401


# ─── /kb/upload ──────────────────────────────────────────────────────────────


def _patch_pipeline(monkeypatch, *, upserted: int = 3) -> dict:
    captured: dict = {}

    async def fake_ensure_collection() -> None:
        captured["ensure"] = True

    async def fake_embed_batch(chunks: list[str]) -> list[list[float]]:
        captured["chunks"] = chunks
        return [[0.0] * settings.QDRANT_VECTOR_SIZE for _ in chunks]

    async def fake_upsert_chunks(vectors, payloads) -> int:
        captured["vectors"] = vectors
        captured["payloads"] = payloads
        return upserted

    monkeypatch.setattr(main_mod, "ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(main_mod, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(main_mod, "upsert_chunks", fake_upsert_chunks)
    return captured


def test_kb_upload_happy_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    captured = _patch_pipeline(monkeypatch)
    tok = _make_token({"id": "user-42"})
    body = b"Salutare. Acesta este un text romanesc pentru testul de upload."
    with TestClient(app) as c:
        r = c.post(
            "/kb/upload",
            files={"file": ("hello.txt", body, "text/plain")},
            cookies={"token": tok},
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["chunks"] == 3
    assert j["filename"] == "hello.txt"
    assert j["bytes"] == len(body)
    assert main_mod._UUID_RE.match(j["doc_id"])
    payloads = captured["payloads"]
    assert all(p["doc_id"] == j["doc_id"] for p in payloads)
    assert all(p["uploaded_by"] == "user-42" for p in payloads)
    assert (tmp_path / j["doc_id"] / "hello.txt").read_bytes() == body


def test_kb_upload_requires_auth(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    with TestClient(app) as c:
        r = c.post(
            "/kb/upload",
            files={"file": ("hello.txt", b"hi there", "text/plain")},
        )
    assert r.status_code == 401


def test_kb_upload_too_large(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(settings, "MAX_USER_UPLOAD_BYTES", 16)
    tok = _make_token()
    with TestClient(app) as c:
        r = c.post(
            "/kb/upload",
            files={"file": ("big.txt", b"x" * 1000, "text/plain")},
            cookies={"token": tok},
        )
    assert r.status_code == 413


def test_kb_upload_empty_file(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    tok = _make_token()
    with TestClient(app) as c:
        r = c.post(
            "/kb/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            cookies={"token": tok},
        )
    assert r.status_code == 400


def test_kb_upload_unsupported_mime(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    tok = _make_token()
    # PNG signature → image/png, not in ALLOWED_MIMES, and .xyz isn't a fallback ext.
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with TestClient(app) as c:
        r = c.post(
            "/kb/upload",
            files={"file": ("nope.xyz", png_bytes, "application/octet-stream")},
            cookies={"token": tok},
        )
    assert r.status_code == 415


# ─── /kb/documents ───────────────────────────────────────────────────────────


def test_kb_list_happy_path(monkeypatch) -> None:
    fake_docs = [{"doc_id": "abc", "filename": "x.txt", "chunk_count": 3}]

    async def fake_list() -> list[dict]:
        return fake_docs

    monkeypatch.setattr(main_mod, "list_documents", fake_list)
    tok = _make_token()
    with TestClient(app) as c:
        r = c.get("/kb/documents", cookies={"token": tok})
    assert r.status_code == 200
    assert r.json() == {"documents": fake_docs}


def test_kb_list_requires_auth() -> None:
    with TestClient(app) as c:
        r = c.get("/kb/documents")
    assert r.status_code == 401


# ─── DELETE /kb/documents/{doc_id} ───────────────────────────────────────────


def test_kb_delete_happy_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    doc_id = "12345678-1234-1234-1234-123456789012"

    async def fake_delete(d: str) -> int:
        assert d == doc_id
        return 4

    monkeypatch.setattr(main_mod, "delete_document", fake_delete)
    (tmp_path / doc_id).mkdir()
    (tmp_path / doc_id / "x.txt").write_bytes(b"x")
    tok = _make_token()
    with TestClient(app) as c:
        r = c.delete(f"/kb/documents/{doc_id}", cookies={"token": tok})
    assert r.status_code == 200
    assert r.json() == {"doc_id": doc_id, "chunks_deleted": 4}
    assert not (tmp_path / doc_id).exists()


def test_kb_delete_invalid_uuid() -> None:
    tok = _make_token()
    with TestClient(app) as c:
        r = c.delete("/kb/documents/not-a-uuid", cookies={"token": tok})
    assert r.status_code == 400


def test_kb_delete_not_found(monkeypatch) -> None:
    async def fake_delete(d: str) -> int:
        return 0

    monkeypatch.setattr(main_mod, "delete_document", fake_delete)
    tok = _make_token()
    with TestClient(app) as c:
        r = c.delete(
            "/kb/documents/12345678-1234-1234-1234-123456789012",
            cookies={"token": tok},
        )
    assert r.status_code == 404


def test_kb_delete_requires_auth() -> None:
    with TestClient(app) as c:
        r = c.delete("/kb/documents/12345678-1234-1234-1234-123456789012")
    assert r.status_code == 401
