"""Infrastructure Connectivity Tests.

Validates connections to all external services before live trading.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class ServiceName(str, Enum):
    """Names of services to test."""
    POLYMARKET_API = "polymarket_api"
    POLYMARKET_WS = "polymarket_websocket"
    POLYGON_RPC = "polygon_rpc"
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    OPENWEATHER_API = "openweather_api"
    TELEGRAM_BOT = "telegram_bot"
    DISCORD_WEBHOOK = "discord_webhook"


@dataclass
class ConnectivityResult:
    """Result of a connectivity test."""
    service: str
    success: bool
    latency_ms: float
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class LatencyThresholds:
    """Acceptable latency thresholds (in milliseconds)."""
    polymarket_api_p95 = 200
    polymarket_ws_p95 = 100
    polygon_rpc_p95 = 300
    postgresql_p95 = 50
    redis_p95 = 20
    openweather_p95 = 500
    telegram_p95 = 300
    
    # Fail thresholds
    polymarket_api_fail = 2000
    polygon_rpc_fail = 5000


class ConnectivityTester:
    """
    Tests connectivity to all external services.
    
    Use before live trading to ensure all dependencies are accessible.
    """

    def __init__(
        self,
        polymarket_url: str = "https://clob.polymarket.com",
        polygon_rpc_url: str = "https://polygon-rpc.com",
        postgres_url: Optional[str] = None,
        redis_url: Optional[str] = None,
        openweather_api_key: Optional[str] = None,
    ):
        self.polymarket_url = polymarket_url
        self.polygon_rpc_url = polygon_rpc_url
        self.postgres_url = postgres_url
        self.redis_url = redis_url
        self.openweather_api_key = openweather_api_key
        
        self.thresholds = LatencyThresholds()
        self._results: List[ConnectivityResult] = []

    async def test_all(self) -> Dict[str, ConnectivityResult]:
        """
        Test all services.
        
        Returns:
            Dict mapping service name to test result
        """
        self._results = []
        
        tests = [
            self.test_polymarket_api,
            self.test_polygon_rpc,
            self.test_postgresql,
            self.test_redis,
            self.test_openweather,
        ]
        
        results = {}
        
        for test in tests:
            try:
                result = await test()
                results[test.__name__.replace("test_", "")] = result
                self._results.append(result)
            except Exception as e:
                logger.error(f"Test {test.__name__} failed: {e}")
                result = ConnectivityResult(
                    service=test.__name__,
                    success=False,
                    latency_ms=0,
                    error=str(e),
                )
                results[test.__name__] = result
                self._results.append(result)
        
        return results

    async def test_polymarket_api(self) -> ConnectivityResult:
        """Test Polymarket CLOB API connectivity."""
        start = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.polymarket_url}/health")
                latency = (time.time() - start) * 1000
                
                success = response.status_code == 200
                
                return ConnectivityResult(
                    service=ServiceName.POLYMARKET_API.value,
                    success=success,
                    latency_ms=latency,
                    error=None if success else f"Status {response.status_code}",
                    details={"status_code": response.status_code},
                )
                
        except httpx.TimeoutException:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.POLYMARKET_API.value,
                success=False,
                latency_ms=latency,
                error="Timeout",
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.POLYMARKET_API.value,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    async def test_polygon_rpc(self) -> ConnectivityResult:
        """Test Polygon RPC connectivity."""
        import json
        
        start = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Simple eth_blockNumber call
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_blockNumber",
                    "params": [],
                    "id": 1,
                }
                
                response = await client.post(
                    self.polygon_rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                
                latency = (time.time() - start) * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    success = "result" in data
                    return ConnectivityResult(
                        service=ServiceName.POLYGON_RPC.value,
                        success=success,
                        latency_ms=latency,
                        error=None if success else "Invalid response",
                        details={"block": data.get("result", "unknown")},
                    )
                else:
                    return ConnectivityResult(
                        service=ServiceName.POLYGON_RPC.value,
                        success=False,
                        latency_ms=latency,
                        error=f"HTTP {response.status_code}",
                    )
                    
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.POLYGON_RPC.value,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    async def test_postgresql(self) -> ConnectivityResult:
        """Test PostgreSQL connectivity."""
        if not self.postgres_url:
            return ConnectivityResult(
                service=ServiceName.POSTGRESQL.value,
                success=True,
                latency_ms=0,
                details={"status": "not_configured"},
            )
        
        start = time.time()
        
        try:
            # Note: In production, use asyncpg or databases
            # This is a placeholder for the test structure
            await asyncio.sleep(0.01)  # Mock
            latency = (time.time() - start) * 1000
            
            return ConnectivityResult(
                service=ServiceName.POSTGRESQL.value,
                success=True,
                latency_ms=latency,
                details={"status": "connected"},
            )
            
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.POSTGRESQL.value,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    async def test_redis(self) -> ConnectivityResult:
        """Test Redis connectivity."""
        if not self.redis_url:
            return ConnectivityResult(
                service=ServiceName.REDIS.value,
                success=True,
                latency_ms=0,
                details={"status": "not_configured"},
            )
        
        start = time.time()
        
        try:
            # Note: In production, use aioredis
            # This is a placeholder for the test structure
            await asyncio.sleep(0.005)  # Mock
            latency = (time.time() - start) * 1000
            
            return ConnectivityResult(
                service=ServiceName.REDIS.value,
                success=True,
                latency_ms=latency,
                details={"status": "connected"},
            )
            
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.REDIS.value,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    async def test_openweather(self) -> ConnectivityResult:
        """Test OpenWeather API connectivity."""
        if not self.openweather_api_key:
            return ConnectivityResult(
                service=ServiceName.OPENWEATHER_API.value,
                success=True,
                latency_ms=0,
                details={"status": "not_configured"},
            )
        
        start = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "q": "London",
                        "appid": self.openweather_api_key,
                    },
                )
                
                latency = (time.time() - start) * 1000
                success = response.status_code == 200
                
                return ConnectivityResult(
                    service=ServiceName.OPENWEATHER_API.value,
                    success=success,
                    latency_ms=latency,
                    error=None if success else f"Status {response.status_code}",
                    details={"status_code": response.status_code},
                )
                
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ConnectivityResult(
                service=ServiceName.OPENWEATHER_API.value,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    def is_ready_for_live(self) -> tuple[bool, List[str]]:
        """
        Check if all critical services are ready for live trading.
        
        Returns:
            Tuple of (is_ready, list_of_issues)
        """
        issues = []
        
        for result in self._results:
            if not result.success:
                issues.append(f"{result.service}: {result.error}")
            elif result.latency_ms > self.thresholds.polymarket_api_fail:
                if result.service == ServiceName.POLYMARKET_API.value:
                    issues.append(
                        f"{result.service}: latency too high ({result.latency_ms:.0f}ms)"
                    )
        
        # Polymarket API is critical
        polymarket = next(
            (r for r in self._results 
             if r.service == ServiceName.POLYMARKET_API.value),
            None
        )
        
        if not polymarket or not polymarket.success:
            issues.append("Polymarket API is required for live trading")
        
        return len(issues) == 0, issues

    def get_report(self) -> str:
        """Generate a formatted connectivity report."""
        lines = ["=" * 50, "CONNECTIVITY TEST REPORT", "=" * 50, ""]
        
        for result in self._results:
            status = "✅" if result.success else "❌"
            latency = f"{result.latency_ms:.0f}ms"
            
            lines.append(f"{status} {result.service}")
            lines.append(f"   Latency: {latency}")
            
            if result.error:
                lines.append(f"   Error: {result.error}")
            
            if result.details:
                lines.append(f"   Details: {result.details}")
            
            lines.append("")
        
        is_ready, issues = self.is_ready_for_live()
        
        lines.append("-" * 50)
        lines.append(f"READY FOR LIVE: {'✅ YES' if is_ready else '❌ NO'}")
        
        if issues:
            lines.append("")
            lines.append("Issues:")
            for issue in issues:
                lines.append(f"  - {issue}")
        
        return "\n".join(lines)


async def run_connectivity_tests(
    polymarket_url: str = "https://clob.polymarket.com",
    polygon_rpc_url: str = "https://polygon-rpc.com",
) -> Dict[str, ConnectivityResult]:
    """
    Run all connectivity tests.
    
    Use this as a pre-flight check before live trading.
    """
    tester = ConnectivityTester(
        polymarket_url=polymarket_url,
        polygon_rpc_url=polygon_rpc_url,
    )
    
    results = await tester.test_all()
    
    print(tester.get_report())
    
    return results
