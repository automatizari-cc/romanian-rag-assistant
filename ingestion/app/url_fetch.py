"""Server-side URL fetcher for /kb/url with SSRF guard + size cap.

Threat model: an authenticated user pastes a URL. We must not let them pivot
into internal services (qdrant, ollama, postgres, the ingestion API itself,
etc.) by submitting URLs that resolve to private/loopback addresses.

Defenses:
- Scheme allowlist (http/https only).
- Reject userinfo in URL.
- Resolve hostname pre-flight; reject if ANY resolved address is private,
  loopback, link-local, multicast, reserved, or unspecified. (TOCTOU window
  exists — httpx re-resolves at connect time. Acceptable for single-tenant.)
- follow_redirects=False — a redirect bypasses our pre-flight check.
- Streaming download with hard byte cap.
- Content-Type allowlist.
- Connection + read timeouts.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_ALLOWED_CONTENT_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
})

_USER_AGENT = "romanian-rag/1.0 (+self-hosted)"


class FetchError(Exception):
    """Any failure in fetch_url. Message is in Romanian and safe to surface."""


def _ip_is_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise FetchError("URL gol.")
    p = urlparse(url.strip())
    if p.scheme.lower() not in _ALLOWED_SCHEMES:
        raise FetchError("Doar URL-uri http:// sau https:// sunt permise.")
    if p.username or p.password:
        raise FetchError("URL-urile cu credențiale nu sunt permise.")
    if not p.hostname:
        raise FetchError("URL fără gazdă.")
    return p.hostname


def _resolve_and_check(hostname: str) -> None:
    # Reject IP literals that are obviously private without going through DNS.
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None and _ip_is_blocked(str(addr)):
        raise FetchError("Adresă internă/privată refuzată.")

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError(f"Gazda nu poate fi rezolvată: {hostname}") from e
    ips = {info[4][0] for info in infos}
    if not ips:
        raise FetchError(f"Gazda nu are adresă: {hostname}")
    if any(_ip_is_blocked(ip) for ip in ips):
        raise FetchError("Adresă internă/privată refuzată.")


async def fetch_url(
    url: str,
    *,
    max_bytes: int,
    connect_timeout: float = 10.0,
    read_timeout: float = 30.0,
) -> tuple[str, bytes]:
    """Fetch a URL after SSRF and size checks.

    Returns (content_type, body) where content_type is the lowercased
    `type/subtype` with parameters stripped. Raises FetchError on rejection.
    """
    hostname = _validate_url(url)
    _resolve_and_check(hostname)

    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=connect_timeout,
        pool=connect_timeout,
    )
    headers = {
        "user-agent": _USER_AGENT,
        "accept": "text/html, application/xhtml+xml, text/plain, text/markdown;q=0.9, */*;q=0.1",
        "accept-language": "ro,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        ) as client:
            async with client.stream("GET", url) as resp:
                if 300 <= resp.status_code < 400:
                    raise FetchError(
                        "URL-ul redirecționează. Folosiți URL-ul canonic.",
                    )
                if resp.status_code >= 400:
                    raise FetchError(
                        f"Răspuns HTTP {resp.status_code} de la URL.",
                    )
                ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ct not in _ALLOWED_CONTENT_TYPES:
                    raise FetchError(
                        f"Tip de conținut nepermis: {ct or 'necunoscut'}.",
                    )
                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    raise FetchError("Pagină prea mare.")

                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise FetchError("Pagină prea mare.")
                return ct, bytes(body)
    except FetchError:
        raise
    except httpx.HTTPError as e:
        raise FetchError(f"Nu am putut accesa URL-ul: {type(e).__name__}.") from e


# Map upstream content-type to a synthetic filename extension so that
# parsers.parse() picks the right branch even when magic.from_buffer disagrees.
EXT_FOR_CONTENT_TYPE: dict[str, str] = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
