"""Polymeteo unified exception hierarchy.

This module provides a typed exception hierarchy for all Polymeteo errors,
organized by domain: API, Network, Database, and Trading errors.

Usage:
    from weather_copy_bot.exceptions import GammaAPIError, RiskViolationError

    try:
        await fetch_markets()
    except GammaAPIError as e:
        logger.error(f"Gamma API failed: {e.endpoint} - {e.status_code}")
        raise
    except RiskViolationError as e:
        logger.critical(f"Risk limit exceeded: {e.limit_type}")
        await emergency_shutdown()
"""

from __future__ import annotations


class PolymeteoError(Exception):
    """Base exception for all Polymeteo errors.

    All custom exceptions in the codebase should inherit from this class
    to enable centralized error handling and consistent error reporting.
    """

    code: str = "POLYMETEO_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class APIError(PolymeteoError):
    """Base class for API-related errors.

    Attributes:
        endpoint: The API endpoint that failed (e.g., "/markets").
        status_code: HTTP status code of the failed request.
    """

    code = "API_ERROR"

    def __init__(
        self,
        message: str,
        endpoint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code

    def __repr__(self) -> str:
        parts = [f"message={self.message!r}"]
        if self.endpoint:
            parts.append(f"endpoint={self.endpoint!r}")
        if self.status_code:
            parts.append(f"status_code={self.status_code}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class GammaAPIError(APIError):
    """Error communicating with the Gamma API (Polymarket primary API).

    Raised when:
    - Market data fetch fails
    - Order book retrieval fails
    - Market creation fails
    """

    code = "GAMMA_API_ERROR"


class DataAPIError(APIError):
    """Error communicating with the Polymarket Data API.

    Raised when:
    - User activity lookup fails
    - Historical trade data fetch fails
    - Position query fails
    """

    code = "DATA_API_ERROR"


class CLOBError(APIError):
    """Error from the Central Limit Order Book (CLOB) API.

    Raised when:
    - Order submission fails
    - Order cancellation fails
    - Order modification fails
    """

    code = "CLOB_ERROR"


class NetworkError(PolymeteoError):
    """Base class for network-related errors.

    Attributes:
        host: The hostname that failed.
        port: The port number that was being connected to.
    """

    code = "NETWORK_ERROR"

    def __init__(
        self,
        message: str,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        super().__init__(message)
        self.host = host
        self.port = port


class ConnectionError(NetworkError):
    """Failed to establish a network connection.

    Raised when:
    - TCP connection times out
    - DNS resolution fails
    - Connection refused
    """

    code = "CONNECTION_ERROR"

    def __init__(
        self,
        message: str,
        host: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(message, host=host)
        self.timeout_seconds = timeout_seconds


class DatabaseError(PolymeteoError):
    """Base class for database-related errors.

    Attributes:
        operation: The SQL operation that failed (e.g., "SELECT", "INSERT").
        details: Additional details about the failure.
    """

    code = "DATABASE_ERROR"

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.details = details


class TradingError(PolymeteoError):
    """Base class for errors during order execution.

    Attributes:
        order_id: The ID of the order that failed.
    """

    code = "TRADING_ERROR"

    def __init__(
        self,
        message: str,
        order_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.order_id = order_id


class RiskViolationError(TradingError):
    """Risk limits were exceeded during trading.

    Raised when:
    - Position size exceeds maximum
    - Leverage exceeds limit
    - Loss limit exceeded
    - Drawdown limit exceeded
    """

    code = "RISK_VIOLATION"

    def __init__(
        self,
        message: str,
        limit_type: str | None = None,
        limit_value: float | None = None,
        actual_value: float | None = None,
    ) -> None:
        super().__init__(message)
        self.limit_type = limit_type
        self.limit_value = limit_value
        self.actual_value = actual_value


class ValidationError(PolymeteoError):
    """Input validation failed.

    Raised when:
    - Price is out of valid range
    - Size is negative or too small
    - Invalid market slug format
    - Missing required parameters
    """

    code = "VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: object | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.value = value
