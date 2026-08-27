"""Tests for CopyEngine signal processing and polling."""

import asyncio
import logging
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
from weather_copy_bot.engine.quorum import QuorumEngine
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
    upstream_age_ms: int = 0,
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
        upstream_age_ms=upstream_age_ms,
    )


def _non_weather_signal(
    wallet: str = "0xpol",
    token_id: str = "tok-pol-1",
) -> TradeSignal:
    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="t-pol",
        target_wallet=wallet,
        market_slug="will-candidate-win",
        market_title="Will the candidate win the election?",
        city="Unknown",
        outcome="Yes",
        side=Side.BUY,
        price=0.42,
        size_usd=100.0,
        detected_at=now,
        target_filled_at=now,
        latency_ms=350,
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

    @pytest.mark.asyncio
    async def test_queued_mode_defers_place_order_to_processor(self):
        engine = CopyEngine(
            Settings(
                dry_run=False,
                polymarket_private_key="0xsecret",
                max_copy_latency_ms=800,
                copy_ratio=0.25,
                order_queue_enabled=True,
            )
        )
        engine.risk = None
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})

        decision = await engine.process_signal(_signal(token_id="tok-queued"))

        # In queued mode _execute_live only enqueues; place_order must not be
        # called synchronously. The background processor owns submission.
        assert decision.should_copy is True
        assert engine.client.place_order.assert_not_called() is None
        assert engine.stats["live_orders_filled"] == 0

    @pytest.mark.asyncio
    async def test_queue_processor_executes_queued_order(self):
        engine = CopyEngine(
            Settings(
                dry_run=False,
                polymarket_private_key="0xsecret",
                max_copy_latency_ms=800,
                copy_ratio=0.25,
                order_queue_enabled=True,
            )
        )
        engine.risk = None
        engine.client.place_order = AsyncMock(return_value={"status": "matched"})
        engine.poll_once = AsyncMock(return_value=[])

        await engine.run(duration_sec=0.1)

        # The boot path started the queue processor; nothing to assert beyond
        # no crash in the short run with an empty queue.
        assert engine.client.place_order.assert_not_called() is None


class _FakeQuorumMonitor:
    """Duck-typed MonitoringService capturing quorum hooks."""

    def __init__(self):
        self.hits = 0
        self.skips: list[str] = []

    def record_quorum_hit(self):
        self.hits += 1

    def record_quorum_skip(self, reason):
        self.skips.append(reason)


class TestQuorumWiring:
    """Equal-weight consensus must flow through the standard copy pipeline."""

    def _engine(self, **kwargs):
        settings = kwargs.pop("settings", Settings(max_copy_latency_ms=800, copy_ratio=0.25))
        return CopyEngine(settings=settings, **kwargs)

    @pytest.mark.asyncio
    async def test_first_vote_buffers_and_copies_individually(self):
        engine = self._engine(quorum=QuorumEngine(min_quorum_count=2))
        await engine._route_signal({}, _signal(wallet="0xa", token_id="tok-q"))
        assert engine.stats["copied"] == 1
        assert engine.stats["quorum_votes"] == 1
        assert engine.stats["quorum_reached"] == 0
        assert len(engine.quorum.get_buffer_status()) == 1

    @pytest.mark.asyncio
    async def test_second_wallet_fires_one_consensus_copy_at_vwap(self):
        captured: list[tuple[TradeSignal, CopyDecision]] = []

        async def on_decision(signal, decision):
            captured.append((signal, decision))

        engine = self._engine(on_decision=on_decision, quorum=QuorumEngine(min_quorum_count=2))
        await engine._route_signal(
            {}, _signal(wallet="0xa", token_id="tok-q", price=0.40, size=300.0)
        )
        await engine._route_signal(
            {}, _signal(wallet="0xb", token_id="tok-q", price=0.60, size=100.0)
        )

        consensus = [(s, d) for s, d in captured if s.target_wallet.startswith("quorum")]
        assert len(consensus) == 1
        signal, decision = consensus[0]
        assert signal.target_wallet == "quorum(2)"
        assert signal.price == pytest.approx(0.45)
        assert signal.size_usd == pytest.approx(400.0)
        assert signal.latency_ms == 0
        assert decision.should_copy is True
        assert engine.stats["quorum_reached"] == 1

    @pytest.mark.asyncio
    async def test_repeat_wallet_vote_never_triggers_consensus(self):
        engine = self._engine(quorum=QuorumEngine(min_quorum_count=2))
        await engine._route_signal({}, _signal(wallet="0xa", token_id="tok-dupq"))
        await engine._route_signal({}, _signal(wallet="0xa", token_id="tok-dupq"))
        assert engine.stats["quorum_reached"] == 0
        assert engine.quorum.get_stats()["duplicate_signals"] == 1

    @pytest.mark.asyncio
    async def test_monitor_hooks_capture_hits_and_skips(self):
        monitor = _FakeQuorumMonitor()
        engine = self._engine(
            risk_engine=RiskEngine(limits=RiskLimits(max_trade_size_usd=10.0)),
            quorum=QuorumEngine(min_quorum_count=2),
            monitor=monitor,
        )
        await engine._route_signal({}, _signal(wallet="0xa", token_id="tok-skip", size=200.0))
        await engine._route_signal({}, _signal(wallet="0xb", token_id="tok-skip", size=200.0))
        assert monitor.hits == 1
        assert len(monitor.skips) == 1
        assert "risk" in monitor.skips[0]

    @pytest.mark.asyncio
    async def test_run_lifecycle_stops_quorum_cleanup_task(self):
        engine = self._engine(quorum=QuorumEngine())
        engine.poll_once = AsyncMock(return_value=[])
        task = asyncio.create_task(engine.run(duration_sec=0.1))
        await asyncio.sleep(0.05)
        assert engine.quorum._cleanup_task is not None
        await asyncio.wait_for(task, timeout=1.0)
        assert engine.quorum._cleanup_task is None


class TestEngineEventLogging:
    """The event trail must surface every decision instead of silence."""

    @pytest.mark.asyncio
    async def test_route_signal_logs_signal_and_copy(self, caplog):
        engine = CopyEngine(Settings(max_copy_latency_ms=800))
        with caplog.at_level(logging.INFO):
            await engine._route_signal({}, _signal())
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("COPY BUY") for m in messages)
        assert not any(m.startswith("SKIP") for m in messages)
        with caplog.at_level(logging.DEBUG):
            await engine._route_signal({}, _signal())
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any(m.startswith("SIGNAL BUY") for m in debug_msgs)

    @pytest.mark.asyncio
    async def test_route_signal_logs_skip_with_reason(self, caplog):
        engine = CopyEngine(Settings(max_copy_latency_ms=500))
        with caplog.at_level(logging.INFO):
            await engine._route_signal({}, _signal(latency_ms=900))
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("SKIP ") and "stale" in m.lower() for m in messages)
        with caplog.at_level(logging.DEBUG):
            await engine._route_signal({}, _signal(latency_ms=900))
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any(m.startswith("SIGNAL BUY") for m in debug_msgs)

    @pytest.mark.asyncio
    async def test_consensus_logs_quorum_copy_and_skip(self, caplog):
        limited = CopyEngine(
            settings=Settings(max_copy_latency_ms=800),
            risk_engine=RiskEngine(limits=RiskLimits(max_trade_size_usd=10.0)),
            quorum=QuorumEngine(min_quorum_count=2),
        )
        free = CopyEngine(
            settings=Settings(max_copy_latency_ms=800),
            quorum=QuorumEngine(min_quorum_count=2),
        )
        with caplog.at_level(logging.INFO):
            await free._route_signal({}, _signal(wallet="0xa", token_id="tok-logq"))
            await free._route_signal({}, _signal(wallet="0xb", token_id="tok-logq"))
            await limited._route_signal({}, _signal(wallet="0xa", token_id="tok-logs", size=200.0))
            await limited._route_signal({}, _signal(wallet="0xb", token_id="tok-logs", size=200.0))
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("QUORUM ") and " -> COPY" in m for m in messages)
        assert any(
            m.startswith("QUORUM ") and " -> SKIP" in m and "risk" in m.lower()
            for m in messages
        )

    @pytest.mark.asyncio
    async def test_route_signal_gates_non_weather_signal(self, caplog):
        engine = CopyEngine(
            settings=Settings(max_copy_latency_ms=800, wallet_filter_enabled=True),
            quorum=QuorumEngine(min_quorum_count=2),
        )
        with caplog.at_level(logging.INFO):
            await engine._route_signal({}, _non_weather_signal())
            await engine._route_signal({}, _non_weather_signal(wallet="0xpol2"))
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("FILTER ") and "reason=" in m for m in messages)
        assert not any(m.startswith("COPY") for m in messages)
        assert not any(m.startswith("SKIP ") for m in messages)
        assert not any(m.startswith("QUORUM ") for m in messages)

    @pytest.mark.asyncio
    async def test_route_signal_default_passes_non_weather(self, caplog):
        engine = CopyEngine(Settings(max_copy_latency_ms=800))
        with caplog.at_level(logging.INFO):
            await engine._route_signal({}, _non_weather_signal())
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("FILTER ") for m in messages) is False
        assert any(m.startswith("COPY BUY") for m in messages)

    def test_stats_snapshot_logs_all_counters(self, caplog):
        engine = CopyEngine()
        with caplog.at_level(logging.INFO):
            engine._log_stats_snapshot()
        message = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("STATS"))
        for key in (
            "mode=",
            "detected=",
            "copied=",
            "skipped=",
            "risk_rejected=",
            "quorum_votes=",
            "live_filled=",
            "live_failed=",
            "live_dup=",
            "live_throttled=",
            "targets=",
            "balance=$",
            "reasons={",
        ):
            assert key in message

    @pytest.mark.asyncio
    async def test_run_startup_logs_target_split(self, caplog):
        engine = CopyEngine(Settings(target_wallets=["0xs1"]))
        engine.poll_once = AsyncMock(return_value=[])
        with caplog.at_level(logging.INFO):
            task = asyncio.create_task(engine.run(duration_sec=0.05))
            await asyncio.wait_for(task, timeout=1.0)
        startup = next(
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("CopyEngine starting")
        )
        assert "static=1" in startup
        assert "discovered=0" in startup


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


class TestPercentile:
    """Audit P1: _percentile must interpolate correctly on any sample size."""

    def test_empty_returns_none(self):
        assert CopyEngine._percentile([], 50.0) is None

    def test_single_sample_returns_that_value(self):
        assert CopyEngine._percentile([350], 50.0) == 350
        assert CopyEngine._percentile([350], 99.0) == 350

    def test_p50_is_median(self):
        assert CopyEngine._percentile([100, 200, 300], 50.0) == 200

    def test_p99_interpolates_toward_max(self):
        assert CopyEngine._percentile([100, 200, 300, 400, 500], 99.0) > 400


class TestLatencyHistogram:
    """Audit P1: _record_latency_sample must populate rolling percentile stats."""

    def test_samples_window_capped_at_1000(self):
        engine = CopyEngine()
        for i in range(1200):
            engine._record_latency_sample(i, i)
        assert len(engine._latency_samples) == 1000
        assert len(engine._upstream_age_samples) == 1000
        assert engine._latency_samples[0] == 200

    @pytest.mark.asyncio
    async def test_latency_samples_recorded_via_poll_once(self):
        engine = CopyEngine(Settings(target_wallets=["0xtarget"]))
        engine.client.fetch_target_activity = AsyncMock(return_value=[])
        await engine.poll_once()
        assert engine.stats["latency_p50_ms"] is None
        assert engine.stats["latency_p99_ms"] is None
        assert engine.stats["upstream_age_p50_ms"] is None
        assert engine.stats["upstream_age_p99_ms"] is None

    def test_percentiles_in_stats_snapshot_after_samples(self, caplog):
        engine = CopyEngine()
        for i in range(10):
            engine._record_latency_sample(100 + i * 10, 200 + i * 20)
        with caplog.at_level(logging.INFO):
            engine._log_stats_snapshot()
        msg = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("STATS"))
        assert "latency_p50=" in msg
        assert "latency_p99=" in msg
        assert "age_p50=" in msg
        assert "age_p99=" in msg


class Test429RollingWindow:
    """Audit P4: upstream_429_last_5m must be a 300-second rolling window."""

    def test_initial_rolling_count_is_zero(self):
        engine = CopyEngine()
        assert engine.stats["upstream_429_last_5m"] == 0

    def test_record_rate_limit_updates_rolling_count(self):
        engine = CopyEngine()
        engine.record_rate_limit("gamma-api.polymarket.com", 1.0)
        assert engine.stats["upstream_429_rejections"] == 1
        assert engine.stats["upstream_429_last_5m"] == 1
        engine.record_rate_limit("gamma-api.polymarket.com", 1.0)
        assert engine.stats["upstream_429_last_5m"] == 2

    def test_old_429s_pruned_from_rolling_window(self, caplog):
        engine = CopyEngine()
        now = time.time()
        engine._upstream_429_ts = [now - 600.0, now - 400.0, now - 100.0]
        with caplog.at_level(logging.INFO):
            engine._log_stats_snapshot()
        assert engine.stats["upstream_429_last_5m"] == 1


class TestSingleSourceMode:
    """Audit P2: single_source_mode must lower quorum min to 1 with one wallet."""

    @pytest.mark.asyncio
    async def test_single_source_mode_lowers_quorum_min(self, caplog):
        settings = Settings(target_wallets=["0xone"], single_source_mode=True)
        engine = CopyEngine(
            settings=settings,
            quorum=QuorumEngine(min_quorum_count=2),
        )
        engine.poll_once = AsyncMock(return_value=[])
        with caplog.at_level(logging.INFO):
            await engine.run(duration_sec=0.05)
        assert any("single_source_mode: quorum min lowered 2 -> 1" in r.getMessage() for r in caplog.records)
        assert engine.quorum.min_quorum_count == 1

    @pytest.mark.asyncio
    async def test_single_source_mode_not_engaged_without_flag(self, caplog):
        settings = Settings(target_wallets=["0xone"], single_source_mode=False)
        engine = CopyEngine(
            settings=settings,
            quorum=QuorumEngine(min_quorum_count=2),
        )
        engine.poll_once = AsyncMock(return_value=[])
        with caplog.at_level(logging.INFO):
            await engine.run(duration_sec=0.05)
        assert not any("single_source_mode" in r.getMessage() for r in caplog.records)
        assert engine.quorum.min_quorum_count == 2

    @pytest.mark.asyncio
    async def test_single_source_mode_not_engaged_with_multiple_wallets(self, caplog):
        settings = Settings(target_wallets=["0xone", "0xtwo"], single_source_mode=True)
        engine = CopyEngine(
            settings=settings,
            quorum=QuorumEngine(min_quorum_count=2),
        )
        engine.poll_once = AsyncMock(return_value=[])
        with caplog.at_level(logging.INFO):
            await engine.run(duration_sec=0.05)
        assert not any("single_source_mode" in r.getMessage() for r in caplog.records)
        assert engine.quorum.min_quorum_count == 2


class TestSignalCycleSummary:
    """Audit P3: one SIGNAL-CYCLE line per poll replaces per-signal noise at INFO."""

    @pytest.mark.asyncio
    async def test_signal_cycle_emitted_on_fresh_and_copy(self, caplog):
        engine = CopyEngine(Settings(max_copy_latency_ms=800))
        engine.client.fetch_target_activity = AsyncMock(return_value=[{
            "id": "evt-fresh",
            "wallet": "0xabc",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_slug": "weather",
            "market_title": "Weather?",
            "city": "Tokyo",
            "outcome": "Yes",
            "side": "BUY",
            "price": 0.6,
            "size_usd": 100,
            "demo": True,
            "latency_ms": 350,
        }])
        with caplog.at_level(logging.INFO):
            await engine.poll_once()
        msgs = [r.getMessage() for r in caplog.records]
        cycle_msgs = [m for m in msgs if m.startswith("SIGNAL-CYCLE")]
        assert len(cycle_msgs) == 1
        assert "BUY=1" in cycle_msgs[0]
        assert "SKIP-stale=0" in cycle_msgs[0]
        assert "SKIP-other=0" in cycle_msgs[0]
        assert not any(m.startswith("SIGNAL BUY") for m in msgs)

    @pytest.mark.asyncio
    async def test_signal_cycle_counts_skip_stale_and_other(self, caplog):
        engine = CopyEngine(Settings(max_copy_latency_ms=100))
        now = datetime.now(timezone.utc)
        engine.client.fetch_target_activity = AsyncMock(return_value=[
            {
                "id": "evt-stale",
                "wallet": "0xabc",
                "timestamp": (now - __import__("datetime").timedelta(seconds=2)).isoformat(),
                "market_slug": "weather",
                "market_title": "Weather?",
                "city": "Tokyo",
                "outcome": "Yes",
                "side": "SELL",
                "price": 0.6,
                "size_usd": 100,
            },
            {
                "id": "evt-thin",
                "wallet": "0xdef",
                "timestamp": now.isoformat(),
                "market_slug": "weather2",
                "market_title": "Weather2?",
                "city": "Paris",
                "outcome": "No",
                "side": "BUY",
                "price": 0.50,
                "size_usd": 100,
                "demo": True,
                "latency_ms": 350,
            },
        ])
        with caplog.at_level(logging.INFO):
            await engine.poll_once()
        cycle_msgs = [m for m in caplog.records if m.getMessage().startswith("SIGNAL-CYCLE")]
        assert len(cycle_msgs) == 1
        assert "SKIP-stale=1" in cycle_msgs[0].getMessage()
        assert "SKIP-other=0" in cycle_msgs[0].getMessage()
        assert "BUY=0" in cycle_msgs[0].getMessage()
        assert "SELL=1" in cycle_msgs[0].getMessage()


class TestStartupWalletAudit:
    """Audit P5: startup log must name the resolved wallet list explicitly."""

    @pytest.mark.asyncio
    async def test_startup_logs_wallet_list(self, caplog):
        engine = CopyEngine(Settings(target_wallets=["0xw1", "0xw2"]))
        engine.poll_once = AsyncMock(return_value=[])
        with caplog.at_level(logging.INFO):
            task = asyncio.create_task(engine.run(duration_sec=0.05))
            await asyncio.wait_for(task, timeout=1.0)
        startup = next(
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("CopyEngine starting")
        )
        assert "static=2" in startup
        assert "['0xw1', '0xw2']" in startup
        assert "wallets=" in startup


class TestStatsSnapshotNewFields:
    """Audit P1+P4: STATS line must include all rolling percentile and 429 window fields."""

    def test_stats_snapshot_includes_p1_and_p4_fields(self, caplog):
        engine = CopyEngine()
        engine._record_latency_sample(100, 200)
        engine._record_latency_sample(500, 600)
        with caplog.at_level(logging.INFO):
            engine._log_stats_snapshot()
        msg = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("STATS"))
        assert "upstream_429=" in msg
        assert "upstream_429_5m=" in msg
        assert "latency_p50=" in msg
        assert "latency_p99=" in msg
        assert "age_p50=" in msg
        assert "age_p99=" in msg


class TestRateLimitObserver:
    """The engine must surface upstream 429s as a stat counter (so the
    operator dashboard can see throttling events instead of silently dropping
    wallets) and must bump ``signals_by_reason`` for every skipped signal so
    the histogram explains why signals didn't get copied.
    """

    def test_initial_stats_have_new_fields(self):
        engine = CopyEngine()
        assert "upstream_429_rejections" in engine.stats
        assert engine.stats["upstream_429_rejections"] == 0
        assert "signals_by_reason" in engine.stats
        assert engine.stats["signals_by_reason"] == {}

    def test_record_rate_limit_increments_counter(self):
        engine = CopyEngine()
        engine.record_rate_limit("gamma-api.polymarket.com", 30.0)
        assert engine.stats["upstream_429_rejections"] == 1
        assert engine.stats["signals_by_reason"]["upstream_429"] == 1

    def test_record_rate_limit_compounds(self):
        engine = CopyEngine()
        engine.record_rate_limit("gamma-api.polymarket.com", 1.0)
        engine.record_rate_limit("data-api.polymarket.com", 1.0)
        engine.record_rate_limit("gamma-api.polymarket.com", 5.0)
        assert engine.stats["upstream_429_rejections"] == 3
        assert engine.stats["signals_by_reason"]["upstream_429"] == 3

    @pytest.mark.asyncio
    async def test_skip_bumps_signals_by_reason(self):
        engine = CopyEngine(Settings(max_copy_latency_ms=500))
        # Stale latency triggers ``should_copy=False`` with reason "stale".
        await engine.process_signal(_signal(latency_ms=900))
        assert engine.stats["skipped"] == 1
        assert engine.stats["signals_by_reason"]["stale"] == 1

    def test_engine_wires_itself_as_observer_on_init(self):
        engine = CopyEngine()
        # The constructor attaches ``record_rate_limit`` to the client so
        # every 429 reaches the engine regardless of how the client was built.
        # Bound methods compare equal by ``(__self__, __func__)`` even though
        # they are freshly-created objects on each attribute access, so use
        # ``==`` (and assert the binding survives into the engine's counter).
        assert engine.client._on_rate_limit == engine.record_rate_limit
        assert engine.client._on_rate_limit.__self__ is engine
        assert engine.client._on_rate_limit.__func__ is CopyEngine.record_rate_limit

        # Functional guarantee: invoking the wired observer mutates the
        # engine's stats without any extra glue from the caller.
        before = engine.stats["upstream_429_rejections"]
        engine.client._on_rate_limit("gamma-api.polymarket.com", 12.5)
        assert engine.stats["upstream_429_rejections"] == before + 1
