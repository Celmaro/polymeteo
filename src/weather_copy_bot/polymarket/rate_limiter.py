"""Token-bucket rate limiter for upstream Polymarket APIs.

Polymarket enforces ~60 calls/min standard and ~120 calls/min premium on the
public REST surface (gamma-api, data-api). A single poll loop can easily issue
4 wallets * 4 polls/s * 3 endpoints ~= 50+ requests/s when targets expand,
so a client-side cap is essential to stop the bot from being throttled into a
permanent 429 spiral.

This module also tracks 429 events and exposes a small callback hook so the
copy engine can count them (instead of silently dropping the wallet).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RateLimiterStats:
    """Lightweight stats counter exposed to the engine."""

    acquired: int = 0
    waited_ms: float = 0.0
    rejections_429: int = 0
    retry_after_hits: int = 0


@dataclass
class TokenBucketRateLimiter:
    """Per-host token bucket with async-safe acquire().

    - ``capacity`` is the burst size (tokens refilled per period).
    - ``refill_per_second`` controls the steady-state cap.
    - ``min_retry_after_seconds`` is the floor when parsing Retry-After so a
      tiny fraction-of-a-second header still pauses the bucket meaningfully.
    """

    capacity: int = 60
    refill_per_second: float = 60.0 / 60.0  # 60 calls / 60s = 1/s sustained
    min_retry_after_seconds: float = 1.0
    stats: RateLimiterStats = field(default_factory=RateLimiterStats)
    _tokens: float = 0.0
    _last_refill: float = field(default_factory=time.monotonic)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)

    async def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self.stats.acquired += 1
                    return
                deficit = 1.0 - self._tokens
                wait_s = max(deficit / max(self.refill_per_second, 0.001), 0.001)
                await asyncio.sleep(wait_s)
                self.stats.waited_ms += wait_s * 1000.0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(
            float(self.capacity),
            self._tokens + elapsed * self.refill_per_second,
        )
        self._last_refill = now

    @staticmethod
    def parse_retry_after(response: httpx.Response) -> float:
        """Read Retry-After (seconds or HTTP-date) and return seconds.

        Returns ``0.0`` when the header is missing/unparseable.
        """
        raw = response.headers.get("Retry-After")
        if not raw:
            return 0.0
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 0.0

    def record_429(self, retry_after_seconds: float = 0.0) -> None:
        """Notify the limiter of a 429; back off briefly so we don't spam."""
        self.stats.rejections_429 += 1
        if retry_after_seconds > 0:
            self.stats.retry_after_hits += 1
        # Penalize: drop a fraction of the bucket so the next acquire() waits.
        penalty = max(self.min_retry_after_seconds, retry_after_seconds)
        self._tokens = max(-float(penalty), self._tokens - penalty * self.refill_per_second)
        logger.warning(
            "upstream 429 (penalty=%.1fs total=%d)", penalty, self.stats.rejections_429
        )


# A single shared bucket per process is enough for the current single-engine
# deployment; multi-engine setups would shard by host instead.
_GAMMA_BUCKET: TokenBucketRateLimiter | None = None
_DATA_BUCKET: TokenBucketRateLimiter | None = None


def get_gamma_bucket() -> TokenBucketRateLimiter:
    global _GAMMA_BUCKET
    if _GAMMA_BUCKET is None:
        # Gamma is mostly market metadata; a small budget keeps discovery polite.
        _GAMMA_BUCKET = TokenBucketRateLimiter(
            capacity=10, refill_per_second=10.0 / 60.0
        )
    return _GAMMA_BUCKET


def get_data_bucket() -> TokenBucketRateLimiter:
    global _DATA_BUCKET
    if _DATA_BUCKET is None:
        # Data API is polled per-wallet; budget must scale with target count.
        _DATA_BUCKET = TokenBucketRateLimiter(
            capacity=30, refill_per_second=30.0 / 60.0
        )
    return _DATA_BUCKET


def reset_buckets() -> None:
    """Test hook: drop the module-level singletons."""
    global _GAMMA_BUCKET, _DATA_BUCKET
    _GAMMA_BUCKET = None
    _DATA_BUCKET = None


# Type alias for the engine-side 429 counter hook.
RateLimitObserver = Callable[[str, float], Awaitable[None]]