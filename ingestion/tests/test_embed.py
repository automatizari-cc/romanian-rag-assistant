from __future__ import annotations

import asyncio
import json

import httpx

from app import embed as embed_mod


def test_embed_batch_splits_at_client_batch_limit(monkeypatch) -> None:
    """embed_batch posts in slices of EMBED_CLIENT_BATCH; TEI returns 413 otherwise."""
    monkeypatch.setattr(embed_mod, "EMBED_CLIENT_BATCH", 4)

    posted_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        posted_sizes.append(len(inputs))
        return httpx.Response(200, json=[[0.1, 0.2] for _ in inputs])

    transport = httpx.MockTransport(handler)
    original = embed_mod.httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(embed_mod.httpx, "AsyncClient", factory)

    vectors = asyncio.run(embed_mod.embed_batch([f"c{i}" for i in range(10)]))

    assert len(vectors) == 10
    assert posted_sizes == [4, 4, 2]
