"""Tests for weather Parquet snapshot export."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
import pytest

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.db.weather_models import WeatherForecast, WeatherObservation
from weather_copy_bot.db.weather_repositories import (
    WeatherForecastRepository,
    WeatherObservationRepository,
)
from weather_copy_bot.weather_snapshots import WeatherSnapshotExporter


@pytest.fixture
def db(tmp_path):
    """Tmp SQLite database with tables created."""
    manager = DatabaseManager(database_url=f"sqlite:///{tmp_path}/snapshots_test.db")
    manager.create_tables()
    yield manager
    manager.drop_tables()


@pytest.fixture
def populated_db(db):
    """Database pre-filled with deterministic weather rows."""
    now = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    forecast_repo = WeatherForecastRepository(db)
    observation_repo = WeatherObservationRepository(db)
    forecast_repo.upsert(
        WeatherForecast(
            forecast_id="fc-1",
            city="Tokyo",
            source="open-meteo",
            target_date="2024-06-02",
            metric="temperature_max",
            value=31.5,
            unit="celsius",
            issued_at=now,
        )
    )
    observation_repo.upsert(
        WeatherObservation(
            observation_id="obs-1",
            city="Tokyo",
            station="tokyo-haneda",
            observed_at=now - timedelta(hours=1),
            metric="temperature_max",
            value=30.2,
            unit="celsius",
        )
    )
    return db


class TestWeatherSnapshotExporter:
    """Test WeatherSnapshotExporter parquet output."""

    def test_exporter_initializes(self, tmp_path, populated_db):
        """Exporter should initialize without errors."""
        exporter = WeatherSnapshotExporter(db=populated_db, output_dir=str(tmp_path))
        assert exporter is not None

    def test_export_forecasts_writes_parquet(self, tmp_path, populated_db):
        """export_forecasts should write a parquet file with forecast rows."""
        exporter = WeatherSnapshotExporter(db=populated_db, output_dir=str(tmp_path))
        path = exporter.export_forecasts()
        assert path.endswith(".parquet")
        table = pq.read_table(path)
        assert table.num_rows == 1
        assert "forecast_id" in table.column_names
        assert table.to_pydict()["city"] == ["Tokyo"]

    def test_export_observations_writes_parquet(self, tmp_path, populated_db):
        """export_observations should write a parquet file with observation rows."""
        exporter = WeatherSnapshotExporter(db=populated_db, output_dir=str(tmp_path))
        path = exporter.export_observations()
        table = pq.read_table(path)
        assert table.num_rows == 1
        assert "observation_id" in table.column_names

    def test_export_all_returns_both_paths(self, tmp_path, populated_db):
        """export_all should return paths for forecasts and observations."""
        exporter = WeatherSnapshotExporter(db=populated_db, output_dir=str(tmp_path))
        result = exporter.export_all()
        assert "forecasts" in result
        assert "observations" in result
        assert result["forecasts"].endswith(".parquet")
        assert result["observations"].endswith(".parquet")

    def test_export_empty_db_writes_empty_parquet(self, tmp_path, db):
        """Exporting an empty database should still produce valid parquet files."""
        exporter = WeatherSnapshotExporter(db=db, output_dir=str(tmp_path))
        path = exporter.export_forecasts()
        table = pq.read_table(path)
        assert table.num_rows == 0
        assert "forecast_id" in table.column_names

    def test_export_is_deterministic_for_same_data(self, tmp_path, populated_db):
        """Exporting the same data twice should yield identical row content."""
        exporter = WeatherSnapshotExporter(db=populated_db, output_dir=str(tmp_path))
        first = pq.read_table(exporter.export_forecasts()).to_pylist()
        second = pq.read_table(exporter.export_forecasts()).to_pylist()
        assert first == second
