"""Tests for FastAPI application endpoints."""

import asyncio
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from weather_copy_bot.api.app import app


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestDashboardEndpoint:
    """Test dashboard endpoint."""

    def test_dashboard_returns_payload(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "generated_at" in data
        assert "headline" in data

    def test_dashboard_includes_performance(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/dashboard")
        data = response.json()
        assert "headline" in data
        assert "mode" in data["headline"]


class TestStatusEndpoint:
    """Test status endpoint."""

    def test_status_returns_config(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/engine/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestCorsHeaders:
    """Test CORS configuration."""

    def test_cors_headers_present(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.options(
            "/api/dashboard",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" in response.headers or response.status_code == 200


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_returns_static_files(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code in [200, 404]


class TestRoutePrecedence:
    """API routes must take precedence over the catch-all dashboard mount (C-2)."""

    def test_api_routes_take_precedence_over_dashboard_mount(self, monkeypatch, tmp_path):
        dist = tmp_path / "dashboard" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html><body>polymeteo-dashboard</body></html>")
        monkeypatch.setenv("APP_ROOT", str(tmp_path))

        from weather_copy_bot.api.app import create_app

        application = create_app()
        client = TestClient(application)

        assert client.get("/api/health").status_code == 200
        assert client.get("/api/dashboard").status_code == 200

        root = client.get("/")
        assert root.status_code == 200
        assert "polymeteo-dashboard" in root.text

    def test_create_app_without_dist_serves_no_mount(self, monkeypatch, tmp_path):
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        monkeypatch.setenv("APP_ROOT", str(empty_root))

        from weather_copy_bot.api.app import create_app

        application = create_app()
        client = TestClient(application)
        assert client.get("/api/health").status_code == 200


class TestEngineStatusLive:
    """When an engine is attached to app.state, /api/engine/status goes live."""

    def test_live_engine_reported_when_attached(self):
        from weather_copy_bot.api.app import create_app
        from weather_copy_bot.config import Settings
        from weather_copy_bot.engine import CopyEngine

        application = create_app()
        engine = CopyEngine(
            Settings(dry_run=True, target_wallets=["0xaaa", "0xbbb"]),
            client=MagicMock(),
        )
        engine.stats["last_heartbeat"] = None
        application.state.engine = engine
        client = TestClient(application, raise_server_exceptions=False)

        data = client.get("/api/engine/status").json()
        assert data["source"] == "live"
        assert data["mode"] == "paper"
        assert data["dry_run"] is True
        assert data["targets_active"] == 2
        assert data["health"] == "starting"
        assert data["stats"]["signals_detected"] == 0

    def test_demo_payload_returned_without_engine(self):
        from weather_copy_bot.api.app import create_app

        application = create_app()
        client = TestClient(application, raise_server_exceptions=False)
        data = client.get("/api/engine/status").json()
        assert data.get("source") != "live"
        assert isinstance(data, dict)


class TestEngineLifespan:
    """ENGINE_ENABLED=true starts the copy loop inside the API process."""

    def test_lifespan_starts_and_stops_engine_when_enabled(self, monkeypatch):
        # Fetch the MODULE from sys.modules: the api package re-exports `app`
        # (the FastAPI instance) under the same name, which shadows normal
        # attribute-based imports.
        import sys

        app_module = sys.modules["weather_copy_bot.api.app"]
        monkeypatch.setenv("ENGINE_ENABLED", "true")
        started: list[object] = []

        class StubEngine:
            def __init__(
                self, settings, target_provider=None, quorum=None, monitor=None
            ):
                self.settings = settings
                self.target_provider = target_provider
                self.quorum = quorum
                self.monitor = monitor
                self.mode = "paper"
                self.stats = {}
                self._running = False

            async def run(self):
                self._running = True
                started.append(self)
                while self._running:
                    await asyncio.sleep(0.01)

            def stop(self):
                self._running = False

        monkeypatch.setattr(app_module, "CopyEngine", StubEngine)
        application = app_module.create_app()
        with TestClient(application) as client:
            assert client.get("/api/health").status_code == 200
            assert len(started) == 1
            assert application.state.engine is started[0]
            assert application.state.engine._running is True
        # Shutdown joined the loop: stop() flipped the flag.
        assert application.state.engine._running is False

    def test_lifespan_starts_discovery_alongside_engine(self, monkeypatch):
        import sys

        from weather_copy_bot.engine import MergedTargetProvider, WalletDiscovery

        app_module = sys.modules["weather_copy_bot.api.app"]
        monkeypatch.setenv("ENGINE_ENABLED", "true")
        monkeypatch.setenv("WALLET_DISCOVERY_ENABLED", "true")
        started: list[object] = []

        class StubEngine:
            def __init__(
                self, settings, target_provider=None, quorum=None, monitor=None
            ):
                self.settings = settings
                self.target_provider = target_provider
                self.quorum = quorum
                self.monitor = monitor
                self.mode = "paper"
                self.stats = {}
                self._running = False

            async def run(self):
                self._running = True
                started.append(self)
                while self._running:
                    await asyncio.sleep(0.01)

            def stop(self):
                self._running = False

        monkeypatch.setattr(app_module, "CopyEngine", StubEngine)
        application = app_module.create_app()
        with TestClient(application) as client:
            assert client.get("/api/health").status_code == 200
            assert len(started) == 1
            discovery = getattr(application.state, "discovery", None)
            assert isinstance(discovery, WalletDiscovery)
            provider = started[0].target_provider
            assert isinstance(provider, MergedTargetProvider)
            assert provider.discovery is discovery
            # The engine consumes static + discovered targets through one seam.
            assert started[0].target_provider.static == []
        assert application.state.discovery._running is False

    def test_discovery_status_disabled_by_default(self):
        from weather_copy_bot.api.app import create_app

        application = create_app()
        client = TestClient(application)
        assert client.get("/api/discovery/status").json() == {"enabled": False}

    def test_lifespan_skips_engine_by_default(self):
        from weather_copy_bot.api.app import create_app

        application = create_app()
        with TestClient(application) as client:
            assert client.get("/api/health").status_code == 200
            assert getattr(application.state, "engine", None) is None
