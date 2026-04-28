from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from .config import settings


def build_context_block(hits: list[dict]) -> str:
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        p = h["payload"]
        src = p.get("source", "necunoscut")
        page = p.get("page")
        loc = f"{src}#p{page}" if page else src
        parts.append(f"[{i}] ({loc})\n{p.get('text', '').strip()}")
    return "\n\n".join(parts)


def build_messages(user_msgs: list[dict], context: str) -> list[dict]:
    sys_prompt = (
        f"{settings.INGEST_SYSTEM_PROMPT_RO}\n\n"
        "CONTEXT:\n"
        f"{context if context else '(niciun context relevant)'}\n\n"
        "Citează sursele între paranteze drepte după informații, ex.: [1], [2]."
    )
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(m for m in user_msgs if m.get("role") != "system")
    return messages


async def ollama_chat_stream(messages: list[dict]) -> AsyncIterator[str]:
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {"num_ctx": settings.OLLAMA_NUM_CTX},
    }
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(base_url=settings.OLLAMA_URL, timeout=timeout) as client:
        async with client.stream("POST", "/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                yield line


def to_openai_chunk(ollama_line: str, completion_id: str, model: str) -> str | None:
    try:
        evt = json.loads(ollama_line)
    except json.JSONDecodeError:
        return None
    delta_content = evt.get("message", {}).get("content", "")
    finish = "stop" if evt.get("done") else None
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta_content} if delta_content else {},
                "finish_reason": finish,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def new_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"
