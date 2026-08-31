"""Repositories for weather forecasts and observations."""

from __future__ import annotations

from sqlalchemy import select

from weather_copy_bot.db.manager import DatabaseManager
from weather_copy_bot.db.weather_models import WeatherForecast, WeatherObservation


class WeatherForecastRepository:
    """Repository for weather forecast operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def upsert(self, forecast: WeatherForecast) -> WeatherForecast:
        """Insert or update a forecast keyed by forecast_id."""
        with self.db.session() as session:
            existing = session.execute(
                select(WeatherForecast).where(
                    WeatherForecast.forecast_id == forecast.forecast_id
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(forecast)
            else:
                for field in (
                    "city",
                    "source",
                    "target_date",
                    "metric",
                    "value",
                    "unit",
                    "issued_at",
                ):
                    setattr(existing, field, getattr(forecast, field))
                forecast = existing
            session.flush()
            return forecast

    def get_by_id(self, forecast_id: str) -> WeatherForecast | None:
        """Get a forecast by its external forecast_id."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherForecast).where(
                    WeatherForecast.forecast_id == forecast_id
                )
            )
            return result.scalar_one_or_none()

    def list_for_city(self, city: str) -> list[WeatherForecast]:
        """List all forecasts for a city."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherForecast)
                .where(WeatherForecast.city == city)
                .order_by(WeatherForecast.forecast_id)
            )
            return list(result.scalars().all())

    def list_between(self, start_date: str, end_date: str) -> list[WeatherForecast]:
        """List forecasts whose target_date falls within [start_date, end_date]."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherForecast)
                .where(
                    WeatherForecast.target_date >= start_date,
                    WeatherForecast.target_date <= end_date,
                )
                .order_by(WeatherForecast.target_date, WeatherForecast.forecast_id)
            )
            return list(result.scalars().all())

    def list_all(self) -> list[WeatherForecast]:
        """List all forecasts in a deterministic order."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherForecast).order_by(WeatherForecast.forecast_id)
            )
            return list(result.scalars().all())


class WeatherObservationRepository:
    """Repository for weather observation operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def upsert(self, observation: WeatherObservation) -> WeatherObservation:
        """Insert or update an observation keyed by observation_id."""
        with self.db.session() as session:
            existing = session.execute(
                select(WeatherObservation).where(
                    WeatherObservation.observation_id == observation.observation_id
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(observation)
            else:
                for field in ("city", "station", "observed_at", "metric", "value", "unit"):
                    setattr(existing, field, getattr(observation, field))
                observation = existing
            session.flush()
            return observation

    def get_by_id(self, observation_id: str) -> WeatherObservation | None:
        """Get an observation by its external observation_id."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherObservation).where(
                    WeatherObservation.observation_id == observation_id
                )
            )
            return result.scalar_one_or_none()

    def list_for_city(self, city: str) -> list[WeatherObservation]:
        """List all observations for a city."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherObservation)
                .where(WeatherObservation.city == city)
                .order_by(WeatherObservation.observed_at)
            )
            return list(result.scalars().all())

    def list_all(self) -> list[WeatherObservation]:
        """List all observations in a deterministic order."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherObservation).order_by(WeatherObservation.observation_id)
            )
            return list(result.scalars().all())

    def latest_for_city(self, city: str) -> WeatherObservation | None:
        """Return the most recent observation for a city."""
        with self.db.session() as session:
            result = session.execute(
                select(WeatherObservation)
                .where(WeatherObservation.city == city)
                .order_by(WeatherObservation.observed_at.desc())
                .limit(1)
            )
            return result.scalars().first()
