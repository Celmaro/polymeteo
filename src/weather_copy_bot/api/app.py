"""FastAPI surface for the weather copy-trading dashboard and control plane."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from weather_copy_bot import __version__

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
    }


@app.get("/api/dashboard")
def dashboard() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import load_dashboard_payload
    return load_dashboard_payload()


@app.get("/api/wallets")
def wallets() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import build_dashboard_payload
    payload = build_dashboard_payload()
    return {"wallets": [w.model_dump(mode="json") for w in payload.wallets]}


@app.get("/api/backtest/summary")
def backtest_summary() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import build_dashboard_payload
    payload = build_dashboard_payload()
    return payload.backtest.model_dump(mode="json")


@app.get("/api/paper/summary")
def paper_summary() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import build_dashboard_payload
    payload = build_dashboard_payload()
    return payload.paper.model_dump(mode="json")


@app.get("/api/engine/status")
def engine_status() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import build_dashboard_payload
    payload = build_dashboard_payload()
    return payload.engine_status


@app.post("/api/demo/refresh")
def refresh_demo() -> Dict[str, Any]:
    from weather_copy_bot.demo_data import export_demo_json
    path = export_demo_json()
    return {"ok": True, "path": str(path)}
