from __future__ import annotations

from io import BytesIO
from pathlib import Path

import magic
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/html",
}


def detect_mime(data: bytes) -> str:
    return magic.from_buffer(data, mime=True)


def parse_pdf(data: bytes) -> list[tuple[int, str]]:
    reader = PdfReader(BytesIO(data))
    return [(i + 1, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages)]


def parse_docx(data: bytes) -> list[tuple[int, str]]:
    doc = Document(BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(1, text)]


def parse_html(data: bytes) -> list[tuple[int, str]]:
    soup = BeautifulSoup(data, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [(1, soup.get_text(separator="\n", strip=True))]


def parse_text(data: bytes) -> list[tuple[int, str]]:
    return [(1, data.decode("utf-8", errors="replace"))]


def parse(filename: str, data: bytes) -> tuple[str, list[tuple[int, str]]]:
    mime = detect_mime(data)
    if mime not in ALLOWED_MIMES:
        ext = Path(filename).suffix.lower()
        if ext in {".md", ".markdown"}:
            mime = "text/markdown"
        elif ext == ".txt":
            mime = "text/plain"
        elif ext in {".html", ".htm"}:
            mime = "text/html"
        else:
            raise ValueError(f"unsupported file type: mime={mime} ext={ext}")

    if mime == "application/pdf":
        return mime, parse_pdf(data)
    if mime.endswith("wordprocessingml.document"):
        return mime, parse_docx(data)
    if mime == "text/html":
        return mime, parse_html(data)
    return mime, parse_text(data)
