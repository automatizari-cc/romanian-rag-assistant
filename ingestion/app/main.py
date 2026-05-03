from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth import current_user
from .auth import router as auth_router
from .chunking import chunk_text
from .config import settings
from .embed import embed_batch
from .llm import build_context_block, build_messages, new_completion_id, ollama_chat_stream, to_openai_chunk
from .parsers import parse
from .retrieval import retrieve
from .store import delete_document, ensure_collection, list_documents, upsert_chunks

log = logging.getLogger("ingestion")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_FILENAME_OK = re.compile(r"[^A-Za-z0-9._-]+")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await ensure_collection()
    except Exception as e:
        log.warning("qdrant not reachable at startup: %s; will retry lazily", e)
    yield


app = FastAPI(title="romanian-rag ingestion", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


class IngestResponse(BaseModel):
    filename: str
    mime: str
    chunks: int
    bytes: int


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = _FILENAME_OK.sub("_", base)
    return cleaned[:200] or "upload"


@app.post("/ingest", response_model=IngestResponse)
async def ingest(file: Annotated[UploadFile, File(...)]) -> IngestResponse:
    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    filename = _safe_filename(file.filename or "upload")
    try:
        mime, pages = parse(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e

    archive = Path(settings.UPLOAD_DIR) / filename
    archive.write_bytes(data)

    all_chunks: list[str] = []
    payloads: list[dict] = []
    for page_no, text in pages:
        for c in chunk_text(text, settings.INGEST_CHUNK_TOKENS, settings.INGEST_CHUNK_OVERLAP):
            all_chunks.append(c)
            payloads.append({"source": filename, "page": page_no, "text": c})

    if not all_chunks:
        raise HTTPException(status_code=422, detail="no text extracted")

    await ensure_collection()
    vectors = await embed_batch(all_chunks)
    upserted = await upsert_chunks(vectors, payloads)
    log.info("ingested %s mime=%s chunks=%d", filename, mime, upserted)
    return IngestResponse(filename=filename, mime=mime, chunks=upserted, bytes=len(data))


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = Field(default=True)
    temperature: float | None = None


@app.get("/v1/models")
async def list_models() -> dict:
    # Open-WebUI fetches /v1/models to populate its dropdown. We expose only
    # the configured backend model — the chat handler uses settings.OLLAMA_MODEL
    # regardless of what the client sends, so listing more would mislead.
    return {
        "object": "list",
        "data": [
            {
                "id": settings.OLLAMA_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "ollama",
            }
        ],
    }


class KbUploadResponse(BaseModel):
    doc_id: str
    filename: str
    mime: str
    chunks: int
    bytes: int
    uploaded_at: str


@app.post("/kb/upload", response_model=KbUploadResponse)
async def kb_upload(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict, Depends(current_user)],
) -> KbUploadResponse:
    data = await file.read()
    if len(data) > settings.MAX_USER_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    filename = _safe_filename(file.filename or "upload")
    try:
        mime, pages = parse(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e

    doc_id = str(uuid.uuid4())
    uploaded_at = datetime.now(UTC).isoformat()
    uploader_id = str(user.get("id") or "unknown")

    archive_dir = Path(settings.UPLOAD_DIR) / doc_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / filename).write_bytes(data)

    all_chunks: list[str] = []
    payloads: list[dict] = []
    for page_no, text in pages:
        for c in chunk_text(text, settings.INGEST_CHUNK_TOKENS, settings.INGEST_CHUNK_OVERLAP):
            all_chunks.append(c)
            payloads.append({
                "source": filename,
                "filename": filename,
                "page": page_no,
                "text": c,
                "doc_id": doc_id,
                "uploaded_by": uploader_id,
                "uploaded_at": uploaded_at,
                "mime": mime,
                "size_bytes": len(data),
            })

    if not all_chunks:
        raise HTTPException(status_code=422, detail="no text extracted")

    await ensure_collection()
    vectors = await embed_batch(all_chunks)
    upserted = await upsert_chunks(vectors, payloads)
    log.info("kb upload doc_id=%s by=%s mime=%s chunks=%d", doc_id, uploader_id, mime, upserted)
    return KbUploadResponse(
        doc_id=doc_id,
        filename=filename,
        mime=mime,
        chunks=upserted,
        bytes=len(data),
        uploaded_at=uploaded_at,
    )


@app.get("/kb/documents")
async def kb_list(_user: Annotated[dict, Depends(current_user)]) -> dict:
    docs = await list_documents()
    return {"documents": docs}


@app.delete("/kb/documents/{doc_id}")
async def kb_delete(
    doc_id: str,
    _user: Annotated[dict, Depends(current_user)],
) -> dict:
    if not _UUID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="invalid doc_id")
    deleted = await delete_document(doc_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="document not found")
    archive_dir = Path(settings.UPLOAD_DIR) / doc_id
    if archive_dir.exists():
        shutil.rmtree(archive_dir, ignore_errors=True)
    return {"doc_id": doc_id, "chunks_deleted": deleted}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages required")

    user_turn = next((m for m in reversed(req.messages) if m.role == "user"), None)
    if user_turn is None:
        raise HTTPException(status_code=400, detail="no user message")

    rid = uuid.uuid4().hex[:8]
    t_req = time.perf_counter()
    timings: dict[str, float] = {}

    hits = await retrieve(user_turn.content, timings=timings)
    context = build_context_block(hits)
    messages = build_messages([m.model_dump() for m in req.messages], context)

    completion_id = new_completion_id()
    model_name = req.model or settings.OLLAMA_MODEL

    log.info(
        "chat rid=%s stage=retrieve embed_ms=%s search_ms=%s rerank_ms=%s hits=%d",
        rid,
        timings.get("embed_ms"),
        timings.get("search_ms"),
        timings.get("rerank_ms"),
        len(hits),
    )

    async def stream():
        t_stream = time.perf_counter()
        async for line in ollama_chat_stream(messages):
            chunk = to_openai_chunk(line, completion_id, model_name)
            if chunk is not None:
                if "ollama_first_token_ms" not in timings:
                    timings["ollama_first_token_ms"] = round(
                        (time.perf_counter() - t_stream) * 1000, 1
                    )
                yield chunk
        timings["ollama_total_ms"] = round((time.perf_counter() - t_stream) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t_req) * 1000, 1)
        log.info(
            "chat rid=%s stage=ollama first_token_ms=%s ollama_total_ms=%s total_ms=%s",
            rid,
            timings.get("ollama_first_token_ms"),
            timings.get("ollama_total_ms"),
            timings.get("total_ms"),
        )
        yield f": rag-timings={json.dumps({'rid': rid, **timings})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
