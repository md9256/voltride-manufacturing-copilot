"""Demo access gate and rate limiting for the public deployment.

Two independent protections for the endpoints that cost money (LLM calls) or
change data:

- DEMO_PASSWORD: when set, those endpoints need a signed access token, issued
  in exchange for the password. Tokens are HMAC-signed with AUTH_SECRET and
  expire; nothing is stored server-side, so they survive restarts as long as
  the secret does. A header token (not a cookie) keeps it working through
  the Vercel -> Hugging Face proxy with no CSRF surface.
- Rate limits: per client IP per minute and per day, plus a global daily cap
  that protects the shared free-tier LLM quota even if IPs are spoofed.

Client IP: behind Vercel and the Hugging Face proxy, uvicorn's proxy-headers
handling sets request.client.host from X-Forwarded-For. Vercel overwrites that
header with the real client address, so it is trustworthy via the Vercel URL;
a caller hitting the Space URL directly could spoof it, which is why the
global cap exists.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.config import get_settings

TOKEN_TTL_S = 7 * 24 * 3600


# --- access tokens ---------------------------------------------------------------


def _secret() -> bytes:
    s = get_settings()
    # Prefer an explicit secret. Deriving one from the password still yields
    # stable tokens across restarts, and changing the password revokes them.
    material = s.auth_secret or f"derived:{s.demo_password}"
    return hashlib.sha256(material.encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(now: float | None = None) -> tuple[str, int]:
    expires = int((now or time.time()) + TOKEN_TTL_S)
    payload = _b64(json.dumps({"exp": expires}).encode())
    signature = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}", expires


def token_valid(token: str, now: float | None = None) -> bool:
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return False
        return json.loads(_unb64(payload))["exp"] > (now or time.time())
    except (ValueError, KeyError, json.JSONDecodeError):
        return False


def password_matches(candidate: str) -> bool:
    expected = get_settings().demo_password
    return bool(expected) and hmac.compare_digest(candidate.encode(), expected.encode())


def access_required() -> bool:
    return bool(get_settings().demo_password)


def require_access(authorization: Annotated[str | None, Header()] = None) -> None:
    """Dependency for endpoints that call the LLM or write data."""
    if not access_required():
        return
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not token or not token_valid(token):
        raise HTTPException(401, "This demo's AI features need the demo password.")


# --- rate limiting --------------------------------------------------------------


@dataclass(frozen=True)
class Limit:
    count: int
    window_s: int
    scope: str  # "ip" or "global"
    label: str


class RateLimiter:
    """Sliding-window limits kept in memory (one container, one process).

    Each limit keeps a deque of hit timestamps per key; a request is allowed
    only if every limit has room, and only then is it recorded everywhere, so
    rejected requests don't consume quota.
    """

    def __init__(self, limits: list[Limit], clock=time.monotonic) -> None:
        self.limits = limits
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, ip: str) -> None:
        now = self._clock()
        with self._lock:
            keys = []
            for limit in self.limits:
                key = (limit.label, ip if limit.scope == "ip" else "*")
                hits = self._hits[key]
                while hits and hits[0] <= now - limit.window_s:
                    hits.popleft()
                if len(hits) >= limit.count:
                    retry = int(hits[0] + limit.window_s - now) + 1
                    who = "from your address" if limit.scope == "ip" else "on this demo"
                    raise HTTPException(
                        429,
                        f"Too many AI requests {who} ({limit.count} per {limit.label}). Try again in {_human(retry)}.",
                        headers={"Retry-After": str(retry)},
                    )
                keys.append(key)
            for key in keys:
                self._hits[key].append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _human(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def _ai_limits() -> list[Limit]:
    s = get_settings()
    return [
        Limit(s.ai_rate_per_minute, 60, "ip", "minute"),
        Limit(s.ai_rate_per_day, 86_400, "ip", "day"),
        Limit(s.ai_rate_global_per_day, 86_400, "global", "day for everyone"),
    ]


ai_limiter = RateLimiter(_ai_limits())
login_limiter = RateLimiter([Limit(10, 60, "ip", "minute")])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_ai(request: Request) -> None:
    """Dependency for endpoints that make LLM calls."""
    ai_limiter.check(client_ip(request))


AiAccess = [Depends(require_access), Depends(limit_ai)]
