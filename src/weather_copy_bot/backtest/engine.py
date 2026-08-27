"""Database-backed backtester with full replay support and strategy versioning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.db import (
    DatabaseManager,
    DecisionRepository,
    FillRepository,
    SignalRepository,
    StrategyRepository,
    StrategyRunRepository,
)
from weather_copy_bot.db.models import Decision as DBDecision
from weather_copy_bot.db.models import Signal as DBSignal
from weather_copy_bot.db.models import Strategy as DBStrategy
from weather_copy_bot.models import (
    BacktestResult,
    CopyDecision,
    EquityPoint,
    Fill,
    PerformanceSummary,
    Side,
    TradeSignal,
)


@dataclass
class StrategyParams:
    """Parameters for a trading strategy."""

    copy_ratio: float = 0.25
    max_position_usd: float = 250.0
    max_daily_loss_usd: float = 500.0
    min_edge_bps: float = 50.0
    max_copy_latency_ms: int = 800
    max_upstream_age_ms: int = 60_000
    base_markup: float = 0.035
    latency_decay_rate: float = 0.012
    fee_rate: float = 0.002

    @classmethod
    def from_db_strategy(cls, strategy: DBStrategy) -> StrategyParams:
        """Create from database strategy."""
        return cls(
            copy_ratio=strategy.copy_ratio,
            max_position_usd=strategy.max_position_usd,
            max_daily_loss_usd=strategy.max_daily_loss_usd,
            min_edge_bps=strategy.min_edge_bps,
            max_copy_latency_ms=strategy.max_copy_latency_ms,
            base_markup=strategy.base_markout,
            latency_decay_rate=strategy.latency_decay_rate,
            fee_rate=strategy.fee_rate,
        )


@dataclass
class ReplayResult:
    """Result of a full tick-by-tick replay."""

    run_id: int
    strategy_id: int
    summary: dict
    fills: list[Fill]
    equity_curve: list[EquityPoint]
    decisions: list[CopyDecision]


class CopyBacktester:
    """Database-backed backtester with replay support."""

    def __init__(
        self,
        settings: Settings | None = None,
        db_manager: DatabaseManager | None = None,
        strategy_id: int | None = None,
    ):
        self.settings = settings or get_settings()
        self.db = db_manager
        self._strategy_id = strategy_id

        # In-memory state (if no DB)
        self._balance = self.settings.paper_starting_balance
        self._peak = self._balance
        self._daily_pnl = 0.0
        self._day_key: str | None = None
        self._fills: list[Fill] = []
        self._curve: list[EquityPoint] = []
        self._decisions: list[CopyDecision] = []

    @property
    def params(self) -> StrategyParams:
        """Get current strategy parameters."""
        if self._strategy_id and self.db:
            with self.db.session() as session:
                repo = StrategyRepository(session)
                strategy = repo.get_by_id(self._strategy_id)
                if strategy:
                    return StrategyParams.from_db_strategy(strategy)

        # Default from settings
        return StrategyParams(
            copy_ratio=self.settings.copy_ratio,
            max_position_usd=self.settings.max_position_usd,
            max_daily_loss_usd=self.settings.max_daily_loss_usd,
            min_edge_bps=self.settings.min_edge_bps,
            max_copy_latency_ms=self.settings.max_copy_latency_ms,
            max_upstream_age_ms=self.settings.max_upstream_age_ms,
        )

    def decide(
        self,
        signal: TradeSignal,
        *,
        skip_edge_check: bool = False,
        min_size_usd: float | None = None,
    ) -> CopyDecision:
        """Make a copy decision for a signal.

        skip_edge_check bypasses ONLY the thin-edge heuristic; consensus
        agreement substitutes for it, while staleness and size checks apply.
        min_size_usd overrides the default $5.00 per-trade floor; the consensus
        path passes Settings.consensus_min_size_usd so a 2-wallet x $5
        agreement (combined $2.50 after copy_ratio) is not auto-rejected.
        """
        p = self.params

        # Two-tier staleness gate (audit P0): upstream age first, then local
        # latency. An hours-old upstream timestamp fails before we ever check
        # how fast we detected it locally.
        if signal.upstream_age_ms > p.max_upstream_age_ms:
            return CopyDecision(
                signal=signal,
                should_copy=False,
                reason=f"stale_upstream:{signal.upstream_age_ms}ms",
            )
        if signal.latency_ms > p.max_copy_latency_ms:
            return CopyDecision(
                signal=signal,
                should_copy=False,
                reason=f"stale_signal:{signal.latency_ms}ms",
            )

        # Calculate size
        size = min(
            signal.size_usd * p.copy_ratio,
            p.max_position_usd,
        )
        floor = 5.0 if min_size_usd is None else min_size_usd
        if size < floor:
            return CopyDecision(signal=signal, should_copy=False, reason="size_too_small")

        # Edge calculation
        if not skip_edge_check:
            edge_bps = abs(0.5 - signal.price) * 10_000 * 0.15
            if edge_bps < p.min_edge_bps:
                return CopyDecision(signal=signal, should_copy=False, reason="thin_edge")

        # Slippage estimate
        slippage = max(4.0, signal.latency_ms * 0.02)

        return CopyDecision(
            signal=signal,
            should_copy=True,
            reason="copy",
            copy_size_usd=round(size, 2),
            expected_slippage_bps=round(slippage, 2),
        )

    def _calculate_markout(
        self, signal: TradeSignal, size: float, params: StrategyParams
    ) -> tuple[float, float, float]:
        """Calculate markout, fee, and net P&L."""
        latency_penalty = signal.latency_ms / 1000.0 * params.latency_decay_rate
        direction = 1.0 if signal.side == Side.BUY else -1.0
        markout = (params.base_markup - latency_penalty) * direction
        pnl = size * markout
        fee = size * params.fee_rate
        pnl -= fee
        return markout, fee, pnl

    def run(
        self,
        signals: Iterable[TradeSignal],
        mode: str = "backtest",
        strategy_id: int | None = None,
        run_id: int | None = None,
        save_to_db: bool = True,
    ) -> BacktestResult:
        """Run backtest on a set of signals."""
        params = self.params
        self._reset_state()

        decisions: list[CopyDecision] = []
        fills: list[Fill] = []
        curve: list[EquityPoint] = []

        for idx, signal in enumerate(sorted(signals, key=lambda s: s.detected_at)):
            # Daily loss cap check
            dkey = signal.detected_at.strftime("%Y-%m-%d")
            if self._day_key != dkey:
                self._day_key = dkey
                self._daily_pnl = 0.0

            decision = self.decide(signal)
            decisions.append(decision)

            if not decision.should_copy:
                continue

            if self._daily_pnl <= -params.max_daily_loss_usd:
                decision.should_copy = False
                decision.reason = "daily_loss_cap"
                continue

            # Calculate P&L
            _markout, fee, pnl = self._calculate_markout(signal, decision.copy_size_usd, params)

            # Update state
            self._balance += pnl
            self._daily_pnl += pnl
            self._peak = max(self._peak, self._balance)
            dd = ((self._balance - self._peak) / self._peak) * 100.0 if self._peak else 0.0

            fill = Fill(
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
                mode=mode,
            )
            fills.append(fill)
            curve.append(
                EquityPoint(
                    timestamp=signal.detected_at,
                    equity_usd=round(self._balance, 2),
                    pnl_usd=round(self._balance - self.settings.paper_starting_balance, 2),
                    drawdown_pct=round(dd, 2),
                )
            )

            # Save to DB if enabled
            if save_to_db and self.db:
                self._save_to_db(signal, decision, fill, strategy_id, run_id)

        summary = self._summarize(fills, curve, mode)
        return BacktestResult(
            summary=summary,
            fills=fills,
            equity_curve=curve,
            decisions=decisions,
        )

    def replay(
        self,
        signals: Iterable[TradeSignal],
        strategy_id: int,
        market_filter: str | None = None,
    ) -> ReplayResult:
        """Full replay with database persistence."""
        if not self.db:
            raise RuntimeError("Database manager required for replay")

        with self.db.session() as session:
            # Create strategy run
            run_repo = StrategyRunRepository(session)
            run = run_repo.create(
                strategy_id=strategy_id,
                mode="backtest",
                market_filter=market_filter,
                starting_balance=self.settings.paper_starting_balance,
            )

            # Run backtest with DB persistence
            self._reset_state()
            params = self.params
            decisions: list[CopyDecision] = []
            fills: list[Fill] = []
            curve: list[EquityPoint] = []

            signal_repo = SignalRepository(session)
            decision_repo = DecisionRepository(session)
            fill_repo = FillRepository(session)

            for idx, signal in enumerate(sorted(signals, key=lambda s: s.detected_at)):
                # Daily loss cap
                dkey = signal.detected_at.strftime("%Y-%m-%d")
                if self._day_key != dkey:
                    self._day_key = dkey
                    self._daily_pnl = 0.0

                decision = self.decide(signal)
                decisions.append(decision)

                if not decision.should_copy:
                    continue

                if self._daily_pnl <= -params.max_daily_loss_usd:
                    decision.should_copy = False
                    decision.reason = "daily_loss_cap"
                    continue

                # Create signal in DB
                db_signal = signal_repo.create(
                    signal_id=signal.signal_id,
                    run_id=run.id,
                    target_wallet=signal.target_wallet,
                    market_slug=signal.market_slug,
                    market_title=signal.market_title,
                    city=signal.city,
                    outcome=signal.outcome,
                    side=signal.side.value,
                    price=signal.price,
                    size_usd=signal.size_usd,
                    token_id=signal.token_id,
                    detected_at=signal.detected_at,
                    target_filled_at=signal.target_filled_at,
                    latency_ms=signal.latency_ms,
                )

                # Calculate P&L
                markout, fee, pnl = self._calculate_markout(signal, decision.copy_size_usd, params)

                # Create decision in DB
                db_decision = decision_repo.create(
                    run_id=run.id,
                    signal_id=db_signal.id,
                    strategy_id=strategy_id,
                    should_copy=decision.should_copy,
                    reason=decision.reason,
                    copy_size_usd=decision.copy_size_usd,
                    expected_slippage_bps=decision.expected_slippage_bps,
                )

                # Update state
                self._balance += pnl
                self._daily_pnl += pnl
                self._peak = max(self._peak, self._balance)
                dd = ((self._balance - self._peak) / self._peak) * 100.0 if self._peak else 0.0

                # Create fill in DB
                _db_fill = fill_repo.create(
                    decision_id=db_decision.id,
                    fill_id=f"bt-{idx:05d}",
                    side=signal.side.value,
                    price=signal.price,
                    size_usd=decision.copy_size_usd,
                    fee_usd=round(fee, 4),
                    pnl_usd=round(pnl, 4),
                    markout=markout,
                    latency_ms=signal.latency_ms,
                    filled_at=signal.detected_at,
                    mode="backtest",
                )

                # In-memory objects
                fill = Fill(
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
                fills.append(fill)
                curve.append(
                    EquityPoint(
                        timestamp=signal.detected_at,
                        equity_usd=round(self._balance, 2),
                        pnl_usd=round(self._balance - self.settings.paper_starting_balance, 2),
                        drawdown_pct=round(dd, 2),
                    )
                )

            # Update run with performance
            summary = self._summarize(fills, curve, "backtest")
            run_repo.update_performance(
                run_id=run.id,
                ending_balance=self._balance,
                total_pnl=self._balance - self.settings.paper_starting_balance,
                trade_count=len(fills),
                win_rate=summary.win_rate,
                sharpe=summary.sharpe,
                max_drawdown_pct=summary.max_drawdown_pct,
            )

            session.commit()

            return ReplayResult(
                run_id=run.id,
                strategy_id=strategy_id,
                summary={
                    "ending_balance": self._balance,
                    "total_pnl": self._balance - self.settings.paper_starting_balance,
                    "trade_count": len(fills),
                    "win_rate": summary.win_rate,
                    "sharpe": summary.sharpe,
                    "max_drawdown_pct": summary.max_drawdown_pct,
                },
                fills=fills,
                equity_curve=curve,
                decisions=decisions,
            )

    def _reset_state(self) -> None:
        """Reset backtest state."""
        self._balance = self.settings.paper_starting_balance
        self._peak = self._balance
        self._daily_pnl = 0.0
        self._day_key = None

    def _save_to_db(
        self,
        signal: TradeSignal,
        decision: CopyDecision,
        fill: Fill,
        strategy_id: int | None,
        run_id: int | None,
    ) -> None:
        """Save decision and fill to database."""
        if not self.db:
            return

        with self.db.session() as session:
            signal_repo = SignalRepository(session)
            decision_repo = DecisionRepository(session)
            fill_repo = FillRepository(session)

            # Check if signal exists
            db_signal = signal_repo.get_by_signal_id(signal.signal_id)
            if not db_signal:
                db_signal = signal_repo.create(
                    signal_id=signal.signal_id,
                    run_id=run_id,
                    target_wallet=signal.target_wallet,
                    market_slug=signal.market_slug,
                    market_title=signal.market_title,
                    city=signal.city,
                    outcome=signal.outcome,
                    side=signal.side.value,
                    price=signal.price,
                    size_usd=signal.size_usd,
                    token_id=signal.token_id,
                    detected_at=signal.detected_at,
                    target_filled_at=signal.target_filled_at,
                    latency_ms=signal.latency_ms,
                )

            db_decision = decision_repo.create(
                run_id=run_id,
                signal_id=db_signal.id,
                strategy_id=strategy_id or 0,
                should_copy=decision.should_copy,
                reason=decision.reason,
                copy_size_usd=decision.copy_size_usd,
                expected_slippage_bps=decision.expected_slippage_bps,
            )

            fill_repo.create(
                decision_id=db_decision.id,
                fill_id=fill.fill_id,
                side=signal.side.value,
                price=signal.price,
                size_usd=decision.copy_size_usd,
                fee_usd=fill.fee_usd,
                pnl_usd=fill.pnl_usd,
                markout=fill.pnl_usd / decision.copy_size_usd,
                latency_ms=signal.latency_ms,
                filled_at=signal.detected_at,
                mode="backtest",
            )

            session.commit()

    def _summarize(
        self, fills: list[Fill], curve: list[EquityPoint], mode: str
    ) -> PerformanceSummary:
        """Generate performance summary."""
        from weather_copy_bot.metrics import summarize_fills

        return summarize_fills(
            fills=fills,
            equity_curve=curve,
            mode=mode,
            starting_balance=self.settings.paper_starting_balance,
        )


class StrategyComparator:
    """Compare multiple strategies for A/B testing."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def compare(
        self,
        signal_ids: list[str],
        strategy_ids: list[int],
    ) -> dict:
        """Compare multiple strategies on the same signals."""
        results = {}

        for strategy_id in strategy_ids:
            with self.db.session() as session:
                decision_repo = DecisionRepository(session)
                _fill_repo = FillRepository(session)

                # Get decisions for this strategy
                decisions = []
                fills = []

                for sid in signal_ids:
                    signal_query = session.query(DBSignal).filter_by(signal_id=sid).first()
                    if signal_query:
                        dec = decision_repo.get_by_signal_and_strategy(signal_query.id, strategy_id)
                        if dec:
                            decisions.append(dec)
                            if dec.fill:
                                fills.append(dec.fill)

                # Calculate stats
                if fills:
                    total_pnl = sum(f.pnl_usd for f in fills)
                    wins = sum(1 for f in fills if f.pnl_usd > 0)
                    results[strategy_id] = {
                        "trade_count": len(fills),
                        "total_pnl": total_pnl,
                        "win_rate": wins / len(fills) * 100,
                        "avg_pnl": total_pnl / len(fills),
                    }
                else:
                    results[strategy_id] = {
                        "trade_count": 0,
                        "total_pnl": 0.0,
                        "win_rate": 0.0,
                        "avg_pnl": 0.0,
                    }

        return results

    def regret_analysis(
        self,
        baseline_strategy_id: int,
        candidate_strategy_id: int,
        run_id: int,
    ) -> dict:
        """Calculate regret: what would the candidate have done vs baseline?"""
        with self.db.session() as session:
            # Get all signals in run
            signals_query = session.query(DBSignal).filter_by(run_id=run_id).all()

            baseline_decisions = {
                d.signal_id: d
                for d in session.query(DBDecision)
                .filter_by(strategy_id=baseline_strategy_id, run_id=run_id)
                .all()
            }

            candidate_decisions = {
                d.signal_id: d
                for d in session.query(DBDecision)
                .filter_by(strategy_id=candidate_strategy_id, run_id=run_id)
                .all()
            }

            # Calculate regret
            missed_profits = 0.0
            extra_losses = 0.0

            for signal in signals_query:
                baseline = baseline_decisions.get(signal.id)
                candidate = candidate_decisions.get(signal.id)

                if baseline and baseline.should_copy and baseline.fill:
                    baseline_pnl = baseline.fill.pnl_usd

                    if candidate and candidate.should_copy and candidate.fill:
                        candidate_pnl = candidate.fill.pnl_usd
                        if candidate_pnl < baseline_pnl:
                            missed_profits += baseline_pnl - candidate_pnl
                    else:
                        missed_profits += baseline_pnl

                elif candidate and candidate.should_copy and candidate.fill:
                    extra_losses += abs(candidate.fill.pnl_usd)

            return {
                "baseline_strategy_id": baseline_strategy_id,
                "candidate_strategy_id": candidate_strategy_id,
                "missed_profits": missed_profits,
                "extra_losses": extra_losses,
                "total_regret": missed_profits + extra_losses,
            }


# For type hint in summarize
