"""Tests for automatic wallet discovery and the merged target provider."""

from __future__ import annotations

import httpx
import pytest

from weather_copy_bot.config import Settings
from weather_copy_bot.engine.copy_engine import CopyEngine
from weather_copy_bot.engine.wallet_discovery import (
    MergedTargetProvider,
    WalletDiscovery,
)
from weather_copy_bot.polymarket.client import PolymarketClient

DEMO_WALLET = "0x7a21c4e8b9f0d3a6e1c58294f0ab73d6e8c91f22"

GAMMA_MARKETS = [
    {
        "conditionId": "0xcond1",
        "slug": "highest-temperature-in-new-york",
        "question": "Highest temperature in New York?",
        "active": True,
    },
    {
        # No conditionId -> must be skipped by the market resolver.
        "slug": "will-it-rain-in-london",
        "question": "Will it rain in London?",
        "active": True,
    },
]


def _discovery_settings(**overrides) -> Settings:
    values: dict = {
        "wallet_discovery_enabled": True,
        "target_wallets": [],
        "max_discovered_targets": 2,
        "min_candidate_trades": 2,
        "min_candidate_volume_usd": 100.0,
    }
    values.update(overrides)
    return Settings(**values)


def _activity_item(wallet: str, size: float, ts: int, side: str = "BUY") -> dict:
    return {
        "proxyWallet": wallet,
        "side": side,
        "usdcSize": size,
        "timestamp": ts,
        "slug": "highest-temperature-in-new-york",
    }


def _activity_event(wallet: str, size: float, ts: float, slug: str = "m1") -> dict:
    return {
        "wallet": wallet,
        "timestamp": ts,
        "size_usd": size,
        "market_slug": slug,
        "side": "BUY",
    }


def _search_events() -> dict:
    """Gamma public-search payload with one live and one closed weather market."""
    return {
        "events": [
            {
                "slug": "highest-temperature-in-new-york",
                "title": "Highest temperature in New York?",
                "markets": [
                    {
                        "conditionId": "0xcond1",
                        "slug": "highest-temperature-in-new-york",
                        "active": True,
                        "closed": False,
                    },
                    {
                        # Closed -> resolver must skip it.
                        "conditionId": "0xclosed",
                        "slug": "resolved-temperature-market",
                        "active": False,
                        "closed": True,
                    },
                ],
            }
        ]
    }


class TestDiscoverWeatherWalletsHttp:
    """HTTP behavior of discover_weather_wallets against a mocked transport."""

    @staticmethod
    def _install_transport(monkeypatch, handler) -> PolymarketClient:
        real_cls = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_cls(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return PolymarketClient()

    async def test_search_supplies_condition_ids_and_parses_observations(
        self, monkeypatch
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                assert request.url.params["events_status"] == "active"
                return httpx.Response(200, json=_search_events())
            # Only the live market reaches the activity scan.
            assert request.url.params["market"] == "0xcond1"
            assert "user" not in request.url.params
            return httpx.Response(
                200,
                json=[
                    _activity_item("0xNewWhale01", 250.0, 1_700_000_000),
                    _activity_item("0xDustWallet01", 1.0, 1_700_000_001),
                    # Missing proxyWallet -> skipped.
                    {"side": "BUY", "usdcSize": 50.0},
                ],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets(
            max_markets=3, trades_per_market=50
        )
        assert [o["wallet"] for o in obs] == ["0xnewwhale01", "0xdustwallet01"]
        assert obs[0]["size_usd"] == 250.0
        assert obs[0]["timestamp"] == 1_700_000_000.0

    async def test_search_survives_invalid_json_from_one_keyword(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                keyword = request.url.params["q"]
                if keyword == "temperature":
                    # Production fault shape: 200 with an HTML challenge body.
                    return httpx.Response(200, text="<html>request blocked</html>")
                if keyword == "weather":
                    return httpx.Response(200, json=_search_events())
                return httpx.Response(200, json={"events": []})
            assert request.url.params["market"] == "0xcond1"
            return httpx.Response(
                200,
                json=[_activity_item("0xResilient01", 250.0, 1_700_000_003)],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets()
        assert [o["wallet"] for o in obs] == ["0xresilient01"]

    async def test_falls_back_to_windowed_scan_when_search_is_empty(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                return httpx.Response(200, json={"events": []})
            if request.url.path.endswith("/markets"):
                return httpx.Response(200, json=GAMMA_MARKETS)
            return httpx.Response(
                200,
                json=[_activity_item("0xFallback01", 120.0, 1_700_000_002)],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets()
        assert [o["wallet"] for o in obs] == ["0xfallback01"]

    async def test_all_markets_rejected_raises(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                return httpx.Response(200, json=_search_events())
            return httpx.Response(403)

        client = self._install_transport(monkeypatch, handler)
        with pytest.raises(RuntimeError, match="discovery activity feed rejected"):
            await client.discover_weather_wallets()

    async def test_offline_gamma_yields_empty_result(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        client = self._install_transport(monkeypatch, handler)
        # Gamma falls back to condition-less stubs, so no market scan happens.
        assert await client.discover_weather_wallets() == []


class TestWalletDiscoveryRegistry:
    @staticmethod
    def _events(wallet: str, n: int, size: float, slug: str = "m1") -> list[dict]:
        return [_activity_event(wallet, size, 1000.0 + i, slug) for i in range(n)]

    def test_observe_aggregates_trades_volume_and_markets(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(self._events("0xAAA", n=3, size=100.0))
        disc.observe([_activity_event("0xAAA", 50.0, 2000.0, slug="m2")])
        qualified = disc.candidates()
        assert len(qualified) == 1
        record = qualified[0]
        assert record.address == "0xaaa"
        assert record.trades_seen == 4
        assert record.volume_usd == 350.0
        assert record.markets == {"m1", "m2"}

    def test_promotion_requires_both_thresholds(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                *self._events("0xbig", n=5, size=500.0),
                *self._events("0xsmall", n=3, size=10.0),
                *self._events("0xsparse", n=1, size=900.0),
            ]
        )
        assert disc.promoted_wallets() == ["0xbig"]

    def test_sorting_prefers_higher_volume_then_caps_targets(self):
        settings = _discovery_settings(max_discovered_targets=1)
        disc = WalletDiscovery(settings=settings)
        disc.observe(
            [
                *self._events("0xlow", n=3, size=110.0),
                *self._events("0xhigh", n=3, size=400.0),
            ]
        )
        assert disc.promoted_wallets() == ["0xhigh"]
        assert len(disc.candidates()) == 2

    def test_static_and_demo_wallets_never_promoted(self):
        settings = _discovery_settings(target_wallets=["0xStatic"])
        disc = WalletDiscovery(settings=settings)
        disc.observe(
            [
                *self._events("0xstatic", n=9, size=900.0),
                *self._events(DEMO_WALLET, n=9, size=900.0),
            ]
        )
        assert disc.promoted_wallets() == []
        assert disc.candidates() == []


class TestMergedTargetProvider:
    def test_static_only_when_discovery_absent(self):
        provider = MergedTargetProvider(["0xS1", " 0xS2 "])
        assert provider.current() == ["0xS1", "0xS2"]

    def test_merges_discovered_after_static(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                _activity_event("0xDISC1", 500.0, 1.0),
                _activity_event("0xDISC1", 500.0, 2.0),
            ]
        )
        provider = MergedTargetProvider(["0xstatic"], discovery=disc)
        assert provider.current() == ["0xstatic", "0xdisc1"]

    def test_case_insensitive_dedup_between_sources(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                _activity_event("0xSTATIC", 500.0, 1.0),
                _activity_event("0xSTATIC", 500.0, 2.0),
            ]
        )
        provider = MergedTargetProvider(["0xStatic"], discovery=disc)
        assert provider.current() == ["0xStatic"]


class _StubClient:
    def __init__(self, events=None):
        self.events = events or []
        self.calls: list[dict] = []

    def default_demo_wallets(self) -> list[str]:
        return ["0xdemo1"]

    async def fetch_target_activity(self, wallets, market_filter):
        self.calls.append({"wallets": list(wallets), "market_filter": market_filter})
        return self.events


def _real_event(wallet: str) -> dict:
    return {
        "id": f"evt-{wallet}",
        "wallet": wallet,
        "timestamp": "2026-08-26T00:00:00+00:00",
        "market_slug": "highest-temperature-in-new-york",
        "market_title": "Highest temperature in New York?",
        "city": "New York",
        "outcome": "Yes",
        "side": "BUY",
        "price": 0.5,
        "size_usd": 10.0,
        "token_id": None,
        "demo": False,
    }


class TestCopyEngineTargetProviderSeam:
    async def test_provider_wallets_drive_polling(self):
        stub = _StubClient(events=[_real_event("0xprovider")])
        provider = MergedTargetProvider(["0xstatic"])
        engine = CopyEngine(
            settings=_discovery_settings(), client=stub, target_provider=provider
        )
        await engine.poll_once()
        assert stub.calls[0]["wallets"] == ["0xstatic"]

    async def test_default_engine_keeps_legacy_resolution(self):
        stub = _StubClient()
        settings = _discovery_settings(target_wallets=["0xlegacy"])
        engine = CopyEngine(settings=settings, client=stub)
        await engine.poll_once()
        assert stub.calls[0]["wallets"] == ["0xlegacy"]

    async def test_empty_provider_resolution_skips_fetch_without_demo_leak(self):
        stub = _StubClient(events=[_real_event("0xdemo1")])
        engine = CopyEngine(
            settings=_discovery_settings(),
            client=stub,
            target_provider=MergedTargetProvider([]),
        )
        signals = await engine.poll_once()
        assert signals == []
        assert stub.calls == []
        assert engine.stats["last_heartbeat"] is not None


class TestWalletDiscoveryRun:
    async def test_single_cycle_observes_and_promotes(self):
        class StubDiscoveryClient(PolymarketClient):
            async def discover_weather_wallets(
                self, max_markets: int = 5, trades_per_market: int = 50
            ):
                return [
                    _activity_event("0xloop", 500.0, 1.0),
                    _activity_event("0xloop", 500.0, 2.0),
                ]

        settings = _discovery_settings(discovery_interval_s=0.01)
        disc = WalletDiscovery(
            settings=settings, client=StubDiscoveryClient(settings)
        )
        await disc.run(duration_sec=0)
        assert disc.stats["cycles"] == 1
        assert disc.promoted_wallets() == ["0xloop"]

    async def test_run_survives_persistent_failures_and_reports_stats(self):
        class ExplodingClient(PolymarketClient):
            async def discover_weather_wallets(
                self, max_markets: int = 5, trades_per_market: int = 50
            ):
                raise RuntimeError("search index unavailable")

        settings = _discovery_settings(discovery_interval_s=0.01)
        disc = WalletDiscovery(settings=settings, client=ExplodingClient(settings))
        await disc.run(duration_sec=0.05)
        assert disc._running is False
        assert disc.stats["cycles"] == 0
        assert disc.stats["consecutive_failures"] >= 1
        assert disc.stats["last_error"] is not None
        assert "RuntimeError" in disc.stats["last_error"]
        assert "unavailable" in disc.stats["last_error"]
