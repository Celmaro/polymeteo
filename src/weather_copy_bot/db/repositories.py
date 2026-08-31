"""Repository layer for database operations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weather_copy_bot.db.models import (
    Decision,
    Fill,
    OrderRecord,
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

    def get_by_id(self, strategy_id: int) -> Strategy | None:
        """Get strategy by ID."""
        return self.session.get(Strategy, strategy_id)

    def get_by_name_version(self, name: str, version: int | None = None) -> Strategy | None:
        """Get strategy by name and optional version."""
        query = select(Strategy).where(Strategy.name == name)
        if version:
            query = query.where(Strategy.version == version)
        else:
            query = query.where(Strategy.is_active.is_(True))
            query = query.order_by(Strategy.version.desc())
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def get_active(self) -> list[Strategy]:
        """Get all active strategies."""
        query = (
            select(Strategy)
            .where(Strategy.is_active.is_(True))
            .order_by(Strategy.name, Strategy.version.desc())
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def deactivate(self, strategy_id: int) -> Strategy | None:
        """Deactivate a strategy."""
        strategy = self.session.get(Strategy, strategy_id)
        if strategy:
            strategy.is_active = False
        return strategy

    def create_new_version(self, base_strategy_id: int, **updates) -> Strategy:
        """Create a new version of a strategy with updated params."""
        base = self.session.get(Strategy, base_strategy_id)
        if not base:
            raise ValueError(f"Strategy {base_strategy_id} not found")

        new_strategy = Strategy(
            name=base.name,
            version=base.version + 1,
            description=updates.get("description"),
            copy_ratio=updates.get("copy_ratio", base.copy_ratio),
            max_position_usd=updates.get("max_position_usd", base.max_position_usd),
            max_daily_loss_usd=updates.get("max_daily_loss_usd", base.max_daily_loss_usd),
            min_edge_bps=updates.get("min_edge_bps", base.min_edge_bps),
            max_copy_latency_ms=updates.get("max_copy_latency_ms", base.max_copy_latency_ms),
            base_markout=updates.get("base_markout", base.base_markout),
            latency_decay_rate=updates.get("latency_decay_rate", base.latency_decay_rate),
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

    def get_by_id(self, run_id: int) -> StrategyRun | None:
        """Get run by ID."""
        return self.session.get(StrategyRun, run_id)

    def update_performance(
        self,
        run_id: int,
        ending_balance: float,
        total_pnl: float,
        trade_count: int,
        **metrics,
    ) -> StrategyRun | None:
        """Update run with performance metrics."""
        run = self.session.get(StrategyRun, run_id)
        if run:
            run.ended_at = datetime.now(timezone.utc)
            run.ending_balance = ending_balance
            run.total_pnl = total_pnl
            run.trade_count = trade_count
            run.win_rate = metrics.get("win_rate")
            run.sharpe = metrics.get("sharpe")
            run.max_drawdown_pct = metrics.get("max_drawdown_pct")
        return run

    def get_by_strategy(self, strategy_id: int, limit: int = 10) -> list[StrategyRun]:
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

    def get_by_signal_id(self, signal_id: str) -> Signal | None:
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

    def get_by_signal_and_strategy(self, signal_id: int, strategy_id: int) -> Decision | None:
        """Get decision for a specific signal and strategy."""
        query = select(Decision).where(
            Decision.signal_id == signal_id,
            Decision.strategy_id == strategy_id,
        )
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def get_by_run(self, run_id: int) -> list[Decision]:
        """Get all decisions for a run."""
        query = select(Decision).where(Decision.run_id == run_id).order_by(Decision.computed_at)
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
            select(Fill).join(Decision).where(Decision.run_id == run_id).order_by(Fill.filled_at)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def get_stats_by_strategy(self, strategy_id: int) -> dict:
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
        query = select(Tick).where(Tick.run_id == run_id).order_by(Tick.timestamp)
        result = self.session.execute(query)
        return list(result.scalars().all())

    def get_market_ticks(self, run_id: int, market_slug: str) -> list[Tick]:
        """Get ticks for a specific market."""
        query = (
            select(Tick)
            .where(Tick.run_id == run_id, Tick.market_slug == market_slug)
            .order_by(Tick.timestamp)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())


class OrderRepository:
    """Repository for the OrderRecord write-ahead log.

    The OrderQueue calls into this repository to durably journal every state
    transition. Writes are best-effort: a failed flush is logged but does
    not raise back into the queue so a degraded DB never blocks live
    trading.
    """

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> OrderRecord:
        """Create a new OrderRecord row."""
        record = OrderRecord(**kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_order_id(self, order_id: str) -> OrderRecord | None:
        query = select(OrderRecord).where(OrderRecord.order_id == order_id)
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    def update_state(
        self,
        order_id: str,
        new_state: str,
        *,
        retries: int | None = None,
        fill_amount: float | None = None,
        submitted_at: datetime | None = None,
        filled_at: datetime | None = None,
        error: str | None = None,
        record_changes: bool = True,
    ) -> OrderRecord | None:
        """Update an order's state and any auxiliary columns.

        Returns the updated row, or None if the order_id is unknown. The
        caller is responsible for committing the session.
        """
        record = self.get_by_order_id(order_id)
        if record is None:
            return None
        record.state = new_state
        if retries is not None:
            record.retries = retries
        if fill_amount is not None:
            record.fill_amount = fill_amount
        if submitted_at is not None:
            record.submitted_at = submitted_at
        if filled_at is not None:
            record.filled_at = filled_at
        if error is not None:
            record.error = error
        if record_changes:
            self.session.flush()
        return record

    def upsert_from_queue(
        self,
        *,
        order_id: str,
        token_id: str,
        side: str,
        size_usd: float,
        price: float,
        state: str,
        retries: int,
        max_retries: int,
        fill_amount: float,
        created_at: datetime,
        submitted_at: datetime | None,
        filled_at: datetime | None,
        error: str | None,
        mode: str,
        metadata_json: dict | None,
    ) -> OrderRecord:
        """Insert-or-update an order record from the in-memory queue.

        Used by the queue's state-transition hooks: the first call for an
        order_id performs an insert, subsequent calls perform an update on
        the matching row.
        """
        record = self.get_by_order_id(order_id)
        if record is None:
            record = OrderRecord(
                order_id=order_id,
                token_id=token_id,
                side=side,
                size_usd=size_usd,
                price=price,
                state=state,
                retries=retries,
                max_retries=max_retries,
                fill_amount=fill_amount,
                created_at=created_at,
                submitted_at=submitted_at,
                filled_at=filled_at,
                error=error,
                mode=mode,
                metadata_json=metadata_json,
            )
            self.session.add(record)
        else:
            record.state = state
            record.retries = retries
            record.fill_amount = fill_amount
            record.submitted_at = submitted_at
            record.filled_at = filled_at
            record.error = error
        self.session.flush()
        return record

    def get_by_state(self, state: str) -> list[OrderRecord]:
        query = (
            select(OrderRecord)
            .where(OrderRecord.state == state)
            .order_by(OrderRecord.created_at)
        )
        result = self.session.execute(query)
        return list(result.scalars().all())

    def get_active(self, mode: str | None = None) -> list[OrderRecord]:
        """Get all non-terminal orders (PENDING, SUBMITTED, PARTIAL)."""
        terminal = {"filled", "cancelled", "rejected", "failed"}
        query = select(OrderRecord).where(OrderRecord.state.notin_(terminal))
        if mode is not None:
            query = query.where(OrderRecord.mode == mode)
        query = query.order_by(OrderRecord.created_at)
        result = self.session.execute(query)
        return list(result.scalars().all())
