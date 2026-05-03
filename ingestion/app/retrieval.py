from __future__ import annotations

import time

from .config import settings
from .embed import embed_batch
from .rerank import rerank
from .store import search


async def retrieve(query: str, timings: dict | None = None) -> list[dict]:
    t = time.perf_counter()
    qvec = (await embed_batch([query]))[0]
    if timings is not None:
        timings["embed_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    candidates = await search(qvec, top_k=settings.INGEST_TOP_K)
    if timings is not None:
        timings["search_ms"] = round((time.perf_counter() - t) * 1000, 1)

    if not candidates:
        return []
    texts = [c["payload"].get("text", "") for c in candidates]

    t = time.perf_counter()
    ranked = await rerank(query, texts)
    if timings is not None:
        timings["rerank_ms"] = round((time.perf_counter() - t) * 1000, 1)

    top = ranked[: settings.INGEST_TOP_N]
    return [
        {**candidates[idx], "rerank_score": score}
        for idx, score in top
    ]
