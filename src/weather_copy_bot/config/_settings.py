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

    # Optional The Graph Network API key used only for the subgraph data
    # fallback in MultiSourceDataFusion. Free tier is available at
    # https://thegraph.com/studio/apikeys. When empty, the subgraph fallback
    # logs a warning and returns no data (the GraphQL fallback still runs),
    # so deployments never need to configure this unless they want subgraph
    # coverage.
    thegraph_api_key: str = ""

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
    # The discovered-wallet rotation is intentionally uncapped: ``max_registry_size``
    # bounds how many wallets the registry tracks and ``candidate_ttl_hours`` evicts
    # stale ones, so promotion cannot grow without bound. A per-call cap can still be
    # applied via ``WalletDiscovery.promoted_wallets(max_targets=...)``.
    min_candidate_trades: int = 3
    min_candidate_volume_usd: float = 100.0
    # Spam / HFT guard: reject any candidate whose busiest UTC day exceeded this
    # many trades. 0 disables the rule (default).
    max_candidate_trades_per_day: int = 0
    # Specialization guard: reject any candidate that touched more than this many
    # distinct NON-weather markets within its observation window — a proxy for the
    # generalist "dispersion" profile. 0 disables the rule (default).
    max_non_weather_markets: int = 0

    # WalletProfiler (first-party P&L enrichment). When enabled, discovered
    # candidates are enriched from Polymarket's own endpoints (closed-positions,
    # user-pnl, WEATHER leaderboard, lb-api profit, /value) instead of a third
    # party. The profiler never blocks promotion while its gates are disabled.
    profiler_enabled: bool = False
    # Reuse a profile for this many seconds before re-fetching (rate limiting).
    profiler_cache_ttl_s: float = 3600.0
    # How many wallets to profile per discovery cycle (burst budget).
    profiler_max_wallets_per_cycle: int = 20
    # Backoff applied to a wallet whose profile fetch failed, before retrying.
    profiler_backoff_s: float = 600.0
    # Optional promotion gates built from profiler metrics. 0 disables each.
    # ROI is realized_pnl / invested on closed positions, expressed as a percent.
    profiler_min_roi_pct: float = 0.0
    profiler_min_win_rate: float = 0.0
    profiler_max_weekly_variance: float = 0.0

    # Demo mode is the ONLY situation where the client returns fabricated
    # stub markets / demo trade events. Defaults to False so production never
    # silently trades on made-up data.
    demo_mode: bool = False

    # Cities (keys into analysis.city_config.CITY_CONFIG) that the slug-based
    # temperature-market event discovery should scan.
    weather_cities: list[str] = Field(
        default_factory=lambda: ["nyc", "chicago", "miami", "los_angeles", "denver"]
    )

    # Bound on the initial WebSocket connect attempt at engine boot; on
    # timeout/failure the engine logs and continues poll-only.
    ws_connect_timeout_s: float = 5.0

    # WalletDiscovery registry hygiene: evict least-recently-seen wallets past
    # this size and drop candidates/promotions whose last_seen is older than
    # the TTL.
    max_registry_size: int = 5000
    candidate_ttl_hours: float = 72.0

    # Minimum fraction of a wallet's observed trades that must be on weather
    # markets before it can be promoted as a copy target. The "specialist" bar
    # (>=80%) is intentional: discovery targets scientists/meteorologists, not
    # generalists who mix crypto, politics and sports into one wallet.
    min_weather_share: float = 0.8

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

    scheduler_enabled: bool = False
    weather_refresh_interval_s: int = 900
    market_refresh_interval_s: int = 300
    snapshot_export_interval_s: int = 3600
    snapshot_output_dir: str = "data/parquet"

    uptime_kuma_push_url: str = ""
    apprise_urls: list[str] = Field(default_factory=list)

    @field_validator("apprise_urls", mode="before")
    @classmethod
    def split_apprise_urls(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [u.strip() for u in value.split(",") if u.strip()]
        if isinstance(value, list):
            return [str(u).strip() for u in value if str(u).strip()]
        return []

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

    @field_validator("weather_cities", mode="before")
    @classmethod
    def split_weather_cities(cls, value: object) -> list[str]:
        if value is None or value == "":
            return ["nyc", "chicago", "miami", "los_angeles", "denver"]
        if isinstance(value, str):
            return [c.strip().lower() for c in value.split(",") if c.strip()]
        if isinstance(value, list):
            return [str(c).strip().lower() for c in value if str(c).strip()]
        return ["nyc", "chicago", "miami", "los_angeles", "denver"]

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
