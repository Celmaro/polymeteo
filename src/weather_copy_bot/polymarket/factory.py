"""Async client factory for Polymarket API clients.

This module provides a singleton factory pattern for HTTP clients,
ensuring connection pooling and efficient resource management.

Usage:
    from weather_copy_bot.polymarket.factory import PolymarketClientFactory

    async with PolymarketClientFactory.get_gamma_client() as client:
        response = await client.get("/markets")
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class ClientConfig:
    """Configuration for HTTP clients.

    Attributes:
        timeout: Request timeout in seconds.
        max_connections: Maximum number of concurrent connections.
        max_keepalive: Maximum number of keep-alive connections.
    """

    timeout: float = 8.0
    max_connections: int = 20
    max_keepalive: int = 10


class PolymarketClientFactory:
    """Factory for managing shared HTTP clients.

    This factory implements the singleton pattern to ensure efficient
    connection pooling across the application. Each client type (gamma,
    data, clob) maintains its own singleton instance.

    Usage:
        gamma = await PolymarketClientFactory.get_gamma_client()
        data = await PolymarketClientFactory.get_data_client()

        # When shutting down:
        await PolymarketClientFactory.close_all()
    """

    _gamma_client: httpx.AsyncClient | None = None
    _data_client: httpx.AsyncClient | None = None
    _clob_client: httpx.AsyncClient | None = None

    @classmethod
    async def get_gamma_client(
        cls,
        config: ClientConfig | None = None,
    ) -> httpx.AsyncClient:
        """Get or create the shared Gamma API client.

        Args:
            config: Optional client configuration. Uses defaults if not provided.

        Returns:
            Shared httpx.AsyncClient instance for Gamma API.
        """
        if cls._gamma_client is None or cls._gamma_client.is_closed:
            cfg = config or ClientConfig()
            cls._gamma_client = httpx.AsyncClient(
                timeout=httpx.Timeout(cfg.timeout),
                limits=httpx.Limits(
                    max_connections=cfg.max_connections,
                    max_keepalive_connections=cfg.max_keepalive,
                ),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return cls._gamma_client

    @classmethod
    async def get_data_client(
        cls,
        config: ClientConfig | None = None,
    ) -> httpx.AsyncClient:
        """Get or create the shared Data API client.

        Args:
            config: Optional client configuration. Uses defaults if not provided.

        Returns:
            Shared httpx.AsyncClient instance for Data API.
        """
        if cls._data_client is None or cls._data_client.is_closed:
            cfg = config or ClientConfig(timeout=6.0)
            cls._data_client = httpx.AsyncClient(
                timeout=httpx.Timeout(cfg.timeout),
                limits=httpx.Limits(
                    max_connections=cfg.max_connections,
                    max_keepalive_connections=cfg.max_keepalive,
                ),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return cls._data_client

    @classmethod
    async def get_clob_client(
        cls,
        config: ClientConfig | None = None,
    ) -> httpx.AsyncClient:
        """Get or create the shared CLOB API client.

        Args:
            config: Optional client configuration. Uses defaults if not provided.

        Returns:
            Shared httpx.AsyncClient instance for CLOB API.
        """
        if cls._clob_client is None or cls._clob_client.is_closed:
            cfg = config or ClientConfig(timeout=5.0)
            cls._clob_client = httpx.AsyncClient(
                timeout=httpx.Timeout(cfg.timeout),
                limits=httpx.Limits(
                    max_connections=cfg.max_connections,
                    max_keepalive_connections=cfg.max_keepalive,
                ),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return cls._clob_client

    @classmethod
    async def close_all(cls) -> None:
        """Close all managed clients.

        Call this during application shutdown to properly release resources.

        Example:
            at app shutdown:
                await PolymarketClientFactory.close_all()
        """
        if cls._gamma_client is not None and not cls._gamma_client.is_closed:
            await cls._gamma_client.aclose()
            cls._gamma_client = None

        if cls._data_client is not None and not cls._data_client.is_closed:
            await cls._data_client.aclose()
            cls._data_client = None

        if cls._clob_client is not None and not cls._clob_client.is_closed:
            await cls._clob_client.aclose()
            cls._clob_client = None
