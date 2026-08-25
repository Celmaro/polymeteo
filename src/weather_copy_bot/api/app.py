"""FastAPI surface for the weather copy-trading dashboard and control plane."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_cached_payload() -> DashboardPayload:
    return build_dashboard_payload()


def _invalidate_cache() -> None:
    _get_cached_payload.cache_clear()


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
        return _get_cached_payload().engine_status

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

    dashboard_dist = os.path.join(os.environ.get("APP_ROOT", "/app"), "dashboard", "dist")
    if os.path.isdir(dashboard_dist):
        app.mount("/", StaticFiles(directory=dashboard_dist, html=True), name="dashboard")

    return app


app = create_app()
