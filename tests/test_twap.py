"""Tests for TWAP Slicer."""

from unittest.mock import AsyncMock

import pytest

from weather_copy_bot.engine.twap import (
    SliceStatus,
    TWAPExecution,
    TWAPIntegration,
    TWAPSlice,
    TWAPSlicer,
)


class TestTWAPSlicer:
    """Tests for TWAPSlicer."""

    @pytest.mark.asyncio
    async def test_simple_execution(self):
        """Test simple TWAP execution."""
        slicer = TWAPSlicer(
            min_slice_size_usd=50.0,  # 2 slices for $100
            max_slices=5,
            slice_interval_seconds=0.1,  # Fast for testing
        )

        # Mock executor
        async def mock_executor(slice_: TWAPSlice) -> bool:
            return True

        async def mock_price_check(token_id: str) -> float:
            return 0.50

        result = await slicer.execute(
            execution_id="exec-1",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,
            initial_price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )

        assert result.status == SliceStatus.FILLED
        assert result.total_filled == 100.0
        assert len(result.slices) == 2

    @pytest.mark.asyncio
    async def test_slice_calculation(self):
        """Test that correct number of slices is created."""
        slicer = TWAPSlicer(
            min_slice_size_usd=25.0,
            max_slices=10,
        )

        # $100 / $25 = 4 slices
        slices = slicer._calculate_slices(100.0, 0.50)
        assert len(slices) == 4

        # Verify each slice has correct size
        for slice_ in slices:
            assert slice_.size_usd == 25.0

    @pytest.mark.asyncio
    async def test_max_slices_limit(self):
        """Test that max_slices is respected."""
        slicer = TWAPSlicer(
            min_slice_size_usd=5.0,  # Would be 20 slices
            max_slices=5,  # But limited to 5
        )

        slices = slicer._calculate_slices(100.0, 0.50)
        assert len(slices) == 5

    @pytest.mark.asyncio
    async def test_partial_execution(self):
        """Test partial execution when some slices fail."""
        slicer = TWAPSlicer(
            min_slice_size_usd=50.0,
            slice_interval_seconds=0.01,
        )

        call_count = 0

        async def mock_executor(slice_: TWAPSlice) -> bool:
            nonlocal call_count
            call_count += 1
            # Fail first slice, succeed second
            return call_count > 1

        async def mock_price_check(token_id: str) -> float:
            return 0.50

        result = await slicer.execute(
            execution_id="exec-2",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,
            initial_price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )

        # Should be partial (not all slices filled)
        assert result.total_filled == 50.0

    @pytest.mark.asyncio
    async def test_price_deviation_cancellation(self):
        """Test that execution is cancelled when price moves too much."""
        slicer = TWAPSlicer(
            min_slice_size_usd=10.0,
            slice_interval_seconds=0.01,
            price_deviation_threshold=0.01,  # 1% threshold
        )

        call_count = 0

        async def mock_executor(slice_: TWAPSlice) -> bool:
            return True

        async def mock_price_check(token_id: str) -> float:
            nonlocal call_count
            call_count += 1
            # Price moves 2% on second check (exceeds 1% threshold)
            return 0.50 + (0.50 * 0.02 if call_count > 1 else 0)

        result = await slicer.execute(
            execution_id="exec-3",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,
            initial_price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )

        # Should have some slices filled, rest skipped
        filled = sum(1 for s in result.slices if s.status == SliceStatus.FILLED)
        skipped = sum(1 for s in result.slices if s.status == SliceStatus.SKIPPED)
        assert filled >= 1
        assert skipped >= 1

    @pytest.mark.asyncio
    async def test_stats(self):
        """Test statistics tracking."""
        slicer = TWAPSlicer()

        async def mock_executor(slice_: TWAPSlice) -> bool:
            return True

        async def mock_price_check(token_id: str) -> float:
            return 0.50

        await slicer.execute(
            execution_id="exec-4",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=50.0,
            initial_price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price_check,
        )

        stats = slicer.get_stats()
        assert stats["executions_started"] == 1
        assert stats["executions_completed"] == 1
        assert stats["slices_submitted"] >= 1


class TestTWAPIntegration:
    """Tests for TWAPIntegration."""

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        """Test that small orders are not TWAPed."""
        twap = TWAPSlicer()
        risk = AsyncMock()

        integration = TWAPIntegration(
            twap_slicer=twap,
            risk_engine=risk,
            twap_threshold_usd=100.0,
        )

        async def mock_executor(slice_):
            return True

        async def mock_price(token_id):
            return 0.50

        result = await integration.execute_with_twap(
            token_id="TOKEN1",
            side="BUY",
            size_usd=50.0,  # Below threshold
            price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price,
        )

        # Should return None (no TWAP)
        assert result is None

    @pytest.mark.asyncio
    async def test_above_threshold_twap(self):
        """Test that large orders use TWAP."""
        twap = TWAPSlicer(
            slice_interval_seconds=0.01,
        )
        risk = AsyncMock()
        risk.check_size_limits.return_value = AsyncMock(passed=True)

        integration = TWAPIntegration(
            twap_slicer=twap,
            risk_engine=risk,
            twap_threshold_usd=50.0,
        )

        async def mock_executor(slice_):
            return True

        async def mock_price(token_id):
            return 0.50

        result = await integration.execute_with_twap(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,  # Above threshold
            price=0.50,
            executor_fn=mock_executor,
            price_check_fn=mock_price,
        )

        # Should return TWAPExecution
        assert result is not None
        assert result.total_size_usd == 100.0


class TestTWAPSlice:
    """Tests for TWAPSlice."""

    def test_slice_creation(self):
        """Test slice creation."""
        slice_ = TWAPSlice(
            slice_id="1",
            slice_number=1,
            total_slices=5,
            size_usd=20.0,
            price_limit=0.50,
        )

        assert slice_.slice_id == "1"
        assert slice_.size_usd == 20.0
        assert slice_.status == SliceStatus.PENDING


class TestTWAPExecution:
    """Tests for TWAPExecution."""

    def test_execution_creation(self):
        """Test execution creation."""
        slices = [
            TWAPSlice("1", 1, 2, 50.0, 0.50),
            TWAPSlice("2", 2, 2, 50.0, 0.51),
        ]

        execution = TWAPExecution(
            execution_id="exec-1",
            token_id="TOKEN1",
            side="BUY",
            total_size_usd=100.0,
            slices=slices,
        )

        assert execution.total_size_usd == 100.0
        assert len(execution.slices) == 2
        assert execution.total_filled == 0.0
