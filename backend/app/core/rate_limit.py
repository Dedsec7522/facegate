"""Small in-process sliding-window rate limiter (per key). Good for a single API node;
swap for a Redis-backed limiter when scaling horizontally."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

from app.core.config import settings


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_limiter = RateLimiter(limit=settings.login_per_minute_per_ip, window_seconds=60)
verify_session_limiter = RateLimiter(limit=settings.verify_sessions_per_minute, window_seconds=60)
generic_limiter = RateLimiter(limit=300, window_seconds=60)


def client_ip(request: Request) -> str:
    # Never read X-Forwarded-For here: any client can send one, and the first entry is whatever it chose, which
    # would let it dodge every per-IP limit and forge audit-log addresses. Uvicorn's proxy-headers middleware has
    # already replaced request.client with the forwarded address, but only when the direct peer is a trusted proxy
    # (--forwarded-allow-ips / FORWARDED_ALLOW_IPS; default 127.0.0.1). In Docker, nginx overwrites the header with
    # $remote_addr and is the only route to the API.
    return request.client.host if request.client else "unknown"


def limit(limiter: RateLimiter):
    async def _dep(request: Request) -> None:
        if not limiter.check(client_ip(request)):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please slow down.")

    return _dep
