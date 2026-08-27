"""Regression tests for MonitoringService alert delivery.

The notifier transport (Telegram/Discord) was removed in audit cleanup N0; the
service now logs triggered alerts in-process and stores them in the
``_pending_alerts`` inbox instead of pushing to an external sink.
"""

from __future__ import annotations

import logging

import pytest

from weather_copy_bot.ops.monitoring import MonitoringService, TradingDashboard

pytestmark = pytest.mark.asyncio


async def test_alerts_are_logged_and_persisted(caplog):
    service = MonitoringService(dashboard=TradingDashboard())
    service.dashboard.daily_pnl = -100.0
    service.dashboard.current_drawdown_pct = 0.20

    with caplog.at_level(logging.WARNING, logger="weather_copy_bot.ops.monitoring"):
        await service._check_alerts()

    pending = service.get_pending_alerts()
    assert len(pending) == 2
    assert any("Daily Loss" in alert["title"] for alert in pending)
    assert any("Drawdown" in alert["title"] for alert in pending)
    assert "CRITICAL: Daily Loss Limit" in caplog.text
    assert "CRITICAL: High Drawdown" in caplog.text


async def test_pending_alerts_inbox_is_capped():
    service = MonitoringService(dashboard=TradingDashboard())
    for _ in range(250):
        await service._handle_alert(
            {
                "severity": "warning",
                "title": "Filler alert",
                "message": "noise",
            }
        )
    pending = service.get_pending_alerts()
    assert len(pending) == 200
    assert all(alert["title"] == "Filler alert" for alert in pending)


async def test_set_dependencies_metrics_hook():
    service = MonitoringService(dashboard=TradingDashboard())

    async def metrics():
        return {
            "balance": 1234.0,
            "daily_pnl": 50.0,
            "total_pnl": 200.0,
            "positions": 3,
            "pending_orders": 1,
            "latency_p95_ms": 250.0,
        }

    service.set_dependencies(metrics)
    await service._fetch_and_update_metrics()
    assert service.dashboard.current_balance_usdc == 1234.0
    assert service.dashboard.daily_pnl == 50.0
