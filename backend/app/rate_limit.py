"""Shared per-IP token-bucket rate limiter.

One bucket per client IP, refilled at ``RATE_LIMIT_PER_MINUTE`` tokens
per minute (30/min by default, from settings). The same limiter is
applied as a dependency to every state-changing / expensive POST
endpoint (analyze, analyze stream, chat messages, tools, image
upload, watchlist create/recheck). GET endpoints are not limited.

Residual risk (documented, deliberately not "fixed"): the bucket key
is ``request.client.host`` with no trusted-proxy handling. All users
behind one proxy/NAT share one bucket, and ``X-Forwarded-For`` is
never trusted, so a spoofed header cannot bypass the limit.
"""

from __future__ import annotations

import math
import time

from fastapi import HTTPException, Request

from .config import get_settings

# Per-IP token buckets: ip -> (tokens, last_refill_monotonic)
_BUCKETS: dict[str, tuple[float, float]] = {}


def reset_rate_limits() -> None:
    """Clear all buckets (used by tests)."""
    _BUCKETS.clear()


def rate_limit(request: Request) -> None:
    """FastAPI dependency: consume one token for the caller's IP."""
    settings = get_settings()
    limit = settings.RATE_LIMIT_PER_MINUTE
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    tokens, last = _BUCKETS.get(ip, (float(limit), now))
    tokens = min(float(limit), tokens + (now - last) * (limit / 60.0))
    if tokens < 1.0:
        retry_after = max(1, math.ceil((1.0 - tokens) / (limit / 60.0)))
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: {limit} requests per minute per IP."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    _BUCKETS[ip] = (tokens - 1.0, now)
