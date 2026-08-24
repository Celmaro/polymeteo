"""Paper-trading loop that mirrors live copy decisions without submitting orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from weather_copy_bot.backtest.engine import CopyBacktester
from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.metrics import summarize_fills
from weather_copy_bot.models import CopyDecision, EquityPoint, Fill, PerformanceSummary, TradeSignal


@dataclass
class PaperLedger:
    starting_balance: float
    balance: float
    fills: list[Fill] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    decisions: list[CopyDecision] = field(default_factory=list)
    peak: float = 0.0

    def __post_init__(self) -> None:
        self.peak = self.starting_balance


class PaperTrader:
    """Stateful paper account driven by detected target signals."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.policy = CopyBacktester(self.settings)
        self.ledger = PaperLedger(
            starting_balance=self.settings.paper_starting_balance,
            balance=self.settings.paper_starting_balance,
        )

    def on_signal(self, signal: TradeSignal) -> CopyDecision:
        decision = self.policy.decide(signal)
        self.ledger.decisions.append(decision)
        if not decision.should_copy:
            return decision

        latency_penalty = signal.latency_ms / 1000.0 * 0.011
        markout = 0.034 - latency_penalty
        pnl = decision.copy_size_usd * markout - decision.copy_size_usd * 0.002
        self.ledger.balance += pnl
        self.ledger.peak = max(self.ledger.peak, self.ledger.balance)
        dd = ((self.ledger.balance - self.ledger.peak) / self.ledger.peak) * 100.0

        fill = Fill(
            fill_id=f"paper-{len(self.ledger.fills):05d}",
            signal_id=signal.signal_id,
            target_wallet=signal.target_wallet,
            market_slug=signal.market_slug,
            market_title=signal.market_title,
            city=signal.city,
            outcome=signal.outcome,
            side=signal.side,
            price=signal.price,
            size_usd=decision.copy_size_usd,
            fee_usd=round(decision.copy_size_usd * 0.002, 4),
            pnl_usd=round(pnl, 4),
            latency_ms=signal.latency_ms,
            filled_at=signal.detected_at or datetime.now(timezone.utc),
            mode="paper",
        )
        self.ledger.fills.append(fill)
        self.ledger.equity_curve.append(
            EquityPoint(
                timestamp=fill.filled_at,
                equity_usd=round(self.ledger.balance, 2),
                pnl_usd=round(self.ledger.balance - self.ledger.starting_balance, 2),
                drawdown_pct=round(dd, 2),
            )
        )
        return decision

    def summary(self) -> PerformanceSummary:
        return summarize_fills(
            self.ledger.fills,
            self.ledger.equity_curve,
            mode="paper",
            starting_balance=self.ledger.starting_balance,
        )
