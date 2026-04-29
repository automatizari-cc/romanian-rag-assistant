"""TEI-compatible HTTP shim for hosts without AVX2.

Exposes /embed and /rerank with the same JSON contract that
ghcr.io/huggingface/text-embeddings-inference uses, so ingestion/app/embed.py
and ingestion/app/rerank.py can talk to it unchanged.

Run as either an embedder or a reranker by setting MODE=embed | rerank and
MODEL_ID=<HF repo>. One image, two compose service definitions.
"""

from __future__ import annotations

import logging
import math
import os
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("tei-shim")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MODE = os.environ.get("MODE", "").strip().lower()
MODEL_ID = os.environ.get("MODEL_ID", "").strip()

if MODE not in ("embed", "rerank"):
    raise RuntimeError(f"MODE must be 'embed' or 'rerank', got {MODE!r}")
if not MODEL_ID:
    raise RuntimeError("MODEL_ID is required")


class _State:
    embedder: Any = None
    reranker: Any = None


state = _State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if MODE == "embed":
        from sentence_transformers import SentenceTransformer

        logger.info("loading embedder %s on cpu", MODEL_ID)
        state.embedder = SentenceTransformer(MODEL_ID, device="cpu")
        logger.info("embedder ready")
    else:
        from sentence_transformers import CrossEncoder

        logger.info("loading reranker %s on cpu", MODEL_ID)
        state.reranker = CrossEncoder(MODEL_ID, device="cpu")
        logger.info("reranker ready")
    yield


app = FastAPI(lifespan=lifespan, title=f"tei-shim ({MODE})")


@app.get("/health")
def health() -> dict[str, str]:
    if MODE == "embed" and state.embedder is None:
        raise HTTPException(503, "embedder not loaded")
    if MODE == "rerank" and state.reranker is None:
        raise HTTPException(503, "reranker not loaded")
    return {"status": "ok", "mode": MODE, "model": MODEL_ID}


class EmbedRequest(BaseModel):
    inputs: list[str] | str = Field(..., description="Text or list of texts to embed")
    normalize: bool = True
    truncate: bool = False  # accepted for TEI compatibility; sentence-transformers truncates by default


@app.post("/embed")
def embed(req: EmbedRequest) -> list[list[float]]:
    if MODE != "embed":
        raise HTTPException(404, "this shim is in rerank mode")
    texts = [req.inputs] if isinstance(req.inputs, str) else req.inputs
    if not texts:
        return []
    vectors = state.embedder.encode(
        texts,
        normalize_embeddings=req.normalize,
        convert_to_numpy=True,
    )
    return np.asarray(vectors, dtype=np.float32).tolist()


class RerankRequest(BaseModel):
    query: str
    texts: list[str]
    raw_scores: bool = False
    return_text: bool = False
    truncate: bool = False  # TEI compat, unused here


class RerankItem(BaseModel):
    index: int
    score: float


@app.post("/rerank")
def rerank(req: RerankRequest) -> list[RerankItem]:
    if MODE != "rerank":
        raise HTTPException(404, "this shim is in embed mode")
    if not req.texts:
        return []
    pairs = [[req.query, t] for t in req.texts]
    raw = state.reranker.predict(pairs, convert_to_numpy=True)
    scores = np.asarray(raw, dtype=np.float64)
    if not req.raw_scores:
        # TEI applies sigmoid to map cross-encoder logits into [0, 1].
        scores = 1.0 / (1.0 + np.exp(-scores))
    order = np.argsort(-scores)  # descending
    return [
        RerankItem(index=int(i), score=float(scores[i]) if math.isfinite(scores[i]) else 0.0)
        for i in order
    ]
