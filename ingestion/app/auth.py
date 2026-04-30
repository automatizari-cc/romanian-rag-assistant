"""Custom login endpoint.

Validates input strictly, rate-limits per client IP, then proxies to
Open-WebUI's signin API and sets the same `token` cookie Open-WebUI
expects on subsequent requests. The browser never talks to Open-WebUI's
auth API directly.
"""
from __future__ import annotations

import re
import time
from collections import deque
from threading import Lock

import httpx
import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from .config import settings

# ─── Config ──────────────────────────────────────────────────────────────────

OPENWEBUI_URL = "http://open-webui:8080"
SIGNIN_PATH = "/api/v1/auths/signin"
COOKIE_NAME = "token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days; matches Open-WebUI default

RL_WINDOW_SEC = 5 * 60
RL_MAX_ATTEMPTS = 5

PWD_MIN = 8
PWD_MAX = 256
EMAIL_MIN = 3
EMAIL_MAX = 254

_CTRL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")  # NUL + ctl bytes (allow tab)

# ─── In-memory per-IP rate limiter ───────────────────────────────────────────
# Process-local; safe for our single-worker uvicorn deployment. Switch to a
# Redis-backed limiter if we ever scale to >1 worker.

_rl_lock = Lock()
_rl_buckets: dict[str, deque[float]] = {}


def _rate_limit_check(client_ip: str) -> tuple[bool, int]:
    now = time.monotonic()
    cutoff = now - RL_WINDOW_SEC
    with _rl_lock:
        bucket = _rl_buckets.setdefault(client_ip, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RL_MAX_ATTEMPTS:
            retry_after = int(bucket[0] + RL_WINDOW_SEC - now) + 1
            return False, max(retry_after, 1)
        bucket.append(now)
        return True, 0


# ─── Request model with strict validation ────────────────────────────────────


class LoginIn(BaseModel):
    email: str = Field(min_length=EMAIL_MIN, max_length=EMAIL_MAX)
    password: str = Field(min_length=PWD_MIN, max_length=PWD_MAX)

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if _CTRL_RE.search(v):
            raise ValueError("invalid characters")
        try:
            info = validate_email(v, check_deliverability=False)
        except EmailNotValidError as e:
            raise ValueError("invalid email") from e
        return info.normalized

    @field_validator("password")
    @classmethod
    def _password_ok(cls, v: str) -> str:
        if _CTRL_RE.search(v):
            raise ValueError("invalid characters")
        return v


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    # nginx + Cloudflare have already collapsed CF-Connecting-IP into
    # X-Real-IP / X-Forwarded-For for us. Trust the leftmost forwarded value.
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── Router ──────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response) -> dict:
    ip = _client_ip(request)
    allowed, retry_after = _rate_limit_check(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many attempts",
            headers={"Retry-After": str(retry_after)},
        )

    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(base_url=OPENWEBUI_URL, timeout=timeout) as client:
        try:
            r = await client.post(
                SIGNIN_PATH,
                json={"email": payload.email, "password": payload.password},
                headers={"accept": "application/json", "content-type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail="auth backend unreachable") from e

    if r.status_code in (400, 401, 403):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail="auth backend error")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="unexpected auth response")

    body = r.json()
    token = body.get("token")
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=502, detail="auth backend returned no token")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    # Token is also returned in the body so login.js can seed localStorage —
    # Open-WebUI's SPA reads localStorage.token to decide whether to render the
    # chat UI or its own login form. Cookie alone is not enough.
    # Redirect to "/" — nginx routes "/" to Open-WebUI when a token cookie is
    # present, and to the static landing when not.
    return {"redirect": "/", "token": token}


def reset_rate_limiter() -> None:
    """Test helper — wipe the in-memory bucket."""
    with _rl_lock:
        _rl_buckets.clear()


# ─── JWT verification (shared with Open-WebUI via WEBUI_SECRET_KEY) ──────────


def verify_webui_jwt(token: str, secret: str) -> dict:
    """Decode and verify an Open-WebUI JWT. Returns the claims dict.

    Raises HTTPException(401) on any verification failure.
    Raises HTTPException(500) if the secret is not configured.
    """
    if not secret:
        raise HTTPException(status_code=500, detail="auth not configured")
    if not token:
        raise HTTPException(status_code=401, detail="auth required")
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="invalid token") from e


def current_user(request: Request) -> dict:
    """FastAPI dependency — returns the verified claims for the cookie token."""
    token = request.cookies.get(COOKIE_NAME, "")
    return verify_webui_jwt(token, settings.WEBUI_SECRET_KEY)
