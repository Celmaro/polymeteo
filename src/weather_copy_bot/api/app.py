"""FastAPI surface for the weather copy-trading dashboard and control plane."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from weather_copy_bot import __version__
from weather_copy_bot.config import get_settings
from weather_copy_bot.demo_data import build_dashboard_payload, export_demo_json, load_dashboard_payload

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Polymarket Weather Copy Bot",
    description=(
        "Analysis, backtest, paper trading, and low-latency copy controls "
        "for Polymarket weather prediction markets."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_demo_data() -> None:
    logger.info("Starting Polymeteo API...")
    logger.info(f"Settings loaded - dry_run={settings.dry_run}, live_trading={settings.live_trading_enabled}")
    try:
        export_demo_json()
        logger.info("Demo data exported successfully")
    except Exception as e:
        logger.error(f"Error exporting demo data: {e}")
        logger.error(traceback.format_exc())


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "mode": "live" if settings.live_trading_enabled else "paper",
        "dry_run": settings.dry_run,
    }


@app.get("/api/dashboard")
def dashboard() -> Dict[str, Any]:
    return load_dashboard_payload()


@app.get("/api/wallets")
def wallets() -> Dict[str, Any]:
    payload = build_dashboard_payload()
    return {"wallets": [w.model_dump(mode="json") for w in payload.wallets]}


@app.get("/api/backtest/summary")
def backtest_summary() -> Dict[str, Any]:
    payload = build_dashboard_payload()
    return payload.backtest.model_dump(mode="json")


@app.get("/api/paper/summary")
def paper_summary() -> Dict[str, Any]:
    payload = build_dashboard_payload()
    return payload.paper.model_dump(mode="json")


@app.get("/api/engine/status")
def engine_status() -> Dict[str, Any]:
    payload = build_dashboard_payload()
    return payload.engine_status


@app.post("/api/demo/refresh")
def refresh_demo() -> Dict[str, Any]:
    path = export_demo_json()
    return {"ok": True, "path": str(path)}
