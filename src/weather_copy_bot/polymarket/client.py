"""Polymarket data + order adapters with a safe demo fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np

from weather_copy_bot.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PolymarketClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._demo_cursor = 0
        self._rng = np.random.default_rng(7)

    def default_demo_wallets(self) -> list[str]:
        return [
            "0x7a21c4e8b9f0d3a6e1c58294f0ab73d6e8c91f22",
            "0x3bf9e1a047d6c28b5e90a1d4c7f83e6a2b19d045",
            "0x91d0aa56c2e84f17b3c9e08d5a6f12b4e70c83aa",
        ]

    async def fetch_weather_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch active markets; falls back to curated weather stubs offline."""
        url = f"{self.settings.gamma_host}/markets"
        params = {"active": "true", "closed": "false", "limit": limit}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                markets = resp.json()
                weather = [
                    m
                    for m in markets
                    if any(
                        k
                        in (m.get("question", "") + " " + m.get("slug", "")).lower()
                        for k in self.settings.weather_keywords
                    )
                ]
                if weather:
                    return weather
        except Exception as exc:
            logger.warning("gamma markets unavailable, using stubs: %s", exc)
        return self._stub_markets()

    async def fetch_target_activity(
        self,
        wallets: list[str],
        market_filter: str = "weather",
    ) -> list[dict[str, Any]]:
        """Pull recent target trades. Uses demo stream when keys/network are unavailable."""
        if not wallets:
            wallets = self.default_demo_wallets()

        # Prefer data API when reachable; otherwise emit demo signals for paper/dev.
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                events: list[dict[str, Any]] = []
                for wallet in wallets:
                    url = f"{self.settings.data_api_host}/activity"
                    resp = await client.get(url, params={"user": wallet, "limit": 20})
                    if resp.status_code != 200:
                        continue
                    for item in resp.json():
                        title = str(item.get("title", item.get("slug", "")))
                        if market_filter and market_filter.lower() not in title.lower() and not any(
                            k in title.lower() for k in self.settings.strict_weather_keywords
                        ):
                            continue
                        events.append(
                            {
                                "id": str(item.get("id", item.get("transactionHash", ""))),
                                "wallet": wallet,
                                "timestamp": item.get("timestamp")
                                or datetime.now(timezone.utc).isoformat(),
                                "market_slug": item.get("slug") or item.get("eventSlug") or "weather",
                                "market_title": title,
                                "city": self._infer_city(title),
                                "outcome": item.get("outcome", "Yes"),
                                "side": "BUY" if str(item.get("side", "BUY")).upper() == "BUY" else "SELL",
                                "price": float(item.get("price", 0.5)),
                                "size_usd": float(item.get("usdcSize", item.get("size", 50))),
                                "token_id": item.get("asset"),
                                "demo": False,
                            }
                        )
                if events:
                    return events
        except Exception as exc:
            logger.debug("activity API unavailable (%s); using demo stream", exc)

        return self._next_demo_events(wallets)

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size_usd: float,
    ) -> dict[str, Any]:
        if self.settings.dry_run or not self.settings.polymarket_private_key:
            logger.info(
                "DRY_RUN order side=%s token=%s price=%.3f size=%.2f",
                side,
                token_id[:12] if token_id else "none",
                price,
                size_usd,
            )
            return {
                "status": "dry_run",
                "side": side,
                "price": price,
                "size_usd": size_usd,
                "token_id": token_id,
            }

        # Live CLOB submission is intentionally gated. Wire py-clob-client here
        # with your credentials before setting DRY_RUN=false.
        raise RuntimeError(
            "Live order routing is locked until CLOB credentials and "
            "py-clob-client signing are configured. Keep DRY_RUN=true for paper."
        )

    def _next_demo_events(self, wallets: list[str]) -> list[dict[str, Any]]:
        # Emit at most one event every few polls to simulate sparse target flow
        self._demo_cursor += 1
        if self._demo_cursor % 3 != 0:
            return []

        cities = ["New York", "London", "Tokyo", "Chicago", "Seattle", "Miami"]
        city = cities[self._demo_cursor % len(cities)]
        wallet = wallets[self._demo_cursor % len(wallets)]
        now = datetime.now(timezone.utc) - timedelta(milliseconds=int(self._rng.integers(220, 640)))
        slug = f"highest-temperature-in-{city.lower().replace(' ', '-')}"
        return [
            {
                "id": f"demo-{self._demo_cursor}",
                "wallet": wallet,
                "timestamp": now.isoformat(),
                "market_slug": slug,
                "market_title": f"Highest temperature in {city}?",
                "city": city,
                "outcome": str(self._rng.choice(["Yes", "No", "70-71°F", "Above 72°F"])),
                "side": "BUY",
                "price": float(round(self._rng.uniform(0.22, 0.78), 3)),
                "size_usd": float(round(self._rng.uniform(40, 180), 2)),
                "token_id": f"demo-token-{self._demo_cursor}",
                "demo": True,
                "latency_ms": int(self._rng.integers(280, 620)),
            }
        ]

    @staticmethod
    def _infer_city(title: str) -> str:
        for city in (
            "New York",
            "London",
            "Tokyo",
            "Chicago",
            "Seattle",
            "Miami",
            "Paris",
            "Sydney",
        ):
            if city.lower() in title.lower():
                return city
        return "Global"

    @staticmethod
    def _stub_markets() -> list[dict[str, Any]]:
        cities = ["New York", "London", "Tokyo", "Chicago", "Seattle", "Miami"]
        return [
            {
                "slug": f"highest-temperature-in-{c.lower().replace(' ', '-')}",
                "question": f"Highest temperature in {c}?",
                "city": c,
                "active": True,
            }
            for c in cities
        ]
