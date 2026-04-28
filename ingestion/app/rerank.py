from __future__ import annotations

import httpx

from .config import settings


async def rerank(query: str, candidates: list[str]) -> list[tuple[int, float]]:
    if not candidates:
        return []
    async with httpx.AsyncClient(base_url=settings.RERANK_URL, timeout=120.0) as client:
        r = await client.post(
            "/rerank",
            json={"query": query, "texts": candidates, "raw_scores": False},
        )
        r.raise_for_status()
        return [(item["index"], item["score"]) for item in r.json()]
