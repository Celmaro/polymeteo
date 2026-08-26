"""Tests for CopyEngine signal processing and polling."""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from weather_copy_bot.backtest.engine import CopyBacktester
from weather_copy_bot.config import Settings
from weather_copy_bot.engine.copy_engine import (
    POLL_FAILURE_BACKOFF_CAP_S,
    SEEN_TTL_SECONDS,
    CopyEngine,
    _failure_backoff_delay,
    _seen_store_path,
)
from weather_copy_bot.engine.order_queue import OrderQueue
from weather_copy_bot.live.risk_engine import RiskEngine, RiskLimits
from weather_copy_bot.models import CopyDecision, Side, TradeSignal
from weather_copy_bot.paper.trader import PaperTrader


def _signal(
    wallet: str = "0xabc",
    latency_ms: int = 350,
    price: float = 0.42,
    size: float = 100.0,
    city: str = "New York",
    side: Side = Side.BUY,
    token_id: str | None = None,
) -> TradeSignal:
    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="t1",
        target_wallet=wallet,
        market_slug="highest-temperature-in-tokyo",
        market_title=f"Highest temperature in {city}?",
        city=city,
        outcome="Yes",
        side=side,
        price=price,
        size_usd=size,
        detected_at=now,
        target_filled_at=now,
        latency_ms=latency_ms,
        token_id=token_id,
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


def _live_settings() -> Settings:
    return Settings(
        dry_run=False,
        polymarket_private_key="0xsecret",
        max_copy_latency_ms=800,
        copy_ratio=0.25,
    )


class TestRiskFeedbackLoop:
    """Realized P&L must flow back into the risk engine and shape gating."""

    @pytest.mark.asyncio
    async def test_paper_losses_trip_daily_loss_limit(self):
        # SELL copies lose size*(markup+decay+fee) ≈ $0.82 each at 350ms;
        # a $20 daily loss cap should stop copies after ~25 fills.
        risk = RiskEngine(limits=RiskLimits(max_daily_loss_usd=20.0))
        engine = CopyEngine(Settings(max_copy_latency_ms=800), risk_engine=risk)

        copied = 0
        rejected = 0
        for i in range(30):
            signal = _signal(wallet=f"0xseller-{i}", latency_ms=350, side=Side.SELL)
            decision = await engine.process_signal(signal)
            if decision.should_copy:
                copied += 1
            else:
                assert "daily_loss_limit" in decision.reason
                rejected += 1

        assert copied == 25
        assert rejected == 5
        assert risk.get_state()["daily_trades"] == 25

    @pytest.mark.asyncio
    async def test_live_fill_records_state_and_trade_count(self):
        risk = RiskEngine()
        engine = CopyEngine(_live_settings(), risk_engine=risk)
        engine.client.place_order = AsyncMock(
            return_value={"status": "matched", "orderID": "abc123"}
        )

        decision = await engine.process_signal(_signal(token_id="tok-live"))

        assert decision.should_copy is True
        assert engine.stats["live_orders_filled"] == 1
        state = risk.get_state()
        assert state["daily_trades"] == 1
        assert state["open_positions"] == 1

    @pytest.mark.asyncio
    async def test_exposure_headroom_clamps_then_rejects(self):
        risk = RiskEngine(limits=RiskLimits(max_total_exposure_usd=40.0))
        engine = CopyEngine(_live_settings(), risk_engine=risk)
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})

        d1 = await engine.process_signal(_signal(wallet="0x1", token_id="tok-a"))
        assert d1.should_copy is True
        assert d1.copy_size_usd == 25.0

        # Headroom is 40 - 25 = 15, so the next copy gets clamped.
        d2 = await engine.process_signal(_signal(wallet="0x2", token_id="tok-b"))
        assert d2.should_copy is True
        assert d2.copy_size_usd == 15.0
        size_arg = engine.client.place_order.await_args_list[1].kwargs["size_usd"]
        assert size_arg == 15.0

        # Exposure is now fully used; the third copy must be rejected.
        d3 = await engine.process_signal(_signal(wallet="0x3", token_id="tok-c"))
        assert d3.should_copy is False
        assert "max_exposure_reached" in d3.reason
        assert engine.client.place_order.await_count == 2


class TestOrderQueueWiring:
    """Live orders must flow through OrderQueue dedup + rate limiting."""

    @pytest.mark.asyncio
    async def test_duplicate_token_blocks_second_order(self):
        engine = CopyEngine(_live_settings())
        engine.risk = None
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})

        d1 = await engine.process_signal(_signal(token_id="tok-dup"))
        d2 = await engine.process_signal(_signal(wallet="0xother", token_id="tok-dup"))

        assert d1.should_copy is True
        assert d2.should_copy is False
        assert "duplicate" in d2.reason
        assert engine.stats["live_orders_duplicated"] == 1
        engine.client.place_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_throttles_second_order(self):
        engine = CopyEngine(_live_settings())
        engine.risk = None
        engine.order_queue = OrderQueue(rate_limit_per_second=1)
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})

        d1 = await engine.process_signal(_signal(token_id="tok-r1"))
        d2 = await engine.process_signal(_signal(wallet="0xother", token_id="tok-r2"))

        assert d1.should_copy is True
        assert d2.reason == "order_rate_limited"
        assert engine.stats["live_orders_throttled"] == 1
        engine.client.place_order.assert_awaited_once()


class TestSeenMemoryManagement:
    """Seen set must expire stale entries and survive engine restarts."""

    @staticmethod
    def _event(event_id: str) -> dict:
        return {
            "id": event_id,
            "wallet": "0xtarget",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_slug": "weather",
            "market_title": "Weather?",
            "city": "Tokyo",
            "outcome": "Yes",
            "side": "BUY",
            "price": 0.5,
            "size_usd": 100,
        }

    @pytest.mark.asyncio
    async def test_stale_seen_entries_are_pruned(self):
        engine = CopyEngine()
        engine._seen.add("evt-old")
        engine._seen_ts["evt-old"] = time.time() - 3700.0
        engine.client.fetch_target_activity = AsyncMock(return_value=[self._event("evt-old")])

        signals = await engine.poll_once()

        assert len(signals) == 1
        assert "evt-old" in engine._seen
        assert time.time() - engine._seen_ts["evt-old"] < SEEN_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_seen_store_persists_across_engines(self):
        e1 = CopyEngine()
        e1.client.fetch_target_activity = AsyncMock(return_value=[self._event("evt-persist")])
        await e1.poll_once()

        store_path = _seen_store_path()
        assert store_path.exists()

        e2 = CopyEngine()
        e2.client.fetch_target_activity = AsyncMock(return_value=[self._event("evt-persist")])
        signals = await e2.poll_once()

        assert len(signals) == 0


class TestPaperTraderEconomics:
    """PaperTrader must price fills from shared StrategyParams, not constants."""

    @staticmethod
    def _paper_trader() -> PaperTrader:
        policy = CopyBacktester(Settings(copy_ratio=0.5))
        return PaperTrader(policy=policy)

    def test_simulate_uses_strategy_params(self):
        trader = self._paper_trader()
        decision = trader.policy.decide(_signal(latency_ms=350))
        assert decision.should_copy is True
        assert decision.copy_size_usd == 50.0

        fill = trader.simulate(decision)

        expected = 50.0 * ((0.035 - 0.35 * 0.012) - 0.002)
        assert fill is not None
        assert fill.pnl_usd == pytest.approx(expected, abs=1e-3)

    def test_on_signal_backward_compat(self):
        trader = self._paper_trader()

        decision = trader.on_signal(_signal(latency_ms=300))

        assert decision.should_copy is True
        assert len(trader.ledger.fills) == 1


class TestPollFailureBackoff:
    """Consecutive poll failures must back off instead of flooding upstreams."""

    def test_first_failure_keeps_base_interval(self):
        assert _failure_backoff_delay(1, 0.25) == pytest.approx(0.25)

    def test_backoff_doubles_up_to_four_steps(self):
        assert _failure_backoff_delay(2, 0.25) == pytest.approx(0.5)
        assert _failure_backoff_delay(3, 0.25) == pytest.approx(1.0)
        assert _failure_backoff_delay(4, 0.25) == pytest.approx(2.0)

    def test_backoff_is_capped(self):
        assert _failure_backoff_delay(6, 0.25) == pytest.approx(4.0)
        huge = _failure_backoff_delay(50, 30.0)
        assert huge == pytest.approx(POLL_FAILURE_BACKOFF_CAP_S)

    def test_run_survives_persistent_poll_failures(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=800, poll_interval_ms=10))
        engine.client.fetch_target_activity = AsyncMock(side_effect=RuntimeError("gamma down"))

        async def _scenario():
            task = asyncio.create_task(engine.run(duration_sec=0.05))
            await asyncio.sleep(0.12)
            engine.stop()
            await task

        asyncio.run(_scenario())

        assert engine._running is False
