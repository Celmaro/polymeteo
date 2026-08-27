"""Demo data service with dependency injection support."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from weather_copy_bot.metrics import summarize_fills
from weather_copy_bot.models import (
    CityBreakdown,
    DashboardPayload,
    EquityPoint,
    Fill,
    LatencyBucket,
    Side,
    WalletScorecard,
)


def _data_dir() -> Path:
    """Resolve at call time so APP_ROOT overrides (e.g. tests) take effect."""
    return Path(os.environ.get("APP_ROOT", "/app")) / "data" / "demo"

CITIES = [
    "New York",
    "London",
    "Tokyo",
    "Chicago",
    "Seattle",
    "Miami",
    "Paris",
    "Sydney",
]

WEATHER_TYPES = [
    ("highest-temperature", "Highest temperature in {}?", "temperature"),
    ("will-it-rain", "Will it rain in {}?", "rain"),
    ("hurricane-category", "Hurricane {} on {}?", "hurricane"),
    ("daily-snowfall", "Daily snowfall in {}?", "snow"),
    ("severe-thunderstorm", "Severe thunderstorm in {}?", "storm"),
    ("tornado-risk", "Tornado risk in {}?", "tornado"),
    ("flash-flood", "Flash flood warning in {}?", "flood"),
    ("blizzard-warning", "Blizzard warning for {}?", "blizzard"),
    ("coastal-flood", "Coastal flood in {}?", "flood"),
    ("extreme-heat", "Extreme heat advisory {}?", "temperature"),
    ("wind-speed", "Peak wind speed in {}?", "wind"),
    ("drought-index", "Drought index for {}?", "drought"),
]

TARGET_WALLETS = [
    {
        "wallet": "0x7a21c4e8b9f0d3a6e1c58294f0ab73d6e8c91f22",
        "alias": "SkylineAlpha",
        "edge": 0.72,
        "specialty": ["New York", "Chicago", "Seattle"],
    },
    {
        "wallet": "0x3bf9e1a047d6c28b5e90a1d4c7f83e6a2b19d045",
        "alias": "Frontogenesis",
        "edge": 0.66,
        "specialty": ["London", "Paris", "Tokyo"],
    },
    {
        "wallet": "0x91d0aa56c2e84f17b3c9e08d5a6f12b4e70c83aa",
        "alias": "DewpointDesk",
        "edge": 0.61,
        "specialty": ["Miami", "Sydney", "Tokyo"],
    },
]


class RandomGenerator:
    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def create_rng(self) -> np.random.Generator:
        return np.random.default_rng(self._seed)


class DemoDataGenerator(ABC):
    @abstractmethod
    def generate_fills(
        self, mode: str, n: int, start_balance: float, base_latency: int
    ) -> tuple[list[Fill], list[EquityPoint]]:
        raise NotImplementedError

    @abstractmethod
    def generate_wallet_scorecards(self, fills: list[Fill]) -> list[WalletScorecard]:
        raise NotImplementedError


class DefaultDemoDataGenerator(DemoDataGenerator):
    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self._rng = rng or np.random.default_rng(42)

    def create_rng(self) -> np.random.Generator:
        return self._rng

    def generate_fills(
        self, mode: str, n: int, start_balance: float, base_latency: int
    ) -> tuple[list[Fill], list[EquityPoint]]:
        fills: list[Fill] = []
        equity = start_balance
        peak = equity
        curve: list[EquityPoint] = []
        now = datetime.now(timezone.utc)

        for i in range(n):
            wallet = TARGET_WALLETS[i % len(TARGET_WALLETS)]
            city = wallet["specialty"][i % len(wallet["specialty"])]
            win = bool(self._rng.random() < (0.58 + wallet["edge"] * 0.12))
            size = float(self._rng.uniform(40, 220))
            pnl = float(self._rng.uniform(8, 62) if win else -self._rng.uniform(5, 28))
            if mode == "paper":
                pnl *= 1.05
            if mode == "backtest":
                pnl *= 0.98

            latency = int(np.clip(self._rng.normal(base_latency, 90), 180, 980))
            ts = now - timedelta(hours=(n - i) * 5)
            equity += pnl
            peak = max(peak, equity)
            dd = ((equity - peak) / peak) * 100.0 if peak else 0.0

            wt_slug, wt_title, _ = WEATHER_TYPES[i % len(WEATHER_TYPES)]
            wt_slug = f"{wt_slug}-in-{city.lower().replace(' ', '-')}-on-date"
            wt_title = wt_title.format(city)
            fills.append(
                Fill(
                    fill_id=f"{mode}-{i:04d}",
                    signal_id=f"sig-{mode}-{i:04d}",
                    target_wallet=wallet["wallet"],
                    market_slug=wt_slug,
                    market_title=wt_title,
                    city=city,
                    outcome=str(
                        self._rng.choice(["Yes", "No", "68-69°F", "70-71°F", "Above 72°F"])
                    ),
                    side=Side.BUY if self._rng.random() > 0.18 else Side.SELL,
                    price=round(float(self._rng.uniform(0.18, 0.82)), 3),
                    size_usd=round(size, 2),
                    fee_usd=round(size * 0.002, 3),
                    pnl_usd=round(pnl, 2),
                    latency_ms=latency,
                    filled_at=ts,
                    mode=mode,
                )
            )
            curve.append(
                EquityPoint(
                    timestamp=ts,
                    equity_usd=round(equity, 2),
                    pnl_usd=round(equity - start_balance, 2),
                    drawdown_pct=round(dd, 2),
                )
            )

        return fills, curve

    def generate_wallet_scorecards(self, fills: list[Fill]) -> list[WalletScorecard]:
        cards: list[WalletScorecard] = []
        for meta in TARGET_WALLETS:
            w_fills = [f for f in fills if f.target_wallet == meta["wallet"]]
            if not w_fills:
                continue
            pnls = [f.pnl_usd for f in w_fills]
            equity = np.cumsum(pnls)
            gains = sum(p for p in pnls if p > 0)
            losses = abs(sum(p for p in pnls if p < 0))
            pf = gains / losses if losses else float("inf")
            wins = sum(1 for p in pnls if p > 0)
            peak = np.maximum.accumulate(equity)
            dd = float(np.min((equity - peak) / np.maximum(peak, 1e-9)) * 100.0)
            rets = np.diff(equity, prepend=0)
            sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252))
            consistency = min(99.0, 55 + wins / len(pnls) * 40 + (2 if pf > 1.8 else 0))
            cards.append(
                WalletScorecard(
                    wallet=meta["wallet"],
                    alias=meta["alias"],
                    total_pnl_usd=round(sum(pnls), 2),
                    win_rate=round(wins / len(pnls) * 100.0, 2),
                    trade_count=len(w_fills),
                    avg_latency_ms=round(float(np.mean([f.latency_ms for f in w_fills])), 1),
                    sharpe=round(sharpe, 2),
                    max_drawdown_pct=round(abs(dd), 2),
                    profit_factor=round(pf, 2),
                    specialty_cities=meta["specialty"],
                    consistency_score=round(consistency, 1),
                    copy_recommendation="PRIMARY" if consistency > 85 else "SATELLITE",
                )
            )
        return sorted(cards, key=lambda c: c.total_pnl_usd, reverse=True)


def _city_breakdown(fills: list[Fill]) -> list[CityBreakdown]:
    out: list[CityBreakdown] = []
    for city in CITIES:
        subset = [f for f in fills if f.city == city]
        if not subset:
            continue
        wins = sum(1 for f in subset if f.pnl_usd > 0)
        out.append(
            CityBreakdown(
                city=city,
                trade_count=len(subset),
                pnl_usd=round(sum(f.pnl_usd for f in subset), 2),
                win_rate=round(wins / len(subset) * 100.0, 2),
            )
        )
    return sorted(out, key=lambda c: c.pnl_usd, reverse=True)


def _latency_buckets(fills: list[Fill]) -> list[LatencyBucket]:
    buckets = [
        ("<350ms", lambda x: x < 350),
        ("350-550ms", lambda x: 350 <= x < 550),
        ("550-750ms", lambda x: 550 <= x < 750),
        ("750ms+", lambda x: x >= 750),
    ]
    out: list[LatencyBucket] = []
    for label, pred in buckets:
        subset = [f for f in fills if pred(f.latency_ms)]
        if not subset:
            out.append(LatencyBucket(bucket=label, trade_count=0, avg_pnl_usd=0.0, win_rate=0.0))
            continue
        wins = sum(1 for f in subset if f.pnl_usd > 0)
        out.append(
            LatencyBucket(
                bucket=label,
                trade_count=len(subset),
                avg_pnl_usd=round(float(np.mean([f.pnl_usd for f in subset])), 2),
                win_rate=round(wins / len(subset) * 100.0, 2),
            )
        )
    return out


class DashboardService:
    def __init__(self, generator: DemoDataGenerator | None = None) -> None:
        self._generator = generator or DefaultDemoDataGenerator()

    @property
    def generator(self) -> DemoDataGenerator:
        return self._generator

    def create_dashboard_payload(self) -> DashboardPayload:
        paper_fills, paper_curve = self._generator.generate_fills(
            "paper", 96, 10_000.0, base_latency=420
        )
        bt_fills, bt_curve = self._generator.generate_fills(
            "backtest", 180, 10_000.0, base_latency=460
        )
        combined = paper_fills + bt_fills
        headline_fills = paper_fills
        headline = summarize_fills(headline_fills, paper_curve, "paper", 10_000.0)
        headline.total_pnl_usd = 47832.45
        headline.ending_balance = 57832.45
        headline.total_return_pct = 478.32
        headline.win_rate = 68.4
        headline.sharpe = 2.41
        headline.sortino = 3.18
        headline.max_drawdown_pct = 8.2
        headline.profit_factor = 2.67
        headline.avg_latency_ms = 412.0
        headline.median_latency_ms = 398.0
        headline.trade_count = 312
        headline.best_trade_usd = 1840.0
        headline.worst_trade_usd = -312.0
        headline.avg_copy_edge_bps = 86.0

        if paper_curve:
            start = 10_000.0
            end = headline.ending_balance
            raw_end = paper_curve[-1].equity_usd
            scale = (end - start) / max(raw_end - start, 1e-9)
            reshaped: list[EquityPoint] = []
            peak = start
            for p in paper_curve:
                eq = start + (p.equity_usd - start) * scale
                peak = max(peak, eq)
                reshaped.append(
                    EquityPoint(
                        timestamp=p.timestamp,
                        equity_usd=round(eq, 2),
                        pnl_usd=round(eq - start, 2),
                        drawdown_pct=round(((eq - peak) / peak) * 100.0, 2),
                    )
                )
            paper_curve = reshaped

        paper_summary = summarize_fills(paper_fills, paper_curve, "paper", 10_000.0)
        paper_summary.total_pnl_usd = round(paper_curve[-1].pnl_usd, 2)
        paper_summary.ending_balance = round(paper_curve[-1].equity_usd, 2)
        paper_summary.total_return_pct = round(
            (paper_summary.ending_balance / 10_000.0 - 1) * 100, 2
        )
        paper_summary.win_rate = 67.7
        paper_summary.sharpe = 2.28
        paper_summary.max_drawdown_pct = 7.4

        bt_summary = summarize_fills(bt_fills, bt_curve, "backtest", 10_000.0)
        bt_summary.total_pnl_usd = 39210.88
        bt_summary.ending_balance = 49210.88
        bt_summary.total_return_pct = 392.11
        bt_summary.win_rate = 66.1
        bt_summary.sharpe = 2.09
        bt_summary.max_drawdown_pct = 9.6
        bt_summary.profit_factor = 2.41

        wallets = self._generator.generate_wallet_scorecards(combined)
        showcase = {
            "SkylineAlpha": {
                "total_pnl_usd": 21440.0,
                "win_rate": 71.2,
                "sharpe": 2.55,
                "max_drawdown_pct": 6.8,
                "profit_factor": 2.91,
                "consistency_score": 93.4,
                "copy_recommendation": "PRIMARY",
                "avg_latency_ms": 390.0,
            },
            "Frontogenesis": {
                "total_pnl_usd": 16280.0,
                "win_rate": 67.8,
                "sharpe": 2.18,
                "max_drawdown_pct": 8.1,
                "profit_factor": 2.44,
                "consistency_score": 88.1,
                "copy_recommendation": "PRIMARY",
                "avg_latency_ms": 430.0,
            },
            "DewpointDesk": {
                "total_pnl_usd": 10112.0,
                "win_rate": 64.5,
                "sharpe": 1.92,
                "max_drawdown_pct": 9.4,
                "profit_factor": 2.11,
                "consistency_score": 84.0,
                "copy_recommendation": "SATELLITE",
                "avg_latency_ms": 460.0,
            },
        }
        for card in wallets:
            patch = showcase.get(card.alias)
            if not patch:
                continue
            for key, value in patch.items():
                setattr(card, key, value)
        wallets = sorted(wallets, key=lambda c: c.total_pnl_usd, reverse=True)

        return DashboardPayload(
            generated_at=datetime.now(timezone.utc),
            headline=headline,
            paper=paper_summary,
            backtest=bt_summary,
            wallets=wallets,
            equity_curve=paper_curve,
            paper_equity=paper_curve,
            backtest_equity=bt_curve,
            recent_fills=sorted(paper_fills, key=lambda f: f.filled_at, reverse=True)[:18],
            city_breakdown=_city_breakdown(paper_fills),
            latency_buckets=_latency_buckets(paper_fills),
            copy_funnel={
                "signals_detected": 1482,
                "passed_filters": 624,
                "latency_ok": 511,
                "copied": 312,
                "skipped_stale": 113,
                "skipped_risk": 199,
            },
            engine_status={
                "mode": "paper",
                "targets_active": len(TARGET_WALLETS),
                "poll_interval_ms": 250,
                "max_copy_latency_ms": 800,
                "avg_detect_to_submit_ms": 412,
                "markets_watched": 48,
                "uptime_hours": 312,
                "health": "healthy",
            },
        )


def export_demo_json() -> Path:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    service = DashboardService()
    payload = service.create_dashboard_payload()
    path = data_dir / "dashboard.json"
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_dashboard_payload() -> dict[str, Any]:
    path = _data_dir() / "dashboard.json"
    if not path.exists():
        export_demo_json()
    return json.loads(path.read_text(encoding="utf-8"))


def get_dashboard_service(generator: DemoDataGenerator | None = None) -> DashboardService:
    return DashboardService(generator)


def build_dashboard_payload() -> DashboardPayload:
    return DashboardService().create_dashboard_payload()
