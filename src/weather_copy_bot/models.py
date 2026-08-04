"""Shared domain models for analysis, backtest, paper, and copy trading."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSignal(BaseModel):
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
    latency_ms: int
    token_id: Optional[str] = None


class CopyDecision(BaseModel):
    signal: TradeSignal
    should_copy: bool
    reason: str
    copy_size_usd: float = 0.0
    expected_slippage_bps: float = 0.0


class Fill(BaseModel):
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
    mode: str  # backtest | paper | live


class WalletScorecard(BaseModel):
    wallet: str
    alias: str
    total_pnl_usd: float
    win_rate: float
    trade_count: int
    avg_latency_ms: float
    sharpe: float
    max_drawdown_pct: float
    profit_factor: float
    specialty_cities: List[str] = Field(default_factory=list)
    consistency_score: float
    copy_recommendation: str


class EquityPoint(BaseModel):
    timestamp: datetime
    equity_usd: float
    pnl_usd: float
    drawdown_pct: float


class PerformanceSummary(BaseModel):
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


class CityBreakdown(BaseModel):
    city: str
    trade_count: int
    pnl_usd: float
    win_rate: float


class LatencyBucket(BaseModel):
    bucket: str
    trade_count: int
    avg_pnl_usd: float
    win_rate: float


class DashboardPayload(BaseModel):
    generated_at: datetime
    headline: PerformanceSummary
    paper: PerformanceSummary
    backtest: PerformanceSummary
    wallets: List[WalletScorecard]
    equity_curve: List[EquityPoint]
    paper_equity: List[EquityPoint]
    backtest_equity: List[EquityPoint]
    recent_fills: List[Fill]
    city_breakdown: List[CityBreakdown]
    latency_buckets: List[LatencyBucket]
    copy_funnel: dict
    engine_status: dict
