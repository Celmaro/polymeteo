"""Tests for Depth-Aware TWAP Slicer."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from weather_copy_bot.engine.twap_depth_aware import (
    TWAPSlicerDepthAware,
    LiquidityEstimator,
    LiquidityEstimate,
    DepthSlice,
    DepthAwareExecution,
    DepthAwareStatus,
    create_depth_aware_twap,
)
from weather_copy_bot.analysis.obi_filter import OrderBook, OrderBookLevel


class TestLiquidityEstimator:
    """Tests for LiquidityEstimator."""

    def test_estimate_with_sufficient_liquidity(self):
        """Test liquidity estimation with sufficient depth."""
        estimator = LiquidityEstimator()
        
        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=100.0),
                OrderBookLevel(price=0.49, size=80.0),
                OrderBookLevel(price=0.48, size=60.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=100.0),
                OrderBookLevel(price=0.52, size=80.0),
                OrderBookLevel(price=0.53, size=60.0),
            ],
            timestamp=0.0,
        )
        
        estimate = estimator.estimate_liquidity(
            order_book=order_book,
            side="BUY",
            target_price=0.51,
            order_size=50.0,
        )
        
        assert estimate.is_sufficient is True
        assert estimate.depth_at_price > 0
        assert estimate.max_slice_size > 0

    def test_estimate_with_insufficient_liquidity(self):
        """Test liquidity estimation with insufficient depth."""
        estimator = LiquidityEstimator(
            min_depth_ratio=0.5,  # Need 50% of order
        )
        
        order_book = OrderBook(
            bids=[
                OrderBookLevel(price=0.50, size=10.0),
            ],
            asks=[
                OrderBookLevel(price=0.51, size=10.0),  # Only $10 available
            ],
            timestamp=0.0,
        )
        
        estimate = estimator.estimate_liquidity(
            order_book=order_book,
            side="BUY",
            target_price=0.51,
            order_size=100.0,  # Order is $100, only $10 available
        )
        
        assert estimate.is_sufficient is False

    def test_adaptive_slice_size_calculation(self):
        """Test adaptive slice size calculation."""
        estimator = LiquidityEstimator()
        
        liquidity = LiquidityEstimate(
            depth_at_price=100.0,
            weighted_depth=150.0,
            max_slice_size=50.0,
            is_sufficient=True,
            spread_bps=20.0,
        )
        
        # First slice
        size_1 = estimator.calculate_adaptive_slice_size(liquidity, 50.0, 0)
        assert size_1 <= 50.0
        
        # Later slice with decay
        size_2 = estimator.calculate_adaptive_slice_size(liquidity, 50.0, 3)
        assert size_2 <= size_1  # Should be smaller due to decay

    def test_empty_order_book(self):
        """Test handling of empty order book."""
        estimator = LiquidityEstimator()
        
        order_book = OrderBook(bids=[], asks=[], timestamp=0.0)
        
        estimate = estimator.estimate_liquidity(
            order_book=order_book,
            side="BUY",
            target_price=0.51,
            order_size=50.0,
        )
        
        assert estimate.is_sufficient is False
        assert estimate.max_slice_size == 0.0


class TestTWAPSlicerDepthAware:
    """Tests for TWAPSlicerDepthAware."""

    @pytest.mark.asyncio
    async def test_execution_with_mocked_orderbook(self):
        """Test depth-aware execution with mocked order book."""
        slicer = TWAPSlicerDepthAware(
            min_slice_size_usd=25.0,
            max_slices=5,
            slice_interval_seconds=0.01,
        )
        
        # Mock order book provider
        async def mock_orderbook_provider(token_id):
            return OrderBook(
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
        
        slicer._get_order_book_provider = lambda: mock_orderbook_provider
        
        async def mock_executor(slice_: DepthSlice) -> bool:
            return True
        
        async def mock_price_check(token_id: str) -> float:
            return 0.51
        
        result = await slicer.execute(
            execution_id="exec-d1",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=50.0,
            initial_price=0.51,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )
        
        assert result.status in [DepthAwareStatus.COMPLETED, DepthAwareStatus.EXECUTING]
        assert result.total_filled > 0

    @pytest.mark.asyncio
    async def test_insufficient_liquidity_rejection(self):
        """Test that insufficient liquidity is rejected."""
        slicer = TWAPSlicerDepthAware(
            min_slice_size_usd=10.0,
            slice_interval_seconds=0.01,
            liquidity_estimator=LiquidityEstimator(min_depth_ratio=0.8),
        )
        
        # Mock provider with very thin order book
        async def mock_orderbook_provider(token_id):
            return OrderBook(
                bids=[OrderBookLevel(price=0.50, size=5.0)],
                asks=[OrderBookLevel(price=0.51, size=5.0)],
                timestamp=0.0,
            )
        
        slicer._get_order_book_provider = lambda: mock_orderbook_provider
        
        async def mock_executor(slice_: DepthSlice) -> bool:
            return True
        
        async def mock_price_check(token_id: str) -> float:
            return 0.51
        
        result = await slicer.execute(
            execution_id="exec-d2",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,  # $100 but only $5 available
            initial_price=0.51,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )
        
        assert result.status == DepthAwareStatus.INSUFFICIENT_LIQUIDITY

    @pytest.mark.asyncio
    async def test_fallback_without_orderbook(self):
        """Test execution falls back when no order book available."""
        slicer = TWAPSlicerDepthAware(
            min_slice_size_usd=25.0,
            max_slices=5,
            slice_interval_seconds=0.01,
        )
        
        # No order book provider
        slicer._get_order_book_provider = lambda: None
        
        async def mock_executor(slice_: DepthSlice) -> bool:
            return True
        
        async def mock_price_check(token_id: str) -> float:
            return 0.51
        
        result = await slicer.execute(
            execution_id="exec-d3",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=50.0,
            initial_price=0.51,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )
        
        # Should still execute with fallback liquidity estimate
        assert result.total_filled > 0

    def test_stats_tracking(self):
        """Test statistics tracking."""
        slicer = TWAPSlicerDepthAware(
            min_slice_size_usd=10.0,
            slice_interval_seconds=0.01,
        )
        
        stats = slicer.get_stats()
        
        assert "executions_started" in stats
        assert "slices_adjusted" in stats
        assert "depth_checks" in stats


class TestDepthSlice:
    """Tests for DepthSlice."""

    def test_slice_creation(self):
        """Test depth slice creation."""
        slice_ = DepthSlice(
            slice_id="1",
            slice_number=1,
            total_slices=5,
            size_usd=20.0,
            size_adjusted=18.0,
            price_limit=0.51,
            depth_available=50.0,
        )
        
        assert slice_.slice_id == "1"
        assert slice_.size_usd == 20.0
        assert slice_.size_adjusted == 18.0  # Adjusted by liquidity


class TestDepthAwareExecution:
    """Tests for DepthAwareExecution."""

    def test_execution_creation(self):
        """Test execution creation."""
        execution = DepthAwareExecution(
            execution_id="exec-1",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,
        )
        
        assert execution.execution_id == "exec-1"
        assert execution.status == DepthAwareStatus.PENDING
        assert execution.total_filled == 0.0


class TestCreateDepthAwareTWAP:
    """Tests for factory function."""

    def test_factory_creation(self):
        """Test factory function creates properly configured slicer."""
        slicer = create_depth_aware_twap(
            min_slice_size=15.0,
            max_slices=10,
        )
        
        assert slicer.min_slice_size == 15.0
        assert slicer.max_slices == 10
        assert slicer.liquidity_estimator is not None
