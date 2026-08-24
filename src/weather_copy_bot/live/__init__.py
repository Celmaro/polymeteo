"""Live trading components."""

from weather_copy_bot.live.wallet_filter import (
    WeatherWalletFilter,
    MultiWalletFilter,
    WalletFilterConfig,
    FilterStats,
    WEATHER_KEYWORDS,
)

from weather_copy_bot.live.signer import (
    EIP712Signer,
    CLOBExecutor,
    CollateralManager,
    Order,
    SignedOrder,
    OrderResult,
)

from weather_copy_bot.live.risk_engine import (
    RiskEngine,
    RiskLimits,
    RiskCheck,
    Position,
    LiquidityChecker,
)

from weather_copy_bot.live.emergency_shutdown import (
    EmergencyShutdown,
    ShutdownReason,
    SystemState,
    ShutdownGuard,
    create_shutdown_guard,
)

__all__ = [
    # Wallet filter
    "WeatherWalletFilter",
    "MultiWalletFilter",
    "WalletFilterConfig",
    "FilterStats",
    "WEATHER_KEYWORDS",
    # Signer
    "EIP712Signer",
    "CLOBExecutor",
    "CollateralManager",
    "Order",
    "SignedOrder",
    "OrderResult",
    # Risk
    "RiskEngine",
    "RiskLimits",
    "RiskCheck",
    "Position",
    "LiquidityChecker",
    # Emergency Shutdown
    "EmergencyShutdown",
    "ShutdownReason",
    "SystemState",
    "ShutdownGuard",
    "create_shutdown_guard",
]
