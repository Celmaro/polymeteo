"""Target-wallet scoring for weather-market copy selection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import numpy as np

from weather_copy_bot.models import Fill, WalletScorecard


class WalletAnalyzer:
    """Ranks wallets by consistency, latency-sensitive edge, and city specialty."""

    def __init__(self, min_trades: int = 20):
        self.min_trades = min_trades

    def score(self, fills: Iterable[Fill]) -> list[WalletScorecard]:
        by_wallet: dict[str, list[Fill]] = defaultdict(list)
        for fill in fills:
            by_wallet[fill.target_wallet].append(fill)

        cards: list[WalletScorecard] = []
        for wallet, w_fills in by_wallet.items():
            if len(w_fills) < self.min_trades:
                continue
            cards.append(self._score_wallet(wallet, w_fills))
        return sorted(cards, key=lambda c: (c.consistency_score, c.total_pnl_usd), reverse=True)

    def _score_wallet(self, wallet: str, fills: list[Fill]) -> WalletScorecard:
        pnls = np.array([f.pnl_usd for f in fills], dtype=float)
        latencies = np.array([f.latency_ms for f in fills], dtype=float)
        wins = int(np.sum(pnls > 0))
        gains = float(np.sum(pnls[pnls > 0])) if np.any(pnls > 0) else 0.0
        losses = float(abs(np.sum(pnls[pnls < 0]))) if np.any(pnls < 0) else 0.0
        pf = gains / losses if losses else (999.0 if gains > 0 else 0.0)

        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        dd = float(abs(np.min((equity - peak) / np.maximum(peak, 1e-9)) * 100.0))
        rets = np.diff(equity, prepend=0.0)
        sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252))

        city_pnl: dict[str, float] = defaultdict(float)
        for f in fills:
            city_pnl[f.city] += f.pnl_usd
        specialty = [c for c, _ in sorted(city_pnl.items(), key=lambda x: x[1], reverse=True)[:3]]

        win_rate = wins / len(fills) * 100.0
        latency_bonus = max(0.0, (700 - float(np.mean(latencies))) / 50.0)
        consistency = min(
            99.5,
            win_rate * 0.55 + min(pf, 3.0) * 8.0 + latency_bonus + (5.0 if dd < 10 else 0.0),
        )
        recommendation = (
            "PRIMARY" if consistency >= 85 and win_rate >= 60 else
            "SATELLITE" if consistency >= 70 else
            "WATCHLIST"
        )

        return WalletScorecard(
            wallet=wallet,
            alias=wallet[:8] + "…" + wallet[-4:],
            total_pnl_usd=round(float(np.sum(pnls)), 2),
            win_rate=round(win_rate, 2),
            trade_count=len(fills),
            avg_latency_ms=round(float(np.mean(latencies)), 1),
            sharpe=round(sharpe, 2),
            max_drawdown_pct=round(dd, 2),
            profit_factor=round(pf, 2),
            specialty_cities=specialty,
            consistency_score=round(consistency, 1),
            copy_recommendation=recommendation,
        )

    def select_targets(self, cards: list[WalletScorecard], max_targets: int = 3) -> list[WalletScorecard]:
        preferred = [c for c in cards if c.copy_recommendation in {"PRIMARY", "SATELLITE"}]
        return preferred[:max_targets]
