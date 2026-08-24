"""Event-driven backtester for weather-market copy strategies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.metrics import summarize_fills
from weather_copy_bot.models import (
    CopyDecision,
    EquityPoint,
    Fill,
    PerformanceSummary,
    Side,
    TradeSignal,
)


@dataclass
class BacktestResult:
    summary: PerformanceSummary
    fills: list[Fill]
    equity_curve: list[EquityPoint]
    decisions: list[CopyDecision]


class CopyBacktester:
    """Replays target fills with latency, sizing, and risk filters."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def decide(self, signal: TradeSignal) -> CopyDecision:
        if signal.latency_ms > self.settings.max_copy_latency_ms:
            return CopyDecision(
                signal=signal,
                should_copy=False,
                reason=f"stale_signal:{signal.latency_ms}ms",
            )
        size = min(
            signal.size_usd * self.settings.copy_ratio,
            self.settings.max_position_usd,
        )
        if size < 5:
            return CopyDecision(signal=signal, should_copy=False, reason="size_too_small")

        # Simple weather-edge heuristic: prefer mid-range prices with room for edge
        edge_bps = abs(0.5 - signal.price) * 10_000 * 0.15
        if edge_bps < self.settings.min_edge_bps and signal.price > 0.85:
            return CopyDecision(signal=signal, should_copy=False, reason="thin_edge")

        slippage = max(4.0, signal.latency_ms * 0.02)
        return CopyDecision(
            signal=signal,
            should_copy=True,
            reason="copy",
            copy_size_usd=round(size, 2),
            expected_slippage_bps=round(slippage, 2),
        )

    def run(self, signals: Iterable[TradeSignal]) -> BacktestResult:
        balance = self.settings.paper_starting_balance
        peak = balance
        daily_pnl = 0.0
        day_key: str | None = None
        fills: list[Fill] = []
        curve: list[EquityPoint] = []
        decisions: list[CopyDecision] = []

        for idx, signal in enumerate(sorted(signals, key=lambda s: s.detected_at)):
            dkey = signal.detected_at.strftime("%Y-%m-%d")
            if day_key != dkey:
                day_key = dkey
                daily_pnl = 0.0

            decision = self.decide(signal)
            decisions.append(decision)
            if not decision.should_copy:
                continue
            if daily_pnl <= -self.settings.max_daily_loss_usd:
                decision.should_copy = False
                decision.reason = "daily_loss_cap"
                continue

            # Realized edge decays with latency
            latency_penalty = signal.latency_ms / 1000.0 * 0.012
            direction = 1.0 if signal.side == Side.BUY else -1.0
            # Synthetic markout favoring faster copies
            markout = (0.035 - latency_penalty) * direction
            pnl = decision.copy_size_usd * markout
            fee = decision.copy_size_usd * 0.002
            pnl -= fee

            balance += pnl
            daily_pnl += pnl
            peak = max(peak, balance)
            dd = ((balance - peak) / peak) * 100.0 if peak else 0.0

            fills.append(
                Fill(
                    fill_id=f"bt-{idx:05d}",
                    signal_id=signal.signal_id,
                    target_wallet=signal.target_wallet,
                    market_slug=signal.market_slug,
                    market_title=signal.market_title,
                    city=signal.city,
                    outcome=signal.outcome,
                    side=signal.side,
                    price=signal.price,
                    size_usd=decision.copy_size_usd,
                    fee_usd=round(fee, 4),
                    pnl_usd=round(pnl, 4),
                    latency_ms=signal.latency_ms,
                    filled_at=signal.detected_at,
                    mode="backtest",
                )
            )
            curve.append(
                EquityPoint(
                    timestamp=signal.detected_at,
                    equity_usd=round(balance, 2),
                    pnl_usd=round(balance - self.settings.paper_starting_balance, 2),
                    drawdown_pct=round(dd, 2),
                )
            )

        summary = summarize_fills(
            fills,
            curve,
            mode="backtest",
            starting_balance=self.settings.paper_starting_balance,
        )
        return BacktestResult(summary=summary, fills=fills, equity_curve=curve, decisions=decisions)
