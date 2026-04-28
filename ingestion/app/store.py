from __future__ import annotations

import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from .config import settings

_client: AsyncQdrantClient | None = None


def client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.QDRANT_URL)
    return _client


async def ensure_collection() -> None:
    c = client()
    existing = {col.name for col in (await c.get_collections()).collections}
    if settings.QDRANT_COLLECTION in existing:
        return
    await c.create_collection(
        collection_name=settings.QDRANT_COLLECTION,
        vectors_config=qm.VectorParams(
            size=settings.QDRANT_VECTOR_SIZE,
            distance=qm.Distance[settings.QDRANT_DISTANCE.upper()],
        ),
    )


async def upsert_chunks(
    vectors: list[list[float]],
    payloads: list[dict],
) -> int:
    c = client()
    points = [
        qm.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
        for v, p in zip(vectors, payloads, strict=True)
    ]
    await c.upsert(collection_name=settings.QDRANT_COLLECTION, points=points, wait=True)
    return len(points)


async def search(query_vector: list[float], top_k: int) -> list[dict]:
    c = client()
    res = await c.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    return [{"score": p.score, "payload": p.payload} for p in res.points]
