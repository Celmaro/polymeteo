"""Export weather forecasts and observations to deterministic parquet snapshots."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.db.weather_repositories import (
    WeatherForecastRepository,
    WeatherObservationRepository,
)

FORECAST_COLUMNS = [
    "forecast_id",
    "city",
    "source",
    "target_date",
    "metric",
    "value",
    "unit",
    "issued_at",
]

OBSERVATION_COLUMNS = [
    "observation_id",
    "city",
    "station",
    "observed_at",
    "metric",
    "value",
    "unit",
]


class WeatherSnapshotExporter:
    """Export weather database tables to parquet snapshots."""

    def __init__(self, db: DatabaseManager, output_dir: str) -> None:
        self.db = db
        self.output_dir = output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def get_parquet_path(self, table_name: str) -> str:
        """Get the path for a parquet snapshot file."""
        return os.path.join(self.output_dir, f"{table_name}.parquet")

    def export_forecasts(self) -> str:
        """Export all weather forecasts to parquet."""
        rows = [
            {column: getattr(forecast, column) for column in FORECAST_COLUMNS}
            for forecast in WeatherForecastRepository(self.db).list_all()
        ]
        df = pd.DataFrame(rows, columns=FORECAST_COLUMNS)
        path = self.get_parquet_path("weather_forecasts")
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    def export_observations(self) -> str:
        """Export all weather observations to parquet."""
        rows = [
            {column: getattr(observation, column) for column in OBSERVATION_COLUMNS}
            for observation in WeatherObservationRepository(self.db).list_all()
        ]
        df = pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)
        path = self.get_parquet_path("weather_observations")
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    def export_all(self) -> dict[str, str]:
        """Export forecasts and observations, returning their file paths."""
        return {
            "forecasts": self.export_forecasts(),
            "observations": self.export_observations(),
        }
