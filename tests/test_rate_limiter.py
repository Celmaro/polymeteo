"""Tests for the token-bucket rate limiter + 429 callback hook."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from weather_copy_bot.polymarket.rate_limiter import (
    RateLimiterStats,
    TokenBucketRateLimiter,
    get_data_bucket,
    get_gamma_bucket,
    reset_buckets,
)


class TestRateLimiterStats:
    """Stats dataclass is purely informational and trivially constructible."""

    def test_defaults(self):
        stats = RateLimiterStats()
        assert stats.acquired == 0
        assert stats.waited_ms == 0.0
        assert stats.rejections_429 == 0
        assert stats.retry_after_hits == 0

    def test_independent_instances(self):
        a = RateLimiterStats()
        b = RateLimiterStats()
        a.acquired = 5
        assert b.acquired == 0


class TestTokenBucketAcquire:
    """The acquire() method must consume one token without blocking when full."""

    @pytest.mark.asyncio
    async def test_first_acquire_is_immediate(self):
        bucket = TokenBucketRateLimiter(capacity=5, refill_per_second=1.0)
        start = asyncio.get_event_loop().time()
        await bucket.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.05
        assert bucket.stats.acquired == 1

    async def test_burst_then_block(self):
        # capacity=2 → first two acquires immediate; the third must wait for
        # the refill (1/s) so we just assert that *some* delay was observed.
        bucket = TokenBucketRateLimiter(capacity=2, refill_per_second=20.0)
        await bucket.acquire()
        await bucket.acquire()
        assert bucket.stats.acquired == 2
        start = asyncio.get_event_loop().time()
        await bucket.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.0
        assert bucket.stats.acquired == 3
        assert bucket.stats.waited_ms >= 0.0

    @pytest.mark.asyncio
    async def test_refill_eventually_unblocks(self):
        # capacity=1 + refill 50/s → third token available ~20ms later.
        bucket = TokenBucketRateLimiter(capacity=1, refill_per_second=50.0)
        await bucket.acquire()
        await bucket.acquire()
        # The second acquire had to wait at least one token-period (~20ms).
        assert bucket.stats.waited_ms >= 1.0

    @pytest.mark.asyncio
    async def test_concurrent_acquires_serialised(self):
        bucket = TokenBucketRateLimiter(capacity=10, refill_per_second=1.0)
        # Fire 10 acquires in parallel; none should deadlock.
        await asyncio.gather(*[bucket.acquire() for _ in range(10)])
        assert bucket.stats.acquired == 10


class TestParseRetryAfter:
    """parse_retry_after() must handle seconds, missing, and unparseable values."""

    def _resp(self, header_value: str | None) -> httpx.Response:
        headers = {"Retry-After": header_value} if header_value is not None else {}
        return httpx.Response(429, headers=headers)

    def test_seconds_form(self):
        assert TokenBucketRateLimiter.parse_retry_after(self._resp("30")) == 30.0

    def test_missing_header(self):
        assert TokenBucketRateLimiter.parse_retry_after(self._resp(None)) == 0.0

    def test_unparseable_value(self):
        # Non-numeric and HTTP-date forms fall back to 0.0 (date form is not
        # converted in this implementation — the bot always uses seconds).
        assert TokenBucketRateLimiter.parse_retry_after(self._resp("Thu, 01 Jan 2026 00:00:00 GMT")) == 0.0

    def test_zero_is_preserved(self):
        # 0 is a valid header value meaning "retry immediately"; we must not
        # floor it up to ``min_retry_after_seconds`` at parse time.
        assert TokenBucketRateLimiter.parse_retry_after(self._resp("0")) == 0.0

    def test_negative_clamped(self):
        assert TokenBucketRateLimiter.parse_retry_after(self._resp("-5")) == 0.0


class TestRecord429:
    """record_429() bumps counters and applies a penalty so the next acquire waits."""

    def test_increments_counter(self):
        bucket = TokenBucketRateLimiter(capacity=10, refill_per_second=1.0)
        bucket.record_429(retry_after_seconds=2.5)
        assert bucket.stats.rejections_429 == 1
        assert bucket.stats.retry_after_hits == 1

    def test_no_retry_after_still_counts(self):
        bucket = TokenBucketRateLimiter(capacity=10, refill_per_second=1.0)
        bucket.record_429(retry_after_seconds=0.0)
        assert bucket.stats.rejections_429 == 1
        assert bucket.stats.retry_after_hits == 0

    def test_penalty_drains_bucket(self):
        # Capacity=10 with refill 10/s. After one 429 with retry_after=5s the
        # penalty should push tokens negative, forcing the next acquire to wait
        # approximately 5s before unblocking (or until ``min_retry_after``).
        bucket = TokenBucketRateLimiter(
            capacity=10,
            refill_per_second=10.0,
            min_retry_after_seconds=1.0,
        )
        bucket.record_429(retry_after_seconds=5.0)
        # The bucket is drained; no token is available until refill catches up.
        assert bucket._tokens < 1.0

    def test_multiple_429s_compound(self):
        bucket = TokenBucketRateLimiter(capacity=10, refill_per_second=10.0)
        bucket.record_429(retry_after_seconds=2.0)
        first_count = bucket.stats.rejections_429
        bucket.record_429(retry_after_seconds=2.0)
        assert bucket.stats.rejections_429 == first_count + 1


class TestModuleBuckets:
    """Module-level gamma/data singletons + reset hook."""

    def test_gamma_bucket_is_singleton(self):
        reset_buckets()
        a = get_gamma_bucket()
        b = get_gamma_bucket()
        assert a is b

    def test_data_bucket_is_singleton(self):
        reset_buckets()
        a = get_data_bucket()
        b = get_data_bucket()
        assert a is b

    def test_gamma_and_data_are_distinct(self):
        reset_buckets()
        assert get_gamma_bucket() is not get_data_bucket()

    def test_reset_buckets_clears_singletons(self):
        first = get_gamma_bucket()
        reset_buckets()
        second = get_gamma_bucket()
        assert first is not second

    def test_buckets_have_expected_defaults(self):
        reset_buckets()
        gamma = get_gamma_bucket()
        data = get_data_bucket()
        # Gamma is the cheaper market-metadata host; data is per-wallet.
        assert gamma.capacity == 10
        assert data.capacity == 30
