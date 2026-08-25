"""Tests for Parquet data export."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.modules["sqlalchemy"] = MagicMock()

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


from weather_copy_bot.parquet_export import (
    MarketDataSchema,
    ParquetExporter,
    PriceHistorySchema,
    TradeDataSchema,
)


class TestMarketDataSchema:
    """Test MarketDataSchema dataclass."""

    def test_schema_has_market_id(self):
        """Schema should have market_id field."""
        schema = MarketDataSchema(
            market_id="test-123",
            question="Test question?",
            volume_usd=1000.0,
        )
        assert schema.market_id == "test-123"

    def test_schema_has_question(self):
        """Schema should have question field."""
        schema = MarketDataSchema(
            market_id="test-123",
            question="Test question?",
            volume_usd=1000.0,
        )
        assert schema.question == "Test question?"

    def test_schema_has_volume_usd(self):
        """Schema should have volume_usd field."""
        schema = MarketDataSchema(
            market_id="test-123",
            question="Test question?",
            volume_usd=1000.0,
        )
        assert schema.volume_usd == 1000.0

    def test_schema_defaults(self):
        """Schema should have default values."""
        schema = MarketDataSchema()
        assert schema.market_id == ""
        assert schema.question == ""
        assert schema.volume_usd == 0.0


class TestTradeDataSchema:
    """Test TradeDataSchema dataclass."""

    def test_schema_has_trade_id(self):
        """Schema should have trade_id field."""
        schema = TradeDataSchema(
            trade_id="trade-456",
            market_id="market-123",
            price=0.55,
            size=100.0,
        )
        assert schema.trade_id == "trade-456"

    def test_schema_has_market_id(self):
        """Schema should have market_id field."""
        schema = TradeDataSchema(
            trade_id="trade-456",
            market_id="market-123",
            price=0.55,
            size=100.0,
        )
        assert schema.market_id == "market-123"

    def test_schema_has_price(self):
        """Schema should have price field."""
        schema = TradeDataSchema(
            trade_id="trade-456",
            market_id="market-123",
            price=0.55,
            size=100.0,
        )
        assert schema.price == 0.55

    def test_schema_has_size(self):
        """Schema should have size field."""
        schema = TradeDataSchema(
            trade_id="trade-456",
            market_id="market-123",
            price=0.55,
            size=100.0,
        )
        assert schema.size == 100.0


class TestPriceHistorySchema:
    """Test PriceHistorySchema dataclass."""

    def test_schema_has_market_id(self):
        """Schema should have market_id field."""
        schema = PriceHistorySchema(
            market_id="market-123",
            timestamp=1000000,
            bid=0.54,
            ask=0.56,
        )
        assert schema.market_id == "market-123"

    def test_schema_has_timestamp(self):
        """Schema should have timestamp field."""
        schema = PriceHistorySchema(
            market_id="market-123",
            timestamp=1000000,
            bid=0.54,
            ask=0.56,
        )
        assert schema.timestamp == 1000000

    def test_schema_has_bid_ask(self):
        """Schema should have bid and ask fields."""
        schema = PriceHistorySchema(
            market_id="market-123",
            timestamp=1000000,
            bid=0.54,
            ask=0.56,
        )
        assert schema.bid == 0.54
        assert schema.ask == 0.56


class TestParquetExporter:
    """Test ParquetExporter class."""

    def test_exporter_initializes(self):
        """Exporter should initialize without errors."""
        exporter = ParquetExporter()
        assert exporter is not None

    def test_exporter_can_be_created_with_path(self):
        """Exporter should accept a custom output path."""
        exporter = ParquetExporter(output_dir="/tmp/data")
        assert exporter.output_dir == "/tmp/data"

    def test_exporter_has_default_output_dir(self):
        """Exporter should have default output directory."""
        exporter = ParquetExporter()
        assert exporter.output_dir is not None

    def test_exporter_can_export_markets(self):
        """Exporter should be able to export markets."""
        exporter = ParquetExporter()
        assert hasattr(exporter, "export_markets")

    def test_exporter_can_export_trades(self):
        """Exporter should be able to export trades."""
        exporter = ParquetExporter()
        assert hasattr(exporter, "export_trades")

    def test_exporter_can_export_price_history(self):
        """Exporter should be able to export price history."""
        exporter = ParquetExporter()
        assert hasattr(exporter, "export_price_history")

    def test_exporter_can_get_parquet_path(self):
        """Exporter should provide parquet file paths."""
        exporter = ParquetExporter(output_dir="/tmp/data")
        path = exporter.get_parquet_path("markets")
        assert "markets" in path
        assert path.endswith(".parquet")
