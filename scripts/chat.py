#!/usr/bin/env python3
"""Asistent RAG — chat în terminal.

Rulare pe server (după SSH în box):
    python3 /opt/rag/scripts/chat.py

Vorbește direct cu ingestion-ul pe 127.0.0.1:8000, ocolind UI-ul Open-WebUI.
Păstrează istoricul conversației pe durata sesiunii. Pentru a ieși: scrie
`ieși`, `exit` sau apasă Ctrl+C.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

API_URL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "rollama3.1:Q4_K_M"
EXIT_WORDS = {"ieși", "iesi", "exit", "quit", "stop"}

BANNER = """
╔══════════════════════════════════════════════════════╗
║                                                      ║
║   Asistent RAG — Tehnologia Vinului                  ║
║                                                      ║
║   Scrie întrebarea ta și apasă Enter.                ║
║   Răspunsul apare în timp real, sub întrebare.       ║
║                                                      ║
║   Pentru a ieși: scrie `ieși` sau apasă Ctrl+C.      ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
"""


def stream_response(messages: list[dict]) -> str | None:
    """Trimite mesajele, afișează tokenii pe măsură ce apar, întoarce textul complet.

    Returnează None dacă apare o eroare de rețea sau de server (mesajul a fost
    deja afișat utilizatorului).
    """
    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 (intentional internal URL)
            for raw in r:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    evt = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = evt.get("choices", [])
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content", "")
                if content:
                    parts.append(content)
                    print(content, end="", flush=True)
    except urllib.error.HTTPError as e:
        print(f"\n\n[Serviciul a răspuns cu eroare {e.code}. Încearcă din nou peste câteva momente.]")
        return None
    except urllib.error.URLError:
        print("\n\n[Nu am putut conecta la asistent. Verifică dacă serviciul rulează.]")
        return None
    except TimeoutError:
        print("\n\n[Răspunsul durează prea mult. Încearcă o întrebare mai scurtă.]")
        return None

    print()  # final newline after the streamed response
    return "".join(parts)


def main() -> int:
    print(BANNER)
    history: list[dict] = []

    while True:
        try:
            question = input("Întrebare > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nLa revedere!")
            return 0

        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            print("La revedere!")
            return 0

        history.append({"role": "user", "content": question})

        print()  # blank line before the answer
        try:
            answer = stream_response(history)
        except KeyboardInterrupt:
            print("\n\n[Răspuns întrerupt.]")
            history.pop()  # drop the unanswered question
            print()
            continue
        print()  # blank line after the answer

        if answer:
            history.append({"role": "assistant", "content": answer})
        else:
            # Eroare deja afișată; nu păstrăm întrebarea fără răspuns în istoric.
            history.pop()


if __name__ == "__main__":
    sys.exit(main())
