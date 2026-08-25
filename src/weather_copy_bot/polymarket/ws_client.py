"""WebSocket client for Polymarket CLOB streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import websockets
from websockets.client import WebSocketClientProtocol

from weather_copy_bot.models import Market, Side, TickData

logger = logging.getLogger(__name__)

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"
CLOB_API_URL = "https://clob.polymarket.com"


@dataclass
class Subscription:
    """Market subscription for CLOB stream."""

    market_slug: str
    enabled: bool = True


@dataclass
class CLOBMessage:
    """Parsed CLOB WebSocket message."""

    type: str
    data: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderBookUpdate:
    """Order book level update."""

    market_slug: str
    price: float
    size: float
    side: Side
    order_id: str
    timestamp: datetime


@dataclass
class TradeUpdate:
    """Trade/fill update from CLOB."""

    market_slug: str
    price: float
    size: float
    side: Side
    trade_id: str
    filler: str
    timestamp: datetime


class CLOBWebSocket:
    """
    WebSocket client for Polymarket CLOB.

    Streams real-time order book updates and trades without REST polling.

    Example:
        async def on_tick(tick: TickData):
            await signal_detector.process(tick)

        async with CLOBWebSocket(on_tick=on_tick) as ws:
            await ws.subscribe("weather-nyc-rain-2024")
            await asyncio.Future()  # Run forever
    """

    def __init__(
        self,
        ws_url: str = CLOB_WS_URL,
        on_order_book: Callable[[OrderBookUpdate], Awaitable[None]] | None = None,
        on_trade: Callable[[TradeUpdate], Awaitable[None]] | None = None,
        on_tick: Callable[[TickData], Awaitable[None]] | None = None,
        on_error: Callable[[Exception], Awaitable[None]] | None = None,
    ):
        self.ws_url = ws_url
        self._ws: WebSocketClientProtocol | None = None
        self._subscriptions: dict[str, Subscription] = {}
        self._running = False

        # Callbacks
        self._on_order_book = on_order_book
        self._on_trade = on_trade
        self._on_tick = on_tick
        self._on_error = on_error

        # Order book state
        self._order_books: dict[str, dict[str, list[tuple[float, float]]]] = {}
        self._last_prices: dict[str, float] = {}

    async def __aenter__(self) -> CLOBWebSocket:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to CLOB WebSocket."""
        if self._ws and self._ws.open:
            return

        logger.info(f"Connecting to {self.ws_url}")
        self._ws = await websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
        )
        self._running = True
        logger.info("Connected to CLOB WebSocket")

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected from CLOB WebSocket")

    async def subscribe(self, market_slug: str) -> None:
        """
        Subscribe to a market's order book and trades.

        Args:
            market_slug: e.g., "weather-nyc-rain-2024"
        """
        if market_slug in self._subscriptions:
            logger.debug(f"Already subscribed to {market_slug}")
            return

        subscription = Subscription(market_slug=market_slug)
        self._subscriptions[market_slug] = subscription
        self._order_books[market_slug] = {"bids": [], "asks": []}

        # Initialize order book via REST
        await self._fetch_initial_book(market_slug)

        # Send subscription message
        subscribe_msg = {
            "type": "subscribe",
            "channel": "orderbook",
            "market": market_slug,
        }

        if self._ws:
            await self._ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to {market_slug}")

    async def unsubscribe(self, market_slug: str) -> None:
        """Unsubscribe from a market."""
        if market_slug not in self._subscriptions:
            return

        del self._subscriptions[market_slug]
        del self._order_books[market_slug]

        if self._ws:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "unsubscribe",
                        "channel": "orderbook",
                        "market": market_slug,
                    }
                )
            )
            logger.info(f"Unsubscribed from {market_slug}")

    async def _fetch_initial_book(self, market_slug: str) -> None:
        """Fetch initial order book via REST."""
        try:
            url = f"{CLOB_API_URL}/orderbook/{market_slug}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    self._order_books[market_slug] = {
                        "bids": [(float(p), float(s)) for p, s in bids],
                        "asks": [(float(p), float(s)) for p, s in asks],
                    }
                    if bids:
                        self._last_prices[market_slug] = float(bids[0][0])
                    logger.debug(f"Fetched initial book for {market_slug}")
        except Exception as e:
            logger.warning(f"Failed to fetch initial book for {market_slug}: {e}")

    async def _handle_message(self, raw: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "orderbook":
                await self._handle_orderbook(msg)
            elif msg_type == "trade":
                await self._handle_trade(msg)
            elif msg_type == "snapshot":
                await self._handle_snapshot(msg)
            elif msg_type == "error":
                logger.error(f"CLOB error: {msg}")
                if self._on_error:
                    await self._on_error(Exception(msg.get("message", "Unknown error")))

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON: {raw[:100]}")
        except Exception as e:
            logger.exception("Error handling message")
            if self._on_error:
                await self._on_error(e)

    async def _handle_orderbook(self, msg: dict) -> None:
        """Handle order book update."""
        market_slug = msg.get("market", "")
        if market_slug not in self._subscriptions:
            return

        updates = msg.get("changes", [])
        for price_str, size_str, side in updates:
            price = float(price_str)
            size = float(size_str)

            book = self._order_books[market_slug]
            key = "bids" if side == "buy" else "asks"

            # Update order book
            levels = book[key]
            if size == 0:
                # Remove level
                book[key] = [(p, s) for p, s in levels if p != price]
            else:
                # Update level
                found = False
                for i, (p, _s) in enumerate(levels):
                    if p == price:
                        levels[i] = (price, size)
                        found = True
                        break
                if not found:
                    levels.append((price, size))
                    levels.sort(key=lambda x: x[0], reverse=(key == "bids"))

            # Fire callback
            if self._on_order_book:
                update = OrderBookUpdate(
                    market_slug=market_slug,
                    price=price,
                    size=size,
                    side=Side.BUY if side == "buy" else Side.SELL,
                    order_id=msg.get("order_id", ""),
                    timestamp=datetime.now(timezone.utc),
                )
                await self._on_order_book(update)

    async def _handle_trade(self, msg: dict) -> None:
        """Handle trade/fill update."""
        market_slug = msg.get("market", "")
        if market_slug not in self._subscriptions:
            return

        trade = TradeUpdate(
            market_slug=market_slug,
            price=float(msg.get("price", 0)),
            size=float(msg.get("size", 0)),
            side=Side.BUY if msg.get("side") == "buy" else Side.SELL,
            trade_id=msg.get("trade_id", ""),
            filler=msg.get("filler", ""),
            timestamp=datetime.now(timezone.utc),
        )

        self._last_prices[market_slug] = trade.price

        if self._on_trade:
            await self._on_trade(trade)

        # Generate tick for signal detection
        if self._on_tick:
            tick = TickData(
                market_slug=market_slug,
                price=trade.price,
                volume=trade.size,
                timestamp=trade.timestamp,
            )
            await self._on_tick(tick)

    async def _handle_snapshot(self, msg: dict) -> None:
        """Handle order book snapshot."""
        market_slug = msg.get("market", "")
        if market_slug not in self._order_books:
            return

        bids = msg.get("bids", [])
        asks = msg.get("asks", [])

        self._order_books[market_slug] = {
            "bids": [(float(p), float(s)) for p, s in bids],
            "asks": [(float(p), float(s)) for p, s in asks],
        }

        if bids:
            self._last_prices[market_slug] = float(bids[0][0])

    async def run(self) -> None:
        """
        Main event loop - run forever processing messages.

        Call this after subscribing to markets.
        """
        while self._running and self._ws:
            with suppress(websockets.ConnectionClosed):
                async for raw in self._ws:
                    try:
                        await self._handle_message(raw)
                    except Exception:
                        logger.exception("Unhandled error processing WebSocket message")
            if self._running:
                logger.warning("Connection closed, reconnecting...")
                await asyncio.sleep(5)
                await self.connect()
                for slug in self._subscriptions:
                    await self.subscribe(slug)

    def get_best_bid_ask(self, market_slug: str) -> tuple[float | None, float | None]:
        """Get best bid and ask for a market."""
        book = self._order_books.get(market_slug, {"bids": [], "asks": []})
        best_bid = book["bids"][0][0] if book["bids"] else None
        best_ask = book["asks"][0][0] if book["asks"] else None
        return best_bid, best_ask

    def get_mid_price(self, market_slug: str) -> float | None:
        """Get mid price for a market."""
        bid, ask = self.get_best_bid_ask(market_slug)
        if bid and ask:
            return (bid + ask) / 2
        return self._last_prices.get(market_slug)


class CLOBRESTClient:
    """
    REST fallback client for CLOB API.

    Used for initial data fetch and when WebSocket is unavailable.
    """

    def __init__(self, api_url: str = CLOB_API_URL, api_key: str | None = None):
        self.api_url = api_url
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> CLOBRESTClient:
        self._client = httpx.AsyncClient(base_url=self.api_url, timeout=10.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    async def get_orderbook(self, market_slug: str) -> dict:
        """Get order book for a market."""
        resp = await self._client.get(f"/orderbook/{market_slug}")
        resp.raise_for_status()
        return resp.json()

    async def get_markets(self, limit: int = 100) -> list[Market]:
        """Get list of markets."""
        resp = await self._client.get("/markets", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
        return [Market(**m) for m in data.get("markets", [])]

    async def get_trades(self, market_slug: str, limit: int = 100) -> list[TradeUpdate]:
        """Get recent trades for a market."""
        resp = await self._client.get(f"/trades/{market_slug}", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
        return [
            TradeUpdate(
                market_slug=market_slug,
                price=float(t["price"]),
                size=float(t["size"]),
                side=Side.BUY if t["side"] == "buy" else Side.SELL,
                trade_id=t["trade_id"],
                filler=t.get("filler", ""),
                timestamp=datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")),
            )
            for t in data.get("trades", [])
        ]
