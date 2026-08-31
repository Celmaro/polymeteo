"""Tests for scheduler/coordinator weather jobs."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.scheduler.weather_jobs import (
    JobResult,
    WeatherJobCoordinator,
    export_snapshots,
    refresh_market_metadata,
    refresh_weather,
)


@pytest.fixture
def db(tmp_path):
    """Tmp SQLite database with tables created."""
    manager = DatabaseManager(database_url=f"sqlite:///{tmp_path}/jobs_test.db")
    manager.create_tables()
    yield manager
    manager.drop_tables()


@pytest.fixture
def fake_weather_client():
    """Deterministic fake weather API client."""

    class FakeWeatherClient:
        async def fetch_forecasts(self, city):
            now = datetime(2024, 6, 1, tzinfo=timezone.utc)
            return [
                {
                    "forecast_id": f"fc-{city.lower()}-1",
                    "city": city,
                    "source": "open-meteo",
                    "target_date": "2024-06-02",
                    "metric": "temperature_max",
                    "value": 30.0,
                    "unit": "celsius",
                    "issued_at": now,
                }
            ]

    return FakeWeatherClient()


class TestRefreshWeatherJob:
    """Test refresh_weather job."""

    async def test_refresh_weather_persists_forecasts(self, db, fake_weather_client):
        """refresh_weather should store fetched forecasts in SQLite."""
        result = await refresh_weather(
            db=db, client=fake_weather_client, cities=["Tokyo"]
        )
        assert isinstance(result, JobResult)
        assert result.success is True
        assert result.records_processed == 1

    async def test_refresh_weather_is_idempotent(self, db, fake_weather_client):
        """Running refresh twice should upsert rather than duplicate."""
        await refresh_weather(db=db, client=fake_weather_client, cities=["Tokyo"])
        result = await refresh_weather(db=db, client=fake_weather_client, cities=["Tokyo"])
        assert result.success is True
        from weather_copy_bot.db.weather_repositories import WeatherForecastRepository

        repo = WeatherForecastRepository(db)
        assert len(repo.list_for_city("Tokyo")) == 1

    async def test_refresh_weather_reports_failure(self, db):
        """A failing client should produce a failed JobResult, not raise."""

        class BrokenClient:
            async def fetch_forecasts(self, city):
                raise RuntimeError("upstream down")

        result = await refresh_weather(db=db, client=BrokenClient(), cities=["Tokyo"])
        assert result.success is False
        assert result.error is not None


class TestRefreshMarketMetadataJob:
    """Test refresh_market_metadata job."""

    async def test_refresh_market_metadata_updates_markets(self, db):
        """refresh_market_metadata should enrich tracked markets."""

        class FakeMetadataSource:
            async def fetch_markets(self):
                return [{"id": "m-1", "question": "Rain in Paris?"}]

        result = await refresh_market_metadata(db=db, source=FakeMetadataSource())
        assert isinstance(result, JobResult)
        assert result.success is True
        assert result.records_processed >= 0

    async def test_refresh_market_metadata_reports_failure(self, db):
        """Source failures should surface as failed JobResult."""

        class BrokenSource:
            async def fetch_markets(self):
                raise RuntimeError("api error")

        result = await refresh_market_metadata(db=db, source=BrokenSource())
        assert result.success is False


class TestExportSnapshotsJob:
    """Test export_snapshots job."""

    async def test_export_snapshots_writes_files(self, db, tmp_path):
        """export_snapshots should export parquet snapshots and report paths."""
        result = await export_snapshots(db=db, output_dir=str(tmp_path))
        assert result.success is True
        assert result.details is not None
        assert "forecasts" in result.details
        assert "observations" in result.details


class TestWeatherJobCoordinator:
    """Test the coordinator that schedules the three jobs."""

    async def test_coordinator_runs_once(self, db, tmp_path, fake_weather_client):
        """Coordinator run_once should execute all registered jobs."""
        coordinator = WeatherJobCoordinator(
            db=db, output_dir=str(tmp_path)
        )
        coordinator.register_weather_client(fake_weather_client, cities=["Tokyo"])
        results = await coordinator.run_once()
        assert set(results) == {
            "refresh_weather",
            "refresh_market_metadata",
            "export_snapshots",
        }
        assert all(r.success for r in results.values())

    async def test_coordinator_continues_after_job_failure(self, db, tmp_path):
        """A failing job should not prevent remaining jobs from running."""

        class BrokenClient:
            async def fetch_forecasts(self, city):
                raise RuntimeError("down")

        coordinator = WeatherJobCoordinator(db=db, output_dir=str(tmp_path))
        coordinator.register_weather_client(BrokenClient(), cities=["Tokyo"])
        results = await coordinator.run_once()
        assert results["refresh_weather"].success is False
        assert results["export_snapshots"].success is True
