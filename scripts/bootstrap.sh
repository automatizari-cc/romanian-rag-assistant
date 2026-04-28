#!/usr/bin/env bash
# Pull the LLM into Ollama and pre-warm TEI embedding/reranker caches.
# Idempotent — safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

: "${OLLAMA_MODEL:?OLLAMA_MODEL not set}"
: "${EMBED_MODEL:?EMBED_MODEL not set}"
: "${RERANK_MODEL:?RERANK_MODEL not set}"

# RoLlama3.1 GGUF is hosted on HF — Ollama can pull directly via hf.co/ syntax.
# If $OLLAMA_MODEL is a tag like rollama3.1:8b-instruct-q4_k_m we need a Modelfile.
HF_GGUF_REPO="${HF_GGUF_REPO:-OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF}"
HF_GGUF_QUANT="${HF_GGUF_QUANT:-Q4_K_M}"

echo "[bootstrap] waiting for ollama to be reachable…"
until docker compose exec -T ollama ollama list >/dev/null 2>&1; do
  sleep 2
done

if docker compose exec -T ollama ollama list | awk '{print $1}' | grep -qx "$OLLAMA_MODEL"; then
  echo "[bootstrap] ollama already has $OLLAMA_MODEL"
else
  echo "[bootstrap] pulling $HF_GGUF_REPO:$HF_GGUF_QUANT into ollama as $OLLAMA_MODEL"
  docker compose exec -T ollama ollama pull "hf.co/${HF_GGUF_REPO}:${HF_GGUF_QUANT}"
  docker compose exec -T ollama ollama cp "hf.co/${HF_GGUF_REPO}:${HF_GGUF_QUANT}" "$OLLAMA_MODEL" || true
fi

echo "[bootstrap] warming tei-embed ($EMBED_MODEL)…"
curl -fsS -X POST "http://127.0.0.1:8081/embed" \
  -H 'content-type: application/json' \
  -d '{"inputs":["salut"],"normalize":true}' >/dev/null

echo "[bootstrap] warming tei-rerank ($RERANK_MODEL)…"
curl -fsS -X POST "http://127.0.0.1:8082/rerank" \
  -H 'content-type: application/json' \
  -d '{"query":"salut","texts":["salut lume","alt text"]}' >/dev/null

echo "[bootstrap] done."
