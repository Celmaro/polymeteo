"""Tests for multi-source data fusion."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from weather_copy_bot.polymarket.multi_source import (
    DataSource,
    MultiSourceDataFusion,
)


@pytest.fixture
def fusion():
    """Create a MultiSourceDataFusion instance for testing."""
    return MultiSourceDataFusion()


class TestMultiSourceDataFusion:
    """Test multi-source data fusion with fallback behavior."""

    @pytest.mark.asyncio
    async def test_fusion_initializes_with_defaults(self, fusion):
        """Fusion should initialize with default settings."""
        assert fusion.use_subgraph_fallback is True
        assert fusion.use_graphql_fallback is True

    @pytest.mark.asyncio
    async def test_fusion_can_disable_subgraph_fallback(self):
        """Fusion should allow disabling subgraph fallback."""
        fusion = MultiSourceDataFusion(use_subgraph_fallback=False)
        assert fusion.use_subgraph_fallback is False

    @pytest.mark.asyncio
    async def test_fusion_can_disable_graphql_fallback(self):
        """Fusion should allow disabling GraphQL fallback."""
        fusion = MultiSourceDataFusion(use_graphql_fallback=False)
        assert fusion.use_graphql_fallback is False


class TestDataSource:
    """Test DataSource enum."""

    def test_data_source_has_expected_values(self):
        """DataSource should have expected enum values."""
        assert DataSource.GAMMA.value == "gamma"
        assert DataSource.SUBGRAPH.value == "subgraph"
        assert DataSource.GRAPHQL.value == "graphql"

    def test_data_source_count(self):
        """DataSource should have exactly 3 values."""
        assert len(DataSource) == 3


class TestFusionFallbackBehavior:
    """Test fallback behavior when primary sources fail."""

    @pytest.mark.asyncio
    async def test_fusion_prioritizes_gamma_api(self, fusion):
        """Fusion should try Gamma API first."""
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(return_value=[{"id": "market1", "question": "Temperature in NYC?"}]),
        ) as mock_gamma:
            result = await fusion.fetch_weather_markets(limit=10)
            mock_gamma.assert_called_once_with(10)
            assert len(result) == 1
            assert result[0]["id"] == "market1"

    @pytest.mark.asyncio
    async def test_fusion_falls_back_to_subgraph_on_gamma_failure(self, fusion):
        """Fusion should fallback to subgraph when Gamma fails."""
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(side_effect=Exception("Gamma unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_subgraph",
            new=AsyncMock(return_value=[{"id": "market2", "question": "Rain in London?"}]),
        ) as mock_subgraph:
            result = await fusion.fetch_weather_markets(limit=10)
            mock_subgraph.assert_called_once_with(10)
            assert len(result) == 1
            assert result[0]["id"] == "market2"

    @pytest.mark.asyncio
    async def test_fusion_falls_back_to_graphql_when_subgraph_fails(self, fusion):
        """Fusion should fallback to GraphQL when subgraph fails."""
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(side_effect=Exception("Gamma unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_subgraph",
            new=AsyncMock(side_effect=Exception("Subgraph unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_graphql",
            new=AsyncMock(return_value=[{"id": "market3", "question": "Snow in Denver?"}]),
        ) as mock_graphql:
            result = await fusion.fetch_weather_markets(limit=10)
            mock_graphql.assert_called_once_with(10)
            assert len(result) == 1
            assert result[0]["id"] == "market3"

    @pytest.mark.asyncio
    async def test_fusion_returns_empty_on_all_failures(self, fusion):
        """Fusion should return empty list when all sources fail."""
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(side_effect=Exception("Gamma unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_subgraph",
            new=AsyncMock(side_effect=Exception("Subgraph unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_graphql",
            new=AsyncMock(side_effect=Exception("GraphQL unavailable")),
        ):
            result = await fusion.fetch_weather_markets(limit=10)
            assert result == []

    @pytest.mark.asyncio
    async def test_fusion_skips_subgraph_when_disabled(self):
        """Fusion should skip subgraph when disabled."""
        fusion = MultiSourceDataFusion(use_subgraph_fallback=False)
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(side_effect=Exception("Gamma unavailable")),
        ), patch.object(
            fusion,
            "_fetch_from_subgraph",
            new=AsyncMock(return_value=[{"id": "should_not_use"}]),
        ) as mock_subgraph:
            result = await fusion.fetch_weather_markets(limit=10)
            mock_subgraph.assert_not_called()
            assert result == []

    @pytest.mark.asyncio
    async def test_fusion_reports_source_used(self, fusion):
        """Fusion should track which source was used."""
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(return_value=[{"id": "market1", "question": "Temperature forecast?"}]),
        ):
            await fusion.fetch_weather_markets(limit=10)
            assert fusion.last_source == DataSource.GAMMA


class TestMarketFiltering:
    """Test market filtering logic."""

    @pytest.mark.asyncio
    async def test_fusion_filters_weather_markets(self, fusion):
        """Fusion should filter for weather-related markets."""
        markets = [
            {"id": "1", "question": "Temperature in NYC?"},
            {"id": "2", "question": "Election winner?"},
            {"id": "3", "question": "Rain tomorrow in London?"},
        ]
        with patch.object(
            fusion,
            "_fetch_from_gamma",
            new=AsyncMock(return_value=markets),
        ):
            result = await fusion.fetch_weather_markets(limit=50)
            assert len(result) == 2
            assert all(
                any(kw in m["question"].lower() for kw in ["temperature", "rain"])
                for m in result
            )
