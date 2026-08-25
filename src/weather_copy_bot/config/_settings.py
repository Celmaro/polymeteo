"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    polymarket_private_key: str = ""
    polymarket_proxy_address: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""

    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    data_api_host: str = "https://data-api.polymarket.com"

    target_wallets: list[str] = Field(default_factory=list)
    copy_ratio: float = 0.25
    max_position_usd: float = 250.0
    max_daily_loss_usd: float = 500.0
    min_edge_bps: float = 50.0
    max_copy_latency_ms: int = 800
    dry_run: bool = True

    poll_interval_ms: int = 250
    market_filter: str = "weather"
    paper_starting_balance: float = 10_000.0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    weather_keywords: list[str] = Field(
        default_factory=lambda: ["temperature", "weather", "rain", "snow", "°f", "°c"]
    )
    strict_weather_keywords: list[str] = Field(
        default_factory=lambda: ["temperature", "rain", "snow"]
    )

    database_url: str = Field(default="sqlite:///./polymeteo.db")

    @field_validator("target_wallets", mode="before")
    @classmethod
    def split_wallets(cls, value: object) -> list[str]:
        import json

        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(w).strip() for w in parsed if str(w).strip()]
                except (json.JSONDecodeError, ValueError):
                    pass
            return [w.strip() for w in value.split(",") if w.strip()]
        if isinstance(value, list):
            return [str(w).strip() for w in value if str(w).strip()]
        return []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> list[str]:
        if value is None or value == "":
            return ["http://localhost:5173"]
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        if isinstance(value, list):
            return [str(o).strip() for o in value if str(o).strip()]
        return ["http://localhost:5173"]

    @property
    def live_trading_enabled(self) -> bool:
        return bool(self.polymarket_private_key) and not self.dry_run


@lru_cache
def get_settings() -> Settings:
    return Settings()
