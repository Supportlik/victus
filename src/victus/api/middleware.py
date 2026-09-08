"""Security headers and a small in-memory rate limit for the sensitive prefixes."""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from victus.api.errors import problem

RATE_LIMITED_PREFIXES = ("/api/v1/auth/", "/api/v1/captures", "/mcp")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int | None = None) -> None:
        self.rate = rate_per_minute / 60.0
        self.capacity = float(burst or rate_per_minute)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        rate_per_minute: int = 120,
        prefixes: tuple[str, ...] = RATE_LIMITED_PREFIXES,
    ) -> None:
        super().__init__(app)
        self.bucket = TokenBucket(rate_per_minute)
        self.prefixes = prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith(self.prefixes):
            client = request.client.host if request.client else "unknown"
            key = f"{client}:{path.split('/')[3] if path.count('/') >= 3 else path}"
            if not self.bucket.allow(key):
                return problem(429, "rate limit exceeded", headers={"Retry-After": "30"})
        return await call_next(request)
