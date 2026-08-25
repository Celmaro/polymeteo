"""Webhook dispatcher for Discord/Slack notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class WebhookConfig:
    """Webhook configuration."""

    discord_url: str | None = None
    slack_url: str | None = None
    enabled: bool = True


@dataclass
class NotificationPayload:
    """Standardized notification payload."""

    title: str
    description: str
    color: int = 0x00FF00  # Green
    fields: list[dict] | None = None
    footer: str | None = None
    url: str | None = None
    thumbnail: str | None = None


class WebhookDispatcher:
    """
    Dispatch notifications to multiple channels (Discord, Slack).

    Example:
        dispatcher = WebhookDispatcher(WebhookConfig(
            discord_url="https://discord.com/api/webhooks/...",
            slack_url="https://hooks.slack.com/...",
        ))

        await dispatcher.send(
            NotificationPayload(
                title="Trade Executed",
                description="Bought 50 shares of weather-nyc",
                color=0x00FF00,
            )
        )
    """

    def __init__(self, config: WebhookConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> WebhookDispatcher:
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    async def send(
        self,
        payload: NotificationPayload,
        channels: list[str] | None = None,
    ) -> dict[str, bool]:
        """
        Send notification to configured channels.

        Args:
            payload: The notification content
            channels: List of channels ("discord", "slack") or None for all

        Returns:
            Dict mapping channel name to success status
        """
        if not self.config.enabled:
            return {}

        channels = channels or []
        results = {}

        if (not channels or "discord" in channels) and self.config.discord_url:
            results["discord"] = await self._send_discord(payload)

        if (not channels or "slack" in channels) and self.config.slack_url:
            results["slack"] = await self._send_slack(payload)

        return results

    async def _send_discord(self, payload: NotificationPayload) -> bool:
        """Send to Discord webhook."""
        if not self.config.discord_url or not self._client:
            return False

        embed = {
            "title": payload.title,
            "description": payload.description,
            "color": payload.color,
        }

        if payload.fields:
            embed["fields"] = [
                {"name": f["name"], "value": f["value"], "inline": f.get("inline", False)}
                for f in payload.fields
            ]

        if payload.footer:
            embed["footer"] = {"text": payload.footer}

        if payload.url:
            embed["url"] = payload.url

        if payload.thumbnail:
            embed["thumbnail"] = {"url": payload.thumbnail}

        data = {"embeds": [embed]}

        try:
            resp = await self._client.post(self.config.discord_url, json=data)
            if resp.status_code == 204 or resp.status_code == 200:
                logger.info(f"Discord notification sent: {payload.title}")
                return True
            logger.warning(f"Discord error: {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    async def _send_slack(self, payload: NotificationPayload) -> bool:
        """Send to Slack webhook."""
        if not self.config.slack_url or not self._client:
            return False

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": payload.title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": payload.description}},
        ]

        if payload.fields:
            fields_text = "\n".join(f"*{f['name']}*: {f['value']}" for f in payload.fields)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": fields_text}})

        if payload.footer:
            blocks.append(
                {"type": "context", "elements": [{"type": "mrkdwn", "text": payload.footer}]}
            )

        data = {"blocks": blocks}

        try:
            resp = await self._client.post(self.config.slack_url, json=data)
            if resp.status_code == 200:
                logger.info(f"Slack notification sent: {payload.title}")
                return True
            logger.warning(f"Slack error: {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    # Convenience methods

    async def notify_trade(
        self,
        side: str,
        market: str,
        size_usd: float,
        pnl_usd: float,
        fill_id: str,
    ) -> dict[str, bool]:
        """Send trade notification."""
        color = 0x00FF00 if pnl_usd >= 0 else 0xFF0000
        emoji = "✅" if pnl_usd >= 0 else "❌"

        payload = NotificationPayload(
            title=f"{emoji} Trade Executed: {side}",
            description=f"**Market:** {market}\n**Fill ID:** `{fill_id[:16]}...`",
            color=color,
            fields=[
                {"name": "Size", "value": f"${size_usd:.2f}"},
                {"name": "P&L", "value": f"${pnl_usd:.2f}"},
            ],
            footer=f"Polymeteo | {fill_id}",
        )
        return await self.send(payload)

    async def notify_signal(
        self,
        signal_id: str,
        market: str,
        wallet: str,
        side: str,
        should_copy: bool,
        reason: str,
    ) -> dict[str, bool]:
        """Send signal detection notification."""
        action = "📋 COPY" if should_copy else "⏭️ SKIP"

        payload = NotificationPayload(
            title=f"{action} Signal Detected",
            description=f"**Market:** {market}",
            color=0x3498DB,
            fields=[
                {"name": "Wallet", "value": f"`{wallet[:12]}...`"},
                {"name": "Side", "value": side},
                {"name": "Decision", "value": reason},
            ],
            footer=f"Signal: {signal_id[:16]}...",
        )
        return await self.send(payload)

    async def notify_error(
        self,
        error_type: str,
        message: str,
        context: str | None = None,
    ) -> dict[str, bool]:
        """Send error notification."""
        payload = NotificationPayload(
            title="⚠️ Error Alert",
            description=f"**{error_type}**\n{message}",
            color=0xFF0000,
            fields=[{"name": "Context", "value": context or "N/A"}] if context else None,
            footer="Polymeteo Alert",
        )
        return await self.send(payload)

    async def notify_daily_report(
        self,
        total_pnl: float,
        trade_count: int,
        win_rate: float,
        balance: float,
    ) -> dict[str, bool]:
        """Send daily P&L report."""
        payload = NotificationPayload(
            title="📊 Daily Report",
            description="Polymeteo Performance Summary",
            color=0x00FF00 if total_pnl >= 0 else 0xFF0000,
            fields=[
                {"name": "Total P&L", "value": f"${total_pnl:.2f}"},
                {"name": "Balance", "value": f"${balance:.2f}"},
                {"name": "Trades", "value": str(trade_count)},
                {"name": "Win Rate", "value": f"{win_rate:.1f}%"},
            ],
            footer="Daily Report",
        )
        return await self.send(payload)
