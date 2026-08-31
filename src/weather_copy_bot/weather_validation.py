"""Validation and replay for parquet weather snapshots via DuckDB and Pandera."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import DataFrameModel
from pandera.typing.pandas import Series


class ValidationError(Exception):
    """Raised when a parquet snapshot fails validation."""


class ForecastFrameSchema(DataFrameModel):
    """Schema for forecast snapshot dataframes."""

    forecast_id: Series[str]
    city: Series[str]
    source: Series[str]
    target_date: Series[str]
    metric: Series[str]
    value: Series[float]
    unit: Series[str]
    issued_at: Series[int]


class ObservationFrameSchema(DataFrameModel):
    """Schema for observation snapshot dataframes."""

    observation_id: Series[str]
    city: Series[str]
    station: Series[str]
    observed_at: Series[int]
    metric: Series[str]
    value: Series[float]
    unit: Series[str]


@dataclass
class ValidationResult:
    """Outcome of validating a parquet snapshot."""

    valid: bool
    row_count: int


@dataclass
class ReplayReport:
    """Outcome of replaying forecasts against observations."""

    matched_count: int
    mean_absolute_error: float | None


class WeatherDataValidator:
    """Validate parquet snapshots and replay forecasts against observations."""

    def _read_parquet(self, path: str) -> pd.DataFrame:
        return duckdb.read_parquet(path).to_df()

    def _validate_frame(
        self, path: str, id_column: str, schema: type[DataFrameModel]
    ) -> ValidationResult:
        frame = self._read_parquet(path)
        required = set(schema.to_schema().columns)
        missing = required - set(frame.columns)
        if missing:
            raise ValidationError(f"Missing required columns: {sorted(missing)}")
        if frame[id_column].isna().any():
            raise ValidationError(f"Null values in {id_column}")
        if frame[id_column].duplicated().any():
            raise ValidationError(f"Duplicate values in {id_column}")
        try:
            schema.validate(frame)
        except pa.errors.SchemaError as exc:
            raise ValidationError(str(exc)) from exc
        return ValidationResult(valid=True, row_count=len(frame))

    def validate_forecasts(self, path: str) -> ValidationResult:
        """Validate a forecasts parquet snapshot."""
        return self._validate_frame(path, "forecast_id", ForecastFrameSchema)

    def validate_observations(self, path: str) -> ValidationResult:
        """Validate an observations parquet snapshot."""
        return self._validate_frame(path, "observation_id", ObservationFrameSchema)

    def replay_forecasts(
        self, forecasts_path: str, observations_path: str
    ) -> ReplayReport:
        """Pair forecasts to observations by city+metric and compute MAE."""
        forecasts = self._read_parquet(forecasts_path).sort_values("forecast_id")
        observations = self._read_parquet(observations_path).sort_values("observed_at")

        available: dict[tuple[str, str], list[dict]] = {}
        for row in observations.to_dict("records"):
            available.setdefault((row["city"], row["metric"]), []).append(row)

        errors: list[float] = []
        for forecast in forecasts.to_dict("records"):
            pool = available.get((forecast["city"], forecast["metric"]), [])
            if not pool:
                continue
            observation = pool.pop(0)
            errors.append(abs(float(forecast["value"]) - float(observation["value"])))

        matched = len(errors)
        mae = sum(errors) / matched if matched else None
        return ReplayReport(matched_count=matched, mean_absolute_error=mae)
