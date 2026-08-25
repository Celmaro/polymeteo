"""CLI commands for database and strategy management."""

import typer
from rich.console import Console
from rich.table import Table

from weather_copy_bot.db import get_db_manager, init_db
from weather_copy_bot.db.repositories import StrategyRepository

app = typer.Typer(help="Database management commands")
console = Console()


@app.command()
def init(
    database_url: str = typer.Option(
        None, "--database-url", "-d", help="Database URL (default: from settings)"
    ),
) -> None:
    """Initialize the database and create tables."""
    console.print("[bold]Initializing database...[/bold]")

    db = init_db(database_url) if database_url else init_db()

    console.print("[green]Database initialized successfully![/green]")
    console.print(f"Database URL: {db.database_url}")


@app.command()
def create_strategy(
    name: str = typer.Option(..., "--name", "-n", help="Strategy name"),
    version: int = typer.Option(None, "--version", "-v", help="Strategy version"),
    copy_ratio: float = typer.Option(0.25, "--copy-ratio", "-r"),
    max_position: float = typer.Option(250.0, "--max-position", "-m"),
    max_daily_loss: float = typer.Option(500.0, "--max-daily-loss", "-l"),
    min_edge_bps: float = typer.Option(50.0, "--min-edge-bps", "-e"),
    max_latency_ms: int = typer.Option(800, "--max-latency", "-t"),
    base_markout: float = typer.Option(0.035, "--base-markout"),
    latency_decay: float = typer.Option(0.012, "--latency-decay"),
    fee_rate: float = typer.Option(0.002, "--fee-rate"),
    description: str = typer.Option(None, "--description", "-d"),
) -> None:
    """Create a new strategy version."""
    db = get_db_manager()

    with db.session() as session:
        repo = StrategyRepository(session)

        # Check if name exists and get latest version
        existing = repo.get_by_name_version(name)
        if existing and version is None:
            version = existing.version + 1
        elif version is None:
            version = 1

        _strategy = repo.create(
            name=name,
            version=version,
            description=description,
            copy_ratio=copy_ratio,
            max_position_usd=max_position,
            max_daily_loss_usd=max_daily_loss,
            min_edge_bps=min_edge_bps,
            max_copy_latency_ms=max_latency_ms,
            base_markout=base_markout,
            latency_decay_rate=latency_decay,
            fee_rate=fee_rate,
        )

        session.commit()

    console.print(f"[green]Created strategy '{name}' v{version}[/green]")


@app.command()
def list_strategies() -> None:
    """List all strategies."""
    db = get_db_manager()

    with db.session() as session:
        repo = StrategyRepository(session)
        strategies = repo.get_active()

    if not strategies:
        console.print("[yellow]No strategies found[/yellow]")
        return

    table = Table(title="Strategies")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Version", style="yellow")
    table.add_column("Copy Ratio", justify="right")
    table.add_column("Max Position", justify="right")
    table.add_column("Min Edge (bps)", justify="right")
    table.add_column("Max Latency (ms)", justify="right")

    for s in strategies:
        table.add_row(
            str(s.id),
            s.name,
            str(s.version),
            f"{s.copy_ratio:.2f}",
            f"${s.max_position_usd:.0f}",
            f"{s.min_edge_bps:.0f}",
            str(s.max_copy_latency_ms),
        )

    console.print(table)


@app.command()
def compare_strategies(
    strategy_ids: str = typer.Option(
        ..., "--strategy-ids", "-s", help="Comma-separated strategy IDs"
    ),
) -> None:
    """Compare multiple strategies by their runs."""
    db = get_db_manager()

    from weather_copy_bot.db.repositories import FillRepository, StrategyRunRepository

    ids = [int(x.strip()) for x in strategy_ids.split(",")]

    with db.session() as session:
        run_repo = StrategyRunRepository(session)
        fill_repo = FillRepository(session)

        table = Table(title="Strategy Comparison")
        table.add_column("Strategy ID", style="cyan")
        table.add_column("Runs", justify="right", style="yellow")
        table.add_column("Total P&L", justify="right")
        table.add_column("Avg Trade", justify="right")
        table.add_column("Best Trade", justify="right")
        table.add_column("Worst Trade", justify="right")

        for sid in ids:
            runs = run_repo.get_by_strategy(sid, limit=100)
            if not runs:
                table.add_row(str(sid), "0", "-", "-", "-", "-")
                continue

            stats = fill_repo.get_stats_by_strategy(sid)
            avg = stats["avg_pnl"] if stats["trade_count"] > 0 else 0

            table.add_row(
                str(sid),
                str(len(runs)),
                f"${stats['total_pnl']:.2f}",
                f"${avg:.2f}",
                f"${stats['best_trade']:.2f}",
                f"${stats['worst_trade']:.2f}",
            )

    console.print(table)


if __name__ == "__main__":
    app()
