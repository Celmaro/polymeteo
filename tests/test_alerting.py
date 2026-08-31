"""Tests for alerting clients: Uptime Kuma heartbeat and Apprise notifications."""
from __future__ import annotations

import pytest

from weather_copy_bot.ops.alerting import (
    AppriseNotifier,
    Notification,
    UptimeKumaHeartbeatClient,
)


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None


@pytest.fixture
def fake_httpx(monkeypatch):
    """Replace httpx.AsyncClient used by the alerting module with a recorder."""
    calls = []

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            calls.append({"method": "GET", "url": url, "params": params})
            return _FakeResponse()

    monkeypatch.setattr("weather_copy_bot.ops.alerting.httpx.AsyncClient", FakeAsyncClient)
    return calls


class TestUptimeKumaHeartbeatClient:
    """Test UptimeKumaHeartbeatClient."""

    def test_client_initializes_with_push_url(self):
        """Client should store its push URL."""
        client = UptimeKumaHeartbeatClient(push_url="https://kuma/api/push/abc123")
        assert client.push_url.endswith("/api/push/abc123")

    async def test_heartbeat_sends_up_status(self, fake_httpx):
        """heartbeat should call the push URL with status=up."""
        client = UptimeKumaHeartbeatClient(push_url="https://kuma/api/push/abc123")
        ok = await client.heartbeat(status="up", msg="OK")
        assert ok is True
        assert fake_httpx[0]["method"] == "GET"
        assert fake_httpx[0]["params"]["status"] == "up"
        assert fake_httpx[0]["params"]["msg"] == "OK"

    async def test_heartbeat_includes_ping(self, fake_httpx):
        """heartbeat should pass optional ping_ms through."""
        client = UptimeKumaHeartbeatClient(push_url="https://kuma/api/push/abc123")
        await client.heartbeat(status="up", msg="OK", ping_ms=42)
        assert fake_httpx[0]["params"]["ping"] == 42

    async def test_heartbeat_returns_false_on_http_error(self, monkeypatch):
        """HTTP failures should return False rather than raise."""
        import httpx as httpx_mod

        class FailingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, params=None):
                raise httpx_mod.ConnectError("down")

        monkeypatch.setattr(
            "weather_copy_bot.ops.alerting.httpx.AsyncClient", FailingClient
        )
        client = UptimeKumaHeartbeatClient(push_url="https://kuma/api/push/abc123")
        assert await client.heartbeat(status="down", msg="fail") is False


class TestAppriseNotifier:
    """Test AppriseNotifier."""

    def test_notifier_initializes_with_urls(self):
        """Notifier should accept a list of Apprise target URLs."""
        notifier = AppriseNotifier(urls=["json://localhost/hook"])
        assert notifier.urls == ["json://localhost/hook"]

    async def test_notify_sends_notification(self, monkeypatch):
        """notify should call into apprise with title and body."""
        sent = []

        class FakeApprise:
            def add(self, url):
                pass

            async def async_notify(self, title, body, **kwargs):
                sent.append({"title": title, "body": body})
                return True

        monkeypatch.setattr("weather_copy_bot.ops.alerting.apprise.Apprise", FakeApprise)
        notifier = AppriseNotifier(urls=["json://localhost/hook"])
        ok = await notifier.notify(
            Notification(title="Weather refresh failed", body="upstream down")
        )
        assert ok is True
        assert sent[0]["title"] == "Weather refresh failed"

    async def test_notify_returns_false_on_failure(self, monkeypatch):
        """Apprise failures should return False rather than raise."""

        class FailingApprise:
            def add(self, url):
                pass

            async def async_notify(self, title, body, **kwargs):
                return False

        monkeypatch.setattr(
            "weather_copy_bot.ops.alerting.apprise.Apprise", FailingApprise
        )
        notifier = AppriseNotifier(urls=["json://localhost/hook"])
        ok = await notifier.notify(Notification(title="t", body="b"))
        assert ok is False

    async def test_notify_empty_urls_returns_false(self):
        """Notifier with no configured URLs should short-circuit to False."""
        notifier = AppriseNotifier(urls=[])
        assert await notifier.notify(Notification(title="t", body="b")) is False
