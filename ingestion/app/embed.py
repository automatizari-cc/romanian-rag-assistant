from __future__ import annotations

import httpx

from .config import settings


async def embed_batch(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(base_url=settings.EMBED_URL, timeout=120.0) as client:
        r = await client.post("/embed", json={"inputs": texts, "normalize": True})
        r.raise_for_status()
        return r.json()
