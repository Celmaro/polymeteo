"""Monitoring Service for Live Trading.

Real-time monitoring, metrics tracking, and dashboard state.
The notifier integration (Telegram/Discord) was removed in the audit cleanup;
the service still tracks metrics, checks alert conditions in-memory, and
exposes the dashboard but no longer pushes to any external transport.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics tracked."""

    BALANCE = "balance"
    PNL = "pnl"
    POSITION = "position"
    ORDER = "order"
    LATENCY = "latency"
    ERROR = "error"
    SYSTEM = "system"


@dataclass
class MetricSnapshot:
    """Single metric data point."""

    metric_type: MetricType
    name: str
    value: float
    timestamp: datetime
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class TradingDashboard:
    """Real-time trading dashboard state."""

    # Balance & P&L
    current_balance_usdc: float = 0.0
    starting_balance: float = 0.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    total_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    # Positions
    open_positions: int = 0
    pending_orders: int = 0
    max_positions: int = 5

    # Risk Metrics
    current_drawdown_pct: float = 0.0
    margin_used_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    # System Health
    last_order_time: datetime | None = None
    api_latency_p50_ms: float = 0.0
    api_latency_p95_ms: float = 0.0
    api_latency_p99_ms: float = 0.0
    error_count_last_hour: int = 0
    total_errors: int = 0

    # Quorum Stats
    quorum_hits: int = 0
    quorum_total_signals: int = 0
    obi_skips: int = 0

    # TWAP Stats
    twap_executions: int = 0
    twap_avg_slippage_bps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "balance": round(self.current_balance_usdc, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "weekly_pnl": round(self.weekly_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "positions": self.open_positions,
            "pending_orders": self.pending_orders,
            "drawdown": round(self.current_drawdown_pct * 100, 2),
            "margin_used": round(self.margin_used_pct * 100, 1),
            "latency_p95": round(self.api_latency_p95_ms, 1),
            "errors_last_hour": self.error_count_last_hour,
            "quorum_hit_rate": round(self.quorum_hits / max(1, self.quorum_total_signals) * 100, 1),
        }

    def to_status_string(self) -> str:
        """Generate human-readable status string for logs/dashboards."""
        if self.error_count_last_hour > 10:
            status_text = "CRITICAL: high error rate"
        elif self.current_drawdown_pct > 0.12:
            status_text = "CRITICAL: high drawdown"
        elif self.margin_used_pct > 0.85:
            status_text = "CRITICAL: high margin"
        elif self.error_count_last_hour > 5:
            status_text = "WARNING: elevated errors"
        elif self.daily_pnl <= -25:
            status_text = "WARNING: loss limit approached"
        else:
            status_text = "OPERATIONAL"

        return (
            f"Polymeteo Status: {status_text}\n"
            f"  Balance: ${self.current_balance_usdc:,.2f}\n"
            f"  Daily P&L: ${self.daily_pnl:+,.2f}\n"
            f"  Total P&L: ${self.total_pnl:+,.2f}\n"
            f"  Positions: {self.open_positions}/{self.max_positions}\n"
            f"  Drawdown: {self.current_drawdown_pct * 100:.2f}%\n"
            f"  Margin Used: {self.margin_used_pct * 100:.1f}%\n"
            f"  P95 Latency: {self.api_latency_p95_ms:.0f}ms\n"
            f"  Errors (1h): {self.error_count_last_hour}\n"
            f"  Quorum: {self.quorum_hits}/{self.quorum_total_signals} hits\n"
        )


class MonitoringService:
    """
    Continuous monitoring service for live trading.

    Features:
    - Periodic metric collection
    - Alert condition checking (in-memory; no external transport)
    - Dashboard updates
    - Performance tracking
    """

    def __init__(
        self,
        dashboard: TradingDashboard | None = None,
        update_interval_seconds: int = 30,
        alert_check_interval_seconds: int = 60,
    ):
        self.dashboard = dashboard or TradingDashboard()
        self.update_interval = update_interval_seconds
        self.alert_interval = alert_check_interval_seconds

        self._get_metrics_fn: Callable[[], Awaitable[dict]] | None = None

        # State
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._metric_history: list[MetricSnapshot] = []
        self._error_timestamps: list[datetime] = []
        self._pending_alerts: list[dict] = []

        # Alert thresholds
        self._alert_thresholds = {
            "daily_loss_warning": -25.0,
            "daily_loss_critical": -40.0,
            "drawdown_warning": 0.10,
            "drawdown_critical": 0.12,
            "latency_warning_ms": 500.0,
            "latency_critical_ms": 1000.0,
            "error_rate_warning": 5,
            "error_rate_critical": 10,
        }

        logger.info(
            "[MONITOR] Service initialized: "
            f"update_interval={self.update_interval}s, "
            f"alert_interval={self.alert_interval}s"
        )

    def set_dependencies(
        self,
        get_metrics_fn: Callable[[], Awaitable[dict]],
    ) -> None:
        """Set metrics dependency. Notifier integration removed (audit N0)."""
        self._get_metrics_fn = get_metrics_fn

    async def start(self) -> None:
        """Start the monitoring service."""
        if self._running:
            logger.warning("[MONITOR] Already running")
            return

        self._running = True
        logger.info("[MONITOR] Starting monitoring service")

        self._tasks = [
            asyncio.create_task(self._update_loop()),
            asyncio.create_task(self._alert_loop()),
        ]

    async def stop(self) -> None:
        """Stop the monitoring service."""
        self._running = False
        logger.info("[MONITOR] Stopping monitoring service")

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _update_loop(self) -> None:
        """Fetch and update metrics periodically."""
        while self._running:
            await self._fetch_and_update_metrics()
            await asyncio.sleep(self.update_interval)

    async def _alert_loop(self) -> None:
        """Check alert conditions periodically and log the outcome."""
        while self._running:
            await self._check_alerts()
            await asyncio.sleep(self.alert_interval)

    async def _fetch_and_update_metrics(self) -> None:
        """Fetch metrics and update dashboard."""
        if not self._get_metrics_fn:
            return

        try:
            metrics = await self._get_metrics_fn()

            self.dashboard.current_balance_usdc = metrics.get("balance", 0)
            self.dashboard.daily_pnl = metrics.get("daily_pnl", 0)
            self.dashboard.total_pnl = metrics.get("total_pnl", 0)
            self.dashboard.open_positions = metrics.get("positions", 0)
            self.dashboard.pending_orders = metrics.get("pending_orders", 0)
            self.dashboard.api_latency_p95_ms = metrics.get("latency_p95_ms", 0)

            if self.dashboard.starting_balance > 0:
                self.dashboard.current_drawdown_pct = max(
                    0,
                    (self.dashboard.starting_balance - self.dashboard.current_balance_usdc)
                    / self.dashboard.starting_balance,
                )

            self._prune_error_timestamps()
            self.dashboard.error_count_last_hour = len(self._error_timestamps)

            snapshot = MetricSnapshot(
                metric_type=MetricType.SYSTEM,
                name="dashboard_update",
                value=1.0,
                timestamp=datetime.now(timezone.utc),
            )
            self._metric_history.append(snapshot)

        except Exception as e:
            logger.error(f"[MONITOR] Failed to fetch metrics: {e}")
            self.record_error(f"metric_fetch: {e}")

    async def _check_alerts(self) -> None:
        """Check alert conditions and log any triggered alerts in-process."""
        alerts_to_send: list[dict] = []

        if self.dashboard.daily_pnl <= self._alert_thresholds["daily_loss_critical"]:
            alerts_to_send.append(
                {
                    "severity": "critical",
                    "title": "CRITICAL: Daily Loss Limit",
                    "message": (
                        f"Daily P&L: ${self.dashboard.daily_pnl:.2f}\n"
                        f"Limit: ${self._alert_thresholds['daily_loss_critical']:.2f}"
                    ),
                }
            )
        elif self.dashboard.daily_pnl <= self._alert_thresholds["daily_loss_warning"]:
            alerts_to_send.append(
                {
                    "severity": "warning",
                    "title": "WARNING: Approaching Daily Loss Limit",
                    "message": (
                        f"Daily P&L: ${self.dashboard.daily_pnl:.2f}\n"
                        f"Warning at: ${self._alert_thresholds['daily_loss_warning']:.2f}"
                    ),
                }
            )

        if self.dashboard.current_drawdown_pct >= self._alert_thresholds["drawdown_critical"]:
            alerts_to_send.append(
                {
                    "severity": "critical",
                    "title": "CRITICAL: High Drawdown",
                    "message": (
                        f"Drawdown: {self.dashboard.current_drawdown_pct * 100:.2f}%\n"
                        f"Limit: {self._alert_thresholds['drawdown_critical'] * 100:.1f}%"
                    ),
                }
            )
        elif self.dashboard.current_drawdown_pct >= self._alert_thresholds["drawdown_warning"]:
            alerts_to_send.append(
                {
                    "severity": "warning",
                    "title": "WARNING: Elevated Drawdown",
                    "message": f"Drawdown: {self.dashboard.current_drawdown_pct * 100:.2f}%",
                }
            )

        if self.dashboard.api_latency_p95_ms >= self._alert_thresholds["latency_critical_ms"]:
            alerts_to_send.append(
                {
                    "severity": "critical",
                    "title": "CRITICAL: High Latency",
                    "message": f"P95 Latency: {self.dashboard.api_latency_p95_ms:.0f}ms",
                }
            )

        if self.dashboard.error_count_last_hour >= self._alert_thresholds["error_rate_critical"]:
            alerts_to_send.append(
                {
                    "severity": "critical",
                    "title": "CRITICAL: High Error Rate",
                    "message": f"Errors (1h): {self.dashboard.error_count_last_hour}",
                }
            )

        for alert in alerts_to_send:
            await self._handle_alert(alert)

    async def _handle_alert(self, alert: dict) -> None:
        """Persist an alert internally; external transport was removed (audit N0)."""
        self._pending_alerts.append(
            {
                **alert,
                "raised_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(self._pending_alerts) > 200:
            self._pending_alerts = self._pending_alerts[-200:]
        logger.warning(
            "[MONITOR][%s] %s — %s",
            alert["severity"].upper(),
            alert["title"],
            alert["message"],
        )

    def _prune_error_timestamps(self) -> None:
        """Remove error timestamps older than 1 hour."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        self._error_timestamps = [ts for ts in self._error_timestamps if ts > cutoff]

    def record_error(self, error_msg: str) -> None:
        """Record an error for tracking."""
        self._error_timestamps.append(datetime.now(timezone.utc))
        self.dashboard.total_errors += 1
        logger.warning(f"[MONITOR] Error recorded: {error_msg}")

    def record_latency(self, operation: str, latency_ms: float) -> None:
        """Record operation latency."""
        if operation == "api_call":
            self.dashboard.api_latency_p95_ms = max(
                self.dashboard.api_latency_p95_ms * 0.9, latency_ms
            )

    def record_quorum_hit(self) -> None:
        """Record successful quorum hit."""
        self.dashboard.quorum_hits += 1
        self.dashboard.quorum_total_signals += 1

    def record_quorum_skip(self, reason: str) -> None:
        """Record quorum skip."""
        self.dashboard.quorum_total_signals += 1
        if "obi" in reason.lower():
            self.dashboard.obi_skips += 1

    def get_dashboard(self) -> TradingDashboard:
        """Get current dashboard state."""
        return self.dashboard

    def get_pending_alerts(self) -> list[dict]:
        """Return the most recent in-process alerts (max 200, newest last)."""
        return list(self._pending_alerts)

    def get_stats(self) -> dict[str, Any]:
        """Get monitoring statistics."""
        return {
            "running": self._running,
            "metric_history_size": len(self._metric_history),
            "error_count_1h": len(self._error_timestamps),
            "total_errors": self.dashboard.total_errors,
            "pending_alerts": len(self._pending_alerts),
            "dashboard": self.dashboard.to_dict(),
        }


def create_monitoring_service(
    update_interval: int = 30,
    alert_interval: int = 60,
) -> MonitoringService:
    """Create a pre-configured monitoring service."""
    return MonitoringService(
        update_interval_seconds=update_interval,
        alert_check_interval_seconds=alert_interval,
    )