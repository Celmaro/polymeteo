"""Tests for weather persistence (SQLite models and repositories)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.db.weather_models import WeatherForecast, WeatherObservation
from weather_copy_bot.db.weather_repositories import (
    WeatherForecastRepository,
    WeatherObservationRepository,
)


@pytest.fixture
def db(tmp_path):
    """Create a DatabaseManager backed by a tmp SQLite file."""
    manager = DatabaseManager(database_url=f"sqlite:///{tmp_path}/weather_test.db")
    manager.create_tables()
    yield manager
    manager.drop_tables()


@pytest.fixture
def forecast_repo(db):
    """WeatherForecastRepository bound to the tmp database."""
    return WeatherForecastRepository(db)


@pytest.fixture
def observation_repo(db):
    """WeatherObservationRepository bound to the tmp database."""
    return WeatherObservationRepository(db)


@pytest.fixture
def sample_forecast():
    """A sample weather forecast for Tokyo."""
    now = datetime.now(timezone.utc)
    return WeatherForecast(
        forecast_id="fc-tokyo-1",
        city="Tokyo",
        source="open-meteo",
        target_date=(now + timedelta(days=1)).date().isoformat(),
        metric="temperature_max",
        value=31.5,
        unit="celsius",
        issued_at=now,
    )


@pytest.fixture
def sample_observation():
    """A sample weather observation for Tokyo."""
    now = datetime.now(timezone.utc)
    return WeatherObservation(
        observation_id="obs-tokyo-1",
        city="Tokyo",
        station="tokyo-haneda",
        observed_at=now,
        metric="temperature_max",
        value=30.2,
        unit="celsius",
    )


class TestWeatherForecastModel:
    """Test WeatherForecast model constraints."""

    def test_forecast_persists_to_sqlite(self, db, sample_forecast):
        """Forecast rows should round-trip through SQLite."""
        repo = WeatherForecastRepository(db)
        repo.upsert(sample_forecast)
        stored = repo.get_by_id("fc-tokyo-1")
        assert stored is not None
        assert stored.city == "Tokyo"
        assert stored.value == 31.5

    def test_forecast_has_source_and_metric(self, db, sample_forecast):
        """Forecast should keep ingestion source and metric name."""
        repo = WeatherForecastRepository(db)
        repo.upsert(sample_forecast)
        stored = repo.get_by_id("fc-tokyo-1")
        assert stored.source == "open-meteo"
        assert stored.metric == "temperature_max"


class TestWeatherForecastRepository:
    """Test WeatherForecastRepository behavior."""

    def test_upsert_is_idempotent(self, forecast_repo, sample_forecast):
        """Upserting the same forecast_id twice should not create duplicates."""
        forecast_repo.upsert(sample_forecast)
        forecast_repo.upsert(sample_forecast)
        assert len(forecast_repo.list_for_city("Tokyo")) == 1

    def test_get_by_id_returns_none_when_missing(self, forecast_repo):
        """Unknown ids should return None rather than raise."""
        assert forecast_repo.get_by_id("missing") is None

    def test_list_for_city_filters_by_city(self, db, forecast_repo, sample_forecast):
        """list_for_city should only return matching city forecasts."""
        other = WeatherForecast(
            forecast_id="fc-nyc-1",
            city="New York",
            source="open-meteo",
            target_date=sample_forecast.target_date,
            metric="temperature_max",
            value=25.0,
            unit="celsius",
            issued_at=sample_forecast.issued_at,
        )
        forecast_repo.upsert(sample_forecast)
        forecast_repo.upsert(other)
        rows = forecast_repo.list_for_city("Tokyo")
        assert [r.forecast_id for r in rows] == ["fc-tokyo-1"]

    def test_list_between_returns_in_range(self, forecast_repo, sample_forecast):
        """list_between should return forecasts whose target_date is in range."""
        forecast_repo.upsert(sample_forecast)
        rows = forecast_repo.list_between(
            sample_forecast.target_date,
            sample_forecast.target_date,
        )
        assert len(rows) == 1

    def test_list_between_excludes_out_of_range(self, forecast_repo, sample_forecast):
        """list_between should exclude forecasts outside the window."""
        forecast_repo.upsert(sample_forecast)
        rows = forecast_repo.list_between("2000-01-01", "2000-01-02")
        assert rows == []


class TestWeatherObservationRepository:
    """Test WeatherObservationRepository behavior."""

    def test_upsert_and_get_observation(self, observation_repo, sample_observation):
        """Observation should round-trip through SQLite."""
        observation_repo.upsert(sample_observation)
        stored = observation_repo.get_by_id("obs-tokyo-1")
        assert stored is not None
        assert stored.station == "tokyo-haneda"
        assert stored.value == 30.2

    def test_latest_for_city_returns_most_recent(self, db, observation_repo, sample_observation):
        """latest_for_city should return the newest observation."""
        newer = WeatherObservation(
            observation_id="obs-tokyo-2",
            city="Tokyo",
            station="tokyo-haneda",
            observed_at=sample_observation.observed_at + timedelta(hours=1),
            metric="temperature_max",
            value=31.0,
            unit="celsius",
        )
        observation_repo.upsert(sample_observation)
        observation_repo.upsert(newer)
        latest = observation_repo.latest_for_city("Tokyo")
        assert latest.observation_id == "obs-tokyo-2"

    def test_latest_for_city_returns_none_when_empty(self, observation_repo):
        """latest_for_city should return None when no observations exist."""
        assert observation_repo.latest_for_city("Tokyo") is None
