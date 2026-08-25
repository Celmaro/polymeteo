"""Failover and Redundancy Configuration for Live Trading.

Provides redundant connections to critical services.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any
from urllib.parse import ParseResult, urlparse

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ServiceType(str, Enum):
    """Types of services with failover support."""

    POLYMARKET_API = "polymarket_api"
    POLYGON_RPC = "polygon_rpc"
    WEBSOCKET = "websocket"
    DATABASE = "database"
    REDIS = "redis"


@dataclass
class EndpointConfig:
    """Configuration for a single endpoint."""

    url: str
    name: str
    priority: int = 1
    timeout_ms: int = 3000
    is_backup: bool = False
    weight: float = 1.0  # For load balancing


@dataclass
class HealthStatus:
    """Health status of an endpoint."""

    endpoint: str
    is_healthy: bool = True
    last_check: float = 0
    consecutive_failures: int = 0
    avg_latency_ms: float = 0
    is_tripped: bool = False


class FailoverManager:
    """
    Manages failover for critical services.

    Features:
    - Multiple endpoint support with priorities
    - Automatic failover on failure
    - Health checking
    - Load balancing (weighted)
    - Circuit breaker per endpoint
    """

    def __init__(
        self,
        health_check_interval_seconds: int = 30,
        max_consecutive_failures: int = 3,
        failure_cooldown_seconds: float = 60.0,
        circuit_breaker_threshold: int = 5,
    ):
        """
        Initialize Failover Manager.

        Args:
            health_check_interval_seconds: How often to check endpoint health
            max_consecutive_failures: Failures before marking endpoint unhealthy
            failure_cooldown_seconds: Time before retrying failed endpoint
            circuit_breaker_threshold: Failures to trip circuit breaker
        """
        self.health_check_interval = health_check_interval_seconds
        self.max_failures = max_consecutive_failures
        self.failure_cooldown = failure_cooldown_seconds
        self.circuit_threshold = circuit_breaker_threshold

        # Endpoint configurations by service type
        self._endpoints: dict[ServiceType, list[EndpointConfig]] = {
            ServiceType.POLYMARKET_API: [],
            ServiceType.POLYGON_RPC: [],
            ServiceType.WEBSOCKET: [],
            ServiceType.DATABASE: [],
            ServiceType.REDIS: [],
        }

        # Health status per endpoint
        self._health: dict[str, HealthStatus] = {}

        # Active endpoints (current choice)
        self._active_endpoints: dict[ServiceType, str] = {}

        # State
        self._running = False
        self._health_check_task: asyncio.Task | None = None
        self._transport: httpx.AsyncBaseTransport | None = None

        # Lock for thread safety
        self._lock = asyncio.Lock()

        logger.info("[FAILOVER] Manager initialized")

    def register_endpoint(
        self,
        service: ServiceType,
        url: str,
        name: str,
        priority: int = 1,
        timeout_ms: int = 3000,
        is_backup: bool = False,
        weight: float = 1.0,
    ) -> None:
        """
        Register an endpoint for a service.

        Args:
            service: Type of service
            url: Endpoint URL
            name: Human-readable name
            priority: Priority (lower = higher priority)
            timeout_ms: Request timeout
            is_backup: True if this is a backup endpoint
            weight: Weight for load balancing
        """
        config = EndpointConfig(
            url=url,
            name=name,
            priority=priority,
            timeout_ms=timeout_ms,
            is_backup=is_backup,
            weight=weight,
        )

        self._endpoints[service].append(config)
        self._health[name] = HealthStatus(endpoint=name)

        # Set active endpoint if first
        if service not in self._active_endpoints:
            self._active_endpoints[service] = name

        logger.info(
            f"[FAILOVER] Registered {service.value} endpoint: "
            f"{name} ({'backup' if is_backup else 'primary'})"
        )

    def get_endpoint(self, service: ServiceType) -> EndpointConfig | None:
        """
        Get the active endpoint for a service.

        Returns the highest priority healthy endpoint.
        """
        endpoints = sorted(self._endpoints.get(service, []), key=lambda x: (x.priority, -x.weight))

        for endpoint in endpoints:
            health = self._health.get(endpoint.name)
            if health and health.is_healthy and not health.is_tripped:
                return endpoint

        # No healthy endpoint, return lowest priority
        return endpoints[-1] if endpoints else None

    async def record_success(self, service: ServiceType, latency_ms: float) -> None:
        """Record successful request."""
        endpoint_name = self._active_endpoints.get(service)
        if not endpoint_name:
            return

        health = self._health.get(endpoint_name)
        if not health:
            return

        # Update metrics
        health.consecutive_failures = 0
        health.is_healthy = True
        health.last_check = time.time()

        # Update latency (exponential moving average)
        if health.avg_latency_ms == 0:
            health.avg_latency_ms = latency_ms
        else:
            health.avg_latency_ms = health.avg_latency_ms * 0.7 + latency_ms * 0.3

        # Reset circuit breaker if recovering
        if health.is_tripped:
            health.is_tripped = False
            logger.info(f"[FAILOVER] {endpoint_name} recovered from circuit breaker")

    async def record_failure(
        self,
        service: ServiceType,
        error: str,
        latency_ms: float | None = None,
    ) -> bool:
        """
        Record failed request.

        Returns True if failover to backup occurred.
        """
        endpoint_name = self._active_endpoints.get(service)
        if not endpoint_name:
            return False

        health = self._health.get(endpoint_name)
        if not health:
            return False

        health.consecutive_failures += 1
        health.last_check = time.time()

        logger.warning(
            f"[FAILOVER] {endpoint_name} failure {health.consecutive_failures}/"
            f"{self.max_failures}: {error}"
        )

        # Check if should failover
        should_failover = False

        if health.consecutive_failures >= self.max_failures:
            health.is_healthy = False
            should_failover = True
            logger.warning(f"[FAILOVER] {endpoint_name} marked unhealthy")

        # Check circuit breaker
        if health.consecutive_failures >= self.circuit_threshold:
            health.is_tripped = True
            should_failover = True
            logger.critical(f"[FAILOVER] {endpoint_name} circuit breaker TRIPPED")

        if should_failover:
            return await self._failover(service)

        return False

    async def _failover(self, service: ServiceType) -> bool:
        """Perform failover to next available endpoint."""
        async with self._lock:
            endpoints = sorted(
                self._endpoints.get(service, []), key=lambda x: (x.priority, -x.weight)
            )

            current = self._active_endpoints.get(service)

            for endpoint in endpoints:
                if endpoint.name == current:
                    continue

                health = self._health.get(endpoint.name)
                if health and (health.is_healthy or not health.is_tripped):
                    old = current
                    self._active_endpoints[service] = endpoint.name

                    logger.warning(f"[FAILOVER] {service.value} failover: {old} -> {endpoint.name}")
                    return True

            logger.error(f"[FAILOVER] No healthy endpoint for {service.value}")
            return False

    async def health_check(self, service: ServiceType) -> dict[str, Any]:
        """
        Perform health check on all endpoints for a service.

        This should be called periodically by the health check loop.
        """
        results = {}

        for endpoint in self._endpoints.get(service, []):
            health = self._health.get(endpoint.name)
            if not health:
                continue

            # Skip if in cooldown
            if not health.is_healthy:
                cooldown_remaining = self.failure_cooldown - (time.time() - health.last_check)
                if cooldown_remaining > 0:
                    results[endpoint.name] = {
                        "status": "cooldown",
                        "cooldown_remaining": cooldown_remaining,
                    }
                    continue

            # Perform health check (ping)
            try:
                started = time.perf_counter()
                is_healthy = await self._ping_endpoint(service, endpoint)
                elapsed_ms = (time.perf_counter() - started) * 1000

                if is_healthy:
                    health.is_healthy = True
                    health.consecutive_failures = 0
                    health.last_check = time.time()
                    health.avg_latency_ms = (
                        elapsed_ms
                        if health.avg_latency_ms == 0
                        else health.avg_latency_ms * 0.7 + elapsed_ms * 0.3
                    )
                else:
                    health.consecutive_failures += 1
                    if health.consecutive_failures >= self.max_failures:
                        health.is_healthy = False

                results[endpoint.name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "latency_ms": round(elapsed_ms, 2),
                    "failures": health.consecutive_failures,
                }

            except Exception as e:
                logger.error(f"[FAILOVER] Health check failed for {endpoint.name}: {e}")
                results[endpoint.name] = {"status": "error", "error": str(e)}

        return results

    async def _ping_endpoint(
        self,
        service: ServiceType,
        endpoint: EndpointConfig,
    ) -> bool:
        """Ping an endpoint with a real network probe."""
        timeout_s = endpoint.timeout_ms / 1000
        parsed = urlparse(endpoint.url)
        scheme = parsed.scheme.lower()

        if scheme in ("sqlite", ""):
            # File-backed/local stores are reachable in-process by definition
            return True

        try:
            if service in (ServiceType.DATABASE, ServiceType.REDIS):
                return await self._tcp_ping(parsed, timeout_s)
            return await self._http_ping(endpoint.url, timeout_s)
        except Exception as e:
            logger.debug(f"[FAILOVER] Probe failed for {endpoint.name}: {e}")
            return False

    async def _http_ping(self, url: str, timeout_s: float) -> bool:
        """HTTP liveness probe; any non-5xx response counts as up."""
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout_s,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            return response.status_code < 500

    async def _tcp_ping(self, parsed: ParseResult, timeout_s: float) -> bool:
        """TCP reachability probe for non-HTTP services (DB/Redis)."""
        host = parsed.hostname
        if not host:
            return False
        default_ports = {
            "redis": 6379,
            "rediss": 6379,
            "postgres": 5432,
            "postgresql": 5432,
        }
        port = parsed.port or default_ports.get(parsed.scheme.lower(), 443)
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout_s
        )
        writer.close()
        return True

    async def start_health_checks(self) -> None:
        """Start periodic health checks."""
        if self._running:
            return

        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("[FAILOVER] Health check loop started")

    async def stop_health_checks(self) -> None:
        """Stop periodic health checks."""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_check_task
        logger.info("[FAILOVER] Health check loop stopped")

    async def _health_check_loop(self) -> None:
        """Periodic health check loop."""
        while self._running:
            for service in ServiceType:
                await self.health_check(service)
            await asyncio.sleep(self.health_check_interval)

    def get_status(self) -> dict[str, Any]:
        """Get status of all services and endpoints."""
        status = {
            "running": self._running,
            "services": {},
        }

        for service in ServiceType:
            endpoints = self._endpoints.get(service, [])
            if not endpoints:
                continue

            service_status = {
                "active": self._active_endpoints.get(service),
                "endpoints": {},
            }

            for endpoint in endpoints:
                health = self._health.get(endpoint.name)
                service_status["endpoints"][endpoint.name] = {
                    "url": endpoint.url,
                    "priority": endpoint.priority,
                    "is_backup": endpoint.is_backup,
                    "is_healthy": health.is_healthy if health else None,
                    "is_tripped": health.is_tripped if health else None,
                    "avg_latency_ms": round(health.avg_latency_ms, 2) if health else None,
                    "consecutive_failures": health.consecutive_failures if health else 0,
                }

            status["services"][service.value] = service_status

        return status


# Default configurations
DEFAULT_POLYGON_RPC_ENDPOINTS = [
    EndpointConfig(
        url="https://polygon-rpc.com",
        name="polygon_main",
        priority=1,
        timeout_ms=3000,
    ),
    EndpointConfig(
        url="https://rpc.ankr.com/polygon",
        name="ankr",
        priority=2,
        timeout_ms=5000,
        is_backup=True,
    ),
    EndpointConfig(
        url="https://1rpc.io/matic",
        name="1rpc",
        priority=3,
        timeout_ms=5000,
        is_backup=True,
    ),
    EndpointConfig(
        url="https://matic-mainnet.chainstacklabs.com",
        name="chainstack",
        priority=4,
        timeout_ms=5000,
        is_backup=True,
    ),
]

DEFAULT_POLYMARKET_ENDPOINTS = [
    EndpointConfig(
        url="https://clob.polymarket.com",
        name="clob_main",
        priority=1,
        timeout_ms=2000,
    ),
]


def create_default_failover_manager() -> FailoverManager:
    """Create a failover manager with default Polygon RPC endpoints."""
    manager = FailoverManager()

    # Register Polygon RPC endpoints
    for endpoint in DEFAULT_POLYGON_RPC_ENDPOINTS:
        manager.register_endpoint(
            service=ServiceType.POLYGON_RPC,
            url=endpoint.url,
            name=endpoint.name,
            priority=endpoint.priority,
            timeout_ms=endpoint.timeout_ms,
            is_backup=endpoint.is_backup,
        )

    # Register Polymarket CLOB endpoint
    for endpoint in DEFAULT_POLYMARKET_ENDPOINTS:
        manager.register_endpoint(
            service=ServiceType.POLYMARKET_API,
            url=endpoint.url,
            name=endpoint.name,
            priority=endpoint.priority,
            timeout_ms=endpoint.timeout_ms,
        )

    return manager
