from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth import router as auth_router
from .chunking import chunk_text
from .config import settings
from .embed import embed_batch
from .llm import build_context_block, build_messages, new_completion_id, ollama_chat_stream, to_openai_chunk
from .parsers import parse
from .retrieval import retrieve
from .store import ensure_collection, upsert_chunks

log = logging.getLogger("ingestion")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_FILENAME_OK = re.compile(r"[^A-Za-z0-9._-]+")


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


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages required")

    user_turn = next((m for m in reversed(req.messages) if m.role == "user"), None)
    if user_turn is None:
        raise HTTPException(status_code=400, detail="no user message")

    hits = await retrieve(user_turn.content)
    context = build_context_block(hits)
    messages = build_messages([m.model_dump() for m in req.messages], context)

    completion_id = new_completion_id()
    model_name = req.model or settings.OLLAMA_MODEL

    async def stream():
        async for line in ollama_chat_stream(messages):
            chunk = to_openai_chunk(line, completion_id, model_name)
            if chunk is not None:
                yield chunk
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
