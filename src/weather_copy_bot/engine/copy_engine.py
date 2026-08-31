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
from typing import TYPE_CHECKING, ClassVar

from weather_copy_bot.backtest.engine import CopyBacktester
from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.engine.order_queue import Order, OrderQueue
from weather_copy_bot.engine.quorum import QuorumEngine, QuorumResult, WalletTradeSignal
from weather_copy_bot.engine.wallet_discovery import MergedTargetProvider
from weather_copy_bot.live.risk_engine import Position, RiskEngine
from weather_copy_bot.live.wallet_filter import WeatherWalletFilter
from weather_copy_bot.models import CopyDecision, Side, TradeSignal
from weather_copy_bot.paper.trader import PaperTrader
from weather_copy_bot.polymarket.client import PolymarketClient
from weather_copy_bot.polymarket.ws_client import CLOBWebSocket, TradeUpdate

if TYPE_CHECKING:
    from weather_copy_bot.ops.monitoring import MonitoringService

logger = logging.getLogger(__name__)

SignalHandler = Callable[[TradeSignal, CopyDecision], Awaitable[None]]

# Seen-set hygiene: entries expire after an hour and the store is capped so a
# long-running process cannot grow its dedup set without bound.
SEEN_TTL_SECONDS = 3600.0
SEEN_MAX_ENTRIES = 10_000
SEEN_FILE_NAME = "copy_seen.json"
SEEN_SAVE_INTERVAL_S = 60.0

# Poll-failure backoff: a hard-down upstream must not flood logs at the poll
# interval (250ms by default), so consecutive failures grow the sleep up to a cap.
POLL_FAILURE_BACKOFF_CAP_S = 5.0

# Periodic one-line summary cadence; keeps quiet stretches observable without
# spamming per-poll noise on top of the per-signal event trail.
STATS_LOG_INTERVAL_S = 60.0

# WS boot bound: the engine degrades to polling when the socket is slow or
# unreachable, so the connect must never block engine startup without limit.
WS_CONNECT_TIMEOUT_S = 5.0


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
        target_provider: MergedTargetProvider | None = None,
        quorum: QuorumEngine | None = None,
        monitor: MonitoringService | None = None,
    ):
        self.settings = settings or get_settings()
        self.client = client or PolymarketClient(self.settings)
        self.policy = CopyBacktester(self.settings)
        self.paper = PaperTrader(self.settings, policy=self.policy)
        self.order_queue = OrderQueue()
        self.risk: RiskEngine | None = risk_engine or RiskEngine()
        self.on_decision = on_decision
        # When set, the polling rotation comes from the provider each cycle
        # (static TARGET_WALLETS merged with promoted discoveries); when None,
        # behavior stays exactly as before (settings, else demo fallback).
        self.target_provider = target_provider
        # Optional consensus layer: distinct wallet votes on the same token/side
        # aggregate and fire exactly once at quorum. The optional monitor gets
        # quorum hit/skip hooks; both are duck-typed to keep tests light.
        self.quorum = quorum
        self.monitor = monitor
        # Optional weather-keyword gate applied before copy AND before the
        # quorum vote so a non-weather fill can neither trade nor influence
        # consensus. Only consulted when settings.wallet_filter_enabled.
        self.wallet_filter = WeatherWalletFilter()
        # Market context per consensus key so the consensus signal minted when
        # wallet B completes the quorum still carries market A's metadata.
        self._quorum_meta: dict[str, dict[str, str]] = {}

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
        self._last_seen_save: float = 0.0

        self._running = False
        self._started_at: float | None = None
        self._ws: CLOBWebSocket | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._ws_subscriptions: set[str] = set()
        self.stats = {
            "signals_detected": 0,
            "copied": 0,
            "skipped": 0,
            "avg_latency_ms": 0.0,
            "last_heartbeat": None,
            "risk_rejections": 0,
            "quorum_votes": 0,
            "quorum_reached": 0,
            "quorum_rejected": 0,
            # Events dropped during poll_once parsing (bad timestamps, missing
            # ids, malformed fields); they are never marked seen so a later
            # well-formed delivery of the same event can still be processed.
            "malformed_events": 0,
            # NOTE: ``live_orders_*`` counters are only meaningful when
            # ``settings.live_trading_enabled`` is True (i.e. dry_run=False AND
            # a private key is configured). In paper mode the submission path
            # is skipped entirely, so these will read 0/0/0/0 even on a busy
            # session. Always cross-check with ``stats["dry_run"]`` or the
            # ``live_trading_enabled`` field in /api/engine/status before
            # interpreting a "0" as "nothing went wrong".
            "live_orders_filled": 0,
            "live_orders_failed": 0,
            "live_orders_duplicated": 0,
            "live_orders_throttled": 0,
            "dry_run": True,
            "upstream_429_rejections": 0,
            # Audit P4: 5-minute rolling count of upstream 429s. The monotonic
            # ``upstream_429_rejections`` lifetime counter is preserved for
            # post-mortem, while this windowed value tells operators whether
            # the bot is currently being throttled (every STATS line ticks
            # up) vs saw a transient spike earlier in the run.
            "upstream_429_last_5m": 0,
            # Audit P1: p50/p99 percentiles of local latency and upstream age.
            # Computed on a rolling window in _log_stats_snapshot; ``None``
            # until the first batch of samples arrives.
            "latency_p50_ms": None,
            "latency_p99_ms": None,
            "upstream_age_p50_ms": None,
            "upstream_age_p99_ms": None,
            "signals_by_reason": {},
        }

        # Rolling samples for the latency / upstream-age percentile histograms
        # (audit P1). Capped so a long-running process cannot grow them without
        # bound; oldest sample is evicted on overflow. Upstream-age entries
        # carry the record timestamp so the percentile can drop data older
        # than _UPSTREAM_AGE_WINDOW_S and reflect current freshness instead of
        # ancient one-off outliers.
        self._latency_samples: list[int] = []
        self._upstream_age_samples: list[tuple[float, int]] = []
        # Audit P4: timestamps of every 429 observed since start; pruned to a
        # 5-minute window on each STATS log so the windowed count stays O(N).
        self._upstream_429_ts: list[float] = []
        self._HIST_MAX_SAMPLES = 1000
        self._UPSTREAM_AGE_WINDOW_S = 3600.0

        # Always route the client's 429 events through the engine so the
        # ``upstream_429_rejections`` counter ticks regardless of how the
        # caller constructed the client.
        self.client._on_rate_limit = self.record_rate_limit

    @property
    def mode(self) -> str:
        if self.settings.live_trading_enabled:
            return "live"
        return "paper"

    async def process_signal(
        self, signal: TradeSignal, *, skip_edge_check: bool = False, min_size_usd: float | None = None
    ) -> CopyDecision:
        self.stats["signals_detected"] += 1

        decision = self.policy.decide(signal, skip_edge_check=skip_edge_check, min_size_usd=min_size_usd)
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
            self._bump_skip_reason(decision)
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

    def record_rate_limit(self, host: str, retry_after: float) -> None:
        """Observer invoked by PolymarketClient when an upstream returns 429.

        Keeps the lifetime counter monotonic;``signals_by_reason`` already
        exposes the full skip taxonomy so the dashboard can render ``429``
        counts there without an extra dimension. The 5-minute rolling window
        (audit P4) lives in ``self._upstream_429_ts`` and is pruned on every
        STATS log so the operator sees current vs lifetime throttle pressure.
        """
        self.stats["upstream_429_rejections"] += 1
        self.stats["signals_by_reason"].setdefault("upstream_429", 0)
        self.stats["signals_by_reason"]["upstream_429"] += 1
        self._upstream_429_ts.append(time.time())
        # Cheap O(N) prune: drop anything older than the window. _log_stats_snapshot
        # also prunes on every STATS tick so this list never exceeds a handful
        # of entries between snapshots.
        now_ts = time.time()
        cutoff = now_ts - 300.0
        self._upstream_429_ts = [ts for ts in self._upstream_429_ts if ts >= cutoff]
        self.stats["upstream_429_last_5m"] = len(self._upstream_429_ts)
        logger.warning(
            "upstream 429 on %s retry_after=%.1fs total=%d last_5m=%d",
            host,
            retry_after,
            self.stats["upstream_429_rejections"],
            self.stats["upstream_429_last_5m"],
        )

    def _record_latency_sample(self, latency_ms: int, upstream_age_ms: int) -> None:
        """Record one local-latency and one upstream-age sample (audit P1).

        Both windows are capped at ``_HIST_MAX_SAMPLES`` so percentiles stay
        cheap and reflect recent traffic, not lifetime. ``latency_ms`` is the
        local processing lag (0 in production where we have no detect-side
        clock), ``upstream_age_ms`` is the age of the upstream event when we
        received it.

        Upstream-age samples are stored as ``(recorded_at, value)`` tuples so
        the STATS snapshot can compute percentiles over a rolling
        ``_UPSTREAM_AGE_WINDOW_S`` window instead of an all-time histogram
        (which pinned age_p99 to ancient events forever).
        """
        self._latency_samples.append(max(0, int(latency_ms)))
        self._upstream_age_samples.append((time.time(), max(0, int(upstream_age_ms))))
        if len(self._latency_samples) > self._HIST_MAX_SAMPLES:
            self._latency_samples = self._latency_samples[-self._HIST_MAX_SAMPLES:]
        if len(self._upstream_age_samples) > self._HIST_MAX_SAMPLES:
            self._upstream_age_samples = self._upstream_age_samples[-self._HIST_MAX_SAMPLES:]

    async def _on_ws_trade(self, trade: TradeUpdate) -> None:
        key = f"ws:{trade.trade_id}"
        if key in self._seen:
            return
        now_ts = time.time()
        self._remember(key, now_ts)
        self._record_latency_sample(0, 0)
        signal = TradeSignal(
            signal_id=str(uuid.uuid4()),
            target_wallet=trade.filler or "clob-stream",
            market_slug=trade.market_slug,
            market_title=trade.market_slug,
            city="Unknown",
            outcome="Unknown",
            side=trade.side,
            price=trade.price,
            size_usd=0.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=trade.timestamp,
            latency_ms=0,
            upstream_age_ms=0,
            token_id=None,
        )
        await self._route_signal({"source": "ws", "trade_id": trade.trade_id}, signal)

    async def _subscribe_ws_markets(self, market_slugs: list[str]) -> None:
        if self._ws is None:
            return
        for slug in market_slugs:
            if slug not in self._ws_subscriptions:
                await self._ws.subscribe(slug)
                self._ws_subscriptions.add(slug)

    @staticmethod
    def _percentile(samples: list[int], p: float) -> int | None:
        """Return the p-th percentile (0..100) of ``samples`` via linear interp.

        Returns None when the window is empty. Linear interpolation between
        adjacent ranks so a single-sample window returns that sample at every
        percentile rather than rounding to a bucket floor.
        """
        if not samples:
            return None
        if len(samples) == 1:
            return int(samples[0])
        ordered = sorted(samples)
        rank = (p / 100.0) * (len(ordered) - 1)
        lo = int(rank)
        hi = min(lo + 1, len(ordered) - 1)
        frac = rank - lo
        return round(ordered[lo] * (1 - frac) + ordered[hi] * frac)

    # Stable bucket keys for the skip-reason histogram. The raw reason strings
    # carry variable suffixes (e.g. ``stale_signal:850ms``,
    # ``risk_rejected:max_trade_size_usd``); folding them into known prefixes
    # keeps the histogram readable and bounded so the dashboard never explodes
    # into per-fill reason keys.
    _SKIP_REASON_BUCKETS: ClassVar[dict[str, str]] = {
        "stale_signal": "stale",
        "stale_upstream": "stale",
        "stale": "stale",
        "risk_rejected": "risk_rejected",
        "clamp_below_min": "clamp_below_min",
        "order_duplicate": "order_duplicate",
        "order_rate_limited": "order_rate_limited",
        "thin_edge": "thin_edge",
        "size_too_small": "size_too_small",
        "daily_loss_cap": "daily_loss_cap",
        "max_exposure_reached": "max_exposure_reached",
        "daily_loss_limit": "daily_loss_limit",
        "upstream_429": "upstream_429",
    }

    def _bump_skip_reason(self, decision: CopyDecision) -> None:
        """Count a single skip in the signals_by_reason histogram.

        Raw reason strings carry variable suffixes (latency numbers, limit
        names); the histogram collapses them to a stable prefix so the
        dashboard sees a bounded set of buckets instead of one key per fill.
        """
        reason = decision.reason or "unknown"
        prefix = reason.split(":", 1)[0]
        bucket_key = self._SKIP_REASON_BUCKETS.get(prefix, prefix)
        bucket = self.stats["signals_by_reason"]
        bucket[bucket_key] = bucket.get(bucket_key, 0) + 1

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

        if self.settings.order_queue_enabled:
            # Background processor (started via self.order_queue.start) owns
            # submit + place_order + state transitions. We just acknowledge the
            # enqueue so the exposure is counted while the copy is in flight.
            return {"status": "queued"}

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

    async def _execute_queued_order(self, order: Order) -> bool:
        """Place one order pulled off the queue (OrderQueue.start executor)."""
        try:
            await self.client.place_order(
                token_id=order.token_id,
                side=order.side,
                price=order.price,
                size_usd=order.size_usd,
            )
        except Exception as exc:
            self.stats["live_orders_failed"] += 1
            await self.order_queue.mark_failed(order.order_id, str(exc))
            logger.exception(
                "LIVE COPY FAILED %s %s: %s", order.side, order.token_id, exc
            )
            return False
        await self.order_queue.mark_filled(order.order_id)
        self.stats["live_orders_filled"] += 1
        logger.info(
            "LIVE COPY FILLED %s %s $%.2f @ %.3f",
            order.side,
            order.token_id,
            order.size_usd,
            order.price,
        )
        return True

    def _resolve_wallets(self) -> list[str]:
        """Static TARGET_WALLETS merged with promoted discoveries, or demo fallback."""
        if self.target_provider is not None:
            return self.target_provider.current()
        return self.settings.target_wallets or self.client.default_demo_wallets()

    async def poll_once(self) -> list[TradeSignal]:
        """Poll target activity and convert fresh fills into copy signals."""
        started = time.perf_counter()
        self._load_seen()
        now_ts = time.time()
        self._prune_seen(now_ts)
        wallets = self._resolve_wallets()
        if self.target_provider is not None and not wallets:
            # Provider-managed mode must never leak into the demo stream.
            self.stats["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            return []
        events = await self.client.fetch_target_activity(
            wallets=wallets,
            market_filter=self.settings.market_filter,
            min_size_usd=self.risk.limits.min_trade_size_usd if self.risk else 0.0,
        )
        fresh: list[TradeSignal] = []
        now = datetime.now(timezone.utc)
        # Per-cycle counters for the SIGNAL-CYCLE summary line (audit P3).
        cycle_buys = 0
        cycle_sells = 0
        cycle_skip_stale = 0
        cycle_skip_other = 0
        for event in events:
            key = event.get("id")
            if not key:
                # Empty transaction hashes must never be deduped (all of them
                # would collide on the same key); skip them with a log instead.
                self.stats["malformed_events"] += 1
                logger.warning("dropping event with empty id: %s", event)
                continue
            if key in self._seen:
                continue
            try:
                target_filled = datetime.fromisoformat(
                    str(event["timestamp"]).replace("Z", "+00:00")
                )
                # Two-tier latency (audit P0): upstream_age_ms is how old the
                # upstream event was when we received it (data staleness);
                # latency_ms is the local detect-to-decision lag. The demo path
                # injects a synthetic local latency so the existing ``latency_ms``
                # semantic (local processing) stays meaningful even when upstream
                # timestamps are absent.
                upstream_age_ms = int((now - target_filled).total_seconds() * 1000)
                latency_ms = int(event.get("latency_ms", 420)) if event.get("demo") else 0
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
                    upstream_age_ms=upstream_age_ms,
                    token_id=event.get("token_id"),
                )
            except Exception as exc:
                self.stats["malformed_events"] += 1
                logger.warning("dropping malformed event id=%s: %s", key, exc)
                continue
            fresh.append(signal)
            decision = await self._route_signal(event, signal)
            # Mark seen only after the event survived parsing AND routing so a
            # transient failure does not permanently swallow the fill.
            self._remember(key, now_ts)
            if decision is not None:
                if decision.should_copy:
                    if signal.side == Side.BUY:
                        cycle_buys += 1
                    else:
                        cycle_sells += 1
                else:
                    prefix = (decision.reason or "").split(":", 1)[0]
                    if prefix in {"stale_signal", "stale_upstream"}:
                        cycle_skip_stale += 1
                    else:
                        cycle_skip_other += 1

        # Record upstream-age samples for the rolling histograms (audit P1).
        for sig in fresh:
            self._record_latency_sample(sig.latency_ms, sig.upstream_age_ms)

        self.stats["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        # Per-cycle summary (audit P3): one SIGNAL-CYCLE line per poll keeps
        # signal-level noise at DEBUG without losing observable signal mix.
        if fresh or cycle_buys or cycle_sells or cycle_skip_stale or cycle_skip_other:
            logger.info(
                "SIGNAL-CYCLE fresh=%s BUY=%s SELL=%s SKIP-stale=%s SKIP-other=%s",
                len(fresh),
                cycle_buys,
                cycle_sells,
                cycle_skip_stale,
                cycle_skip_other,
            )
        if now_ts - self._last_seen_save >= SEEN_SAVE_INTERVAL_S:
            self._save_seen()
            self._last_seen_save = now_ts
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.debug("poll_once processed=%s elapsed_ms=%.1f", len(fresh), elapsed_ms)
        return fresh

    async def _route_signal(self, event: dict, signal: TradeSignal) -> CopyDecision | None:
        """Process an individual fill, then feed the consensus buffer.

        Every fresh fill is copied (or skipped) exactly as before. When a
        quorum engine is attached, the same fill also registers as one vote;
        N distinct wallets on the same token/side fire consensus once.
        When settings.wallet_filter_enabled, a non-weather signal is gated out
        up front so it is neither copied nor counted as a quorum vote.
        Returns the per-signal CopyDecision (or None when the wallet filter
        rejects before any decision is made) so the per-cycle SIGNAL-CYCLE
        summary line can count buys/sells/skips without re-deciding.
        """
        # Per-signal trail demoted to DEBUG (audit P3); the SIGNAL-CYCLE line
        # replaces it as the INFO-level summary so quiet stretches are still
        # observable without spamming one line per fill.
        logger.debug(
            "SIGNAL %s %s $%.2f @ %.3f wallet=%s latency=%sms upstream_age=%sms",
            signal.side.value,
            signal.market_slug,
            signal.size_usd,
            signal.price,
            signal.target_wallet,
            signal.latency_ms,
            signal.upstream_age_ms,
        )
        if self.settings.wallet_filter_enabled:
            allowed, reason = self.wallet_filter.should_copy(signal)
            if not allowed:
                logger.info(
                    "FILTER %s %s (reason=%s)",
                    signal.side.value,
                    signal.market_slug,
                    reason,
                )
                return None
        decision = await self.process_signal(signal)
        if decision.should_copy:
            logger.info(
                "COPY %s %s $%.2f @ %.3f",
                signal.side.value,
                signal.market_slug,
                decision.copy_size_usd,
                signal.price,
            )
        else:
            logger.info("SKIP %s (%s)", signal.market_slug, decision.reason)
        if self.quorum is None:
            return decision
        if event.get("source") == "ws" and (
            not signal.token_id or signal.size_usd <= 0
        ):
            # Stream-origin trades carry no token id / size; feeding them into
            # the quorum buffer would mint consensus votes that can never map
            # back to a real copyable market.
            return decision
        key = f"{signal.token_id or signal.market_slug}:{signal.side.value}"
        self._quorum_meta[key] = {
            "market_slug": signal.market_slug,
            "market_title": signal.market_title,
            "city": signal.city,
            "outcome": signal.outcome,
        }
        # Evict oldest-inserted entries so a long-running engine cannot grow
        # the metadata map without bound.
        while len(self._quorum_meta) > 1000:
            oldest_key = next(iter(self._quorum_meta))
            del self._quorum_meta[oldest_key]
        result = self.quorum.register_signal(
            WalletTradeSignal(
                wallet_address=signal.target_wallet,
                token_id=signal.token_id or signal.market_slug,
                side=signal.side.value,
                entry_price=signal.price,
                size_usd=signal.size_usd,
            )
        )
        qstats = self.quorum.get_stats()
        self.stats["quorum_votes"] = qstats["signals_received"]
        self.stats["quorum_reached"] = qstats["quorum_reached"]
        self.stats["quorum_rejected"] = qstats["quorum_rejected"]
        if result is not None:
            if self.monitor is not None:
                self.monitor.record_quorum_hit()
            await self._process_consensus(result)
        return decision

    async def _process_consensus(self, result: QuorumResult) -> None:
        """Turn one fired consensus into a single fresh copy decision.

        The consensus signal is born now (latency 0), so the staleness gate
        passes naturally, and skip_edge_check lets the agreement itself stand
        in for the thin-edge heuristic.
        """
        meta = self._quorum_meta.get(f"{result.token_id}:{result.side}", {})
        now = datetime.now(timezone.utc)
        consensus_signal = TradeSignal(
            signal_id=str(uuid.uuid4()),
            target_wallet=f"quorum({result.quorum_size})",
            market_slug=str(meta.get("market_slug") or result.token_id),
            market_title=str(meta.get("market_title") or "Consensus"),
            city=str(meta.get("city") or "Unknown"),
            outcome=str(meta.get("outcome") or "Yes"),
            side=Side(result.side),
            price=result.vwap_price,
            size_usd=result.total_size_usd,
            detected_at=now,
            target_filled_at=now,
            latency_ms=0,
            upstream_age_ms=0,
            token_id=result.token_id,
        )
        decision = await self.process_signal(
            consensus_signal,
            skip_edge_check=True,
            min_size_usd=self.settings.consensus_min_size_usd,
        )
        if decision.should_copy:
            logger.info(
                "QUORUM %s %s wallets=%s vwap=%.3f size=$%.2f -> COPY $%.2f @ %.3f",
                result.side,
                result.token_id[:16],
                result.quorum_size,
                result.vwap_price,
                result.total_size_usd,
                decision.copy_size_usd,
                result.vwap_price,
            )
        else:
            logger.info(
                "QUORUM %s %s wallets=%s vwap=%.3f size=$%.2f -> SKIP (%s)",
                result.side,
                result.token_id[:16],
                result.quorum_size,
                result.vwap_price,
                result.total_size_usd,
                decision.reason,
            )
        if not decision.should_copy and self.monitor is not None:
            self.monitor.record_quorum_skip(decision.reason)

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

    def _log_stats_snapshot(self) -> None:
        """One-line periodic summary so quiet stretches stay observable."""
        s = self.stats
        # ``dry_run`` is a runtime flag operators flip from the dashboard; mirror
        # the live value into the snapshot so the STATS heartbeat itself tells
        # operators whether ``live_orders_*`` zeros are expected (paper mode) or
        # worth investigating (live mode).
        s["dry_run"] = bool(self.settings.dry_run)
        # Audit P4: re-prune the 429 window so the rolling count stays fresh
        # even if no 429 has been observed recently (record_rate_limit also
        # prunes, but a long quiet stretch after the last 429 leaves stale
        # entries until the next event).
        now_ts = time.time()
        cutoff = now_ts - 300.0
        self._upstream_429_ts = [ts for ts in self._upstream_429_ts if ts >= cutoff]
        s["upstream_429_last_5m"] = len(self._upstream_429_ts)
        # Audit P1: refresh p50/p99 for both latency dimensions from the
        # rolling sample windows. Stored as ints in stats so dashboards can
        # chart them directly without re-running percentile math.
        s["latency_p50_ms"] = self._percentile(self._latency_samples, 50.0)
        s["latency_p99_ms"] = self._percentile(self._latency_samples, 99.0)
        # Rolling-window upstream-age percentiles: drop samples older than
        # _UPSTREAM_AGE_WINDOW_S so p99 reflects *current* freshness instead
        # of the worst event since process start.
        age_cutoff = now_ts - self._UPSTREAM_AGE_WINDOW_S
        self._upstream_age_samples = [
            (ts, v) for ts, v in self._upstream_age_samples if ts >= age_cutoff
        ]
        age_values = [v for _, v in self._upstream_age_samples]
        s["upstream_age_p50_ms"] = self._percentile(age_values, 50.0)
        s["upstream_age_p99_ms"] = self._percentile(age_values, 99.0)
        # Collapse the signals_by_reason histogram into a compact ``a=1,b=2``
        # suffix so a single STATS line still tells the operator why signals
        # were skipped (stale / size / edge / risk / dedup / upstream_429).
        reasons = ",".join(f"{k}={v}" for k, v in sorted(s["signals_by_reason"].items()))
        # Surface the risk-gate state on every heartbeat: a tripped circuit
        # breaker silently freezes ``risk_rejected`` (all trades rejected with
        # no counter movement), so the STATS line must name the active gate.
        risk_state = self.risk.get_state() if self.risk is not None else {}
        breaker = risk_state.get("circuit_breaker_tripped", False)
        breaker_reason = risk_state.get("circuit_breaker_reason") or "-"
        daily_pnl = float(risk_state.get("daily_pnl", 0.0) or 0.0)
        logger.info(
            "STATS mode=%s detected=%s copied=%s skipped=%s risk_rejected=%s "
            "quorum_votes=%s reached=%s rejected=%s live_filled=%s live_failed=%s "
            "live_dup=%s live_throttled=%s targets=%s balance=$%.2f upstream_429=%s "
            "upstream_429_5m=%s latency_p50=%s latency_p99=%s age_p50=%s age_p99=%s "
            "breaker=%s breaker_reason=%s daily_pnl=$%.2f reasons={%s}",
            "paper" if s["dry_run"] else "live",
            s["signals_detected"],
            s["copied"],
            s["skipped"],
            s["risk_rejections"],
            s["quorum_votes"],
            s["quorum_reached"],
            s["quorum_rejected"],
            s["live_orders_filled"],
            s["live_orders_failed"],
            s["live_orders_duplicated"],
            s["live_orders_throttled"],
            len(self._resolve_wallets()),
            self._balance,
            s["upstream_429_rejections"],
            s["upstream_429_last_5m"],
            s["latency_p50_ms"] if s["latency_p50_ms"] is not None else "-",
            s["latency_p99_ms"] if s["latency_p99_ms"] is not None else "-",
            s["upstream_age_p50_ms"] if s["upstream_age_p50_ms"] is not None else "-",
            s["upstream_age_p99_ms"] if s["upstream_age_p99_ms"] is not None else "-",
            breaker,
            breaker_reason,
            daily_pnl,
            reasons,
        )

    async def run(self, duration_sec: float | None = None) -> None:
        self._running = True
        self._started_at = time.time()
        if self.quorum is not None:
            self.quorum.start_cleanup_task()
        started_queue = False
        if self.settings.order_queue_enabled:
            # Without this the OrderQueue's dedup + rate-limit + stale-cleanup
            # loops never run: orders would be enqueued but never executed.
            await self.order_queue.start(self._execute_queued_order)
            started_queue = True
        wallets = self._resolve_wallets()
        # Audit P5: surface the resolved wallet set explicitly so an operator
        # can tell at a glance whether they have 1, 2, or 3 active targets
        # (the long-standing "targets=2 vs default_demo_wallets=3" mystery
        # resolves here). Useful even when static and discovered counts look
        # fine on their own.
        logger.info(
            "CopyEngine starting mode=%s targets=%s static=%s discovered=%s max_latency=%sms wallets=%s",
            self.mode,
            len(wallets),
            len(self.settings.target_wallets),
            max(len(wallets) - len(self.settings.target_wallets), 0),
            self.settings.max_copy_latency_ms,
            wallets,
        )
        # Audit P2: when only one wallet is configured and single_source_mode
        # is on, drop the consensus minimum to 1 so the layer is no longer
        # structurally unreachable. Logged so an operator can spot when the
        # bypass actually engages (otherwise the production deployment sits
        # silent at quorum_min_count=2 with one source forever).
        if (
            self.quorum is not None
            and len(wallets) == 1
            and self.settings.single_source_mode
            and self.quorum.min_quorum_count != 1
        ):
            logger.info(
                "single_source_mode: quorum min lowered %s -> 1 (one wallet configured)",
                self.quorum.min_quorum_count,
            )
            self.quorum.min_quorum_count = 1

        self._ws = CLOBWebSocket(on_trade=self._on_ws_trade)
        try:
            await asyncio.wait_for(self._ws.connect(), timeout=WS_CONNECT_TIMEOUT_S)
            logger.info("CLOB WebSocket connected")
        except Exception as exc:
            logger.warning("CLOB WebSocket connect failed (continuing with polling only): %s", exc)
            self._ws = None

        if self._ws is not None:
            self._ws_task = asyncio.create_task(self._ws.run())
            try:
                markets = await self.client.fetch_weather_markets()
                slugs = [m.get("slug") or m.get("condition_id", "") for m in markets]
                slugs = [s for s in slugs if s]
                if slugs:
                    await self._subscribe_ws_markets(slugs)
                    logger.info("WS subscribed to %s weather markets", len(slugs))
            except Exception as exc:
                logger.warning("Failed to fetch weather markets for WS subscription: %s", exc)

        started = time.time()
        last_stats_log = started
        interval = self.settings.poll_interval_ms / 1000.0
        consecutive_failures = 0
        try:
            while self._running:
                try:
                    await self.poll_once()
                    consecutive_failures = 0
                    now_s = time.time()
                    if now_s - last_stats_log >= STATS_LOG_INTERVAL_S:
                        last_stats_log = now_s
                        self._log_stats_snapshot()
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
        finally:
            if self.quorum is not None:
                await self.quorum.stop_cleanup_task()
            if started_queue:
                await self.order_queue.stop()
            if self._ws_task is not None:
                self._ws_task.cancel()
                await asyncio.gather(self._ws_task, return_exceptions=True)
                self._ws_task = None
            if self._ws is not None:
                await self._ws.disconnect()
            self._running = False

    def stop(self) -> None:
        self._running = False
