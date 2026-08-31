"""Tests for automatic wallet discovery and the merged target provider."""

from __future__ import annotations

import time

import httpx
import pytest
from polymarket_apis.clients.data_client import PolymarketDataClient
from polymarket_apis.clients.gamma_client import PolymarketGammaClient

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
        "min_candidate_trades": 2,
        "min_candidate_volume_usd": 100.0,
    }
    values.update(overrides)
    return Settings(**values)


def _trade_item(wallet: str, shares: float, price: float, ts: int, side: str = "BUY") -> dict:
    """Data-api /trades row: USD notional is derived as size * price.

    Production code calls ``item.model_dump()`` which emits snake_case keys,
    so this fixture uses ``proxy_wallet`` (not ``proxyWallet``) to mirror the
    dumped shape and avoid Pydantic validation in the test transport.
    """
    return {
        "proxy_wallet": wallet,
        "side": side,
        "size": shares,
        "price": price,
        "timestamp": ts,
        "slug": "highest-temperature-in-new-york",
    }


def _activity_event(wallet: str, size: float, ts: float, slug: str = "highest-temperature-in-new-york") -> dict:
    return {
        "wallet": wallet,
        "timestamp": ts,
        "size_usd": size,
        "market_slug": slug,
        "side": "BUY",
    }


def _search_events() -> dict:
    """Gamma public-search payload (post-model_dump snake_case keys).

    ``PolymarketGammaClient.search`` returns ``Event`` models; the production
    code calls ``event.model_dump()`` which emits snake_case keys, so the
    resolver reads ``condition_id`` (not ``conditionId``). The fixtures
    therefore mirror the dumped shape rather than the raw API response.
    """
    return {
        "events": [
            {
                "slug": "highest-temperature-in-new-york",
                "title": "Highest temperature in New York?",
                "markets": [
                    {
                        "condition_id": "0xcond1",
                        "slug": "highest-temperature-in-new-york",
                        "active": True,
                        "closed": False,
                    },
                    {
                        # Closed -> resolver must skip it.
                        "condition_id": "0xclosed",
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
        """Patch PolymarketGammaClient.search/get_markets and
        PolymarketDataClient.get_trades to invoke ``handler`` directly,
        bypassing the polymarket-apis Pydantic validation that would otherwise
        reject the lightweight test fixtures.

        Each fake function constructs an ``httpx.Request`` that mirrors the
        URL + params the production code would emit, hands it to the test
        handler, and then shapes the JSON response into duck-typed objects
        (``_FakeEvent`` / ``_FakeTrade``) that expose the same
        ``model_dump()`` contract Pydantic models use, so the production
        resolver code reads them transparently.
        """

        class _FakeEvent:
            def __init__(self, data: dict) -> None:
                self._data = data

            def model_dump(self) -> dict:
                return self._data

        class _FakeSearchResult:
            def __init__(self, data: dict) -> None:
                self.events = [
                    _FakeEvent(e) for e in (data.get("events") or [])
                ]

        class _FakeMarket:
            def __init__(self, data: dict) -> None:
                self._data = data
                # Production code mixes ``getattr(m, "question", ...)`` and
                # ``m.model_dump().get("condition_id")``; expose the raw
                # camelCase attributes so duck-typed reads succeed without
                # Pydantic validation.
                for key, value in data.items():
                    setattr(self, key, value)

            def model_dump(self) -> dict:
                return self._data

        class _FakeTrade:
            def __init__(self, data: dict) -> None:
                self._data = data

            def model_dump(self) -> dict:
                return self._data

        def _fake_search(self, query, **kwargs):
            params: dict[str, object] = {"q": query}
            if kwargs.get("status"):
                params["events_status"] = kwargs["status"]
            if kwargs.get("limit_per_type"):
                params["limit_per_type"] = kwargs["limit_per_type"]
            request = httpx.Request(
                "GET",
                self._build_url("/public-search"),
                params=params,
            )
            response = handler(request)
            if response._request is None:
                response._request = request
            response.raise_for_status()
            return _FakeSearchResult(response.json())

        def _fake_get_markets(self, **kwargs):
            request = httpx.Request(
                "GET",
                self._build_url("/markets"),
                params=kwargs,
            )
            response = handler(request)
            if response._request is None:
                response._request = request
            response.raise_for_status()
            return [_FakeMarket(m) for m in (response.json() or [])]

        def _fake_get_trades(
            self,
            limit=100,
            offset=0,
            taker_only=True,
            filter_type=None,
            filter_amount=None,
            condition_id=None,
            event_id=None,
            user=None,
            side=None,
            **_,
        ):
            params: dict[str, object] = {
                "limit": min(limit, 500),
                "offset": offset,
                "takerOnly": taker_only,
            }
            if isinstance(condition_id, str):
                params["market"] = condition_id
            elif isinstance(condition_id, list):
                params["market"] = ",".join(condition_id)
            if isinstance(event_id, str):
                params["eventId"] = event_id
            elif isinstance(event_id, int):
                params["eventId"] = str(event_id)
            if user:
                params["user"] = user
            if side:
                params["side"] = side
            request = httpx.Request(
                "GET",
                self._build_url("/trades"),
                params=params,
            )
            response = handler(request)
            if response._request is None:
                response._request = request
            response.raise_for_status()
            return [_FakeTrade(t) for t in (response.json() or [])]

        monkeypatch.setattr(PolymarketGammaClient, "search", _fake_search)
        monkeypatch.setattr(PolymarketGammaClient, "get_markets", _fake_get_markets)
        monkeypatch.setattr(PolymarketDataClient, "get_trades", _fake_get_trades)
        return PolymarketClient()

    async def test_search_supplies_condition_ids_and_parses_observations(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                assert request.url.params["events_status"] == "active"
                return httpx.Response(200, json=_search_events())
            # Only the live market reaches the public trades scan.
            assert request.url.path.endswith("/trades")
            assert request.url.params["market"] == "0xcond1"
            assert "user" not in request.url.params
            return httpx.Response(
                200,
                json=[
                    _trade_item("0xNewWhale01", 500.0, 0.5, 1_700_000_000),
                    _trade_item("0xDustWallet01", 2.0, 0.5, 1_700_000_001),
                    # Missing proxyWallet -> skipped.
                    {"side": "BUY", "size": 100.0, "price": 0.5},
                ],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets(max_markets=3, trades_per_market=50)
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
                json=[_trade_item("0xResilient01", 250.0, 1.0, 1_700_000_003)],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets()
        assert [o["wallet"] for o in obs] == ["0xresilient01"]

    async def test_search_tolerates_null_events_payload(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                if request.url.params["q"] == "\u00b0f":
                    # Gamma answers degree-sign queries with {"events": null}.
                    return httpx.Response(200, json={"events": None})
                return httpx.Response(200, json=_search_events())
            return httpx.Response(
                200,
                json=[_trade_item("0xNullTolerant01", 300.0, 0.5, 1_700_000_004)],
            )

        client = self._install_transport(monkeypatch, handler)
        obs = await client.discover_weather_wallets()
        assert [o["wallet"] for o in obs] == ["0xnulltolerant01"]

    async def test_falls_back_to_windowed_scan_when_search_is_empty(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/public-search"):
                return httpx.Response(200, json={"events": []})
            if request.url.path.endswith("/markets"):
                return httpx.Response(200, json=GAMMA_MARKETS)
            return httpx.Response(
                200,
                json=[_trade_item("0xFallback01", 240.0, 0.5, 1_700_000_002)],
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
        with pytest.raises(RuntimeError, match="discovery trades feed rejected"):
            await client.discover_weather_wallets()

    async def test_offline_gamma_yields_empty_result(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        client = self._install_transport(monkeypatch, handler)
        # Gamma falls back to condition-less stubs, so no market scan happens.
        assert await client.discover_weather_wallets() == []


class TestWalletDiscoveryRegistry:
    @staticmethod
    def _events(wallet: str, n: int, size: float, slug: str = "highest-temperature-in-new-york") -> list[dict]:
        # Recent timestamps: promotion now enforces a candidate TTL, so
        # historical (epoch-1970) events would age out of the candidate pool.
        base = time.time()
        return [_activity_event(wallet, size, base - i, slug) for i in range(n)]

    def test_observe_aggregates_trades_volume_and_markets(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(self._events("0xAAA", n=3, size=100.0))
        disc.observe(
            [_activity_event("0xAAA", 50.0, time.time(), slug="will-it-rain-in-london")]
        )
        qualified = disc.candidates()
        assert len(qualified) == 1
        record = qualified[0]
        assert record.address == "0xaaa"
        assert record.trades_seen == 4
        assert record.volume_usd == 350.0
        assert record.markets == {"highest-temperature-in-new-york", "will-it-rain-in-london"}

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

    def test_sorting_prefers_higher_volume(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                *self._events("0xlow", n=3, size=110.0),
                *self._events("0xhigh", n=3, size=400.0),
            ]
        )
        assert disc.promoted_wallets() == ["0xhigh", "0xlow"]
        assert len(disc.candidates()) == 2

    def test_explicit_max_targets_caps_promotion(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                *self._events("0xlow", n=3, size=110.0),
                *self._events("0xhigh", n=3, size=400.0),
            ]
        )
        assert disc.promoted_wallets(max_targets=1) == ["0xhigh"]

    def test_uncapped_default_promotes_every_qualified_wallet(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        disc.observe(
            [
                *self._events("0xlow", n=3, size=110.0),
                *self._events("0xmid", n=3, size=220.0),
                *self._events("0xhigh", n=3, size=400.0),
            ]
        )
        promoted = disc.promoted_wallets()
        assert promoted == ["0xhigh", "0xmid", "0xlow"]
        assert len(promoted) == len(disc.candidates())

    def test_settings_has_no_rotation_cap(self):
        # The discovered-wallet rotation is intentionally uncapped; registry size
        # and TTL are the only growth bounds. No MAX_DISCOVERED_TARGETS field
        # should exist.
        assert not hasattr(Settings(), "max_discovered_targets")

    def test_max_trades_per_day_gate_rejects_spammer(self):
        settings = _discovery_settings(max_candidate_trades_per_day=3)
        disc = WalletDiscovery(settings=settings)
        now = time.time()
        disc.observe(
            [_activity_event("0xspam", 200.0, now - i * 60) for i in range(5)]
        )
        assert disc.promoted_wallets() == []

    def test_max_trades_per_day_gate_passes_within_budget(self):
        settings = _discovery_settings(max_candidate_trades_per_day=3)
        disc = WalletDiscovery(settings=settings)
        now = time.time()
        disc.observe(
            [_activity_event("0xsteady", 200.0, now - i * 60) for i in range(3)]
        )
        assert disc.promoted_wallets() == ["0xsteady"]

    def test_non_weather_dispersion_gate_rejects_generalist(self):
        settings = _discovery_settings(
            max_non_weather_markets=1, min_weather_share=0.0
        )
        disc = WalletDiscovery(settings=settings)
        now = time.time()
        disc.observe(
            [
                _activity_event("0xg", 300.0, now - 4 * 60),
                _activity_event("0xg", 300.0, now - 3 * 60),
                _activity_event("0xg", 300.0, now - 2 * 60),
                _activity_event("0xg", 300.0, now - 60, slug="us-presidential-election-2024"),
                _activity_event("0xg", 300.0, now, slug="btc-will-close-above-100k"),
            ]
        )
        assert disc.promoted_wallets() == []

    def test_non_weather_dispersion_gate_passes_when_specialized(self):
        settings = _discovery_settings(
            max_non_weather_markets=1, min_weather_share=0.0
        )
        disc = WalletDiscovery(settings=settings)
        now = time.time()
        disc.observe(
            [
                _activity_event("0xs", 300.0, now - 2 * 60),
                _activity_event("0xs", 300.0, now - 60, slug="us-presidential-election-2024"),
                _activity_event("0xs", 300.0, now, slug="us-presidential-election-2024"),
            ]
        )
        assert disc.promoted_wallets() == ["0xs"]

    def test_min_weather_share_default_rejects_generalist(self):
        # The default min_weather_share is 0.8: a wallet that is only 50% weather
        # must be rejected even though it clears the other activity gates.
        settings = _discovery_settings(min_candidate_trades=2)
        disc = WalletDiscovery(settings=settings)
        now = time.time()
        disc.observe(
            [
                _activity_event("0xmixed", 300.0, now - 3 * 60),
                _activity_event("0xmixed", 300.0, now - 2 * 60, slug="us-presidential-election-2024"),
            ]
        )
        assert disc.promoted_wallets() == []

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
        now = time.time()
        disc.observe(
            [
                _activity_event("0xDISC1", 500.0, now - 1.0),
                _activity_event("0xDISC1", 500.0, now),
            ]
        )
        provider = MergedTargetProvider(["0xstatic"], discovery=disc)
        assert provider.current() == ["0xstatic", "0xdisc1"]

    def test_case_insensitive_dedup_between_sources(self):
        disc = WalletDiscovery(settings=_discovery_settings())
        now = time.time()
        disc.observe(
            [
                _activity_event("0xSTATIC", 500.0, now - 1.0),
                _activity_event("0xSTATIC", 500.0, now),
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

    async def fetch_target_activity(self, wallets, market_filter, min_size_usd=0.0):
        self.calls.append(
            {"wallets": list(wallets), "market_filter": market_filter, "min_size_usd": min_size_usd}
        )
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
        engine = CopyEngine(settings=_discovery_settings(), client=stub, target_provider=provider)
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
        base = time.time()

        class StubDiscoveryClient(PolymarketClient):
            async def discover_weather_wallets(
                self, max_markets: int = 5, trades_per_market: int = 50
            ):
                return [
                    _activity_event("0xloop", 500.0, base - 1.0),
                    _activity_event("0xloop", 500.0, base),
                ]

        settings = _discovery_settings(discovery_interval_s=0.01)
        disc = WalletDiscovery(settings=settings, client=StubDiscoveryClient(settings))
        await disc.run(duration_sec=0)
        assert disc.stats["discovery_cycles"] == 1
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
        assert disc.stats["discovery_cycles"] == 0
        assert disc.stats["consecutive_failures"] >= 1
        assert disc.stats["last_error"] is not None
        assert disc.stats["discovery_last_error_at"] is not None
        assert "RuntimeError" in disc.stats["last_error"]
        assert "unavailable" in disc.stats["last_error"]
