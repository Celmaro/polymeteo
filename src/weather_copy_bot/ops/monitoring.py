"""Monitoring Service for Live Trading.

Real-time monitoring, metrics tracking, and alerting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Callable, Awaitable

if TYPE_CHECKING:
    from weather_copy_bot.ops.notifications import NotificationHandler

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
    tags: Dict[str, str] = field(default_factory=dict)


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
    last_order_time: Optional[datetime] = None
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

    def to_dict(self) -> Dict[str, Any]:
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
            "quorum_hit_rate": round(
                self.quorum_hits / max(1, self.quorum_total_signals) * 100, 1
            ),
        }

    def to_status_string(self) -> str:
        """Generate status string for Telegram notifications."""
        # Status emoji
        if self.error_count_last_hour > 10:
            status_emoji = "🔴"
            status_text = "CRITICAL"
        elif self.current_drawdown_pct > 0.12:
            status_emoji = "🔴"
            status_text = "HIGH DRAWDOWN"
        elif self.margin_used_pct > 0.85:
            status_emoji = "🔴"
            status_text = "HIGH MARGIN"
        elif self.error_count_last_hour > 5:
            status_emoji = "🟡"
            status_text = "ELEVATED ERRORS"
        elif self.daily_pnl <= -25:
            status_emoji = "🟡"
            status_text = "LOSS LIMIT"
        else:
            status_emoji = "🟢"
            status_text = "OPERATIONAL"
        
        return f"""
📊 **Polymeteo Status**: {status_emoji} {status_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **Balance**: ${self.current_balance_usdc:,.2f}
📈 **Daily P&L**: ${self.daily_pnl:+,.2f}
📊 **Total P&L**: ${self.total_pnl:+,.2f}
💵 **Unrealized**: ${self.unrealized_pnl:+,.2f}

📋 **Positions**: {self.open_positions}/{self.max_positions}
⏳ **Pending Orders**: {self.pending_orders}
📉 **Drawdown**: {self.current_drawdown_pct*100:.2f}%
🔧 **Margin Used**: {self.margin_used_pct*100:.1f}%

⚡ **Latency P95**: {self.api_latency_p95_ms:.0f}ms
⚠️ **Errors (1h)**: {self.error_count_last_hour}

📊 **Quorum**: {self.quorum_hits}/{self.quorum_total_signals} hits
"""


class MonitoringService:
    """
    Continuous monitoring service for live trading.
    
    Features:
    - Periodic metric collection
    - Alert condition checking
    - Dashboard updates
    - Performance tracking
    """

    def __init__(
        self,
        dashboard: Optional[TradingDashboard] = None,
        update_interval_seconds: int = 30,
        alert_check_interval_seconds: int = 60,
    ):
        """
        Initialize Monitoring Service.
        
        Args:
            dashboard: TradingDashboard instance to update
            update_interval_seconds: How often to fetch metrics
            alert_check_interval_seconds: How often to check alerts
        """
        self.dashboard = dashboard or TradingDashboard()
        self.update_interval = update_interval_seconds
        self.alert_interval = alert_check_interval_seconds
        
        # Dependencies
        self._notifier: Optional[NotificationHandler] = None
        self._get_metrics_fn: Optional[Callable[[], Awaitable[Dict]]] = None
        
        # State
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._metric_history: List[MetricSnapshot] = []
        self._error_timestamps: List[datetime] = []
        
        # Alert thresholds
        self._alert_thresholds = {
            "daily_loss_warning": -25.0,  # $25
            "daily_loss_critical": -40.0,  # $40
            "drawdown_warning": 0.10,  # 10%
            "drawdown_critical": 0.12,  # 12%
            "latency_warning_ms": 500.0,
            "latency_critical_ms": 1000.0,
            "error_rate_warning": 5,
            "error_rate_critical": 10,
        }
        
        logger.info(
            f"[MONITOR] Service initialized: "
            f"update_interval={update_interval}s, "
            f"alert_interval={alert_check_interval}s"
        )

    def set_dependencies(
        self,
        notifier: NotificationHandler,
        get_metrics_fn: Callable[[], Awaitable[Dict]],
    ) -> None:
        """Set dependencies for monitoring."""
        self._notifier = notifier
        self._get_metrics_fn = get_metrics_fn

    async def start(self) -> None:
        """Start the monitoring service."""
        if self._running:
            logger.warning("[MONITOR] Already running")
            return
        
        self._running = True
        logger.info("[MONITOR] Starting monitoring service")
        
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._update_loop()),
            asyncio.create_task(self._alert_loop()),
            asyncio.create_task(self._hourly_report_loop()),
        ]

    async def stop(self) -> None:
        """Stop the monitoring service."""
        self._running = False
        logger.info("[MONITOR] Stopping monitoring service")
        
        # Cancel tasks
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _update_loop(self) -> None:
        """Fetch and update metrics periodically."""
        while self._running:
            try:
                await self._fetch_and_update_metrics()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MONITOR] Update loop error: {e}")
                await asyncio.sleep(5)

    async def _alert_loop(self) -> None:
        """Check for alert conditions periodically."""
        while self._running:
            try:
                await self._check_alerts()
                await asyncio.sleep(self.alert_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MONITOR] Alert loop error: {e}")
                await asyncio.sleep(5)

    async def _hourly_report_loop(self) -> None:
        """Send hourly status report."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # 1 hour
                await self._send_hourly_report()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MONITOR] Hourly report error: {e}")

    async def _fetch_and_update_metrics(self) -> None:
        """Fetch metrics and update dashboard."""
        if not self._get_metrics_fn:
            return
        
        try:
            metrics = await self._get_metrics_fn()
            
            # Update dashboard
            self.dashboard.current_balance_usdc = metrics.get("balance", 0)
            self.dashboard.daily_pnl = metrics.get("daily_pnl", 0)
            self.dashboard.total_pnl = metrics.get("total_pnl", 0)
            self.dashboard.open_positions = metrics.get("positions", 0)
            self.dashboard.pending_orders = metrics.get("pending_orders", 0)
            self.dashboard.api_latency_p95_ms = metrics.get("latency_p95_ms", 0)
            
            # Update drawdown
            if self.dashboard.starting_balance > 0:
                self.dashboard.current_drawdown_pct = max(
                    0,
                    (self.dashboard.starting_balance - self.dashboard.current_balance_usdc) 
                    / self.dashboard.starting_balance
                )
            
            # Track errors
            self._prune_error_timestamps()
            self.dashboard.error_count_last_hour = len(self._error_timestamps)
            
            # Record snapshot
            snapshot = MetricSnapshot(
                metric_type=MetricType.SYSTEM,
                name="dashboard_update",
                value=1.0,
                timestamp=datetime.now(),
            )
            self._metric_history.append(snapshot)
            
        except Exception as e:
            logger.error(f"[MONITOR] Failed to fetch metrics: {e}")
            self.record_error(f"metric_fetch: {e}")

    async def _check_alerts(self) -> None:
        """Check alert conditions and send notifications."""
        if not self._notifier:
            return
        
        alerts_to_send = []
        
        # Daily loss alerts
        if self.dashboard.daily_pnl <= self._alert_thresholds["daily_loss_critical"]:
            alerts_to_send.append({
                "severity": "critical",
                "title": "🚨 CRITICAL: Daily Loss Limit",
                "message": f"Daily P&L: ${self.dashboard.daily_pnl:.2f}\nLimit: ${self._alert_thresholds['daily_loss_critical']:.2f}",
            })
        elif self.dashboard.daily_pnl <= self._alert_thresholds["daily_loss_warning"]:
            alerts_to_send.append({
                "severity": "warning",
                "title": "⚠️ WARNING: Approaching Daily Loss Limit",
                "message": f"Daily P&L: ${self.dashboard.daily_pnl:.2f}\nWarning at: ${self._alert_thresholds['daily_loss_warning']:.2f}",
            })
        
        # Drawdown alerts
        if self.dashboard.current_drawdown_pct >= self._alert_thresholds["drawdown_critical"]:
            alerts_to_send.append({
                "severity": "critical",
                "title": "🚨 CRITICAL: High Drawdown",
                "message": f"Drawdown: {self.dashboard.current_drawdown_pct*100:.2f}%\nLimit: {self._alert_thresholds['drawdown_critical']*100:.1f}%",
            })
        elif self.dashboard.current_drawdown_pct >= self._alert_thresholds["drawdown_warning"]:
            alerts_to_send.append({
                "severity": "warning",
                "title": "⚠️ WARNING: Elevated Drawdown",
                "message": f"Drawdown: {self.dashboard.current_drawdown_pct*100:.2f}%",
            })
        
        # Latency alerts
        if self.dashboard.api_latency_p95_ms >= self._alert_thresholds["latency_critical_ms"]:
            alerts_to_send.append({
                "severity": "critical",
                "title": "🚨 CRITICAL: High Latency",
                "message": f"P95 Latency: {self.dashboard.api_latency_p95_ms:.0f}ms",
            })
        
        # Error rate alerts
        if self.dashboard.error_count_last_hour >= self._alert_thresholds["error_rate_critical"]:
            alerts_to_send.append({
                "severity": "critical",
                "title": "🚨 CRITICAL: High Error Rate",
                "message": f"Errors (1h): {self.dashboard.error_count_last_hour}",
            })
        
        # Send alerts
        for alert in alerts_to_send:
            try:
                await self._notifier.send_alert(
                    title=alert["title"],
                    message=alert["message"],
                    severity=alert["severity"],
                )
            except Exception as e:
                logger.error(f"[MONITOR] Failed to send alert: {e}")

    async def _send_hourly_report(self) -> None:
        """Send hourly status report."""
        if not self._notifier:
            return
        
        try:
            status = self.dashboard.to_status_string()
            await self._notifier.send_message(status)
        except Exception as e:
            logger.error(f"[MONITOR] Failed to send hourly report: {e}")

    def _prune_error_timestamps(self) -> None:
        """Remove error timestamps older than 1 hour."""
        cutoff = datetime.now() - timedelta(hours=1)
        self._error_timestamps = [
            ts for ts in self._error_timestamps if ts > cutoff
        ]

    def record_error(self, error_msg: str) -> None:
        """Record an error for tracking."""
        self._error_timestamps.append(datetime.now())
        self.dashboard.total_errors += 1
        logger.warning(f"[MONITOR] Error recorded: {error_msg}")

    def record_latency(self, operation: str, latency_ms: float) -> None:
        """Record operation latency."""
        if operation == "api_call":
            # Simple rolling average for P95
            # In production, use proper percentile tracking
            self.dashboard.api_latency_p95_ms = max(
                self.dashboard.api_latency_p95_ms * 0.9,
                latency_ms
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

    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        return {
            "running": self._running,
            "metric_history_size": len(self._metric_history),
            "error_count_1h": len(self._error_timestamps),
            "total_errors": self.dashboard.total_errors,
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
