"""Low-latency copy engine for Polymarket weather markets.

Design goals:
1. Detect target wallet fills as early as possible
2. Reject stale signals beyond max_copy_latency_ms
3. Size with copy_ratio + hard risk caps
4. Paper by default; live only when DRY_RUN=false and keys exist
5. Feed realized P&L back into the risk engine (breakers see live state)
6. Route live orders through OrderQueue (dedup + rate limit + state machine)
7. Persist the seen-event set across restarts with TTL pruning
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from weather_copy_bot.backtest.engine import CopyBacktester
from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.engine.order_queue import OrderQueue
from weather_copy_bot.live.risk_engine import Position, RiskEngine
from weather_copy_bot.models import CopyDecision, Side, TradeSignal
from weather_copy_bot.paper.trader import PaperTrader
from weather_copy_bot.polymarket.client import PolymarketClient

logger = logging.getLogger(__name__)

SignalHandler = Callable[[TradeSignal, CopyDecision], Awaitable[None]]

# Seen-set hygiene: entries expire after an hour and the store is capped so a
# long-running process cannot grow its dedup set without bound.
SEEN_TTL_SECONDS = 3600.0
SEEN_MAX_ENTRIES = 10_000
SEEN_FILE_NAME = "copy_seen.json"

# Poll-failure backoff: a hard-down upstream must not flood logs at the poll
# interval (250ms by default), so consecutive failures grow the sleep up to a cap.
POLL_FAILURE_BACKOFF_CAP_S = 5.0


def _failure_backoff_delay(failures: int, base_interval_s: float) -> float:
    """Exponential backoff after consecutive poll failures, capped at 5s."""
    doubled = base_interval_s * (2 ** min(max(failures - 1, 0), 4))
    return min(doubled, POLL_FAILURE_BACKOFF_CAP_S)


def _seen_store_path() -> Path:
    root = Path(os.environ.get("APP_ROOT", "/app"))
    return root / "data" / SEEN_FILE_NAME


class CopyEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        client: PolymarketClient | None = None,
        on_decision: SignalHandler | None = None,
        risk_engine: RiskEngine | None = None,
    ):
        self.settings = settings or get_settings()
        self.client = client or PolymarketClient(self.settings)
        self.policy = CopyBacktester(self.settings)
        self.paper = PaperTrader(self.settings, policy=self.policy)
        self.order_queue = OrderQueue()
        self.risk: RiskEngine | None = risk_engine or RiskEngine()
        self.on_decision = on_decision

        # Engine-owned account state, folded back into the risk engine after
        # every fill so breakers/daily-loss/exposure checks see reality.
        self._balance = float(self.settings.paper_starting_balance)
        self._daily_pnl = 0.0
        self._day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._open_positions: dict[str, Position] = {}

        # Dedup state: `_seen` must stay a plain set; timestamps plus on-disk
        # persistence live alongside it.
        self._seen: set[str] = set()
        self._seen_ts: dict[str, float] = {}
        self._seen_loaded = False

        self._running = False
        self._started_at: float | None = None
        self.stats = {
            "signals_detected": 0,
            "copied": 0,
            "skipped": 0,
            "avg_latency_ms": 0.0,
            "last_heartbeat": None,
            "risk_rejections": 0,
            "live_orders_filled": 0,
            "live_orders_failed": 0,
            "live_orders_duplicated": 0,
            "live_orders_throttled": 0,
        }

    @property
    def mode(self) -> str:
        if self.settings.live_trading_enabled:
            return "live"
        return "paper"

    async def process_signal(self, signal: TradeSignal) -> CopyDecision:
        self.stats["signals_detected"] += 1

        decision = self.policy.decide(signal)
        self._apply_risk_gate(decision)

        if decision.should_copy:
            if self.mode == "paper":
                fill = self.paper.simulate(decision)
                if fill is not None:
                    self._record_fill_outcome(
                        market_slug=fill.market_slug,
                        side=fill.side,
                        price=fill.price,
                        size=fill.size_usd,
                        pnl=fill.pnl_usd,
                    )
            else:
                result = await self._execute_live(decision)
                status = result.get("status")
                if status == "duplicate":
                    decision.should_copy = False
                    decision.reason = "order_duplicate"
                elif status == "rate_limited":
                    decision.should_copy = False
                    decision.reason = "order_rate_limited"
                elif status != "error":
                    # Live P&L settles later; record exposure immediately so
                    # caps and trade counters include in-flight copies.
                    self._record_fill_outcome(
                        market_slug=signal.market_slug,
                        side=signal.side,
                        price=signal.price,
                        size=decision.copy_size_usd,
                        pnl=0.0,
                    )

        if not decision.should_copy:
            self.stats["skipped"] += 1
        else:
            self.stats["copied"] += 1
            n = self.stats["copied"]
            prev = self.stats["avg_latency_ms"]
            self.stats["avg_latency_ms"] = prev + (signal.latency_ms - prev) / n

        if self.on_decision:
            await self.on_decision(signal, decision)
        return decision

    def _apply_risk_gate(self, decision: CopyDecision) -> None:
        """Two-tier gate: hard size limits first, then full trade checks."""
        if self.risk is None or not decision.should_copy:
            return
        self._maybe_reset_day()

        size_check = self.risk.check_size_limits(decision.copy_size_usd)
        if size_check.rejected:
            self._reject(decision, size_check.reason)
            return

        check = self.risk.check_trade(
            signal=decision.signal,
            size_usd=decision.copy_size_usd,
            balance=self._balance,
            daily_pnl=self._daily_pnl,
            positions=list(self._open_positions.values()),
        )
        if check.rejected:
            self._reject(decision, check.reason)
            return

        if check.adjustment is not None and check.adjustment < decision.copy_size_usd:
            clamped = round(check.adjustment, 2)
            if clamped < self.risk.limits.min_trade_size_usd:
                self._reject(decision, f"clamp_below_min:{clamped}")
                return
            logger.info(
                "Risk engine clamped copy size %.2f -> %.2f (%s)",
                decision.copy_size_usd,
                clamped,
                check.reason,
            )
            decision.copy_size_usd = clamped

    def _reject(self, decision: CopyDecision, reason: str) -> None:
        logger.warning("Copy blocked by risk engine: %s", reason)
        decision.should_copy = False
        decision.reason = f"risk_rejected:{reason}"
        self.stats["risk_rejections"] += 1

    def _maybe_reset_day(self) -> None:
        """Reset local daily counters alongside the risk engine's own reset."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day_key:
            logger.info("Resetting CopyEngine daily counters for %s", today)
            self._daily_pnl = 0.0
            self._open_positions.clear()
            self._day_key = today

    def _record_fill_outcome(
        self,
        *,
        market_slug: str,
        side: Side,
        price: float,
        size: float,
        pnl: float,
    ) -> None:
        """Fold a realized fill back into account state and the risk engine."""
        self._maybe_reset_day()
        self._balance += pnl
        self._daily_pnl += pnl

        existing = self._open_positions.get(market_slug)
        if side == Side.BUY:
            if existing is None:
                self._open_positions[market_slug] = Position(
                    market_slug=market_slug,
                    side=side,
                    size_usd=size,
                    entry_price=price,
                    current_price=price,
                )
            else:
                existing.size_usd += size
                existing.current_price = price
        elif existing is not None:
            existing.size_usd -= size
            existing.current_price = price
            if existing.size_usd <= 0:
                del self._open_positions[market_slug]

        if self.risk is not None:
            self.risk.update_balance(self._balance, self._daily_pnl)
            self.risk.update_positions(list(self._open_positions.values()))
            self.risk.record_trade(pnl)

    async def _execute_live(self, decision: CopyDecision) -> dict:
        signal = decision.signal
        logger.info(
            "LIVE COPY %s %s $%.2f @ %.3f latency=%sms",
            signal.side.value,
            signal.market_slug,
            decision.copy_size_usd,
            signal.price,
            signal.latency_ms,
        )
        order_id = await self.order_queue.enqueue(
            token_id=signal.token_id or "",
            side=signal.side.value,
            size_usd=decision.copy_size_usd,
            price=signal.price,
            metadata={"signal_id": signal.signal_id, "market_slug": signal.market_slug},
        )
        if order_id is None:
            self.stats["live_orders_duplicated"] += 1
            logger.warning(
                "LIVE COPY DUPLICATE %s %s (recent order for same token/side)",
                signal.side.value,
                signal.market_slug,
            )
            return {"status": "duplicate"}

        if not await self.order_queue.submit(order_id):
            await self.order_queue.mark_cancelled(order_id, "rate_limited")
            self.stats["live_orders_throttled"] += 1
            logger.warning("LIVE COPY THROTTLED order=%s (rate limit)", order_id)
            return {"status": "rate_limited"}

        try:
            result = await self.client.place_order(
                token_id=signal.token_id or "",
                side=signal.side.value,
                price=signal.price,
                size_usd=decision.copy_size_usd,
            )
        except Exception as exc:
            self.stats["live_orders_failed"] += 1
            await self.order_queue.mark_failed(order_id, str(exc))
            logger.exception(
                "LIVE COPY FAILED %s %s: %s", signal.side.value, signal.market_slug, exc
            )
            return {"status": "error", "error": str(exc)}
        await self.order_queue.mark_filled(order_id)
        self.stats["live_orders_filled"] += 1
        return result if isinstance(result, dict) else {"status": "filled"}

    async def poll_once(self) -> list[TradeSignal]:
        """Poll target activity and convert fresh fills into copy signals."""
        started = time.perf_counter()
        self._load_seen()
        now_ts = time.time()
        self._prune_seen(now_ts)
        events = await self.client.fetch_target_activity(
            wallets=self.settings.target_wallets or self.client.default_demo_wallets(),
            market_filter=self.settings.market_filter,
        )
        fresh: list[TradeSignal] = []
        now = datetime.now(timezone.utc)
        for event in events:
            key = (
                event.get("id")
                or f"{event.get('wallet')}:{event.get('timestamp')}:{event.get('market')}"
            )
            if key in self._seen:
                continue
            self._remember(key, now_ts)
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
        self._save_seen()
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.debug("poll_once processed=%s elapsed_ms=%.1f", len(fresh), elapsed_ms)
        return fresh

    def _remember(self, key: str, ts: float) -> None:
        self._seen.add(key)
        self._seen_ts[key] = ts
        while len(self._seen_ts) > SEEN_MAX_ENTRIES:
            oldest = min(self._seen_ts, key=lambda k: self._seen_ts[k])
            del self._seen_ts[oldest]
            self._seen.discard(oldest)

    def _prune_seen(self, now_ts: float) -> None:
        expired = [k for k, ts in self._seen_ts.items() if now_ts - ts > SEEN_TTL_SECONDS]
        for key in expired:
            del self._seen_ts[key]
            self._seen.discard(key)
        if expired:
            logger.debug("Pruned %s expired seen ids", len(expired))

    def _load_seen(self) -> None:
        """Load persisted seen-event ids once per engine lifetime."""
        if self._seen_loaded:
            return
        self._seen_loaded = True
        path = _seen_store_path()
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
                loaded = time.time()
                for key, ts in entries.items():
                    if loaded - float(ts) <= SEEN_TTL_SECONDS:
                        self._remember(key, float(ts))
                logger.debug("Loaded %s seen ids from %s", len(self._seen), path)
        except Exception:
            logger.warning("Failed to load seen store at %s", path, exc_info=True)

    def _save_seen(self) -> None:
        """Persist seen ids atomically; never crash the trading loop."""
        path = _seen_store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"saved_at": time.time(), "entries": self._seen_ts}
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            logger.warning("Failed to persist seen store at %s", path, exc_info=True)

    async def run(self, duration_sec: float | None = None) -> None:
        self._running = True
        self._started_at = time.time()
        logger.info(
            "CopyEngine starting mode=%s targets=%s max_latency=%sms",
            self.mode,
            len(self.settings.target_wallets) or "demo",
            self.settings.max_copy_latency_ms,
        )
        started = time.time()
        interval = self.settings.poll_interval_ms / 1000.0
        consecutive_failures = 0
        while self._running:
            try:
                await self.poll_once()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                delay = _failure_backoff_delay(consecutive_failures, interval)
                logger.exception(
                    "poll_once failed consecutive=%s backing_off=%.2fs",
                    consecutive_failures,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            if duration_sec is not None and (time.time() - started) >= duration_sec:
                break
            await asyncio.sleep(interval)
        self._running = False

    def stop(self) -> None:
        self._running = False
