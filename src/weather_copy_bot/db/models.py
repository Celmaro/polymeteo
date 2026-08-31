"""Database models for tick-level storage and strategy versioning."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SideEnum(PyEnum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyMode(PyEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Strategy(Base):
    """Versioned trading strategy with reproducible parameters."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Core parameters
    copy_ratio: Mapped[float] = mapped_column(Float, default=0.25)
    max_position_usd: Mapped[float] = mapped_column(Float, default=250.0)
    max_daily_loss_usd: Mapped[float] = mapped_column(Float, default=500.0)
    min_edge_bps: Mapped[float] = mapped_column(Float, default=50.0)
    max_copy_latency_ms: Mapped[int] = mapped_column(Integer, default=800)

    # Markout model parameters
    base_markout: Mapped[float] = mapped_column(Float, default=0.035)
    latency_decay_rate: Mapped[float] = mapped_column(Float, default=0.012)
    fee_rate: Mapped[float] = mapped_column(Float, default=0.002)

    # JSON for any extra parameters
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    runs: Mapped[list[StrategyRun]] = relationship(back_populates="strategy")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_strategy_name_version"),
        Index("ix_strategy_name_active", "name", "is_active"),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("version", 1)
        kwargs.setdefault("copy_ratio", 0.25)
        kwargs.setdefault("max_position_usd", 250.0)
        kwargs.setdefault("max_daily_loss_usd", 500.0)
        kwargs.setdefault("min_edge_bps", 50.0)
        kwargs.setdefault("max_copy_latency_ms", 800)
        kwargs.setdefault("base_markout", 0.035)
        kwargs.setdefault("latency_decay_rate", 0.012)
        kwargs.setdefault("fee_rate", 0.002)
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)


class StrategyRun(Base):
    """A backtest/paper/live run associated with a strategy version."""

    __tablename__ = "strategy_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategies.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), default="backtest")

    # Run metadata
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Market filter for this run
    market_filter: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Starting balance
    starting_balance: Mapped[float] = mapped_column(Float, default=10_000.0)

    # Performance summary (computed after run)
    ending_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    strategy: Mapped[Strategy] = relationship(back_populates="runs")
    ticks: Mapped[list[Tick]] = relationship(back_populates="run")
    signals: Mapped[list[Signal]] = relationship(back_populates="run")
    decisions: Mapped[list[Decision]] = relationship(back_populates="run")

    __table_args__ = (Index("ix_strategy_run_strategy_started", "strategy_id", "started_at"),)


class Tick(Base):
    """Minute-level market data for replay."""

    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("strategy_runs.id"), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    market_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    market_title: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Price data
    yes_price: Mapped[float] = mapped_column(Float, nullable=False)
    no_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional weather-specific fields
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    run: Mapped[StrategyRun] = relationship(back_populates="ticks")

    __table_args__ = (
        Index("ix_tick_run_timestamp", "run_id", "timestamp"),
        Index("ix_tick_market_timestamp", "market_slug", "timestamp"),
    )


class Signal(Base):
    """Detected trading signal from target wallet activity."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy_runs.id"), nullable=True
    )

    signal_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # Source info
    target_wallet: Mapped[str] = mapped_column(String(100), nullable=False)
    market_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    market_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Signal details
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    token_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timing
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    target_filled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    run: Mapped[StrategyRun | None] = relationship(back_populates="signals")
    decisions: Mapped[list[Decision]] = relationship(back_populates="signal")

    __table_args__ = (
        Index("ix_signal_signal_id", "signal_id", unique=True),
        Index("ix_signal_run_detected", "run_id", "detected_at"),
    )


class Decision(Base):
    """Bot decision for a signal with strategy versioning."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy_runs.id"), nullable=True
    )
    signal_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("signals.id"), nullable=False)

    # Strategy info at decision time
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategies.id"), nullable=False
    )

    # Decision result
    should_copy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)

    # Size and slippage
    copy_size_usd: Mapped[float] = mapped_column(Float, default=0.0)
    expected_slippage_bps: Mapped[float] = mapped_column(Float, default=0.0)

    # Computed values at decision time
    edge_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    run: Mapped[StrategyRun | None] = relationship(back_populates="decisions")
    signal: Mapped[Signal] = relationship(back_populates="decisions")
    strategy: Mapped[Strategy] = relationship()
    fill: Mapped[Fill | None] = relationship(back_populates="decision")

    __table_args__ = (Index("ix_decision_signal_strategy", "signal_id", "strategy_id"),)


class Fill(Base):
    """Executed trade fill with P&L."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("decisions.id"), unique=True, nullable=False
    )

    fill_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # Position details
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Fees and P&L
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_usd: Mapped[float] = mapped_column(Float, nullable=False)
    markout: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timing
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="backtest")

    # Relationships
    decision: Mapped[Decision] = relationship(back_populates="fill")
    equity_points: Mapped[list[EquityPoint]] = relationship(back_populates="fill")

    __table_args__ = (
        Index("ix_fill_filled_at", "filled_at"),
        Index("ix_fill_fill_id", "fill_id", unique=True),
    )


class EquityPoint(Base):
    """Equity curve snapshots for performance visualization."""

    __tablename__ = "equity_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fill_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fills.id"), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    balance_usd: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_usd: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    fill: Mapped[Fill | None] = relationship(back_populates="equity_points")

    __table_args__ = (Index("ix_equity_timestamp", "timestamp"),)


class OrderRecord(Base):
    """Write-ahead log of order state transitions for OrderQueue.

    Persists the full lifecycle of each order (PENDING -> SUBMITTED -> FILLED /
    CANCELLED / REJECTED / FAILED) so that a process restart can reconcile
    in-flight orders against durable storage rather than losing them when
    the in-memory dict is wiped. The queue remains the source of truth at
    runtime; this table is the durable journal.
    """

    __tablename__ = "order_records"

    # SQLite ignores autoincrement on BigInteger; use Integer on sqlite so the
    # ROWID alias still produces ROWID for autoincrement. Postgres keeps
    # BigInteger.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    # External order id (UUID4 generated by the queue).
    order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Order details
    token_id: Mapped[str] = mapped_column(String(100), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)

    # Lifecycle (string column mirrors the in-memory OrderState enum so
    # queries can filter without an additional join).
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    fill_amount: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps (DateTime so queries can use date range filters; the
    # in-memory Order dataclass stores epoch floats which we convert on
    # flush).
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Error context for the latest state transition.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Mode tag (backtest / paper / live) so operators can scope dashboards.
    mode: Mapped[str] = mapped_column(String(20), default="paper")

    # Optional metadata (signal id, target wallet, slippage estimate, ...).
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # When this journal row was last written to disk.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_order_record_order_id", "order_id", unique=True),
        Index("ix_order_record_state_created", "state", "created_at"),
        Index("ix_order_record_token_side", "token_id", "side"),
    )
