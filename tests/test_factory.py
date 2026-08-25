"""Tests for Polymarket client factory."""

from __future__ import annotations

import pytest

from weather_copy_bot.polymarket.factory import (
    ClientConfig,
    PolymarketClientFactory,
)


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset factory state before and after each test."""
    PolymarketClientFactory._gamma_client = None
    PolymarketClientFactory._data_client = None
    PolymarketClientFactory._clob_client = None
    yield
    PolymarketClientFactory._gamma_client = None
    PolymarketClientFactory._data_client = None
    PolymarketClientFactory._clob_client = None


class TestClientConfig:
    """Test ClientConfig dataclass."""

    def test_default_config(self):
        """Default config should have sensible values."""
        config = ClientConfig()
        assert config.timeout == 8.0
        assert config.max_connections == 20
        assert config.max_keepalive == 10

    def test_custom_config(self):
        """Custom config should override defaults."""
        config = ClientConfig(timeout=15.0, max_connections=50, max_keepalive=25)
        assert config.timeout == 15.0
        assert config.max_connections == 50
        assert config.max_keepalive == 25


class TestPolymarketClientFactory:
    """Test PolymarketClientFactory singleton behavior."""

    @pytest.mark.asyncio
    async def test_get_gamma_client_creates_client(self):
        """First call should create a new client."""
        client = await PolymarketClientFactory.get_gamma_client()
        assert client is not None
        assert not client.is_closed

    @pytest.mark.asyncio
    async def test_get_gamma_client_returns_same_instance(self):
        """Multiple calls should return the same client instance."""
        client1 = await PolymarketClientFactory.get_gamma_client()
        client2 = await PolymarketClientFactory.get_gamma_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_get_data_client_creates_client(self):
        """First call should create a new data client."""
        client = await PolymarketClientFactory.get_data_client()
        assert client is not None
        assert not client.is_closed

    @pytest.mark.asyncio
    async def test_get_data_client_returns_same_instance(self):
        """Multiple calls should return the same data client instance."""
        client1 = await PolymarketClientFactory.get_data_client()
        client2 = await PolymarketClientFactory.get_data_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_gamma_and_data_clients_are_separate(self):
        """Gamma and data clients should be different instances."""
        gamma_client = await PolymarketClientFactory.get_gamma_client()
        data_client = await PolymarketClientFactory.get_data_client()
        assert gamma_client is not data_client

    @pytest.mark.asyncio
    async def test_close_all_closes_all_clients(self):
        """close_all should close all managed clients."""
        gamma = await PolymarketClientFactory.get_gamma_client()
        data = await PolymarketClientFactory.get_data_client()

        await PolymarketClientFactory.close_all()

        assert gamma.is_closed
        assert data.is_closed

    @pytest.mark.asyncio
    async def test_close_all_idempotent(self):
        """close_all should be safe to call multiple times."""
        await PolymarketClientFactory.get_gamma_client()
        await PolymarketClientFactory.close_all()
        await PolymarketClientFactory.close_all()

    @pytest.mark.asyncio
    async def test_close_all_handles_none_clients(self):
        """close_all should handle None clients gracefully."""
        await PolymarketClientFactory.close_all()

    @pytest.mark.asyncio
    async def test_client_config_applies_timeout(self):
        """Client should use the configured timeout."""
        config = ClientConfig(timeout=15.0)
        client = await PolymarketClientFactory.get_gamma_client(config)
        assert client.timeout.connect == 15.0

    @pytest.mark.asyncio
    async def test_default_timeout_is_8_seconds(self):
        """Default client should have 8 second timeout."""
        client = await PolymarketClientFactory.get_gamma_client()
        assert client.timeout.connect == 8.0


class TestClientFactoryWithMockedSettings:
    """Test factory behavior with mocked settings."""

    @pytest.mark.asyncio
    async def test_factory_includes_content_type_header(self):
        """Client should include Content-Type header."""
        client = await PolymarketClientFactory.get_gamma_client()
        headers = {k.lower(): v for k, v in client.headers.items()}
        assert "content-type" in headers
        assert headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_factory_includes_accept_header(self):
        """Client should include Accept header."""
        client = await PolymarketClientFactory.get_gamma_client()
        headers = {k.lower(): v for k, v in client.headers.items()}
        assert "accept" in headers
