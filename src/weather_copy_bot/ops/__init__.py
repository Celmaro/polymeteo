"""Operations and notification components."""

from weather_copy_bot.ops.telegram import (
    TelegramBot,
    TelegramConfig,
    BotStatus,
    send_telegram_message,
)

from weather_copy_bot.ops.webhooks import (
    WebhookDispatcher,
    WebhookConfig,
    NotificationPayload,
)

from weather_copy_bot.ops.monitoring import (
    MonitoringService,
    TradingDashboard,
    MetricType,
    MetricSnapshot,
    create_monitoring_service,
)

from weather_copy_bot.ops.reporting import (
    ReportGenerator,
    ReportFormatter,
    DailyReport,
    WeeklyReport,
    MonthlyReport,
    TradeSummary,
    ReportPeriod,
)

from weather_copy_bot.ops.failover import (
    FailoverManager,
    ServiceType,
    EndpointConfig,
    HealthStatus,
    create_default_failover_manager,
)

__all__ = [
    # Telegram
    "TelegramBot",
    "TelegramConfig",
    "BotStatus",
    "send_telegram_message",
    # Webhooks
    "WebhookDispatcher",
    "WebhookConfig",
    "NotificationPayload",
    # Monitoring
    "MonitoringService",
    "TradingDashboard",
    "MetricType",
    "MetricSnapshot",
    "create_monitoring_service",
    # Reporting
    "ReportGenerator",
    "ReportFormatter",
    "DailyReport",
    "WeeklyReport",
    "MonthlyReport",
    "TradeSummary",
    "ReportPeriod",
    # Failover
    "FailoverManager",
    "ServiceType",
    "EndpointConfig",
    "HealthStatus",
    "create_default_failover_manager",
]
