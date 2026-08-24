"""Repository layer for database operations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weather_copy_bot.db.models import (
    Decision,
    EquityPoint,
    Fill,
    Signal,
    Strategy,
    StrategyRun,
    Tick,
)


class StrategyRepository:
    """Repository for strategy CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Strategy:
        """Create a new strategy."""
        strategy = Strategy(**kwargs)
        self.session.add(strategy)
        self.session.flush()
        return strategy

    def get_by_id(self, strategy_id: int) -> Optional[Strategy]:
        """Get strategy by ID."""
        return self.session.get(Strategy, strategy_id)

    def get_by_name_version(
        self, name: str, version: Optional[int] = None
    ) -> Optional[Strategy]:
        """Get strategy by name and optional version."""
        query = select(Strategy).where(Strategy.name == name)
        if version:
            query = query.where(Strategy.version == version)
        else:
            query = query.where(Strategy.is_active == True)
            query = query.order_by(Strategy.version.desc())
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def get_active(self) -> list[Strategy]:
        """Get all active strategies."""
        query = (
            select(Strategy)
            .where(Strategy.is_active == True)
            .order_by(Strategy.name, Strategy.version.desc())
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def deactivate(self, strategy_id: int) -> Optional[Strategy]:
        """Deactivate a strategy."""
        strategy = self.session.get(Strategy, strategy_id)
        if strategy:
            strategy.is_active = False
        return strategy

    def create_new_version(
        self, base_strategy_id: int, **updates
    ) -> Strategy:
        """Create a new version of a strategy with updated params."""
        base = self.session.get(Strategy, base_strategy_id)
        if not base:
            raise ValueError(f"Strategy {base_strategy_id} not found")

        new_strategy = Strategy(
            name=base.name,
            version=base.version + 1,
            description=updates.get("description"),
            copy_ratio=updates.get("copy_ratio", base.copy_ratio),
            max_position_usd=updates.get(
                "max_position_usd", base.max_position_usd
            ),
            max_daily_loss_usd=updates.get(
                "max_daily_loss_usd", base.max_daily_loss_usd
            ),
            min_edge_bps=updates.get("min_edge_bps", base.min_edge_bps),
            max_copy_latency_ms=updates.get(
                "max_copy_latency_ms", base.max_copy_latency_ms
            ),
            base_markout=updates.get("base_markout", base.base_markout),
            latency_decay_rate=updates.get(
                "latency_decay_rate", base.latency_decay_rate
            ),
            fee_rate=updates.get("fee_rate", base.fee_rate),
            params_json=updates.get("params_json"),
        )
        self.session.add(new_strategy)
        self.session.flush()
        return new_strategy


class StrategyRunRepository:
    """Repository for strategy run operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, strategy_id: int, **kwargs) -> StrategyRun:
        """Create a new strategy run."""
        run = StrategyRun(strategy_id=strategy_id, **kwargs)
        self.session.add(run)
        self.session.flush()
        return run

    def get_by_id(self, run_id: int) -> Optional[StrategyRun]:
        """Get run by ID."""
        return self.session.get(StrategyRun, run_id)

    def update_performance(
        self,
        run_id: int,
        ending_balance: float,
        total_pnl: float,
        trade_count: int,
        **metrics,
    ) -> Optional[StrategyRun]:
        """Update run with performance metrics."""
        run = self.session.get(StrategyRun, run_id)
        if run:
            run.ended_at = datetime.utcnow()
            run.ending_balance = ending_balance
            run.total_pnl = total_pnl
            run.trade_count = trade_count
            run.win_rate = metrics.get("win_rate")
            run.sharpe = metrics.get("sharpe")
            run.max_drawdown_pct = metrics.get("max_drawdown_pct")
        return run

    def get_by_strategy(
        self, strategy_id: int, limit: int = 10
    ) -> list[StrategyRun]:
        """Get recent runs for a strategy."""
        query = (
            select(StrategyRun)
            .where(StrategyRun.strategy_id == strategy_id)
            .order_by(StrategyRun.started_at.desc())
            .limit(limit)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())


class SignalRepository:
    """Repository for signal operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Signal:
        """Create a new signal."""
        signal = Signal(**kwargs)
        self.session.add(signal)
        self.session.flush()
        return signal

    def get_by_signal_id(self, signal_id: str) -> Optional[Signal]:
        """Get signal by external signal_id."""
        query = select(Signal).where(Signal.signal_id == signal_id)
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def bulk_create(self, signals: list[dict]) -> list[Signal]:
        """Bulk create signals."""
        signal_objects = [Signal(**s) for s in signals]
        self.session.add_all(signal_objects)
        self.session.flush()
        return signal_objects


class DecisionRepository:
    """Repository for decision operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Decision:
        """Create a new decision."""
        decision = Decision(**kwargs)
        self.session.add(decision)
        self.session.flush()
        return decision

    def get_by_signal_and_strategy(
        self, signal_id: int, strategy_id: int
    ) -> Optional[Decision]:
        """Get decision for a specific signal and strategy."""
        query = select(Decision).where(
            Decision.signal_id == signal_id,
            Decision.strategy_id == strategy_id,
        )
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def get_by_run(self, run_id: int) -> list[Decision]:
        """Get all decisions for a run."""
        query = (
            select(Decision)
            .where(Decision.run_id == run_id)
            .order_by(Decision.computed_at)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())


class FillRepository:
    """Repository for fill operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, decision_id: int, **kwargs) -> Fill:
        """Create a new fill."""
        fill = Fill(decision_id=decision_id, **kwargs)
        self.session.add(fill)
        self.session.flush()
        return fill

    def get_by_run(self, run_id: int) -> list[Fill]:
        """Get all fills for a run."""
        query = (
            select(Fill)
            .join(Decision)
            .where(Decision.run_id == run_id)
            .order_by(Fill.filled_at)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def get_stats_by_strategy(
        self, strategy_id: int
    ) -> dict:
        """Get aggregate stats for a strategy."""
        query = (
            select(
                func.count(Fill.id).label("trade_count"),
                func.sum(Fill.pnl_usd).label("total_pnl"),
                func.avg(Fill.pnl_usd).label("avg_pnl"),
                func.max(Fill.pnl_usd).label("best_trade"),
                func.min(Fill.pnl_usd).label("worst_trade"),
            )
            .join(Decision)
            .where(Decision.strategy_id == strategy_id)
        )
        result = self.session.execute(query)
        row = result.one()
        return {
            "trade_count": row.trade_count or 0,
            "total_pnl": row.total_pnl or 0.0,
            "avg_pnl": row.avg_pnl or 0.0,
            "best_trade": row.best_trade or 0.0,
            "worst_trade": row.worst_trade or 0.0,
        }


class TickRepository:
    """Repository for tick data operations."""

    def __init__(self, session: Session):
        self.session = session

    def bulk_create(self, ticks: list[dict]) -> list[Tick]:
        """Bulk create ticks for replay."""
        tick_objects = [Tick(**t) for t in ticks]
        self.session.add_all(tick_objects)
        self.session.flush()
        return tick_objects

    def get_by_run(self, run_id: int) -> list[Tick]:
        """Get all ticks for a run, ordered by time."""
        query = (
            select(Tick)
            .where(Tick.run_id == run_id)
            .order_by(Tick.timestamp)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def get_market_ticks(
        self, run_id: int, market_slug: str
    ) -> list[Tick]:
        """Get ticks for a specific market."""
        query = (
            select(Tick)
            .where(Tick.run_id == run_id, Tick.market_slug == market_slug)
            .order_by(Tick.timestamp)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())
