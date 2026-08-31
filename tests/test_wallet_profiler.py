"""Tests for the first-party P&L wallet profiler and its promotion gates."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from weather_copy_bot.config import Settings
from weather_copy_bot.engine.wallet_discovery import WalletDiscovery
from weather_copy_bot.engine.wallet_profiler import WalletProfiler


def _profiler_settings(**overrides) -> Settings:
    values: dict = {
        "profiler_enabled": True,
        "profiler_cache_ttl_s": 3600.0,
        "profiler_backoff_s": 600.0,
        "profiler_max_wallets_per_cycle": 20,
    }
    values.update(overrides)
    return Settings(**values)


def _closed_position(
    pk: float,
    total_bought: float,
    ts: str = "2026-08-01T00:00:00+00:00",
) -> dict:
    return {
        "proxy_wallet": "0xabc",
        "realized_pnl": pk,
        "total_bought": total_bought,
        "timestamp": ts,
        "title": "Highest temperature in New York?",
        "slug": "highest-temperature-in-new-york",
    }


class _FakeClient:
    """Duck-typed PolymarketClient exposing only the profiler fetch surface."""

    def __init__(
        self,
        closed: list[dict] | None = None,
        pnl: list[dict] | None = None,
        rank: int | None = None,
        profit: float = 0.0,
        value: float = 0.0,
        fail_closed: bool = False,
    ) -> None:
        self.closed = closed or []
        self.pnl = pnl or []
        self.rank = rank
        self.profit = profit
        self.value = value
        self.fail_closed = fail_closed
        self.calls: list[tuple[str, str]] = []

    def default_demo_wallets(self) -> list[str]:
        return ["0xdemo1"]

    async def fetch_closed_positions(self, address: str) -> list[dict]:
        self.calls.append(("closed", address))
        if self.fail_closed:
            raise RuntimeError("upstream closed-positions unavailable")
        return self.closed

    async def fetch_pnl_timeseries(self, address: str, period="all", frequency="1h"):
        self.calls.append(("pnl", address))
        return self.pnl

    async def fetch_weather_rank(self, address: str) -> int | None:
        self.calls.append(("rank", address))
        return self.rank

    async def fetch_user_profit(self, address: str) -> float:
        self.calls.append(("profit", address))
        return self.profit

    async def fetch_position_value(self, address: str) -> float:
        self.calls.append(("value", address))
        return self.value


class TestWalletProfilerMetrics:
    async def test_computes_realized_pnl_winrate_roi_and_age(self):
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=90)).isoformat()
        client = _FakeClient(
            closed=[
                _closed_position(20.0, 100.0, old_ts),
                _closed_position(-5.0, 50.0),
                _closed_position(10.0, 80.0),
                _closed_position(-2.0, 20.0),
            ]
        )
        profiler = WalletProfiler(settings=_profiler_settings(), client=client)
        profile = await profiler.profile_wallet("0xAbC")
        assert profile.address == "0xabc"
        assert profile.realized_pnl == 23.0
        assert profile.closed_positions == 4
        assert profile.wins == 2
        assert profile.win_rate == 0.5
        assert profile.invested == 250.0
        # 23 / 250 * 100
        assert profile.roi_pct == 9.2
        assert profile.age_days >= 89.0
        assert profile.data_available is True

    async def test_enriches_cv_rank_profit_and_value(self):
        client = _FakeClient(
            closed=[_closed_position(5.0, 50.0)],
            pnl=[{"value": 1.0, "timestamp": "2026-08-01T00:00:00Z"},
                 {"value": 3.0, "timestamp": "2026-08-01T01:00:00Z"}],
            rank=7,
            profit=123.0,
            value=456.0,
        )
        profiler = WalletProfiler(settings=_profiler_settings(), client=client)
        profile = await profiler.profile_wallet("0xabc")
        # CV of [1.0, 3.0] = std/mean*100 = 1.0/2.0*100 = 50.
        assert profile.weekly_cv == 50.0
        assert profile.weather_rank == 7
        assert profile.overall_profit == 123.0
        assert profile.position_value == 456.0
        # Every enrichment step made one call.
        names = [c[0] for c in client.calls]
        assert names == ["closed", "pnl", "rank", "profit", "value"]

    async def test_empty_closed_positions_still_available(self):
        client = _FakeClient(closed=[])
        profiler = WalletProfiler(settings=_profiler_settings(), client=client)
        profile = await profiler.profile_wallet("0xabc")
        assert profile.data_available is True
        assert profile.closed_positions == 0
        assert profile.win_rate == 0.0
        assert profile.roi_pct == 0.0

    async def test_failure_returns_placeholder_and_backs_off(self):
        client = _FakeClient(fail_closed=True)
        profiler = WalletProfiler(settings=_profiler_settings(), client=client)
        first = await profiler.profile_wallet("0xabc")
        assert first.data_available is False
        assert first.address == "0xabc"
        assert len(client.calls) == 1
        # Immediate re-fetch within backoff hits the cache path, no new call.
        second = await profiler.profile_wallet("0xabc")
        assert second.data_available is False
        assert len(client.calls) == 1

    async def test_cached_profile_within_ttl_skips_network(self):
        client = _FakeClient(closed=[_closed_position(5.0, 50.0)])
        profiler = WalletProfiler(settings=_profiler_settings(), client=client)
        await profiler.profile_wallet("0xabc")
        cached_calls = len(client.calls)
        await profiler.profile_wallet("0xabc")
        assert len(client.calls) == cached_calls

    async def test_profile_wallets_respects_budget(self):
        client = _FakeClient(closed=[_closed_position(5.0, 50.0)])
        profiler = WalletProfiler(
            settings=_profiler_settings(profiler_max_wallets_per_cycle=2),
            client=client,
        )
        profiles = await profiler.profile_wallets(
            ["0xaaa", "0xbbb", "0xccc", "0xddd"]
        )
        assert list(profiles.keys()) == ["0xaaa", "0xbbb"]
        # Only the two in-budget wallets were fetched (each costs 5 calls).
        assert {a for name, a in client.calls if name == "closed"} == {
            "0xaaa",
            "0xbbb",
        }
        assert len(client.calls) == 10


class TestWalletDiscoveryProfileGates:
    @staticmethod
    def _events(wallet: str, n: int, size: float) -> list[dict]:
        base = time.time()
        return [
            {
                "wallet": wallet,
                "timestamp": base - i,
                "size_usd": size,
                "market_slug": "highest-temperature-in-new-york",
            }
            for i in range(n)
        ]

    async def test_roi_gate_rejects_low_roi_wallet(self):
        client = _FakeClient(closed=[_closed_position(10.0, 500.0)])
        settings = _profiler_settings(
            min_candidate_trades=2,
            min_candidate_volume_usd=100.0,
            profiler_min_roi_pct=50.0,
        )
        disc = WalletDiscovery(settings=settings, client=client)
        disc.observe(self._events("0xwallet", n=3, size=300.0))
        await disc._profile_candidates()
        # ROI = 10/500 = 2% < 50% -> rejected.
        assert disc.candidates() == []

    async def test_roi_gate_passes_high_roi_wallet(self):
        client = _FakeClient(closed=[_closed_position(200.0, 500.0)])
        settings = _profiler_settings(
            min_candidate_trades=2,
            min_candidate_volume_usd=100.0,
            profiler_min_roi_pct=30.0,
        )
        disc = WalletDiscovery(settings=settings, client=client)
        disc.observe(self._events("0xwallet", n=3, size=300.0))
        await disc._profile_candidates()
        # ROI = 200/500 = 40% >= 30% -> promoted.
        assert [w.address for w in disc.candidates()] == ["0xwallet"]
        assert disc.candidates()[0].profile is not None
        assert disc.stats["profiled"] == 1

    async def test_roi_gate_requires_verified_profile(self):
        client = _FakeClient(fail_closed=True)
        settings = _profiler_settings(
            min_candidate_trades=2,
            min_candidate_volume_usd=100.0,
            profiler_min_roi_pct=10.0,
        )
        disc = WalletDiscovery(settings=settings, client=client)
        disc.observe(self._events("0xwallet", n=3, size=300.0))
        await disc._profile_candidates()
        # No verified profile -> even with gates armed, wallet is not promoted.
        assert disc.candidates() == []

    async def test_gates_disabled_promote_without_profile(self):
        client = _FakeClient(closed=[])
        settings = _profiler_settings(
            min_candidate_trades=2,
            min_candidate_volume_usd=100.0,
            profiler_min_roi_pct=0.0,
            profiler_min_win_rate=0.0,
            profiler_max_weekly_cv=0.0,
        )
        disc = WalletDiscovery(settings=settings, client=client)
        disc.observe(self._events("0xwallet", n=3, size=300.0))
        # No profile needed since all profiler gates are disabled.
        assert [w.address for w in disc.candidates()] == ["0xwallet"]
