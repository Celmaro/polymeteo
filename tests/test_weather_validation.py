"""Tests for DuckDB/Pandera trustworthy validation and replay of weather data."""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from weather_copy_bot.weather_validation import (
    ForecastFrameSchema,
    ObservationFrameSchema,
    ValidationError,
    WeatherDataValidator,
)


@pytest.fixture
def forecasts_parquet(tmp_path):
    """Write a valid forecasts parquet fixture."""
    table = pa.table(
        {
            "forecast_id": ["fc-1", "fc-2"],
            "city": ["Tokyo", "Tokyo"],
            "source": ["open-meteo", "open-meteo"],
            "target_date": ["2024-06-01", "2024-06-02"],
            "metric": ["temperature_max", "temperature_max"],
            "value": [30.5, 31.0],
            "unit": ["celsius", "celsius"],
            "issued_at": [1700000000, 1700003600],
        }
    )
    path = tmp_path / "forecasts.parquet"
    pq.write_table(table, path)
    return str(path)


@pytest.fixture
def validator():
    """WeatherDataValidator instance."""
    return WeatherDataValidator()


class TestFrameSchemas:
    """Test Pandera schema definitions exist and are usable."""

    def test_forecast_schema_exists(self):
        """ForecastFrameSchema should be defined."""
        assert ForecastFrameSchema is not None

    def test_observation_schema_exists(self):
        """ObservationFrameSchema should be defined."""
        assert ObservationFrameSchema is not None


class TestWeatherDataValidator:
    """Test validator over parquet snapshots via DuckDB + Pandera."""

    def test_validate_forecasts_accepts_valid_file(self, validator, forecasts_parquet):
        """Well-formed forecasts parquet should validate cleanly."""
        result = validator.validate_forecasts(forecasts_parquet)
        assert result.valid is True
        assert result.row_count == 2

    def test_validate_forecasts_rejects_missing_columns(self, validator, tmp_path):
        """Missing required columns should produce a ValidationError."""
        bad = tmp_path / "bad.parquet"
        pq.write_table(pa.table({"city": ["Tokyo"]}), bad)
        with pytest.raises(ValidationError):
            validator.validate_forecasts(str(bad))

    def test_validate_forecasts_rejects_null_ids(self, validator, tmp_path):
        """Null forecast_id values should fail validation."""
        bad = tmp_path / "nulls.parquet"
        pq.write_table(
            pa.table(
                {
                    "forecast_id": pa.array(["fc-1", None], type=pa.string()),
                    "city": ["Tokyo", "Tokyo"],
                    "source": ["open-meteo"] * 2,
                    "target_date": ["2024-06-01"] * 2,
                    "metric": ["temperature_max"] * 2,
                    "value": [30.0, 31.0],
                    "unit": ["celsius"] * 2,
                    "issued_at": [1700000000, 1700003600],
                }
            ),
            bad,
        )
        with pytest.raises(ValidationError):
            validator.validate_forecasts(str(bad))

    def test_validate_forecasts_rejects_duplicate_ids(self, validator, tmp_path):
        """Duplicate forecast_id values should fail validation."""
        bad = tmp_path / "dupes.parquet"
        pq.write_table(
            pa.table(
                {
                    "forecast_id": ["fc-1", "fc-1"],
                    "city": ["Tokyo"] * 2,
                    "source": ["open-meteo"] * 2,
                    "target_date": ["2024-06-01"] * 2,
                    "metric": ["temperature_max"] * 2,
                    "value": [30.0, 30.0],
                    "unit": ["celsius"] * 2,
                    "issued_at": [1700000000, 1700003600],
                }
            ),
            bad,
        )
        with pytest.raises(ValidationError):
            validator.validate_forecasts(str(bad))

    def test_validate_is_deterministic(self, validator, forecasts_parquet):
        """Repeated validation of the same file should return identical results."""
        first = validator.validate_forecasts(forecasts_parquet)
        second = validator.validate_forecasts(forecasts_parquet)
        assert first == second


class TestForecastReplay:
    """Test replaying forecasts against recorded observations."""

    @pytest.fixture
    def observations_parquet(self, tmp_path):
        """Write a valid observations parquet fixture."""
        table = pa.table(
            {
                "observation_id": ["obs-1", "obs-2"],
                "city": ["Tokyo", "Tokyo"],
                "station": ["tokyo-haneda", "tokyo-haneda"],
                "observed_at": [1700003600, 1700087200],
                "metric": ["temperature_max", "temperature_max"],
                "value": [30.0, 32.0],
                "unit": ["celsius", "celsius"],
            }
        )
        path = tmp_path / "observations.parquet"
        pq.write_table(table, path)
        return str(path)

    def test_replay_returns_report(self, validator, forecasts_parquet, observations_parquet):
        """replay_forecasts should return a replay report."""
        report = validator.replay_forecasts(forecasts_parquet, observations_parquet)
        assert hasattr(report, "matched_count")
        assert hasattr(report, "mean_absolute_error")
        assert report.matched_count == 2

    def test_replay_mean_absolute_error(self, validator, forecasts_parquet, observations_parquet):
        """MAE should be computed against matched observations."""
        report = validator.replay_forecasts(forecasts_parquet, observations_parquet)
        # |30.5-30.0| = 0.5, |31.0-32.0| = 1.0 -> 0.75
        assert report.mean_absolute_error == pytest.approx(0.75)

    def test_replay_with_no_matches(self, validator, tmp_path, observations_parquet):
        """Replay with unmatched forecasts should report zero matches."""
        table = pa.table(
            {
                "forecast_id": ["fc-x"],
                "city": ["Osaka"],
                "source": ["open-meteo"],
                "target_date": ["2024-06-01"],
                "metric": ["temperature_max"],
                "value": [30.0],
                "unit": ["celsius"],
                "issued_at": [1700000000],
            }
        )
        path = tmp_path / "osaka_forecasts.parquet"
        pq.write_table(table, path)
        report = validator.replay_forecasts(str(path), observations_parquet)
        assert report.matched_count == 0
