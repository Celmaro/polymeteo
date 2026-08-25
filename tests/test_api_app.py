"""Tests for FastAPI application endpoints."""

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
