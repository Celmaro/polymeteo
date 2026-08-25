"""Regression tests for CLOBWebSocket message-loop error handling."""

from __future__ import annotations

import logging

import pytest

from weather_copy_bot.polymarket.ws_client import CLOBWebSocket

pytestmark = pytest.mark.asyncio


class FakeWS:
    """Minimal async-iterable stand-in for a WebSocket connection."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self.open = True
        self.sent: list[str] = []

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.open = False


async def test_run_logs_handler_errors_instead_of_silently_dropping(caplog):
    client = CLOBWebSocket()
    client._running = True
    client._ws = FakeWS(['{"type": "trade", "market": "m1"}'])

    async def exploding_handler(raw: str) -> None:
        client._running = False
        raise RuntimeError("handler exploded")

    client._handle_message = exploding_handler

    with caplog.at_level(logging.ERROR, logger="weather_copy_bot.polymarket.ws_client"):
        await client.run()

    assert "handler exploded" in caplog.text
