"""
app/middleware/rate_limiter.py

Module 06 — Tiered rate limiting using SlowAPI.

SlowAPI wraps the `limits` library and integrates natively with FastAPI /
Starlette. It supports multiple storage backends: Redis in production,
in-memory for testing (or when Redis is unavailable).

Limit tiers (all are sliding-window, per-minute):
  ┌─────────────────────────────┬────────────┬─────────────────────────────┐
  │ Tier                        │ Scope      │ Limit                       │
  ├─────────────────────────────┼────────────┼─────────────────────────────┤
  │ Global catch-all            │ per IP     │ 100 req / min               │
  │ Auth (login, refresh)       │ per IP     │ 10 req / min                │
  │ Intake submit               │ per user   │ 5 req / min                 │
  │ Admin endpoints             │ per user   │ 60 req / min                │
  └─────────────────────────────┴────────────┴─────────────────────────────┘

Degradation:
  SlowAPI stores rate limit state lazily — it connects to Redis on the FIRST
  request that hits a rate-limited endpoint, NOT at startup. We therefore
  must probe Redis with a synchronous ping() at build time. If Redis is
  unreachable (e.g., local dev / tests without Docker), the limiter falls
  back to in-memory storage automatically. This avoids ConnectionErrors at
  request time and keeps tests green without needing a live Redis.

Usage in routes:
    from app.middleware.rate_limiter import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    def login(request: Request, ...):
        ...

The `request: Request` parameter MUST be present in the route signature for
SlowAPI to detect and apply the limit.
"""

import logging

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _redis_is_reachable(redis_url: str, timeout: float = 1.0) -> bool:
    """
    Probe Redis with a synchronous ping. Returns True if reachable.

    This is called once at module import time so the limiter is configured
    with the correct backend before the first request arrives.
    A short timeout keeps startup fast even when Redis is down.
    """
    try:
        import redis as _redis_lib
        client = _redis_lib.from_url(
            redis_url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        client.ping()
        client.close()
        return True
    except Exception as exc:
        logger.warning(
            "[rate_limiter] Redis probe failed (%s). "
            "Falling back to in-memory rate limit storage. "
            "Limits will NOT persist across worker restarts.",
            exc,
        )
        return False


def _build_limiter() -> Limiter:
    """
    Create the Limiter instance.

    - If rate limiting is disabled via config: returns a limiter backed by
      in-memory storage (limits are still applied, just not shared across
      processes — useful for testing).
    - If Redis is reachable: uses Redis-backed sliding-window storage.
    - If Redis is unreachable: falls back to in-memory storage gracefully.
    """
    if not settings.rate_limit_enabled:
        logger.info("[rate_limiter] Rate limiting is DISABLED via config. Using in-memory storage.")
        return Limiter(key_func=get_remote_address, storage_uri="memory://")

    redis_url = settings.redis_url
    if _redis_is_reachable(redis_url):
        logger.info("[rate_limiter] Redis reachable — using Redis storage at %s", redis_url)
        return Limiter(key_func=get_remote_address, storage_uri=redis_url)

    # Redis not available — degrade gracefully to in-memory
    return Limiter(key_func=get_remote_address, storage_uri="memory://")


# ── Shared limiter instance ────────────────────────────────────────────────────
# Import this in route files:   from app.middleware.rate_limiter import limiter
limiter = _build_limiter()


# ── Rate-limit strings ─────────────────────────────────────────────────────────
# Pre-built from settings so routes don't embed magic numbers.
LIMIT_GLOBAL  = f"{settings.rate_limit_global_per_minute}/minute"
LIMIT_AUTH    = f"{settings.rate_limit_auth_per_minute}/minute"
LIMIT_INTAKE  = f"{settings.rate_limit_intake_per_minute}/minute"
LIMIT_ADMIN   = f"{settings.rate_limit_admin_per_minute}/minute"


def get_rate_limit_exceeded_handler():
    """Return the SlowAPI 429 handler for registration with the FastAPI app."""
    return RateLimitExceeded, _rate_limit_exceeded_handler
