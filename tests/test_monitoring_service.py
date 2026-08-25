"""Regression tests for MonitoringService alert delivery."""

from __future__ import annotations

import logging

import pytest

from weather_copy_bot.ops.monitoring import MonitoringService, TradingDashboard

pytestmark = pytest.mark.asyncio


class FlakyNotifier:
    """Notifier stub that raises for selected alert titles."""

    def __init__(self, fail_fragments: set[str]) -> None:
        self.fail_fragments = fail_fragments
        self.attempts: list[str] = []

    async def send_alert(self, title: str, message: str, severity: str = "info") -> None:
        self.attempts.append(title)
        if any(fragment in title for fragment in self.fail_fragments):
            raise RuntimeError("telegram down")


async def test_failed_alert_send_is_logged(caplog):
    service = MonitoringService(dashboard=TradingDashboard())
    notifier = FlakyNotifier({"Daily Loss"})
    service.set_dependencies(notifier, None)
    service.dashboard.daily_pnl = -100.0
    service.dashboard.current_drawdown_pct = 0.20

    with caplog.at_level(logging.ERROR, logger="weather_copy_bot.ops.monitoring"):
        await service._check_alerts()

    assert len(notifier.attempts) == 2
    assert any("Daily Loss" in title for title in notifier.attempts)
    assert "Failed to send alert" in caplog.text
    assert "telegram down" in caplog.text
