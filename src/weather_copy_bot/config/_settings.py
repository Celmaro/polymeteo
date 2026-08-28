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
    min_edge_bps: float = 40.0
    # Two-tier latency gate (audit P0): ``max_upstream_age_ms`` bounds the age of
    # the upstream event we received (data staleness), while ``max_copy_latency_ms``
    # bounds only the local processing lag between detect and decision. A fill
    # whose upstream timestamp is hours old fails the upstream-age gate even if
    # we detected it within 50 ms locally.
    max_upstream_age_ms: int = 600_000
    max_copy_latency_ms: int = 800
    dry_run: bool = True

    poll_interval_ms: int = 250
    market_filter: str = "weather"
    paper_starting_balance: float = 10_000.0

    # Start the CopyEngine polling loop inside the API process lifespan.
    # Defaults to False so web-only deploys and tests never hit Polymarket;
    # production opts in explicitly via ENGINE_ENABLED=true.
    engine_enabled: bool = False

    # Automatic wallet discovery scans public activity on active weather
    # markets to promote new copy targets alongside TARGET_WALLETS. Defaults
    # to False so deploys opt in explicitly via WALLET_DISCOVERY_ENABLED=true.
    wallet_discovery_enabled: bool = False
    discovery_interval_s: float = 30.0
    discovery_max_markets: int = 5
    discovery_trades_per_market: int = 50
    # None promotes every qualified candidate into the polling rotation;
    # set an integer via MAX_DISCOVERED_TARGETS to cap it explicitly.
    max_discovered_targets: int | None = None
    min_candidate_trades: int = 3
    min_candidate_volume_usd: float = 100.0

    # Consensus quorum: when N distinct target wallets take the same token/side
    # within the window, one copy fires at the size-weighted average price.
    # Every wallet counts equally (no category weights); size shapes the entry
    # price only. Defaults to False so web-only deploys and tests never fire
    # consensus; production opts in explicitly via QUORUM_ENABLED=true.
    quorum_enabled: bool = False
    quorum_min_count: int = 2
    quorum_window_seconds: int = 600
    quorum_max_acceptable_price: float = 0.85
    # Consensus aggregates several small per-wallet fills into one combined
    # copy; the per-trade floor (5.0 in CopyBacktester) would otherwise reject
    # a 2-wallet x $5 agreement at 2 x 5 x 0.25 = $2.50. This knob lowers the
    # floor specifically for the consensus path (agreement substitutes for
    # conviction). Leave at 5.0 to keep the floor identical to single-wallet.
    consensus_min_size_usd: float = 2.5

    # Signal consensus window (audit P0b): wallets voting within this many
    # milliseconds on the same token/side count toward the same quorum bucket.
    # Independent from ``quorum_window_seconds`` (the absolute wall-clock window
    # the QuorumEngine keeps for cleanup) so consensus can be tightened without
    # changing how long votes are retained.
    signal_consensus_window_ms: int = 5_000

    # Single-source mode (audit P2): when the resolved target set has exactly
    # one wallet, the quorum layer is structurally unreachable
    # (``quorum_min_count`` defaults to 2). Set False to keep requiring an
    # explicit second source, or True to relax the quorum requirement so a
    # single-wallet deployment can actually fire. Defaults to True so the
    # canonical "one wallet" production deployment is not silently dead.
    single_source_mode: bool = True

    # Weather keyword gate applied in CopyEngine._route_signal before the
    # quorum layer. Defaults to False so behavior stays identical to prior
    # releases; production opts in explicitly via WALLET_FILTER_ENABLED=true.
    wallet_filter_enabled: bool = False

    # Wire OrderQueue.start() into the engine boot path so the queue's
    # background processor (dedup + rate limiting + order state machine +
    # stale-order cleanup) actually runs. When enabled, _execute_live only
    # enqueues and the processor submits and places the order. Defaults to
    # False so behavior stays identical to prior releases; production opts in
    # explicitly via ORDER_QUEUE_ENABLED=true.
    order_queue_enabled: bool = False

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

    sentry_dsn: str = ""
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = 1.0

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
