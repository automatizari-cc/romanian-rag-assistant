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
    if settings.QDRANT_COLLECTION not in existing:
        await c.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=qm.VectorParams(
                size=settings.QDRANT_VECTOR_SIZE,
                distance=qm.Distance[settings.QDRANT_DISTANCE.upper()],
            ),
        )
    # Idempotent: Qdrant ignores re-creation if the index already exists.
    # Required for fast filter-delete + filter-count by doc_id.
    await c.create_payload_index(
        collection_name=settings.QDRANT_COLLECTION,
        field_name="doc_id",
        field_schema=qm.PayloadSchemaType.KEYWORD,
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


_DOC_FIELDS = ("doc_id", "filename", "uploaded_by", "uploaded_at", "mime", "size_bytes")


async def list_documents() -> list[dict]:
    """Scroll the collection and return one summary per distinct doc_id.

    Chunks pre-dating the doc_id payload field are skipped.
    """
    c = client()
    docs: dict[str, dict] = {}
    counts: dict[str, int] = {}
    next_offset = None
    while True:
        points, next_offset = await c.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=512,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            doc_id = payload.get("doc_id")
            if not doc_id:
                continue
            counts[doc_id] = counts.get(doc_id, 0) + 1
            if doc_id not in docs:
                docs[doc_id] = {k: payload.get(k) for k in _DOC_FIELDS}
        if next_offset is None:
            break
    for doc_id, info in docs.items():
        info["chunk_count"] = counts[doc_id]
    return sorted(docs.values(), key=lambda d: d.get("uploaded_at") or "", reverse=True)


async def delete_document(doc_id: str) -> int:
    """Delete every point with this doc_id. Returns the count deleted (0 if none)."""
    c = client()
    flt = qm.Filter(
        must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]
    )
    pre = await c.count(
        collection_name=settings.QDRANT_COLLECTION,
        count_filter=flt,
        exact=True,
    )
    if pre.count == 0:
        return 0
    await c.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=qm.FilterSelector(filter=flt),
        wait=True,
    )
    return pre.count
