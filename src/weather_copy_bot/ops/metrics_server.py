"""Prometheus metrics exporter for the copy-trading bot.

Provides a /metrics HTTP endpoint that Prometheus scrapes to build live
dashboards for latency, throughput, upstream throttling, and risk metrics.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

signals_detected = Counter(
    "polymeteo_signals_detected_total",
    "Total trade signals detected (all sources: poll + WebSocket)",
)
signals_copied = Counter(
    "polymeteo_signals_copied_total",
    "Total signals that passed all gates and were copied",
)
signals_skipped = Counter(
    "polymeteo_signals_skipped_total",
    "Total signals rejected by any gate",
)
risk_rejections = Counter(
    "polymeteo_risk_rejections_total",
    "Signals rejected by the risk engine",
)
upstream_429_total = Counter(
    "polymeteo_upstream_429_total",
    "Total upstream 429 (rate limit) responses from Polymarket",
)
live_orders_filled = Counter(
    "polymeteo_live_orders_filled_total",
    "Live orders successfully filled (live mode only)",
)
live_orders_failed = Counter(
    "polymeteo_live_orders_failed_total",
    "Live orders that failed (live mode only)",
)
live_orders_duplicated = Counter(
    "polymeteo_live_orders_duplicated_total",
    "Live orders rejected as duplicates",
)
live_orders_throttled = Counter(
    "polymeteo_live_orders_throttled_total",
    "Live orders rejected by the order queue rate limiter",
)
quorum_votes = Counter(
    "polymeteo_quorum_votes_total",
    "Total wallet votes registered with the quorum engine",
)
quorum_reached = Counter(
    "polymeteo_quorum_reached_total",
    "Consensus quorum fires",
)
quorum_rejected = Counter(
    "polymeteo_quorum_rejected_total",
    "Consensus fires but is rejected by risk engine",
)

balance_gauge = Gauge(
    "polymeteo_balance_usd",
    "Current account balance in USD",
)
daily_pnl_gauge = Gauge(
    "polymeteo_daily_pnl_usd",
    "Realized P&L for the current UTC day",
)
open_positions_gauge = Gauge(
    "polymeteo_open_positions",
    "Number of currently open positions",
)

engine_running = Gauge(
    "polymeteo_engine_running",
    "1 if the CopyEngine loop is running, 0 otherwise",
)
ws_connected = Gauge(
    "polymeteo_ws_connected",
    "1 if the CLOB WebSocket is connected, 0 otherwise",
)

upstream_age_seconds = Histogram(
    "polymeteo_upstream_age_seconds",
    "Age of upstream event when detected (seconds)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
local_latency_ms = Histogram(
    "polymeteo_local_latency_ms",
    "Local detect-to-decision latency in milliseconds",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500),
)

skip_reason_counter: dict[str, Counter] = {}


def _get_skip_counter(reason: str) -> Counter:
    if reason not in skip_reason_counter:
        skip_reason_counter[reason] = Counter(
            f"polymeteo_skip_reason_{reason}",
            f"Signals skipped with reason prefix: {reason}",
        )
    return skip_reason_counter[reason]


def _engine_stats_to_metrics(stats: dict[str, Any]) -> None:
    signals_detected.inc(max(stats.get("signals_detected", 0) - signals_detected._value.get(), 0))
    signals_copied.inc(max(stats.get("copied", 0) - signals_copied._value.get(), 0))
    signals_skipped.inc(max(stats.get("skipped", 0) - signals_skipped._value.get(), 0))
    risk_rejections.inc(max(stats.get("risk_rejections", 0) - risk_rejections._value.get(), 0))
    upstream_429_total.inc(
        max(stats.get("upstream_429_rejections", 0) - upstream_429_total._value.get(), 0)
    )
    live_orders_filled.inc(
        max(stats.get("live_orders_filled", 0) - live_orders_filled._value.get(), 0)
    )
    live_orders_failed.inc(
        max(stats.get("live_orders_failed", 0) - live_orders_failed._value.get(), 0)
    )
    live_orders_duplicated.inc(
        max(stats.get("live_orders_duplicated", 0) - live_orders_duplicated._value.get(), 0)
    )
    live_orders_throttled.inc(
        max(stats.get("live_orders_throttled", 0) - live_orders_throttled._value.get(), 0)
    )
    quorum_votes.inc(max(stats.get("quorum_votes", 0) - quorum_votes._value.get(), 0))
    quorum_reached.inc(max(stats.get("quorum_reached", 0) - quorum_reached._value.get(), 0))
    quorum_rejected.inc(
        max(stats.get("quorum_rejected", 0) - quorum_rejected._value.get(), 0)
    )
    reasons: dict[str, int] = stats.get("signals_by_reason", {})
    for reason, count in reasons.items():
        c = _get_skip_counter(reason)
        c.inc(max(count - c._value.get(), 0))


def sync_engine_to_metrics(app: FastAPI) -> None:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        return
    stats = dict(getattr(engine, "stats", {}))
    _engine_stats_to_metrics(stats)
    balance_gauge.set(getattr(engine, "_balance", 0.0))
    daily_pnl_gauge.set(getattr(engine, "_daily_pnl", 0.0))
    open_positions_gauge.set(len(getattr(engine, "_open_positions", {})))
    engine_running.set(1 if getattr(engine, "_running", False) else 0)
    ws = getattr(engine, "_ws", None)
    ws_connected.set(1 if ws is not None else 0)


def register_metrics_routes(app: FastAPI) -> None:
    @app.get("/metrics")
    def metrics() -> Response:
        sync_engine_to_metrics(app)
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def readiness() -> dict[str, Any]:
        engine = getattr(app.state, "engine", None)
        if engine is None:
            return {"status": "ready", "engine": False}
        running = bool(getattr(engine, "_running", False))
        heartbeat = (engine.stats or {}).get("last_heartbeat")
        healthy = False
        if running and heartbeat:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(str(heartbeat))
                healthy = age.total_seconds() < 30.0
            except ValueError:
                healthy = False
        return {"status": "ready" if healthy else "degraded", "engine": running, "heartbeat": heartbeat}
