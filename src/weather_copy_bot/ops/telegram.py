"""Telegram bot for remote bot control and notifications."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    bot_token: str
    allowed_users: list[int] = []  # Telegram user IDs
    admin_user_ids: list[int] = []  # Users with admin privileges
    commands: list[str] = ["start", "stop", "status", "pnl", "positions", "wallets", "help"]


class BotStatus(BaseModel):
    """Current bot status for reporting."""

    running: bool
    mode: str  # "paper", "backtest", "live"
    balance_usd: float
    daily_pnl: float
    open_positions: int
    watched_wallets: int
    latency_avg_ms: float
    last_signal_at: str | None = None


class TelegramBot:
    """
    Telegram bot for remote control and notifications.

    Commands:
        /start - Start the trading bot
        /stop - Stop the trading bot
        /status - Show current status
        /pnl - Show P&L summary
        /positions - List open positions
        /wallets - List watched wallets
        /help - Show help message

    Example:
        bot = TelegramBot(config=TelegramConfig(
            bot_token="123456:ABC-DEF...",
            admin_user_ids=[12345678],
        ))

        await bot.send_notification("Bot started", alert=True)
    """

    def __init__(
        self,
        config: TelegramConfig,
        status_provider: Callable[[], Awaitable[BotStatus]] | None = None,
        start_handler: Callable[[], Awaitable[None]] | None = None,
        stop_handler: Callable[[], Awaitable[None]] | None = None,
    ):
        self.config = config
        self._status_provider = status_provider
        self._start_handler = start_handler
        self._stop_handler = stop_handler
        self._running = False

    async def start(self) -> None:
        """Start the Telegram bot polling."""
        logger.info("Telegram bot initialized")
        self._running = True

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        logger.info("Telegram bot stopped")

    async def send_message(self, text: str, chat_id: int | None = None) -> bool:
        """Send a message to a chat."""
        # In production, this would use python-telegram-bot or httpx
        logger.info(f"Telegram message: {text[:100]}")
        return True

    async def send_notification(
        self,
        message: str,
        alert: bool = False,
        chat_id: int | None = None,
    ) -> bool:
        """
        Send a notification (with optional alert formatting).

        Args:
            message: The notification text
            alert: Add alert formatting (🔔, ⚠️, ❌, etc.)
            chat_id: Optional specific chat ID
        """
        prefix = "🔔 " if alert else ""
        formatted = f"{prefix}{message}"
        return await self.send_message(formatted, chat_id)

    async def send_trade_notification(
        self,
        side: str,
        market: str,
        size_usd: float,
        pnl_usd: float,
        fill_id: str,
    ) -> bool:
        """Send a trade execution notification."""
        emoji = "🟢" if pnl_usd >= 0 else "🔴"
        message = f"""
{emoji} Trade Executed

Market: {market}
Side: {side}
Size: ${size_usd:.2f}
P&L: ${pnl_usd:.2f}
Fill ID: {fill_id[:16]}...
"""
        return await self.send_notification(message.strip(), alert=True)

    async def send_error_alert(
        self,
        error_type: str,
        error_message: str,
        context: str | None = None,
    ) -> bool:
        """Send an error alert."""
        message = f"""
⚠️ Error Alert

Type: {error_type}
Message: {error_message}
{f"Context: {context}" if context else ""}
"""
        return await self.send_notification(message.strip(), alert=True)

    def format_status(self, status: BotStatus) -> str:
        """Format status as a Telegram message."""
        running_emoji = "🟢 Running" if status.running else "🔴 Stopped"

        message = f"""
📊 Polymeteo Status
━━━━━━━━━━━━━━━━━━
Mode: {status.mode}
Status: {running_emoji}
Balance: ${status.balance_usd:.2f}
Daily P&L: ${status.daily_pnl:.2f}
Open Positions: {status.open_positions}
Watched Wallets: {status.watched_wallets}
Avg Latency: {status.latency_avg_ms:.0f}ms
Last Signal: {status.last_signal_at or "None"}
"""
        return message.strip()

    async def handle_command(
        self,
        command: str,
        user_id: int,
        args: list[str] | None = None,
    ) -> str | None:
        """
        Handle a Telegram command.

        Returns response message or None.
        """
        args = args or []

        # Check authorization
        is_admin = user_id in self.config.admin_user_ids
        is_allowed = user_id in self.config.allowed_users or is_admin

        if not is_allowed:
            return "⛔ You are not authorized to use this bot."

        # Route commands
        if command == "/start":
            if self._start_handler and is_admin:
                await self._start_handler()
            return "✅ Polymeteo started!"

        if command == "/stop":
            if self._stop_handler and is_admin:
                await self._stop_handler()
            return "⏹️ Polymeteo stopped."

        if command == "/status":
            if self._status_provider:
                status = await self._status_provider()
                return self.format_status(status)
            return "Status provider not configured."

        if command == "/pnl":
            if self._status_provider:
                status = await self._status_provider()
                return f"""
💰 P&L Summary
━━━━━━━━━━━━━━
Balance: ${status.balance_usd:.2f}
Daily: ${status.daily_pnl:.2f}
"""
            return "Status provider not configured."

        if command == "/help":
            return """
📚 Commands
━━━━━━━━━━━
/start - Start bot (admin)
/stop - Stop bot (admin)
/status - Show status
/pnl - Show P&L
/positions - List positions
/wallets - Watched wallets
/help - This help
"""

        return "Unknown command. Send /help for list."


# Simple inline bot without full Telegram library dependency
async def send_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
) -> bool:
    """
    Send a simple Telegram message via API.

    Requires:
        - bot_token: From @BotFather
        - chat_id: Telegram chat ID
    """
    import httpx

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False
