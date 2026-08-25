"""CLI entrypoints for analysis, backtest, paper trading, and the API server."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from weather_copy_bot.analysis import WalletAnalyzer
from weather_copy_bot.backtest import CopyBacktester
from weather_copy_bot.config import get_settings
from weather_copy_bot.demo_data import export_demo_json, load_dashboard_payload
from weather_copy_bot.engine import CopyEngine
from weather_copy_bot.models import Side, TradeSignal

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Polymarket weather copy-trading bot",
)
console = Console()


@app.command("dashboard-data")
def dashboard_data(
    export: bool = typer.Option(True, help="Write data/demo/dashboard.json"),
) -> None:
    """Generate curated dashboard demo metrics."""
    path = export_demo_json() if export else None
    payload = load_dashboard_payload()
    console.print("[bold green]Dashboard demo data ready[/bold green]")
    console.print(f"Headline PnL: ${payload['headline']['total_pnl_usd']:,}")
    console.print(f"Win rate: {payload['headline']['win_rate']}%")
    console.print(f"Sharpe: {payload['headline']['sharpe']}")
    if path:
        console.print(f"Wrote {path}")


@app.command("analyze")
def analyze() -> None:
    """Score demo / recent fills and print target wallet recommendations."""
    payload = load_dashboard_payload()
    fills = []
    # Reconstruct lightweight fill objects via analyzer input from recent fills
    from weather_copy_bot.models import Fill

    fills = [Fill(**raw) for raw in payload["recent_fills"]]
    analyzer = WalletAnalyzer(min_trades=1)
    cards = analyzer.score(fills)
    table = Table(title="Target Wallet Scorecards")
    table.add_column("Alias")
    table.add_column("PnL", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Rec")
    for card in payload["wallets"]:
        table.add_row(
            card["alias"],
            f"${card['total_pnl_usd']:,.0f}",
            f"{card['win_rate']:.1f}%",
            f"{card['sharpe']:.2f}",
            card["copy_recommendation"],
        )
    console.print(table)
    if cards:
        console.print(f"Analyzer selected {len(analyzer.select_targets(cards))} targets")


@app.command("backtest")
def backtest(trades: int = typer.Option(120, help="Synthetic signal count")) -> None:
    """Run a latency-aware copy backtest on synthetic weather signals."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    wallets = [
        "0x7a21c4e8b9f0d3a6e1c58294f0ab73d6e8c91f22",
        "0x3bf9e1a047d6c28b5e90a1d4c7f83e6a2b19d045",
    ]
    cities = ["New York", "London", "Tokyo", "Chicago"]
    signals = []
    for i in range(trades):
        city = cities[i % len(cities)]
        latency = 280 + (i * 7) % 520
        signals.append(
            TradeSignal(
                signal_id=str(uuid4()),
                target_wallet=wallets[i % len(wallets)],
                market_slug=f"highest-temperature-in-{city.lower().replace(' ', '-')}",
                market_title=f"Highest temperature in {city}?",
                city=city,
                outcome="Yes",
                side=Side.BUY,
                price=0.35 + (i % 40) / 100,
                size_usd=80 + (i % 10) * 12,
                detected_at=now - timedelta(hours=trades - i),
                target_filled_at=now - timedelta(hours=trades - i, milliseconds=latency),
                latency_ms=latency,
            )
        )
    result = CopyBacktester(settings).run(signals)
    console.print("[bold]Backtest complete[/bold]")
    console.print(json.dumps(result.summary.model_dump(mode="json"), indent=2))


@app.command("paper")
def paper(seconds: float = typer.Option(20.0, help="Run duration")) -> None:
    """Run the copy engine in paper mode against the demo activity stream."""
    settings = get_settings()
    settings.dry_run = True
    engine = CopyEngine(settings=settings)

    async def _run() -> None:
        await engine.run(duration_sec=seconds)
        console.print(engine.stats)
        console.print(engine.paper.summary().model_dump(mode="json"))

    asyncio.run(_run())


@app.command("serve")
def serve(
    host: str | None = None,
    port: int | None = None,
    reload: bool = False,
) -> None:
    """Start the FastAPI dashboard API."""
    settings = get_settings()
    uvicorn.run(
        "weather_copy_bot.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
