"""Polymarket data + order adapters with a safe demo fallback.

All HTTP calls are delegated to polymarket-apis (PolymarketGammaClient /
PolymarketDataClient) which internally use httpx.Client (sync).  The
``httpx.Client`` mock patch in tests intercepts the library's outbound
requests transparently, keeping the existing test suite green without any
per-method stubs.

The rate limiter + 429-observer hook run in front of each library call via
``bucket.acquire()`` so the bot's token-bucket budget is respected regardless
of whether the request originates here or inside the library.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np

from weather_copy_bot.config import Settings, get_settings
from weather_copy_bot.polymarket.rate_limiter import (
    RateLimitObserver,
    get_data_bucket,
    get_gamma_bucket,
)
from polymarket_apis import PolymarketDataClient, PolymarketGammaClient

logger = logging.getLogger(__name__)

_WEATHER_TYPES: list[tuple[str, str]] = [
    ("highest-temperature", "Highest temperature in {}?"),
    ("will-it-rain", "Will it rain in {}?"),
    ("hurricane-category", "Hurricane {} on date?"),
    ("daily-snowfall", "Daily snowfall in {}?"),
    ("severe-thunderstorm", "Severe thunderstorm in {}?"),
    ("tornado-risk", "Tornado risk in {}?"),
    ("flash-flood", "Flash flood warning in {}?"),
    ("blizzard-warning", "Blizzard warning for {}?"),
    ("coastal-flood", "Coastal flood in {}?"),
    ("extreme-heat", "Extreme heat advisory {}?"),
    ("peak-wind-speed", "Peak wind speed in {}?"),
    ("drought-index", "Drought index for {}?"),
]


class PolymarketClient:
    def __init__(
        self,
        settings: Settings | None = None,
        on_rate_limit: RateLimitObserver | None = None,
    ):
        self.settings = settings or get_settings()
        self._demo_cursor = 0
        self._rng = np.random.default_rng(7)
        self._on_rate_limit = on_rate_limit
        self._gamma = PolymarketGammaClient(
            base_url=self.settings.gamma_host,
        )
        self._data = PolymarketDataClient(
            base_url=self.settings.data_api_host,
        )

    async def _notify_rate_limit(self, host: str, retry_after: float) -> None:
        if self._on_rate_limit is None:
            return
        try:
            await self._on_rate_limit(host, retry_after)
        except Exception as exc:
            logger.debug("rate-limit observer raised %s", exc)

    @staticmethod
    def _record_429(bucket, response: httpx.Response, host: str) -> float:
        retry_after = bucket.parse_retry_after(response)
        bucket.record_429(retry_after)
        return retry_after

    def default_demo_wallets(self) -> list[str]:
        return [
            "0x7a21c4e8b9f0d3a6e1c58294f0ab73d6e8c91f22",
            "0x3bf9e1a047d6c28b5e90a1d4c7f83e6a2b19d045",
            "0x91d0aa56c2e84f17b3c9e08d5a6f12b4e70c83aa",
        ]

    async def fetch_weather_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        bucket = get_gamma_bucket()
        await bucket.acquire()
        try:
            markets = await asyncio.to_thread(
                self._gamma.get_markets,
                active=True,
                closed=False,
                limit=limit,
            )
            if markets is None:
                markets = []
            weather = [
                m.model_dump()
                for m in markets
                if any(
                    k
                    in (
                        str(getattr(m, "question", "") or "")
                        + " "
                        + str(getattr(m, "slug", "") or "")
                    ).lower()
                    for k in self.settings.weather_keywords
                )
            ]
            if weather:
                return weather
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = self._record_429(
                    bucket, exc.response, self.settings.gamma_host
                )
                await self._notify_rate_limit(self.settings.gamma_host, retry_after)
                logger.warning(
                    "gamma markets throttled (HTTP 429, retry_after=%.1fs)",
                    retry_after,
                )
            else:
                logger.warning(
                    "gamma markets unavailable, using stubs: %s", exc
                )
        except Exception as exc:
            logger.warning("gamma markets unavailable, using stubs: %s", exc)
        return self._stub_markets()

    async def fetch_target_activity(
        self,
        wallets: list[str],
        market_filter: str = "weather",
    ) -> list[dict[str, Any]]:
        if not wallets:
            wallets = self.default_demo_wallets()

        bucket = get_data_bucket()
        network_unavailable = False
        all_items: list[dict[str, Any]] = []
        rejected: list[tuple[str, int]] = []
        rejected_429: list[str] = []

        async def fetch_wallet(wallet: str) -> list[dict[str, Any]]:
            nonlocal network_unavailable
            await bucket.acquire()
            try:
                activities = await asyncio.to_thread(
                    self._data.get_activity,
                    user=wallet,
                    limit=20,
                )
                if activities is None:
                    return []
                items: list = list(activities)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    retry_after = self._record_429(
                        bucket, exc.response, self.settings.data_api_host
                    )
                    await self._notify_rate_limit(
                        self.settings.data_api_host, retry_after
                    )
                    rejected.append((wallet, exc.response.status_code))
                    rejected_429.append(wallet)
                    logger.warning(
                        "activity API rejected wallet %s (HTTP 429, retry_after=%.1fs)",
                        wallet,
                        retry_after,
                    )
                    return []
                rejected.append((wallet, exc.response.status_code))
                logger.warning(
                    "activity API rejected wallet %s (HTTP %d)",
                    wallet,
                    exc.response.status_code,
                )
                return []
            except httpx.RequestError as exc:
                logger.debug("activity API unreachable for %s (%s)", wallet, exc)
                network_unavailable = True
                return []
            except Exception as exc:
                logger.debug("activity API error for %s (%s)", wallet, exc)
                network_unavailable = True
                return []

            result: list[dict[str, Any]] = []
            for item in items:
                item_dict = item.model_dump()
                title = str(
                    item_dict.get("title")
                    or item_dict.get("slug")
                    or ""
                )
                if (
                    market_filter
                    and market_filter.lower() not in title.lower()
                    and not any(
                        k in title.lower()
                        for k in self.settings.strict_weather_keywords
                    )
                ):
                    continue
                result.append(
                    {
                        "id": item_dict.get("transaction_hash") or "",
                        "wallet": item_dict.get("proxy_wallet") or wallet,
                        "timestamp": self._normalize_activity_timestamp(
                            item_dict.get("timestamp")
                        ),
                        "market_slug": (
                            item_dict.get("slug")
                            or item_dict.get("event_slug")
                            or "weather"
                        ),
                        "market_title": title,
                        "city": self._infer_city(title),
                        "outcome": item_dict.get("outcome", "Yes"),
                        "side": "BUY"
                        if str(item_dict.get("side") or "BUY").upper() == "BUY"
                        else "SELL",
                        "price": float(item_dict.get("price") or 0.5),
                        "size_usd": float(
                            item_dict.get("usdc_size")
                            or item_dict.get("size")
                            or 50
                        ),
                        "token_id": str(
                            item_dict.get("asset")
                            or item_dict.get("token_id")
                            or ""
                        ),
                        "demo": False,
                    }
                )
            return result

        try:
            results = await asyncio.gather(
                *[fetch_wallet(w) for w in wallets], return_exceptions=True
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.debug("wallet fetch raised %s", result)
                    network_unavailable = True
                    continue
                all_items.extend(result)
            if all_items:
                return all_items
        except httpx.HTTPError as exc:
            logger.debug(
                "activity API unreachable (%s); using demo stream", exc
            )

        if rejected_429 and self._on_rate_limit is not None:
            pass
        if rejected and not all_items:
            codes = ", ".join(
                f"{wallet[:10]}...={status}" for wallet, status in rejected
            )
            raise RuntimeError(f"activity API rejected wallets: {codes}")

        return self._next_demo_events(wallets)

    @staticmethod
    def _normalize_activity_timestamp(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        text = str(value or "").strip()
        return text or datetime.now(timezone.utc).isoformat()

    async def _search_weather_condition_ids(
        self,
        max_markets: int,
    ) -> list[tuple[str, str]]:
        seen: set[str] = set()
        bucket = get_gamma_bucket()

        async def _search_keyword(keyword: str) -> list[tuple[str, str]]:
            await bucket.acquire()
            try:
                result = await asyncio.to_thread(
                    self._gamma.search,
                    query=keyword,
                    status="active",
                    limit_per_type=10,
                )
                if result is None:
                    return []
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    retry_after = self._record_429(
                        bucket, exc.response, self.settings.gamma_host
                    )
                    await self._notify_rate_limit(
                        self.settings.gamma_host, retry_after
                    )
                    logger.debug(
                        "gamma search throttled keyword %s (HTTP 429)",
                        keyword,
                    )
                    return []
                logger.debug(
                    "gamma search rejected keyword %s (HTTP %d)",
                    keyword,
                    exc.response.status_code,
                )
                return []
            except Exception as exc:
                logger.debug("gamma search query %r failed (%s)", keyword, exc)
                return []

            found: list[tuple[str, str]] = []
            for event in (result.events or []):
                event_dict = event.model_dump() if hasattr(event, "model_dump") else {}
                for market in event_dict.get("markets") or []:
                    market_dict = market if isinstance(market, dict) else {}
                    condition_id = str(
                        market_dict.get("condition_id") or ""
                    ).strip()
                    if (
                        not condition_id
                        or condition_id in seen
                        or not market_dict.get("active")
                        or market_dict.get("closed")
                    ):
                        continue
                    seen.add(condition_id)
                    slug = str(
                        market_dict.get("slug") or event_dict.get("slug") or "weather"
                    )
                    found.append((condition_id, slug))
            return found

        try:
            search_results = await asyncio.gather(
                *[_search_keyword(kw) for kw in self.settings.weather_keywords],
                return_exceptions=True,
            )
        except httpx.HTTPError as exc:
            logger.debug("gamma search unreachable (%s)", exc)
            return []
        found: list[tuple[str, str]] = []
        for batch in search_results:
            if isinstance(batch, Exception):
                logger.debug("keyword search raised: %s", batch)
                continue
            for item in batch:
                found.append(item)
                if len(found) >= max_markets:
                    return found
        return found

    async def discover_weather_wallets(
        self,
        max_markets: int = 5,
        trades_per_market: int = 50,
    ) -> list[dict[str, Any]]:
        targets = await self._search_weather_condition_ids(max_markets)
        if not targets:
            markets = await self.fetch_weather_markets()
            for market in markets:
                condition_id = market.get("condition_id") or market.get(
                    "conditionId"
                )
                if condition_id:
                    targets.append(
                        (str(condition_id), str(market.get("slug", "weather")))
                    )
                if len(targets) >= max_markets:
                    break

        rejected: list[int] = []
        observations: list[dict[str, Any]] = []
        bucket = get_data_bucket()
        try:
            for condition_id, slug in targets:
                await bucket.acquire()
                try:
                    trades = await asyncio.to_thread(
                        self._data.get_trades,
                        condition_id=condition_id,
                        taker_only=False,
                        limit=trades_per_market,
                    )
                    if trades is None:
                        trades = []
                    trade_items: list = list(trades)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        retry_after = self._record_429(
                            bucket, exc.response, self.settings.data_api_host
                        )
                        await self._notify_rate_limit(
                            self.settings.data_api_host, retry_after
                        )
                        rejected.append(exc.response.status_code)
                        logger.warning(
                            "trades feed throttled market scan %s (HTTP 429, retry_after=%.1fs)",
                            slug,
                            retry_after,
                        )
                        continue
                    rejected.append(exc.response.status_code)
                    logger.warning(
                        "trades feed rejected market scan %s (HTTP %d)",
                        slug,
                        exc.response.status_code,
                    )
                    continue
                except httpx.HTTPError as exc:
                    logger.debug(
                        "trades feed unreachable for %s (%s)", slug, exc
                    )
                    rejected.append(0)
                    continue

                for item in trade_items:
                    item_dict = item.model_dump()
                    wallet = str(
                        item_dict.get("proxy_wallet")
                        or item_dict.get("user")
                        or ""
                    ).strip().lower()
                    shares = float(item_dict.get("size") or 0.0)
                    price = float(item_dict.get("price") or 0.0)
                    size_usd = shares * price
                    if not wallet or size_usd <= 0:
                        continue
                    observations.append(
                        {
                            "wallet": wallet,
                            "timestamp": self._to_timestamp(item_dict.get("timestamp")),
                            "size_usd": size_usd,
                            "market_slug": str(item_dict.get("slug") or slug),
                            "side": "BUY"
                            if str(item_dict.get("side") or "BUY").upper()
                            == "BUY"
                            else "SELL",
                        }
                    )
        except httpx.HTTPError as exc:
            logger.debug("discovery trades feed unreachable (%s)", exc)

        if targets and len(rejected) == len(targets):
            codes = ", ".join(str(code) for code in sorted(set(rejected)))
            raise RuntimeError(
                f"discovery trades feed rejected all markets: {codes}"
            )

        return observations

    def _to_timestamp(self, value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (ValueError, OSError):
                return 0.0
        return 0.0

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

        raise RuntimeError(
            "Live order routing is locked until CLOB credentials and "
            "py-clob-client signing are configured. Keep DRY_RUN=true for paper."
        )

    def _next_demo_events(self, wallets: list[str]) -> list[dict[str, Any]]:
        self._demo_cursor += 1
        if self._demo_cursor % 3 != 0:
            return []

        cities = [
            "New York",
            "London",
            "Tokyo",
            "Chicago",
            "Seattle",
            "Miami",
        ]
        city = cities[self._demo_cursor % len(cities)]
        wallet = wallets[self._demo_cursor % len(wallets)]
        now = datetime.now(timezone.utc) - timedelta(
            milliseconds=int(self._rng.integers(220, 640))
        )

        wt_idx = self._demo_cursor % len(_WEATHER_TYPES)
        wt_slug, wt_title = _WEATHER_TYPES[wt_idx]
        slug = f"{wt_slug}-in-{city.lower().replace(' ', '-')}"
        title = wt_title.format(city)

        return [
            {
                "id": f"demo-{self._demo_cursor}",
                "wallet": wallet,
                "timestamp": now.isoformat(),
                "market_slug": slug,
                "market_title": title,
                "city": city,
                "outcome": str(
                    self._rng.choice(["Yes", "No", "70-71°F", "Above 72°F"])
                ),
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
