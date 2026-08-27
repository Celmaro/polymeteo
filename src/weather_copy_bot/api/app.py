"""FastAPI surface for the weather copy-trading dashboard and control plane."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from weather_copy_bot import __version__
from weather_copy_bot.config import get_settings
from weather_copy_bot.demo_data import (
    DashboardPayload,
    build_dashboard_payload,
    export_demo_json,
    load_dashboard_payload,
)
from weather_copy_bot.engine import (
    CopyEngine,
    MergedTargetProvider,
    QuorumEngine,
    WalletDiscovery,
)
from weather_copy_bot.ops.monitoring import MonitoringService
from weather_copy_bot.ops.metrics_server import register_metrics_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# The poll loop fires dozens of upstream requests per second; their
# success lines would drown out every engine event at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_cached_payload() -> DashboardPayload:
    return build_dashboard_payload()


def _invalidate_cache() -> None:
    _get_cached_payload.cache_clear()


HEARTBEAT_STALE_SECONDS = 30.0


def _live_engine_status(engine: CopyEngine) -> dict[str, Any]:
    """Build the engine/status payload from a live CopyEngine instance.

    Field names mirror the demo payload so the dashboard frontend can render
    either source without special-casing.
    """
    stats = dict(engine.stats)
    running = bool(getattr(engine, "_running", False))
    healthy = False
    if running:
        heartbeat = stats.get("last_heartbeat")
        if not heartbeat:
            # Loop started but the first poll has not completed yet.
            healthy = True
        else:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(str(heartbeat))
                healthy = age.total_seconds() < HEARTBEAT_STALE_SECONDS
            except ValueError:
                healthy = False
    started_at = getattr(engine, "_started_at", None)
    uptime_hours = round(max(time.time() - started_at, 0.0) / 3600.0, 2) if started_at else 0.0
    # The live rotation merges static TARGET_WALLETS with discovery
    # promotions; report the split so the dashboard shows both sources.
    provider = getattr(engine, "target_provider", None)
    rotation = provider.current() if isinstance(provider, MergedTargetProvider) else None
    static_count = len(engine.settings.target_wallets)
    discovered_count = max(len(rotation) - static_count, 0) if rotation is not None else 0
    return {
        "mode": engine.mode,
        "targets_active": len(rotation) if rotation is not None else static_count,
        "targets_static": static_count,
        "targets_discovered": discovered_count,
        "poll_interval_ms": engine.settings.poll_interval_ms,
        "max_copy_latency_ms": engine.settings.max_copy_latency_ms,
        "avg_detect_to_submit_ms": round(float(stats.pop("avg_latency_ms", 0.0)), 1),
        "uptime_hours": uptime_hours,
        "health": "healthy" if healthy else "starting",
        "running": running,
        "dry_run": engine.settings.dry_run,
        "live_trading_enabled": engine.settings.live_trading_enabled,
        "quorum_enabled": engine.quorum is not None,
        "source": "live",
        # Operators need to confirm at a glance that the live settings match
        # what they deployed. Without this, a deploy with the wrong env vars
        # looks identical to a healthy deploy until the first signal.
        "config": {
            "copy_ratio": engine.settings.copy_ratio,
            "max_position_usd": engine.settings.max_position_usd,
            "max_daily_loss_usd": engine.settings.max_daily_loss_usd,
            "min_edge_bps": engine.settings.min_edge_bps,
            "min_trade_size_usd": getattr(engine.policy, "min_trade_size_usd", 5.0),
            "wallet_discovery_enabled": engine.settings.wallet_discovery_enabled,
            "discovery_interval_s": engine.settings.discovery_interval_s,
            "discovery_min_trades": engine.settings.min_candidate_trades,
            "discovery_min_volume": engine.settings.min_candidate_volume_usd,
            "discovery_max_markets": engine.settings.discovery_max_markets,
            "quorum_min_count": engine.settings.quorum_min_count,
            "quorum_window_seconds": engine.settings.quorum_window_seconds,
            "quorum_max_acceptable_price": engine.settings.quorum_max_acceptable_price,
            "consensus_min_size_usd": engine.settings.consensus_min_size_usd,
            "wallet_filter_enabled": engine.settings.wallet_filter_enabled,
            "order_queue_enabled": engine.settings.order_queue_enabled,
        },
        "stats": stats,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the copy-trading engine inside the API process when enabled.

    ENGINE_ENABLED=false (the default) keeps web-only deploys inert; tests use
    that default so no test ever talks to Polymarket.
    """
    settings = get_settings()

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
        )
        logger.info("Sentry initialized (env=%s)", settings.sentry_environment)
    else:
        logger.info("Sentry DSN not set — error tracking disabled")

    engine: CopyEngine | None = None
    task: asyncio.Task[None] | None = None
    discovery: WalletDiscovery | None = None
    discovery_task: asyncio.Task[None] | None = None
    monitor: MonitoringService | None = None

    # Discovery starts before the engine so promotions are visible from the
    # very first poll of the merged rotation.
    if settings.wallet_discovery_enabled:
        discovery = WalletDiscovery(settings=settings)
        app.state.discovery = discovery
        discovery_task = asyncio.create_task(discovery.run(), name="wallet-discovery")
        logger.info(
            "WalletDiscovery loop enabled interval_s=%s max_markets=%s",
            settings.discovery_interval_s,
            settings.discovery_max_markets,
        )
    if settings.engine_enabled:
        provider = MergedTargetProvider(
            static_wallets=settings.target_wallets,
            discovery=discovery,
        )
        quorum_engine: QuorumEngine | None = None
        if settings.quorum_enabled:
            quorum_engine = QuorumEngine(
                min_quorum_count=settings.quorum_min_count,
                window_seconds=float(settings.quorum_window_seconds),
                max_acceptable_price=settings.quorum_max_acceptable_price,
            )
            logger.info(
                "Quorum consensus enabled min_count=%s window_s=%s max_price=%s",
                settings.quorum_min_count,
                settings.quorum_window_seconds,
                settings.quorum_max_acceptable_price,
            )
        # Monitoring service: count quorum hits/skips via the engine hooks AND
        # run the dashboard / alert background loops.
        monitor = MonitoringService() if quorum_engine is not None else None
        if monitor is not None:
            async def _get_metrics() -> dict[str, Any]:
                # ``_live_engine_status`` is sync; wrap so the monitoring loop
                # can ``await`` it without blocking the event loop.
                return _live_engine_status(engine)
            monitor.set_dependencies(_get_metrics)
        engine = CopyEngine(
            settings=settings,
            target_provider=provider,
            quorum=quorum_engine,
            monitor=monitor,
        )
        app.state.engine = engine
        task = asyncio.create_task(engine.run(), name="copy-engine")
        if monitor is not None:
            # ``start()`` schedules update_loop / alert_loop background tasks
            # and returns immediately. ``stop()`` cancels them at shutdown below.
            await monitor.start()
            logger.info(
                "MonitoringService started update_interval_s=%s alert_interval_s=%s",
                monitor.update_interval,
                monitor.alert_interval,
            )
        logger.info(
            "CopyEngine loop enabled mode=%s static_targets=%s poll_interval_ms=%s",
            engine.mode,
            len(settings.target_wallets),
            settings.poll_interval_ms,
        )
    try:
        yield
    finally:
        if monitor is not None:
            logger.info("Stopping MonitoringService")
            try:
                await asyncio.wait_for(monitor.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("MonitoringService did not stop within 5s")
            except Exception:
                logger.exception("MonitoringService crashed during shutdown")
        if engine is not None and task is not None:
            logger.info("Stopping CopyEngine loop")
            engine.stop()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("CopyEngine loop did not stop within 5s; cancelled")
            except Exception:
                logger.exception("CopyEngine loop crashed during shutdown")
        if discovery is not None and discovery_task is not None:
            logger.info("Stopping WalletDiscovery loop")
            discovery.stop()
            try:
                await asyncio.wait_for(discovery_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("WalletDiscovery loop did not stop within 5s; cancelled")
            except Exception:
                logger.exception("WalletDiscovery loop crashed during shutdown")


def _register_api_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return load_dashboard_payload()

    @app.get("/api/wallets")
    def wallets() -> dict[str, Any]:
        payload = _get_cached_payload()
        return {"wallets": [w.model_dump(mode="json") for w in payload.wallets]}

    @app.get("/api/backtest/summary")
    def backtest_summary() -> dict[str, Any]:
        return _get_cached_payload().backtest.model_dump(mode="json")

    @app.get("/api/paper/summary")
    def paper_summary() -> dict[str, Any]:
        return _get_cached_payload().paper.model_dump(mode="json")

    @app.get("/api/engine/status")
    def engine_status() -> dict[str, Any]:
        engine = getattr(app.state, "engine", None)
        if isinstance(engine, CopyEngine):
            return _live_engine_status(engine)
        return _get_cached_payload().engine_status

    @app.get("/api/discovery/status")
    def discovery_status() -> dict[str, Any]:
        disc = getattr(app.state, "discovery", None)
        if isinstance(disc, WalletDiscovery):
            return disc.status()
        return {"enabled": False}

    @app.post("/api/demo/refresh")
    def refresh_demo() -> dict[str, Any]:
        _invalidate_cache()
        path = export_demo_json()
        return {"ok": True, "path": str(path)}


def create_app() -> FastAPI:
    """Build the FastAPI application.

    API routes are registered before the dashboard catch-all mount so that
    a deployed dist directory can never shadow the control-plane endpoints.
    """
    app = FastAPI(
        title="Polymarket Weather Copy Bot",
        description=(
            "Analysis, backtest, paper trading, and low-latency copy controls "
            "for Polymarket weather prediction markets."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    _register_api_routes(app)
    register_metrics_routes(app)

    dashboard_dist = os.path.join(os.environ.get("APP_ROOT", "/app"), "dashboard", "dist")
    if os.path.isdir(dashboard_dist):
        app.mount("/", StaticFiles(directory=dashboard_dist, html=True), name="dashboard")

    return app


app = create_app()
