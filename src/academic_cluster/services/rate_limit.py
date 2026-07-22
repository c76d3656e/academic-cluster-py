"""Distributed fixed-window limits for public authentication endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

import structlog

from ..config import get_settings
from .cache import get_cache

logger = structlog.get_logger()

_FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RateLimitBackendUnavailable(RuntimeError):
    """Raised in production when the distributed limiter cannot fail safely."""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class RateLimiter:
    """Redis-backed limiter with a bounded development-only local fallback."""

    def __init__(self) -> None:
        self._fallback: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _redis_key(scope: str) -> str:
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        return f"security:rate:{digest}"

    async def _fallback_check(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        now = time.monotonic()
        async with self._lock:
            count, expires_at = self._fallback.get(key, (0, now + window_seconds))
            if expires_at <= now:
                count, expires_at = 0, now + window_seconds
            count += 1
            self._fallback[key] = (count, expires_at)
            if len(self._fallback) > 10_000:
                self._fallback = {
                    item_key: value
                    for item_key, value in self._fallback.items()
                    if value[1] > now
                }
        retry_after = max(1, int(expires_at - now))
        return RateLimitResult(
            allowed=count <= limit,
            remaining=max(0, limit - count),
            retry_after=retry_after,
        )

    async def check(
        self, scope: str, *, limit: int, window_seconds: int
    ) -> RateLimitResult:
        key = self._redis_key(scope)
        try:
            raw = await get_cache().redis.eval(
                _FIXED_WINDOW_SCRIPT,
                1,
                key,
                window_seconds,
            )
            count, ttl = int(raw[0]), max(1, int(raw[1]))
            return RateLimitResult(
                allowed=count <= limit,
                remaining=max(0, limit - count),
                retry_after=ttl,
            )
        except Exception as error:
            settings = get_settings()
            if settings.is_production:
                logger.error("Authentication rate limiter unavailable", error=str(error))
                raise RateLimitBackendUnavailable(
                    "authentication rate limiter is unavailable"
                ) from error
            logger.warning("Using local development rate limiter", error=str(error))
            return await self._fallback_check(key, limit, window_seconds)


_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter
