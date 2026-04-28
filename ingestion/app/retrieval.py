from __future__ import annotations

from .config import settings
from .embed import embed_batch
from .rerank import rerank
from .store import search


async def retrieve(query: str) -> list[dict]:
    qvec = (await embed_batch([query]))[0]
    candidates = await search(qvec, top_k=settings.INGEST_TOP_K)
    if not candidates:
        return []
    texts = [c["payload"].get("text", "") for c in candidates]
    ranked = await rerank(query, texts)
    top = ranked[: settings.INGEST_TOP_N]
    return [
        {**candidates[idx], "rerank_score": score}
        for idx, score in top
    ]
