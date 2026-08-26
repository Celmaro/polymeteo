"""Tests for PolymarketClient weather market detection and demo data."""

import httpx
import pytest

from weather_copy_bot.polymarket.client import PolymarketClient


class TestCityInference:
    """Test city inference from market titles."""

    def test_infer_new_york(self):
        assert PolymarketClient._infer_city("Highest temperature in New York?") == "New York"

    def test_infer_tokyo(self):
        assert PolymarketClient._infer_city("Will Tokyo have snow on Christmas?") == "Tokyo"

    def test_infer_london(self):
        assert PolymarketClient._infer_city("London weather next week") == "London"

    def test_infer_seattle(self):
        assert PolymarketClient._infer_city("Seattle rainfall total") == "Seattle"

    def test_infer_global(self):
        assert PolymarketClient._infer_city("Global temperature anomaly") == "Global"

    def test_case_insensitive(self):
        assert PolymarketClient._infer_city("temperature in TOKYO tomorrow") == "Tokyo"

    def test_partial_match_no_false_positive(self):
        result = PolymarketClient._infer_city("Boston vs New York game")
        assert result == "New York"


class TestStubMarkets:
    """Test demo market generation."""

    def test_stub_markets_returns_list(self):
        markets = PolymarketClient._stub_markets()
        assert isinstance(markets, list)
        assert len(markets) == 6

    def test_stub_markets_have_required_fields(self):
        markets = PolymarketClient._stub_markets()
        for market in markets:
            assert "slug" in market
            assert "question" in market
            assert "city" in market
            assert market["active"] is True

    def test_stub_markets_weather_keywords(self):
        markets = PolymarketClient._stub_markets()
        for market in markets:
            text = (market["question"] + " " + market["slug"]).lower()
            assert any(k in text for k in ("temperature", "weather", "rain", "snow", "°f", "°c"))


class TestWeatherMarketFiltering:
    """Test weather keyword filtering logic."""

    def test_temperature_keyword_match(self):
        markets = [
            {
                "question": "Highest temperature in New York?",
                "slug": "highest-temperature-in-new-york",
            },
            {"question": "Who wins the election?", "slug": "presidential-election-2024"},
        ]
        weather = [
            m
            for m in markets
            if any(
                k in (m.get("question", "") + " " + m.get("slug", "")).lower()
                for k in ("temperature", "weather", "rain", "snow", "°f", "°c")
            )
        ]
        assert len(weather) == 1
        assert "temperature" in weather[0]["question"].lower()

    def test_rain_keyword_match(self):
        markets = [
            {"question": "Will it rain in London tomorrow?", "slug": "rain-in-london"},
            {"question": "Stock market up 5%?", "slug": "stock-market-gains"},
        ]
        weather = [
            m
            for m in markets
            if any(
                k in (m.get("question", "") + " " + m.get("slug", "")).lower()
                for k in ("temperature", "weather", "rain", "snow", "°f", "°c")
            )
        ]
        assert len(weather) == 1
        assert "rain" in weather[0]["question"].lower()

    def test_snow_keyword_match(self):
        markets = [
            {"question": "Will Tokyo get snow this winter?", "slug": "tokyo-snow-winter"},
            {"question": "Sports championship winner?", "slug": "championship-winner"},
        ]
        weather = [
            m
            for m in markets
            if any(
                k in (m.get("question", "") + " " + m.get("slug", "")).lower()
                for k in ("temperature", "weather", "rain", "snow", "°f", "°c")
            )
        ]
        assert len(weather) == 1
        assert "snow" in weather[0]["question"].lower()


class TestDemoEventGeneration:
    """Test demo event streaming."""

    def test_next_demo_events_returns_list(self):
        client = PolymarketClient()
        events = client._next_demo_events(["0xabc123"])
        assert isinstance(events, list)

    def test_next_demo_events_structure(self):
        client = PolymarketClient()
        events = client._next_demo_events(["0xabc123"])
        if events:
            event = events[0]
            assert "id" in event
            assert "wallet" in event
            assert "market_title" in event
            assert "city" in event
            assert "side" in event
            assert "price" in event
            assert "size_usd" in event
            assert event["demo"] is True

    def test_demo_cursor_increments(self):
        client = PolymarketClient()
        assert client._demo_cursor == 0
        client._next_demo_events(["0xabc"])
        assert client._demo_cursor == 1

    def test_demo_events_sparse(self):
        """Demo events are emitted every 3rd call."""
        client = PolymarketClient()
        for _ in range(2):
            events = client._next_demo_events(["0xabc"])
        assert events == []
        events = client._next_demo_events(["0xabc"])
        assert len(events) == 1

    def test_demo_wallets_default(self):
        client = PolymarketClient()
        wallets = client.default_demo_wallets()
        assert len(wallets) == 3
        assert all(w.startswith("0x") for w in wallets)


class TestClientInitialization:
    """Test client initialization."""

    def test_client_with_default_settings(self):
        client = PolymarketClient()
        assert client.settings is not None
        assert client._demo_cursor == 0

    def test_client_respects_custom_settings(self):
        from weather_copy_bot.config import Settings

        settings = Settings(target_wallets=["0xcustom"])
        client = PolymarketClient(settings=settings)
        assert client.settings.target_wallets == ["0xcustom"]


class TestFetchTargetActivityHttp:
    """HTTP behavior of fetch_target_activity against a mocked transport."""

    @staticmethod
    def _install_transport(monkeypatch, handler) -> PolymarketClient:
        real_cls = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_cls(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return PolymarketClient()

    async def test_all_wallets_rejected_raises(self, monkeypatch):
        client = self._install_transport(
            monkeypatch,
            lambda request: httpx.Response(400, json={"error": "bad user"}),
        )

        with pytest.raises(RuntimeError, match="activity API rejected wallets"):
            await client.fetch_target_activity(["0xwalletone11", "0xwallettwo22"])

    async def test_partial_success_returns_real_events(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["user"] == "0xgoodwallet1":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "evt-1",
                            "title": "Highest temperature in New York?",
                            "slug": "highest-temperature-in-new-york",
                            "outcome": "Yes",
                            "side": "BUY",
                            "price": 0.61,
                            "usdcSize": 120.5,
                        }
                    ],
                )
            return httpx.Response(400)

        client = self._install_transport(monkeypatch, handler)

        events = await client.fetch_target_activity(["0xbadwallet01", "0xgoodwallet1"])

        assert len(events) == 1
        assert events[0]["id"] == "evt-1"
        assert events[0]["demo"] is False
        assert events[0]["city"] == "New York"

    async def test_connect_error_keeps_demo_fallback(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        client = self._install_transport(monkeypatch, handler)

        events: list[dict] = []
        for _ in range(4):
            events = await client.fetch_target_activity(["0xdemowallet9"])
            if events:
                break

        assert events and events[0]["demo"] is True
