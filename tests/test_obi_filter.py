"""Tests for OBI Filter."""

import pytest

from weather_copy_bot.analysis.obi_filter import (
    OBIAnalyzer,
    OBIIntegration,
    OBISignal,
    OrderBook,
    OrderBookLevel,
)


class TestOBIAnalyzer:
    """Tests for OBIAnalyzer."""

    def test_basic_obi_calculation(self):
        """Test basic OBI calculation."""
        analyzer = OBIAnalyzer()

        bids = [(0.50, 100.0), (0.49, 80.0), (0.48, 60.0)]
        asks = [(0.51, 100.0), (0.52, 80.0), (0.53, 60.0)]

        metrics = analyzer.calculate_obi(bids, asks)

        assert metrics.signal == OBISignal.NEUTRAL
        assert abs(metrics.obi) < 0.1  # Nearly balanced

    def test_heavy_buy_pressure(self):
        """Test OBI with heavy buy pressure."""
        analyzer = OBIAnalyzer()

        # Heavy bid side
        bids = [(0.50, 500.0), (0.49, 400.0), (0.48, 300.0)]
        asks = [(0.51, 50.0), (0.52, 40.0), (0.53, 30.0)]

        metrics = analyzer.calculate_obi(bids, asks)

        assert metrics.obi > 0.6
        assert metrics.signal == OBISignal.STRONG_BUY

    def test_heavy_sell_pressure(self):
        """Test OBI with heavy sell pressure."""
        analyzer = OBIAnalyzer()

        # Heavy ask side
        bids = [(0.50, 50.0), (0.49, 40.0), (0.48, 30.0)]
        asks = [(0.51, 500.0), (0.52, 400.0), (0.53, 300.0)]

        metrics = analyzer.calculate_obi(bids, asks)

        assert metrics.obi < -0.6
        assert metrics.signal == OBISignal.STRONG_SELL

    def test_insufficient_data(self):
        """Test with insufficient levels."""
        analyzer = OBIAnalyzer(min_levels=5)

        # Only 2 levels
        bids = [(0.50, 100.0), (0.49, 80.0)]
        asks = [(0.51, 100.0), (0.52, 80.0)]

        metrics = analyzer.calculate_obi(bids, asks)

        assert metrics.signal == OBISignal.INSUFFICIENT_DATA

    def test_order_book_check_buy_pass(self):
        """Test order book check passing for BUY."""
        analyzer = OBIAnalyzer()

        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=100.0),
                OrderBookLevel(price=0.49, size=80.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=100.0),
                OrderBookLevel(price=0.52, size=80.0),
            ],
            timestamp=0.0,
        )

        result = analyzer.check_order_book(order_book, "BUY", 0.51)

        assert result.passed is True
        assert result.recommendation == "execute"

    def test_order_book_check_buy_reject(self):
        """Test order book check rejecting for BUY."""
        analyzer = OBIAnalyzer(obi_threshold=0.3)

        # Heavy buy pressure (thin ask side)
        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=500.0),
                OrderBookLevel(price=0.49, size=400.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=20.0),
                OrderBookLevel(price=0.52, size=15.0),
            ],
            timestamp=0.0,
        )

        result = analyzer.check_order_book(order_book, "BUY", 0.51)

        assert result.passed is False
        assert result.recommendation in ["skip", "adjust_size"]

    def test_order_book_check_sell_pass(self):
        """Test order book check passing for SELL."""
        analyzer = OBIAnalyzer()

        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=100.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=100.0),
            ],
            timestamp=0.0,
        )

        result = analyzer.check_order_book(order_book, "SELL", 0.50)

        assert result.passed is True

    def test_slippage_estimation(self):
        """Test slippage estimation."""
        analyzer = OBIAnalyzer()

        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=100.0),
                OrderBookLevel(price=0.49, size=50.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=100.0),
                OrderBookLevel(price=0.52, size=50.0),
            ],
            timestamp=0.0,
        )

        # Small order
        slippage = analyzer.estimate_slippage(order_book, "BUY", 10.0)
        assert slippage < 50  # Low slippage for small order

        # Large order
        slippage = analyzer.estimate_slippage(order_book, "BUY", 200.0)
        assert slippage > 50  # Higher slippage for large order

    def test_empty_book(self):
        """Test handling of empty order book."""
        analyzer = OBIAnalyzer()

        order_book = OrderBook(
            bids=[],
            asks=[],
            timestamp=0.0,
        )

        slippage = analyzer.estimate_slippage(order_book, "BUY", 100.0)
        assert slippage == 100.0  # Unknown = assume high slippage


class TestOBIIntegration:
    """Tests for OBIIntegration."""

    @pytest.mark.asyncio
    async def test_check_before_execution(self):
        """Test OBI check before execution."""
        integration = OBIIntegration(
            obi_analyzer=OBIAnalyzer(),
        )

        result = await integration.check_before_execution(
            token_id="TOKEN1",
            side="BUY",
            target_price=0.51,
            size_usd=10.0,
        )

        assert result is not None
        assert integration.get_stats()["checks_performed"] == 1

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test statistics tracking."""
        integration = OBIIntegration(
            obi_analyzer=OBIAnalyzer(),
        )

        await integration.check_before_execution(
            token_id="TOKEN1",
            side="BUY",
            target_price=0.51,
            size_usd=10.0,
        )

        stats = integration.get_stats()
        assert stats["checks_performed"] == 1


class TestOrderBook:
    """Tests for OrderBook."""

    def test_mid_price(self):
        """Test mid price calculation."""
        book = OrderBook(
            bids=[OrderBookLevel(price=0.50, size=100.0)],
            asks=[OrderBookLevel(price=0.52, size=100.0)],
            timestamp=0.0,
        )

        assert book.mid_price == 0.51

    def test_spread(self):
        """Test spread calculation."""
        book = OrderBook(
            bids=[OrderBookLevel(price=0.50, size=100.0)],
            asks=[OrderBookLevel(price=0.52, size=100.0)],
            timestamp=0.0,
        )

        assert book.spread == pytest.approx(0.02, abs=1e-10)

    def test_spread_bps(self):
        """Test spread in basis points."""
        book = OrderBook(
            bids=[OrderBookLevel(price=0.50, size=100.0)],
            asks=[OrderBookLevel(price=0.51, size=100.0)],
            timestamp=0.0,
        )

        # 0.01 / 0.505 * 10000 = ~198 bps
        assert book.spread_bps > 150


class TestOBISignal:
    """Tests for OBISignal enum."""

    def test_signal_values(self):
        """Test OBI signal values."""
        assert OBISignal.STRONG_BUY == "strong_buy"
        assert OBISignal.STRONG_SELL == "strong_sell"
        assert OBISignal.NEUTRAL == "neutral"
