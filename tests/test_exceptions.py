"""Tests for Polymeteo exception hierarchy."""

from __future__ import annotations

import pytest

from weather_copy_bot.exceptions import (
    APIError,
    CLOBError,
    ConnectionError,
    DataAPIError,
    DatabaseError,
    GammaAPIError,
    NetworkError,
    PolymeteoError,
    RiskViolationError,
    TradingError,
    ValidationError,
)


class TestPolymeteoErrorHierarchy:
    """Test that all exceptions inherit from PolymeteoError."""

    def test_polymeteo_error_is_base(self):
        """PolymeteoError should be the base exception."""
        exc = PolymeteoError("test message")
        assert isinstance(exc, Exception)
        assert exc.code == "POLYMETEO_ERROR"
        assert str(exc) == "test message"

    def test_api_error_inherits_from_polymeteo_error(self):
        """APIError should inherit from PolymeteoError."""
        exc = APIError("API failed", endpoint="/test", status_code=500)
        assert isinstance(exc, PolymeteoError)
        assert isinstance(exc, Exception)
        assert exc.code == "API_ERROR"
        assert exc.endpoint == "/test"
        assert exc.status_code == 500

    def test_gamma_api_error_inherits_from_api_error(self):
        """GammaAPIError should inherit from APIError."""
        exc = GammaAPIError(
            "Gamma unavailable",
            endpoint="/markets",
            status_code=503,
        )
        assert isinstance(exc, APIError)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "GAMMA_API_ERROR"

    def test_data_api_error_inherits_from_api_error(self):
        """DataAPIError should inherit from APIError."""
        exc = DataAPIError(
            "Data API timeout",
            endpoint="/activity",
            status_code=504,
        )
        assert isinstance(exc, APIError)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "DATA_API_ERROR"

    def test_clob_error_inherits_from_api_error(self):
        """CLOBError should inherit from APIError."""
        exc = CLOBError("Order rejected", endpoint="/orders", status_code=400)
        assert isinstance(exc, APIError)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "CLOB_ERROR"

    def test_network_error_inherits_from_polymeteo_error(self):
        """NetworkError should inherit from PolymeteoError."""
        exc = NetworkError("Connection refused", host="gamma.polymarket.com", port=443)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "NETWORK_ERROR"
        assert exc.host == "gamma.polymarket.com"
        assert exc.port == 443

    def test_connection_error_inherits_from_network_error(self):
        """ConnectionError should inherit from NetworkError."""
        exc = ConnectionError("Timeout", host="data.polymarket.com", timeout_seconds=30.0)
        assert isinstance(exc, NetworkError)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "CONNECTION_ERROR"
        assert exc.timeout_seconds == 30.0

    def test_database_error_inherits_from_polymeteo_error(self):
        """DatabaseError should inherit from PolymeteoError."""
        exc = DatabaseError("SQLite corruption", operation="SELECT", details="disk full")
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "DATABASE_ERROR"
        assert exc.operation == "SELECT"

    def test_trading_error_inherits_from_polymeteo_error(self):
        """TradingError should inherit from PolymeteoError."""
        exc = TradingError("Order execution failed", order_id="order-123")
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "TRADING_ERROR"
        assert exc.order_id == "order-123"

    def test_risk_violation_error_inherits_from_trading_error(self):
        """RiskViolationError should inherit from TradingError."""
        exc = RiskViolationError(
            "Max position size exceeded",
            limit_type="max_position",
            limit_value=1000.0,
            actual_value=1500.0,
        )
        assert isinstance(exc, TradingError)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "RISK_VIOLATION"
        assert exc.limit_type == "max_position"
        assert exc.limit_value == 1000.0
        assert exc.actual_value == 1500.0

    def test_validation_error_inherits_from_polymeteo_error(self):
        """ValidationError should inherit from PolymeteoError."""
        exc = ValidationError("Invalid price", field="price", value=-1.0)
        assert isinstance(exc, PolymeteoError)
        assert exc.code == "VALIDATION_ERROR"
        assert exc.field == "price"
        assert exc.value == -1.0


class TestExceptionRaising:
    """Test that exceptions can be raised and caught correctly."""

    def test_can_raise_polymeteo_error(self):
        """Should be able to raise and catch PolymeteoError."""
        with pytest.raises(PolymeteoError):
            raise PolymeteoError("test")

    def test_can_raise_gamma_api_error(self):
        """Should be able to raise and catch GammaAPIError."""
        with pytest.raises(GammaAPIError) as exc_info:
            raise GammaAPIError("Gamma down", endpoint="/markets", status_code=500)
        assert exc_info.value.status_code == 500

    def test_can_raise_network_error(self):
        """Should be able to raise and catch NetworkError."""
        with pytest.raises(NetworkError) as exc_info:
            raise NetworkError("DNS failed", host="example.com")
        assert exc_info.value.host == "example.com"

    def test_can_raise_risk_violation(self):
        """Should be able to raise and catch RiskViolationError."""
        with pytest.raises(RiskViolationError) as exc_info:
            raise RiskViolationError("Over leverage", "max_leverage", 10.0, 15.0)
        assert exc_info.value.actual_value == 15.0


class TestExceptionChaining:
    """Test exception chaining behavior."""

    def test_exception_preserves_original_cause(self):
        """Exception should preserve original cause when chaining."""
        original = ValueError("original error")
        try:
            raise GammaAPIError("wrapped", endpoint="/test", status_code=500) from original
        except GammaAPIError as e:
            assert e.__cause__ == original
