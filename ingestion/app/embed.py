from __future__ import annotations

import httpx

from .config import settings

# TEI's default --max-client-batch-size. Larger requests get 413 from /embed.
EMBED_CLIENT_BATCH = 32


async def embed_batch(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    async with httpx.AsyncClient(base_url=settings.EMBED_URL, timeout=120.0) as client:
        for i in range(0, len(texts), EMBED_CLIENT_BATCH):
            r = await client.post(
                "/embed",
                json={"inputs": texts[i : i + EMBED_CLIENT_BATCH], "normalize": True},
            )
            r.raise_for_status()
            out.extend(r.json())
    return out
