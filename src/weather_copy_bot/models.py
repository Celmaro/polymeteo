"""Shared domain models for analysis, backtest, paper, and copy trading."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSignal(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    signal_id: str
    target_wallet: str
    market_slug: str
    market_title: str
    city: str
    outcome: str
    side: Side
    price: float
    size_usd: float
    detected_at: datetime
    target_filled_at: datetime
    # Two-tier latency (audit P0):
    #   ``latency_ms``       - local processing lag between detect and decision
    #   ``upstream_age_ms``  - age of the upstream event when we received it
    # Defaults to 0 so historical replays and synthesized signals stay valid.
    latency_ms: int = 0
    upstream_age_ms: int = 0
    token_id: str | None = None


class CopyDecision(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    signal: TradeSignal
    should_copy: bool
    reason: str
    copy_size_usd: float = 0.0
    expected_slippage_bps: float = 0.0


class Fill(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    fill_id: str
    signal_id: str
    target_wallet: str
    market_slug: str
    market_title: str
    city: str
    outcome: str
    side: Side
    price: float
    size_usd: float
    fee_usd: float
    pnl_usd: float
    latency_ms: int
    filled_at: datetime
    mode: str


class WalletScorecard(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    wallet: str
    alias: str
    total_pnl_usd: float
    win_rate: float
    trade_count: int
    avg_latency_ms: float
    sharpe: float
    max_drawdown_pct: float
    profit_factor: float
    specialty_cities: list[str] = Field(default_factory=list)
    consistency_score: float
    copy_recommendation: str


class EquityPoint(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    timestamp: datetime
    equity_usd: float
    pnl_usd: float
    drawdown_pct: float


class PerformanceSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    mode: str
    starting_balance: float
    ending_balance: float
    total_pnl_usd: float
    total_return_pct: float
    win_rate: float
    trade_count: int
    avg_latency_ms: float
    median_latency_ms: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    profit_factor: float
    best_trade_usd: float
    worst_trade_usd: float
    avg_copy_edge_bps: float


class BacktestResult(BaseModel):
    """Aggregated output of a backtest run."""

    model_config = ConfigDict(extra="ignore", frozen=False)

    summary: PerformanceSummary
    fills: list[Fill] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    decisions: list[CopyDecision] = Field(default_factory=list)


class CityBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    city: str
    trade_count: int
    pnl_usd: float
    win_rate: float


class LatencyBucket(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    bucket: str
    trade_count: int
    avg_pnl_usd: float
    win_rate: float


class DashboardPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)

    generated_at: datetime
    headline: PerformanceSummary
    paper: PerformanceSummary
    backtest: PerformanceSummary
    wallets: list[WalletScorecard]
    equity_curve: list[EquityPoint]
    paper_equity: list[EquityPoint]
    backtest_equity: list[EquityPoint]
    recent_fills: list[Fill]
    city_breakdown: list[CityBreakdown]
    latency_buckets: list[LatencyBucket]
    copy_funnel: dict
    engine_status: dict


class TickData(BaseModel):
    """Real-time tick data from CLOB."""

    model_config = ConfigDict(extra="ignore", frozen=False)

    market_slug: str
    price: float
    volume: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    best_bid: float | None = None
    best_ask: float | None = None


class Market(BaseModel):
    """Polymarket market info."""

    model_config = ConfigDict(extra="ignore", frozen=False)

    slug: str
    title: str
    question: str
    outcomes: list[str]
    outcome_prices: dict[str, float]
    volume: float
    liquidity: float
    expires_at: datetime | None = None
    closed: bool = False
