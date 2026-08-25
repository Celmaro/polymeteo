"""Tests for FailoverManager real health probing."""

from __future__ import annotations

import httpx
import pytest

from weather_copy_bot.ops.failover import FailoverManager, ServiceType

pytestmark = pytest.mark.asyncio


def _manager(handler) -> FailoverManager:
    manager = FailoverManager(max_consecutive_failures=1)
    manager._transport = httpx.MockTransport(handler)
    return manager


async def test_health_check_marks_dead_http_endpoint_unhealthy():
    manager = _manager(lambda request: httpx.Response(503))
    manager.register_endpoint(ServiceType.POLYMARKET_API, "https://clob.example.com", "primary")

    results = await manager.health_check(ServiceType.POLYMARKET_API)

    assert results["primary"]["status"] == "unhealthy"
    health = manager._health["primary"]
    assert health.is_healthy is False
    assert health.consecutive_failures >= 1


async def test_get_endpoint_fails_over_to_healthy_backup():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dead.example.com":
            return httpx.Response(500)
        return httpx.Response(200)

    manager = _manager(handler)
    manager.register_endpoint(
        ServiceType.POLYMARKET_API, "https://dead.example.com", "primary", priority=1
    )
    manager.register_endpoint(
        ServiceType.POLYMARKET_API,
        "https://alive.example.com",
        "backup",
        priority=2,
        is_backup=True,
    )

    await manager.health_check(ServiceType.POLYMARKET_API)

    active = manager.get_endpoint(ServiceType.POLYMARKET_API)
    assert active is not None
    assert active.name == "backup"


async def test_tcp_endpoint_with_closed_port_is_unhealthy():
    manager = FailoverManager(max_consecutive_failures=1)
    manager.register_endpoint(ServiceType.REDIS, "redis://127.0.0.1:1", "local_redis")

    results = await manager.health_check(ServiceType.REDIS)

    assert results["local_redis"]["status"] == "unhealthy"
    assert manager._health["local_redis"].is_healthy is False
