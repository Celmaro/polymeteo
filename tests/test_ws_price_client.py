"""Tests for WebSocket price client."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from weather_copy_bot.ws_price_client import (
    ConnectionState,
    PriceFeedCallback,
    PriceUpdate,
    WebSocketConfig,
    WebSocketPriceClient,
)


class TestConnectionState:
    """Test ConnectionState enum."""

    def test_has_disconnected(self):
        """Should have disconnected state."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"

    def test_has_connected(self):
        """Should have connected state."""
        assert ConnectionState.CONNECTED.value == "connected"


class TestWebSocketConfig:
    """Test WebSocketConfig dataclass."""

    def test_default_url(self):
        """Should have default URL."""
        config = WebSocketConfig()
        assert "polymarket" in config.url

    def test_default_ping_interval(self):
        """Should have default ping interval."""
        config = WebSocketConfig()
        assert config.ping_interval == 15.0

    def test_custom_config(self):
        """Should accept custom config."""
        config = WebSocketConfig(
            url="wss://custom.example.com",
            ping_interval=30.0,
            max_reconnect_attempts=10,
        )
        assert config.url == "wss://custom.example.com"
        assert config.ping_interval == 30.0
        assert config.max_reconnect_attempts == 10


class TestPriceUpdate:
    """Test PriceUpdate dataclass."""

    def test_has_market_id(self):
        """Should have market_id field."""
        update = PriceUpdate(
            market_id="test123",
            yes_price=0.65,
            no_price=0.35,
            volume=10000.0,
            timestamp=1234567890.0,
        )
        assert update.market_id == "test123"

    def test_has_prices(self):
        """Should have yes/no prices."""
        update = PriceUpdate(
            market_id="test",
            yes_price=0.7,
            no_price=0.3,
            volume=0.0,
            timestamp=0.0,
        )
        assert update.yes_price == 0.7
        assert update.no_price == 0.3


class TestWebSocketPriceClient:
    """Test WebSocketPriceClient class."""

    def test_initializes(self):
        """Should initialize without errors."""
        client = WebSocketPriceClient()
        assert client is not None

    def test_initial_state_disconnected(self):
        """Should start in disconnected state."""
        client = WebSocketPriceClient()
        assert client.state == ConnectionState.DISCONNECTED

    def test_accepts_config(self):
        """Should accept custom config."""
        config = WebSocketConfig(url="wss://test.example.com")
        client = WebSocketPriceClient(config=config)
        assert client.config.url == "wss://test.example.com"

    def test_accepts_callback(self):
        """Should accept callback."""
        callback = MagicMock(spec=PriceFeedCallback)
        client = WebSocketPriceClient(callback=callback)
        assert client.callback is callback

    def test_empty_subscriptions_initially(self):
        """Should have no subscriptions initially."""
        client = WebSocketPriceClient()
        assert len(client._subscriptions) == 0

    def test_state_property(self):
        """Should expose state property."""
        client = WebSocketPriceClient()
        assert client.state == client._state

    def test_default_config_values(self):
        """Should have sensible defaults."""
        client = WebSocketPriceClient()
        assert client.config.reconnect_delay == 1.0
        assert client.config.max_reconnect_attempts == 5
        assert client.config.subscription_timeout == 10.0


class TestPriceFeedCallback:
    """Test PriceFeedCallback class."""

    def test_on_price_update_exists(self):
        """Should have on_price_update method."""
        callback = PriceFeedCallback()
        assert hasattr(callback, "on_price_update")

    def test_on_connection_state_change_exists(self):
        """Should have on_connection_state_change method."""
        callback = PriceFeedCallback()
        assert hasattr(callback, "on_connection_state_change")

    @pytest.mark.asyncio
    async def test_on_price_update_is_async(self):
        """on_price_update should be async."""
        callback = PriceFeedCallback()
        update = PriceUpdate(
            market_id="test",
            yes_price=0.5,
            no_price=0.5,
            volume=0.0,
            timestamp=0.0,
        )
        await callback.on_price_update(update)

    @pytest.mark.asyncio
    async def test_on_connection_state_change_is_async(self):
        """on_connection_state_change should be async."""
        callback = PriceFeedCallback()
        await callback.on_connection_state_change(ConnectionState.CONNECTED)


class TestWebSocketClientSubscriptions:
    """Test subscription management."""

    @pytest.mark.asyncio
    async def test_subscribe_adds_to_set(self):
        """Subscribe should add market IDs."""
        client = WebSocketPriceClient()
        await client.subscribe(["market1", "market2"])
        assert "market1" in client._subscriptions
        assert "market2" in client._subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_from_set(self):
        """Unsubscribe should remove market IDs."""
        client = WebSocketPriceClient()
        await client.subscribe(["market1", "market2"])
        await client.unsubscribe(["market1"])
        assert "market1" not in client._subscriptions
        assert "market2" in client._subscriptions

    @pytest.mark.asyncio
    async def test_multiple_subscriptions_no_duplicates(self):
        """Multiple subscriptions should not create duplicates."""
        client = WebSocketPriceClient()
        await client.subscribe(["market1"])
        await client.subscribe(["market1"])
        assert len(client._subscriptions) == 1


class TestWebSocketClientAsync:
    """Test async methods of WebSocket client."""

    @pytest.mark.asyncio
    async def test_connect_without_websocket_module(self):
        """Connect should raise ConnectionError without websockets."""
        client = WebSocketPriceClient()
        with pytest.raises(ConnectionError, match="Failed to connect"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Disconnect should work when not connected."""
        client = WebSocketPriceClient()
        await client.disconnect()
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_get_message_timeout(self):
        """get_message should return None on timeout."""
        client = WebSocketPriceClient()
        result = await client.get_message(timeout=0.1)
        assert result is None
