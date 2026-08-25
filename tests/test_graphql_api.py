"""Tests for GraphQL API layer."""
import pytest
from weather_copy_bot.graphql_api import (
    schema,
    MarketCategory,
    PriceData,
    MarketSummary,
    ConsensusSignal,
)


class TestGraphQLSchema:
    def test_market_category_enum(self):
        assert MarketCategory.SPORTS.value == "sports"
        assert MarketCategory.POLITICS.value == "politics"
        assert MarketCategory.ECONOMICS.value == "economics"
        assert MarketCategory.WEATHER.value == "weather"
        assert MarketCategory.CRYPTO.value == "crypto"
        assert MarketCategory.OTHER.value == "other"

    def test_price_data_creation(self):
        from datetime import datetime
        price_data = PriceData(
            yes_price=0.65,
            no_price=0.35,
            volume=1000000.0,
            updated_at=datetime.now(),
        )
        assert price_data.yes_price == 0.65
        assert price_data.no_price == 0.35
        assert price_data.volume == 1000000.0

    def test_market_summary_creation(self):
        from datetime import datetime
        price_data = PriceData(
            yes_price=0.55,
            no_price=0.45,
            volume=500000.0,
            updated_at=datetime.now(),
        )
        market = MarketSummary(
            market_id="test-market-1",
            question="Will it rain tomorrow?",
            description="Test market description",
            category=MarketCategory.WEATHER,
            current_price=price_data,
            liquidity=10000.0,
            volume_24h=5000.0,
        )
        assert market.market_id == "test-market-1"
        assert market.question == "Will it rain tomorrow?"
        assert market.category == MarketCategory.WEATHER

    def test_consensus_signal_creation(self):
        signal = ConsensusSignal(
            market_id="test-market-1",
            consensus_probability=0.72,
            confidence=0.85,
            num_sources=3,
            weighted_sources=[("source1", 0.70), ("source2", 0.75)],
        )
        assert signal.market_id == "test-market-1"
        assert signal.consensus_probability == 0.72
        assert signal.confidence == 0.85
        assert signal.num_sources == 3
        assert len(signal.weighted_sources) == 2

    def test_query_markets_returns_list(self):
        result = schema.execute_sync("{ markets { marketId } }")
        assert result.errors is None
        assert result.data == {"markets": []}

    def test_query_market_returns_null(self):
        result = schema.execute_sync('{ market(marketId: "test") { marketId } }')
        assert result.errors is None
        assert result.data == {"market": None}

    @pytest.mark.asyncio
    async def test_mutation_copy_trade(self):
        result = await schema.execute(
            """
            mutation {
                copyTrade(marketId: "test", positionSize: 100.0, walletAddress: "0x123") {
                    walletAddress
                    marketId
                    positionSize
                }
            }
            """
        )
        assert result.errors is None
        assert result.data["copyTrade"]["walletAddress"] == "0x123"
        assert result.data["copyTrade"]["marketId"] == "test"
        assert result.data["copyTrade"]["positionSize"] == 100.0

    @pytest.mark.asyncio
    async def test_mutation_close_position(self):
        result = await schema.execute(
            """
            mutation {
                closePosition(marketId: "test", walletAddress: "0x123") {
                    walletAddress
                    marketId
                    positionSize
                }
            }
            """
        )
        assert result.errors is None
        assert result.data["closePosition"]["walletAddress"] == "0x123"
        assert result.data["closePosition"]["positionSize"] == 0.0
