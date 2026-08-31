"""Periodic weather jobs: refresh, metadata sync, and snapshot export."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.db.weather_models import WeatherForecast
from weather_copy_bot.db.weather_repositories import WeatherForecastRepository
from weather_copy_bot.weather_snapshots import WeatherSnapshotExporter


@dataclass
class JobResult:
    """Outcome of a single scheduled job run."""

    success: bool
    records_processed: int = 0
    error: str | None = None
    details: dict[str, Any] | None = None


async def refresh_weather(db, client, cities) -> JobResult:
    """Fetch forecasts for each city and persist them idempotently."""
    try:
        repo = WeatherForecastRepository(db)
        records = 0
        for city in cities:
            forecasts = await client.fetch_forecasts(city)
            for row in forecasts:
                repo.upsert(
                    row if isinstance(row, WeatherForecast) else WeatherForecast(**row)
                )
                records += 1
        return JobResult(success=True, records_processed=records)
    except Exception as exc:
        return JobResult(success=False, error=str(exc))


async def refresh_market_metadata(db, source=None) -> JobResult:
    """Fetch market metadata from a source."""
    try:
        if source is None:
            return JobResult(success=True, records_processed=0)
        markets = await source.fetch_markets()
        return JobResult(
            success=True,
            records_processed=len(markets),
            details={"markets": markets},
        )
    except Exception as exc:
        return JobResult(success=False, error=str(exc))


async def export_snapshots(db, output_dir) -> JobResult:
    """Export weather tables to parquet snapshots."""
    try:
        paths = WeatherSnapshotExporter(db=db, output_dir=output_dir).export_all()
        return JobResult(success=True, details=paths)
    except Exception as exc:
        return JobResult(success=False, error=str(exc))


class WeatherJobCoordinator:
    """Runs registered weather jobs and reports per-job results."""

    def __init__(self, db: DatabaseManager, output_dir: str):
        self.db = db
        self.output_dir = output_dir
        self._weather_client = None
        self._cities: list[str] = []
        self._metadata_source = None

    def register_weather_client(self, client, cities: list[str]) -> None:
        """Register the upstream weather client and cities to refresh."""
        self._weather_client = client
        self._cities = list(cities)

    def register_metadata_source(self, source) -> None:
        """Register the market metadata source."""
        self._metadata_source = source

    async def run_once(self) -> dict[str, JobResult]:
        """Run all registered jobs once; failures never raise."""
        results: dict[str, JobResult] = {}
        if self._weather_client is not None:
            results["refresh_weather"] = await refresh_weather(
                db=self.db, client=self._weather_client, cities=self._cities
            )
        else:
            results["refresh_weather"] = JobResult(success=True, records_processed=0)
        results["refresh_market_metadata"] = await refresh_market_metadata(
            db=self.db, source=self._metadata_source
        )
        results["export_snapshots"] = await export_snapshots(
            db=self.db, output_dir=self.output_dir
        )
        return results


@dataclass
class SchedulerOptions:
    """Interval configuration for the APScheduler wrapper."""

    refresh_weather_minutes: int = 30
    refresh_market_metadata_minutes: int = 60
    export_snapshots_minutes: int = 60
    job_defaults: dict[str, Any] = field(default_factory=dict)


def build_scheduler(coordinator: WeatherJobCoordinator, options: SchedulerOptions | None = None):
    """Wrap coordinator jobs in an APScheduler AsyncIOScheduler."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    options = options or SchedulerOptions()
    job_defaults = options.job_defaults or {"coalesce": True, "max_instances": 1}
    scheduler = AsyncIOScheduler(job_defaults=job_defaults)
    scheduler.add_job(
        refresh_weather,
        "interval",
        minutes=options.refresh_weather_minutes,
        id="refresh_weather",
        kwargs={
            "db": coordinator.db,
            "client": coordinator._weather_client,
            "cities": coordinator._cities,
        },
    )
    scheduler.add_job(
        refresh_market_metadata,
        "interval",
        minutes=options.refresh_market_metadata_minutes,
        id="refresh_market_metadata",
        kwargs={"db": coordinator.db, "source": coordinator._metadata_source},
    )
    scheduler.add_job(
        export_snapshots,
        "interval",
        minutes=options.export_snapshots_minutes,
        id="export_snapshots",
        kwargs={"db": coordinator.db, "output_dir": coordinator.output_dir},
    )
    return scheduler
