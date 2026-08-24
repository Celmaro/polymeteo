"""Low-latency copy engine for Polymarket weather markets.

Design goals:
1. Detect target wallet fills as early as possible
2. Reject stale signals beyond max_copy_latency_ms
3. Size with copy_ratio + hard risk caps
4. Paper by default; live only when DRY_RUN=false and keys exist
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from weather_copy_bot.backtest.engine import CopyBacktester
from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.models import CopyDecision, Side, TradeSignal
from weather_copy_bot.paper.trader import PaperTrader
from weather_copy_bot.polymarket.client import PolymarketClient

logger = logging.getLogger(__name__)

SignalHandler = Callable[[TradeSignal, CopyDecision], Awaitable[None]]


class CopyEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        client: PolymarketClient | None = None,
        on_decision: SignalHandler | None = None,
    ):
        self.settings = settings or get_settings()
        self.client = client or PolymarketClient(self.settings)
        self.policy = CopyBacktester(self.settings)
        self.paper = PaperTrader(self.settings)
        self.on_decision = on_decision
        self._seen: set[str] = set()
        self._running = False
        self.stats = {
            "signals_detected": 0,
            "copied": 0,
            "skipped": 0,
            "avg_latency_ms": 0.0,
            "last_heartbeat": None,
        }

    @property
    def mode(self) -> str:
        if self.settings.live_trading_enabled:
            return "live"
        return "paper"

    async def process_signal(self, signal: TradeSignal) -> CopyDecision:
        self.stats["signals_detected"] += 1
        decision = self.policy.decide(signal)
        if not decision.should_copy:
            self.stats["skipped"] += 1
            if self.on_decision:
                await self.on_decision(signal, decision)
            return decision

        if self.mode == "paper":
            decision = self.paper.on_signal(signal)
        else:
            await self._execute_live(decision)

        self.stats["copied"] += 1
        n = self.stats["copied"]
        prev = self.stats["avg_latency_ms"]
        self.stats["avg_latency_ms"] = prev + (signal.latency_ms - prev) / n

        if self.on_decision:
            await self.on_decision(signal, decision)
        return decision

    async def _execute_live(self, decision: CopyDecision) -> None:
        signal = decision.signal
        logger.info(
            "LIVE COPY %s %s $%.2f @ %.3f latency=%sms",
            signal.side.value,
            signal.market_slug,
            decision.copy_size_usd,
            signal.price,
            signal.latency_ms,
        )
        await self.client.place_order(
            token_id=signal.token_id or "",
            side=signal.side.value,
            price=signal.price,
            size_usd=decision.copy_size_usd,
        )

    async def poll_once(self) -> list[TradeSignal]:
        """Poll target activity and convert fresh fills into copy signals."""
        started = time.perf_counter()
        events = await self.client.fetch_target_activity(
            wallets=self.settings.target_wallets or self.client.default_demo_wallets(),
            market_filter=self.settings.market_filter,
        )
        fresh: list[TradeSignal] = []
        now = datetime.now(timezone.utc)
        for event in events:
            key = event.get("id") or f"{event.get('wallet')}:{event.get('timestamp')}:{event.get('market')}"
            if key in self._seen:
                continue
            self._seen.add(key)
            target_filled = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            latency_ms = int((now - target_filled).total_seconds() * 1000)
            # When using demo stream, inject realistic detect latency
            if event.get("demo"):
                latency_ms = int(event.get("latency_ms", 420))
            signal = TradeSignal(
                signal_id=str(uuid.uuid4()),
                target_wallet=event["wallet"],
                market_slug=event["market_slug"],
                market_title=event.get("market_title", event["market_slug"]),
                city=event.get("city", "Unknown"),
                outcome=event.get("outcome", "Yes"),
                side=Side(event.get("side", "BUY")),
                price=float(event.get("price", 0.5)),
                size_usd=float(event.get("size_usd", 50)),
                detected_at=now,
                target_filled_at=target_filled,
                latency_ms=latency_ms,
                token_id=event.get("token_id"),
            )
            fresh.append(signal)
            await self.process_signal(signal)

        self.stats["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.debug("poll_once processed=%s elapsed_ms=%.1f", len(fresh), elapsed_ms)
        return fresh

    async def run(self, duration_sec: float | None = None) -> None:
        self._running = True
        logger.info(
            "CopyEngine starting mode=%s targets=%s max_latency=%sms",
            self.mode,
            len(self.settings.target_wallets) or "demo",
            self.settings.max_copy_latency_ms,
        )
        started = time.time()
        interval = self.settings.poll_interval_ms / 1000.0
        while self._running:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("poll_once failed")
            if duration_sec is not None and (time.time() - started) >= duration_sec:
                break
            await asyncio.sleep(interval)
        self._running = False

    def stop(self) -> None:
        self._running = False
