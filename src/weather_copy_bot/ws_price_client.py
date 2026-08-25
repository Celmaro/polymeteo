"""WebSocket client for Polymarket price feeds."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConnectionState(Enum):
    """WebSocket connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class PriceUpdate:
    """Price update from WebSocket."""

    market_id: str
    yes_price: float
    no_price: float
    volume: float
    timestamp: float


@dataclass
class WebSocketConfig:
    """Configuration for WebSocket client."""

    url: str = "wss://ws-subscriptions-clob.polymarket.com"
    ping_interval: float = 15.0
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 5
    subscription_timeout: float = 10.0


class PriceFeedCallback:
    """Callback interface for price updates."""

    async def on_price_update(self, update: PriceUpdate) -> None:
        """Called when price update is received."""

    async def on_connection_state_change(self, state: ConnectionState) -> None:
        """Called when connection state changes."""


class WebSocketPriceClient:
    """WebSocket client for Polymarket price feeds."""

    def __init__(
        self,
        config: WebSocketConfig | None = None,
        callback: PriceFeedCallback | None = None,
    ) -> None:
        self.config = config or WebSocketConfig()
        self.callback = callback
        self._state = ConnectionState.DISCONNECTED
        self._ws: Any = None
        self._reader_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._reconnect_attempts = 0
        self._running = False
        self._subscriptions: set[str] = set()
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    def set_state(self, state: ConnectionState) -> None:
        """Set connection state and notify callback."""
        self._state = state
        if self.callback:
            asyncio.create_task(self.callback.on_connection_state_change(state))  # noqa: RUF006

    async def connect(self) -> None:
        """Connect to WebSocket server."""
        if self._state == ConnectionState.CONNECTED:
            return

        self.set_state(ConnectionState.CONNECTING)
        try:
            import websockets
            self._ws = await websockets.connect(self.config.url)
            self.set_state(ConnectionState.CONNECTED)
            self._reconnect_attempts = 0
            self._running = True
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())
        except Exception as e:
            self.set_state(ConnectionState.DISCONNECTED)
            raise ConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._ping_task:
            self._ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ping_task
        if self._ws:
            await self._ws.close()
            self._ws = None
        self.set_state(ConnectionState.DISCONNECTED)

    async def subscribe(self, market_ids: list[str]) -> None:
        """Subscribe to price updates for markets."""
        self._subscriptions.update(market_ids)
        if self._ws and self._state == ConnectionState.CONNECTED:
            await self._send_subscription(market_ids)

    async def unsubscribe(self, market_ids: list[str]) -> None:
        """Unsubscribe from price updates."""
        self._subscriptions.difference_update(market_ids)
        if self._ws and self._state == ConnectionState.CONNECTED:
            await self._send_unsubscription(market_ids)

    async def _send_subscription(self, market_ids: list[str]) -> None:
        """Send subscription message."""
        import json
        message = {
            "type": "subscribe",
            "channel": "prices",
            "market_ids": market_ids,
        }
        await self._ws.send(json.dumps(message))

    async def _send_unsubscription(self, market_ids: list[str]) -> None:
        """Send unsubscription message."""
        import json
        message = {
            "type": "unsubscribe",
            "channel": "prices",
            "market_ids": market_ids,
        }
        await self._ws.send(json.dumps(message))

    async def _reader_loop(self) -> None:
        """Read messages from WebSocket."""
        try:
            async for message in self._ws:
                import json
                data = json.loads(message)
                await self._message_queue.put(data)
                asyncio.create_task(self._process_message(data))  # noqa: RUF006
        except asyncio.CancelledError:
            pass
        except Exception:
            if self._running:
                await self._handle_disconnect()

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process incoming message."""
        if data.get("type") == "price_update" and self.callback:
            update = PriceUpdate(
                market_id=data.get("market_id", ""),
                yes_price=float(data.get("yes_price", 0)),
                no_price=float(data.get("no_price", 0)),
                volume=float(data.get("volume", 0)),
                timestamp=float(data.get("timestamp", 0)),
            )
            await self.callback.on_price_update(update)

    async def _ping_loop(self) -> None:
        """Send periodic pings."""
        import json
        while self._running and self._ws:
            await asyncio.sleep(self.config.ping_interval)
            if self._ws and self._running:
                try:
                    await self._ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    break

    async def _handle_disconnect(self) -> None:
        """Handle disconnection and reconnect."""
        if self._reconnect_attempts >= self.config.max_reconnect_attempts:
            self.set_state(ConnectionState.DISCONNECTED)
            return

        self.set_state(ConnectionState.RECONNECTING)
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay * (2 ** (self._reconnect_attempts - 1))
        await asyncio.sleep(delay)
        try:
            await self.connect()
            if self._subscriptions:
                await self.subscribe(list(self._subscriptions))
        except Exception:
            await self._handle_disconnect()

    async def get_message(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Get next message from queue."""
        try:
            return await asyncio.wait_for(self._message_queue.get(), timeout)
        except asyncio.TimeoutError:
            return None
