"""Alerting integrations: Uptime Kuma heartbeats and Apprise notifications."""

from __future__ import annotations

from dataclasses import dataclass

import apprise
import httpx


@dataclass
class Notification:
    """A notification to deliver via Apprise."""

    title: str
    body: str


class UptimeKumaHeartbeatClient:
    """Push heartbeats to an Uptime Kuma push monitor."""

    def __init__(self, push_url: str) -> None:
        self.push_url = push_url

    async def heartbeat(
        self, status: str = "up", msg: str = "OK", ping_ms: int | None = None
    ) -> bool:
        """Send a heartbeat; returns False instead of raising on failure."""
        params: dict[str, object] = {"status": status, "msg": msg}
        if ping_ms is not None:
            params["ping"] = ping_ms
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.push_url, params=params)
                response.raise_for_status()
            return True
        except Exception:
            return False


class AppriseNotifier:
    """Send notifications to one or more Apprise targets."""

    def __init__(self, urls: list[str]) -> None:
        self.urls = list(urls)

    async def notify(self, notification: Notification) -> bool:
        """Deliver a notification; returns False instead of raising on failure."""
        if not self.urls:
            return False
        try:
            apobj = apprise.Apprise()
            for url in self.urls:
                apobj.add(url)
            return bool(
                await apobj.async_notify(
                    title=notification.title, body=notification.body
                )
            )
        except Exception:
            return False
