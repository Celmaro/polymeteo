"""Tests for honest Telegram message handling."""

import pytest

from weather_copy_bot.ops.telegram import TelegramBot, TelegramConfig


@pytest.mark.asyncio
async def test_send_message_without_token_returns_false():
    bot = TelegramBot(config=TelegramConfig(bot_token=""))
    assert await bot.send_message("hello") is False


@pytest.mark.asyncio
async def test_send_message_delegates_to_real_transport(monkeypatch):
    posted = {}

    async def fake_send(token, chat_id, text):
        posted.update({"token": token, "chat_id": chat_id, "text": text})
        return True

    monkeypatch.setattr(
        "weather_copy_bot.ops.telegram.send_telegram_message", fake_send
    )
    bot = TelegramBot(config=TelegramConfig(bot_token="tok123"))
    assert await bot.send_message("deploy ok", chat_id=42) is True
    assert posted == {"token": "tok123", "chat_id": 42, "text": "deploy ok"}


@pytest.mark.asyncio
async def test_send_notification_without_token_is_false_not_fake(monkeypatch):
    bot = TelegramBot(config=TelegramConfig(bot_token=""))
    ok = await bot.send_notification("EMERGENCY SHUTDOWN", alert=True)
    assert ok is False
