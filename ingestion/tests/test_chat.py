from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import main as main_mod
from app.config import settings
from app.llm import format_sources
from app.main import app

# ─── format_sources ──────────────────────────────────────────────────────────


def test_format_sources_empty() -> None:
    assert format_sources([]) == ""


def test_format_sources_pdf_with_page() -> None:
    hits = [
        {"payload": {"filename": "Tehnologia_vinului.pdf", "page": 42, "mime": "application/pdf"}},
    ]
    out = format_sources(hits)
    assert "**Surse:**" in out
    assert "[1] Tehnologia_vinului.pdf, p. 42" in out


def test_format_sources_pdf_page_one_skips_page() -> None:
    hits = [
        {"payload": {"filename": "Doc.pdf", "page": 1, "mime": "application/pdf"}},
    ]
    out = format_sources(hits)
    assert "[1] Doc.pdf" in out
    assert "p. 1" not in out


def test_format_sources_url_no_page_suffix() -> None:
    hits = [
        {"payload": {"filename": "https://ro.wikipedia.org/wiki/Vin", "page": 1, "mime": "text/html"}},
    ]
    out = format_sources(hits)
    assert "[1] https://ro.wikipedia.org/wiki/Vin" in out
    assert "p. 1" not in out


def test_format_sources_truncates_long_name() -> None:
    long_url = "https://example.com/" + "x" * 200
    hits = [{"payload": {"filename": long_url, "mime": "text/html"}}]
    out = format_sources(hits)
    line = next(ln for ln in out.split("\n") if ln.startswith("[1]"))
    assert line.endswith("...")
    assert len(line) <= len("[1] ") + 100


def test_format_sources_numbers_match_chunk_index() -> None:
    hits = [
        {"payload": {"filename": "a.pdf", "page": 3, "mime": "application/pdf"}},
        {"payload": {"filename": "b.pdf", "page": 7, "mime": "application/pdf"}},
        {"payload": {"filename": "https://example.ro/", "mime": "text/html"}},
    ]
    out = format_sources(hits)
    assert "[1] a.pdf, p. 3" in out
    assert "[2] b.pdf, p. 7" in out
    assert "[3] https://example.ro/" in out


def test_format_sources_falls_back_to_source_then_unknown() -> None:
    hits = [
        {"payload": {"source": "fallback.txt"}},  # no filename
        {"payload": {}},  # neither
    ]
    out = format_sources(hits)
    assert "[1] fallback.txt" in out
    assert "[2] (necunoscut)" in out


# ─── abstain + sources flow ──────────────────────────────────────────────────


def _hit(score: float, filename: str, mime: str, page: int = 1) -> dict:
    return {
        "rerank_score": score,
        "payload": {"filename": filename, "page": page, "mime": mime, "text": "..."},
    }


def _patch_retrieve(monkeypatch, hits: list[dict]) -> None:
    async def fake_retrieve(query, timings=None):
        if timings is not None:
            timings["embed_ms"] = 1.0
            timings["search_ms"] = 1.0
            timings["rerank_ms"] = 1.0
        return hits

    monkeypatch.setattr(main_mod, "retrieve", fake_retrieve)


def _patch_ollama(monkeypatch, *, lines: list[str] | None = None) -> dict:
    """Replace ollama_chat_stream. lines defaults to a one-token Romanian reply."""
    captured: dict = {"calls": 0}
    if lines is None:
        lines = [
            json.dumps({"message": {"content": "Răspuns scurt."}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]

    async def fake_stream(messages):
        captured["calls"] += 1
        captured["messages"] = messages
        for ln in lines:
            yield ln

    monkeypatch.setattr(main_mod, "ollama_chat_stream", fake_stream)
    return captured


def _read_sse(text: str) -> list[dict]:
    """Parse OpenAI-format SSE stream into a list of decoded chunk dicts."""
    out: list[dict] = []
    for raw in text.split("\n\n"):
        line = raw.strip()
        if not line.startswith("data: "):
            continue
        body = line[len("data: "):].strip()
        if body == "[DONE]":
            continue
        try:
            out.append(json.loads(body))
        except json.JSONDecodeError:
            pass
    return out


def _content(chunks: list[dict]) -> str:
    return "".join(c["choices"][0].get("delta", {}).get("content", "") for c in chunks)


def test_chat_abstains_on_no_hits(monkeypatch) -> None:
    _patch_retrieve(monkeypatch, [])
    captured = _patch_ollama(monkeypatch)
    monkeypatch.setattr(settings, "INGEST_ABSTAIN_MESSAGE_RO", "ABSTAIN_MARKER")
    with TestClient(app) as c:
        r = c.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "ce e Veuve Clicquot?"}]},
        )
    assert r.status_code == 200
    chunks = _read_sse(r.text)
    assert "ABSTAIN_MARKER" in _content(chunks)
    assert "Surse:" not in _content(chunks)
    assert captured["calls"] == 0  # Ollama must NOT be called


def test_chat_abstains_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INGEST_RELEVANCE_THRESHOLD", 0.5)
    _patch_retrieve(monkeypatch, [_hit(0.1, "x.pdf", "application/pdf", page=2)])
    captured = _patch_ollama(monkeypatch)
    monkeypatch.setattr(settings, "INGEST_ABSTAIN_MESSAGE_RO", "ABSTAIN_MARKER")
    with TestClient(app) as c:
        r = c.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "ceva"}]},
        )
    chunks = _read_sse(r.text)
    assert "ABSTAIN_MARKER" in _content(chunks)
    assert captured["calls"] == 0


def test_chat_answers_with_sources_footer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INGEST_RELEVANCE_THRESHOLD", 0.3)
    _patch_retrieve(monkeypatch, [
        _hit(0.85, "Tehnologia_vinului.pdf", "application/pdf", page=42),
        _hit(0.72, "https://ro.wikipedia.org/wiki/Vin", "text/html"),
    ])
    captured = _patch_ollama(monkeypatch, lines=[
        json.dumps({"message": {"content": "Răspuns [1] și [2]."}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ])
    with TestClient(app) as c:
        r = c.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "ceva"}]},
        )
    chunks = _read_sse(r.text)
    body = _content(chunks)
    assert captured["calls"] == 1
    assert "Răspuns [1] și [2]." in body
    assert "**Surse:**" in body
    assert "[1] Tehnologia_vinului.pdf, p. 42" in body
    assert "[2] https://ro.wikipedia.org/wiki/Vin" in body


def test_chat_finish_chunk_is_emitted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INGEST_RELEVANCE_THRESHOLD", 0.0)
    _patch_retrieve(monkeypatch, [_hit(0.5, "a.pdf", "application/pdf")])
    _patch_ollama(monkeypatch)
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    chunks = _read_sse(r.text)
    finishes = [c for c in chunks if c["choices"][0].get("finish_reason") == "stop"]
    assert len(finishes) == 1
