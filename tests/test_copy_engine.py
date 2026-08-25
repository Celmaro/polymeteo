"""Tests for CopyEngine signal processing and polling."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from weather_copy_bot.config import Settings
from weather_copy_bot.engine.copy_engine import CopyEngine
from weather_copy_bot.models import CopyDecision, Side, TradeSignal


def _signal(
    wallet: str = "0xabc",
    latency_ms: int = 350,
    price: float = 0.42,
    size: float = 100.0,
    city: str = "New York",
) -> TradeSignal:
    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="t1",
        target_wallet=wallet,
        market_slug="highest-temperature-in-tokyo",
        market_title=f"Highest temperature in {city}?",
        city=city,
        outcome="Yes",
        side=Side.BUY,
        price=price,
        size_usd=size,
        detected_at=now,
        target_filled_at=now,
        latency_ms=latency_ms,
    )


class TestCopyEngineInitialization:
    """Test engine initialization."""

    def test_engine_with_defaults(self):
        engine = CopyEngine()
        assert engine.settings is not None
        assert engine.client is not None
        assert engine.policy is not None
        assert engine.paper is not None
        assert engine.mode == "paper"

    def test_engine_with_custom_settings(self):
        settings = Settings(max_copy_latency_ms=500, copy_ratio=0.5)
        engine = CopyEngine(settings=settings)
        assert engine.settings.max_copy_latency_ms == 500
        assert engine.settings.copy_ratio == 0.5

    def test_engine_initial_stats(self):
        engine = CopyEngine()
        assert engine.stats["signals_detected"] == 0
        assert engine.stats["copied"] == 0
        assert engine.stats["skipped"] == 0
        assert engine.stats["avg_latency_ms"] == 0.0

    def test_engine_mode_paper_by_default(self):
        engine = CopyEngine()
        assert engine.mode == "paper"

    def test_engine_mode_live_when_enabled(self):
        settings = Settings(dry_run=False, polymarket_private_key="0xsecret")
        engine = CopyEngine(settings=settings)
        assert engine.mode == "live"


class TestProcessSignal:
    """Test signal processing logic."""

    @pytest.mark.asyncio
    async def test_process_stale_signal_rejected(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=500))
        signal = _signal(latency_ms=800)
        decision = await engine.process_signal(signal)
        assert decision.should_copy is False
        assert "stale" in decision.reason.lower()
        assert engine.stats["skipped"] == 1
        assert engine.stats["copied"] == 0

    @pytest.mark.asyncio
    async def test_process_fresh_signal_copied(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=800, copy_ratio=0.25))
        signal = _signal(latency_ms=300)
        decision = await engine.process_signal(signal)
        assert decision.should_copy is True
        assert decision.copy_size_usd == 25.0
        assert engine.stats["copied"] == 1

    @pytest.mark.asyncio
    async def test_process_signal_updates_stats(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=800))
        signal = _signal(latency_ms=400)
        await engine.process_signal(signal)
        assert engine.stats["signals_detected"] == 1

    @pytest.mark.asyncio
    async def test_process_signal_avg_latency_tracking(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=800))
        await engine.process_signal(_signal(latency_ms=300))
        assert engine.stats["avg_latency_ms"] == 300.0
        await engine.process_signal(_signal(latency_ms=500))
        assert engine.stats["avg_latency_ms"] == 400.0

    @pytest.mark.asyncio
    async def test_process_with_callback(self):
        callback_results: list[tuple[TradeSignal, CopyDecision]] = []

        async def on_decision(signal: TradeSignal, decision: CopyDecision):
            callback_results.append((signal, decision))

        engine = CopyEngine(on_decision=on_decision)
        signal = _signal(latency_ms=300)
        await engine.process_signal(signal)
        assert len(callback_results) == 1
        assert callback_results[0][0].signal_id == signal.signal_id


class TestPollOnce:
    """Test polling logic."""

    @pytest.mark.asyncio
    async def test_poll_fetches_activity(self):
        engine = CopyEngine()
        mock_events = [
            {
                "id": "evt-1",
                "wallet": "0xtarget",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market_slug": "weather-tokyo",
                "market_title": "Temperature in Tokyo?",
                "city": "Tokyo",
                "outcome": "Yes",
                "side": "BUY",
                "price": 0.5,
                "size_usd": 100,
                "demo": False,
            }
        ]
        engine.client.fetch_target_activity = AsyncMock(return_value=mock_events)
        signals = await engine.poll_once()
        assert len(signals) == 1
        assert signals[0].target_wallet == "0xtarget"

    @pytest.mark.asyncio
    async def test_poll_skips_seen_events(self):
        engine = CopyEngine()
        engine._seen.add("evt-1")
        mock_events = [
            {
                "id": "evt-1",
                "wallet": "0xtarget",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market_slug": "weather",
                "market_title": "Weather?",
                "city": "Tokyo",
                "outcome": "Yes",
                "side": "BUY",
                "price": 0.5,
                "size_usd": 100,
            },
        ]
        engine.client.fetch_target_activity = AsyncMock(return_value=mock_events)
        signals = await engine.poll_once()
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_poll_injects_demo_latency(self):
        engine = CopyEngine()
        mock_events = [
            {
                "id": "evt-demo",
                "wallet": "0xtarget",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market_slug": "weather",
                "market_title": "Weather?",
                "city": "Tokyo",
                "outcome": "Yes",
                "side": "BUY",
                "price": 0.5,
                "size_usd": 100,
                "demo": True,
                "latency_ms": 350,
            },
        ]
        engine.client.fetch_target_activity = AsyncMock(return_value=mock_events)
        signals = await engine.poll_once()
        assert len(signals) == 1
        assert signals[0].latency_ms == 350

    @pytest.mark.asyncio
    async def test_poll_updates_heartbeat(self):
        engine = CopyEngine()
        engine.client.fetch_target_activity = AsyncMock(return_value=[])
        await engine.poll_once()
        assert engine.stats["last_heartbeat"] is not None


class TestEngineLifecycle:
    """Test engine start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_run_starts_and_stops(self):
        engine = CopyEngine()
        engine.poll_once = AsyncMock(return_value=[])
        task = asyncio.create_task(engine.run(duration_sec=0.1))
        await asyncio.sleep(0.2)
        engine.stop()
        await asyncio.wait_for(task, timeout=1.0)
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_stop_halts_loop(self):
        engine = CopyEngine()
        poll_count = 0

        async def counting_poll():
            nonlocal poll_count
            poll_count += 1
            return []

        engine.poll_once = counting_poll
        task = asyncio.create_task(engine.run(duration_sec=0.5))
        await asyncio.sleep(0.2)
        engine.stop()
        await asyncio.wait_for(task, timeout=2.0)
        assert engine._running is False
        assert poll_count <= 3


class TestLiveRiskGating:
    """Live execution must pass through RiskEngine and record order results."""

    def _live_engine(self) -> CopyEngine:
        settings = Settings(
            dry_run=False,
            polymarket_private_key="0xsecret",
            max_copy_latency_ms=800,
            copy_ratio=0.25,
        )
        return CopyEngine(settings=settings)

    @pytest.mark.asyncio
    async def test_risk_rejection_blocks_live_order(self):
        from weather_copy_bot.live.risk_engine import RiskEngine, RiskLimits

        engine = self._live_engine()
        engine.risk = RiskEngine(limits=RiskLimits(max_trade_size_usd=10.0))
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})

        decision = await engine.process_signal(_signal(size=1000.0))

        engine.client.place_order.assert_not_called()
        assert decision.should_copy is False
        assert "risk" in decision.reason.lower()
        assert engine.stats["risk_rejections"] == 1
        assert engine.stats["copied"] == 0
        assert engine.stats["skipped"] == 1

    @pytest.mark.asyncio
    async def test_live_order_success_recorded(self):
        engine = self._live_engine()
        engine.risk = None
        engine.client.place_order = AsyncMock(
            return_value={"status": "matched", "orderID": "abc123"}
        )

        await engine.process_signal(_signal())

        engine.client.place_order.assert_awaited_once()
        assert engine.stats["live_orders_filled"] == 1
        assert engine.stats["live_orders_failed"] == 0

    @pytest.mark.asyncio
    async def test_live_order_failure_recorded(self):
        engine = self._live_engine()
        engine.risk = None
        engine.client.place_order = AsyncMock(side_effect=RuntimeError("CLOB locked"))

        await engine.process_signal(_signal())

        assert engine.stats["live_orders_failed"] == 1
        assert engine.stats["live_orders_filled"] == 0
