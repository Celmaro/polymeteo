"""Multi-source data fusion for Polymarket data.

This module provides a robust data fetching strategy that tries multiple
sources in order of preference, with automatic fallback when sources fail.

Primary source: Gamma API
Fallback 1: The Graph subgraph
Fallback 2: GraphQL endpoint

Usage:
    fusion = MultiSourceDataFusion()
    markets = await fusion.fetch_weather_markets(limit=50)
"""
from __future__ import annotations

import logging
from enum import Enum

from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.polymarket.factory import PolymarketClientFactory

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Enum representing available data sources."""

    GAMMA = "gamma"
    SUBGRAPH = "subgraph"
    GRAPHQL = "graphql"


class MultiSourceDataFusion:
    """Multi-source data fusion with fallback support.

    This class implements a cascading fallback strategy for fetching market data.
    It tries sources in order (Gamma -> Subgraph -> GraphQL) and returns
    data from the first source that responds successfully.

    Attributes:
        use_subgraph_fallback: Whether to try The Graph subgraph on failure.
        use_graphql_fallback: Whether to try GraphQL endpoint on failure.
        last_source: The source that provided the most recent data.

    Example:
        fusion = MultiSourceDataFusion()
        markets = await fusion.fetch_weather_markets(limit=50)
        print(f"Data from: {fusion.last_source.value}")
    """

    def __init__(
        self,
        settings: Settings | None = None,
        use_subgraph_fallback: bool = True,
        use_graphql_fallback: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.use_subgraph_fallback = use_subgraph_fallback
        self.use_graphql_fallback = use_graphql_fallback
        self.last_source: DataSource | None = None
        self._weather_keywords = set(self.settings.weather_keywords)

    async def fetch_weather_markets(self, limit: int = 50) -> list[dict]:
        """Fetch weather-related markets with automatic fallback.

        Args:
            limit: Maximum number of markets to return.

        Returns:
            List of weather-related market dictionaries.
        """
        try:
            markets = await self._fetch_from_gamma(limit)
            if markets:
                self.last_source = DataSource.GAMMA
                return self._filter_weather_markets(markets)
        except Exception as exc:
            logger.warning("Gamma API failed: %s", exc)

        if self.use_subgraph_fallback:
            try:
                markets = await self._fetch_from_subgraph(limit)
                if markets:
                    self.last_source = DataSource.SUBGRAPH
                    return self._filter_weather_markets(markets)
            except Exception as exc:
                logger.warning("Subgraph fallback failed: %s", exc)

        if self.use_graphql_fallback:
            try:
                markets = await self._fetch_from_graphql(limit)
                if markets:
                    self.last_source = DataSource.GRAPHQL
                    return self._filter_weather_markets(markets)
            except Exception as exc:
                logger.warning("GraphQL fallback failed: %s", exc)

        self.last_source = None
        return []

    async def _fetch_from_gamma(self, limit: int) -> list[dict]:
        """Fetch markets from Gamma API.

        Args:
            limit: Maximum number of markets to return.

        Returns:
            List of market dictionaries from Gamma API.

        Raises:
            Exception: If the API request fails.
        """
        client = await PolymarketClientFactory.get_gamma_client()
        url = f"{self.settings.gamma_host}/markets"
        params = {"active": "true", "closed": "false", "limit": limit}

        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_from_subgraph(self, limit: int) -> list[dict]:
        """Fetch markets from The Graph subgraph.

        Uses the The Graph Network gateway (the legacy api.thegraph.com hosted
        endpoints are deprecated and the Goldsky Polymarket subgraphs are
        paused). Requires ``thegraph_api_key`` in settings; when absent this
        returns an empty list so the caller falls through to the GraphQL
        fallback instead of erroring.

        Args:
            limit: Maximum number of markets to return.

        Returns:
            List of market dictionaries from subgraph.

        Raises:
            Exception: If the subgraph query fails.
        """
        api_key = self.settings.thegraph_api_key
        if not api_key:
            logger.warning(
                "Subgraph fallback skipped: THEGRAPH_API_KEY not configured"
            )
            return []
        client = await PolymarketClientFactory.get_data_client()
        url = (
            "https://gateway.thegraph.com/api/"
            f"{api_key}/subgraphs/id/"
            "Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp"
        )
        query = """
        query GetMarkets($limit: Int!) {
            markets(first: $limit, where: {active: true}) {
                id
                question
                slug
                active
            }
        }
        """
        resp = await client.post(
            url,
            json={"query": query, "variables": {"limit": limit}},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("markets", [])

    async def _fetch_from_graphql(self, limit: int) -> list[dict]:
        """Fetch markets from GraphQL endpoint.

        Args:
            limit: Maximum number of markets to return.

        Returns:
            List of market dictionaries from GraphQL.

        Raises:
            Exception: If the GraphQL query fails.
        """
        client = await PolymarketClientFactory.get_gamma_client()
        query = """
        query GetWeatherMarkets($limit: Int!) {
            markets(where: {category: "weather"}, limit: $limit) {
                id
                question
                slug
            }
        }
        """
        url = f"{self.settings.gamma_host}/graphql"
        resp = await client.post(
            url,
            json={"query": query, "variables": {"limit": limit}},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("markets", [])

    def _filter_weather_markets(self, markets: list[dict]) -> list[dict]:
        """Filter markets to only weather-related ones.

        Args:
            markets: List of market dictionaries.

        Returns:
            Filtered list of weather-related markets.
        """
        weather_markets = []
        for market in markets:
            question = market.get("question", "")
            slug = market.get("slug", "")
            combined = f"{question} {slug}".lower()

            if any(keyword in combined for keyword in self._weather_keywords):
                weather_markets.append(market)

        return weather_markets
