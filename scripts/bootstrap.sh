#!/usr/bin/env bash
# Pull/build the LLM into Ollama and pre-warm TEI embedding/reranker caches.
# Idempotent — safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

: "${OLLAMA_MODEL:?OLLAMA_MODEL not set}"
: "${EMBED_MODEL:?EMBED_MODEL not set}"
: "${RERANK_MODEL:?RERANK_MODEL not set}"

# If MODELFILE is set, $OLLAMA_MODEL is built via `ollama create -f <file>`.
# The Modelfile's FROM line pulls the base GGUF on first run, so no separate
# pull step is needed. If MODELFILE is empty, $OLLAMA_MODEL must be a stock
# registry tag and we fall back to `ollama pull`.
MODELFILE="${MODELFILE:-}"

echo "[bootstrap] waiting for ollama to be reachable…"
until docker compose exec -T ollama ollama list >/dev/null 2>&1; do
  sleep 2
done

if docker compose exec -T ollama ollama list | awk '{print $1}' | grep -qx "$OLLAMA_MODEL"; then
  echo "[bootstrap] ollama already has $OLLAMA_MODEL"
elif [[ -n "$MODELFILE" ]]; then
  if [[ ! -f "$MODELFILE" ]]; then
    echo "[bootstrap] MODELFILE=$MODELFILE not found on host" >&2
    exit 1
  fi
  echo "[bootstrap] creating $OLLAMA_MODEL from $MODELFILE (pulls base GGUF on first run)"
  docker compose cp "$MODELFILE" ollama:/tmp/bootstrap.Modelfile
  docker compose exec -T ollama ollama create "$OLLAMA_MODEL" -f /tmp/bootstrap.Modelfile
else
  echo "[bootstrap] pulling $OLLAMA_MODEL"
  docker compose exec -T ollama ollama pull "$OLLAMA_MODEL"
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
