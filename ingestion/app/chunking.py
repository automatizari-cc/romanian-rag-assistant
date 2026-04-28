from __future__ import annotations

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def chunk_text(text: str, max_tokens: int, overlap: int) -> list[str]:
    if not text.strip():
        return []
    tokens = _ENC.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    chunks: list[str] = []
    step = max(1, max_tokens - overlap)
    for start in range(0, len(tokens), step):
        end = start + max_tokens
        chunk_tokens = tokens[start:end]
        chunks.append(_ENC.decode(chunk_tokens))
        if end >= len(tokens):
            break
    return chunks
