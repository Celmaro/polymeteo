"""Performance metric helpers used across backtest, paper, and live modes."""

from __future__ import annotations

from typing import Iterable, List, Sequence

import numpy as np

from weather_copy_bot.models import EquityPoint, Fill, PerformanceSummary


def _returns_from_equity(equity: Sequence[float]) -> np.ndarray:
    if len(equity) < 2:
        return np.array([])
    arr = np.asarray(equity, dtype=float)
    prev = np.maximum(arr[:-1], 1e-9)
    return (arr[1:] - arr[:-1]) / prev


def sharpe_ratio(equity: Sequence[float], periods_per_year: float = 365.0) -> float:
    rets = _returns_from_equity(equity)
    if rets.size == 0 or np.std(rets) == 0:
        return 0.0
    return float(np.mean(rets) / np.std(rets) * np.sqrt(periods_per_year))


def sortino_ratio(equity: Sequence[float], periods_per_year: float = 365.0) -> float:
    rets = _returns_from_equity(equity)
    downside = rets[rets < 0]
    if rets.size == 0 or downside.size == 0 or np.std(downside) == 0:
        return 0.0
    return float(np.mean(rets) / np.std(downside) * np.sqrt(periods_per_year))


def max_drawdown_pct(equity: Sequence[float]) -> float:
    if not equity:
        return 0.0
    arr = np.asarray(equity, dtype=float)
    peaks = np.maximum.accumulate(arr)
    dd = (arr - peaks) / np.maximum(peaks, 1e-9)
    return float(abs(dd.min()) * 100.0)


def profit_factor(fills: Iterable[Fill]) -> float:
    gains = sum(f.pnl_usd for f in fills if f.pnl_usd > 0)
    losses = abs(sum(f.pnl_usd for f in fills if f.pnl_usd < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_fills(
    fills: List[Fill],
    equity_curve: List[EquityPoint],
    mode: str,
    starting_balance: float,
) -> PerformanceSummary:
    if not fills:
        return PerformanceSummary(
            mode=mode,
            starting_balance=starting_balance,
            ending_balance=starting_balance,
            total_pnl_usd=0.0,
            total_return_pct=0.0,
            win_rate=0.0,
            trade_count=0,
            avg_latency_ms=0.0,
            median_latency_ms=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown_pct=0.0,
            profit_factor=0.0,
            best_trade_usd=0.0,
            worst_trade_usd=0.0,
            avg_copy_edge_bps=0.0,
        )

    pnls = [f.pnl_usd for f in fills]
    latencies = [f.latency_ms for f in fills]
    equity = [p.equity_usd for p in equity_curve] or [starting_balance + sum(pnls)]
    ending = equity[-1]
    wins = sum(1 for p in pnls if p > 0)

    return PerformanceSummary(
        mode=mode,
        starting_balance=starting_balance,
        ending_balance=round(ending, 2),
        total_pnl_usd=round(sum(pnls), 2),
        total_return_pct=round(((ending / starting_balance) - 1.0) * 100.0, 2),
        win_rate=round(wins / len(pnls) * 100.0, 2),
        trade_count=len(fills),
        avg_latency_ms=round(float(np.mean(latencies)), 1),
        median_latency_ms=round(float(np.median(latencies)), 1),
        sharpe=round(sharpe_ratio(equity), 2),
        sortino=round(sortino_ratio(equity), 2),
        max_drawdown_pct=round(max_drawdown_pct(equity), 2),
        profit_factor=round(profit_factor(fills), 2),
        best_trade_usd=round(max(pnls), 2),
        worst_trade_usd=round(min(pnls), 2),
        avg_copy_edge_bps=round(float(np.mean([max(0.0, p) for p in pnls]) * 10), 1),
    )
