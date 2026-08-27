"""Polymarket data + order adapters with a safe demo fallback.

The client surface stays compatible with the ``monkeypatch.setattr(httpx,
"AsyncClient", factory)`` test pattern by always going through
``httpx.AsyncClient`` for the wire request while the rate limiter + observer
hook run in front of it. This keeps existing tests green while still
preventing the production poll loop from spamming gamma/data into a 429
spiral.
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

    async def _notify_rate_limit(self, host: str, retry_after: float) -> None:
        """Forward 429 events to the engine's observer (if one is wired)."""
        if self._on_rate_limit is None:
            return
        try:
            await self._on_rate_limit(host, retry_after)
        except Exception as exc:  # pragma: no cover - observer errors must not break poll
            logger.debug("rate-limit observer raised %s", exc)

    @staticmethod
    def _record_429(bucket, response: httpx.Response, host: str) -> float:
        """Bookkeeping for a 429 response. Returns the parsed Retry-After."""
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
        """Fetch active markets; falls back to curated weather stubs offline."""
        url = f"{self.settings.gamma_host}/markets"
        params = {"active": "true", "closed": "false", "limit": limit}
        bucket = get_gamma_bucket()
        await bucket.acquire()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    retry_after = self._record_429(bucket, resp, self.settings.gamma_host)
                    await self._notify_rate_limit(self.settings.gamma_host, retry_after)
                    logger.warning(
                        "gamma markets throttled (HTTP 429, retry_after=%.1fs)", retry_after
                    )
                else:
                    resp.raise_for_status()
                markets = resp.json()
                weather = [
                    m
                    for m in markets
                    if any(
                        k in (m.get("question", "") + " " + m.get("slug", "")).lower()
                        for k in self.settings.weather_keywords
                    )
                ]
                if weather:
                    return weather
        except httpx.HTTPStatusError as exc:
            logger.warning("gamma markets unavailable, using stubs: %s", exc)
        except Exception as exc:
            logger.warning("gamma markets unavailable, using stubs: %s", exc)
        return self._stub_markets()

    async def fetch_target_activity(
        self,
        wallets: list[str],
        market_filter: str = "weather",
    ) -> list[dict[str, Any]]:
        """Pull recent target trades. Falls back to the demo stream only on network errors."""
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
            url = f"{self.settings.data_api_host}/activity"
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(url, params={"user": wallet, "limit": 20})
            except httpx.RequestError as exc:
                logger.debug("activity API unreachable for %s (%s)", wallet, exc)
                network_unavailable = True
                return []
            if resp.status_code == 429:
                retry_after = self._record_429(bucket, resp, self.settings.data_api_host)
                await self._notify_rate_limit(self.settings.data_api_host, retry_after)
                rejected.append((wallet, resp.status_code))
                rejected_429.append(wallet)
                logger.warning(
                    "activity API rejected wallet %s (HTTP 429, retry_after=%.1fs)",
                    wallet,
                    retry_after,
                )
                return []
            if resp.status_code != 200:
                rejected.append((wallet, resp.status_code))
                logger.warning(
                    "activity API rejected wallet %s (HTTP %d)",
                    wallet,
                    resp.status_code,
                )
                return []
            return resp.json()

        try:
            results = await asyncio.gather(
                *[fetch_wallet(w) for w in wallets], return_exceptions=True
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.debug("wallet fetch raised %s", result)
                    network_unavailable = True
                    continue
                for item in result:
                    title = str(item.get("title", item.get("slug", "")))
                    if (
                        market_filter
                        and market_filter.lower() not in title.lower()
                        and not any(
                            k in title.lower() for k in self.settings.strict_weather_keywords
                        )
                    ):
                        continue
                    wallet = item.get("wallet", "")
                    all_items.append(
                        {
                            "id": str(item.get("id", item.get("transactionHash", ""))),
                            "wallet": wallet,
                            "timestamp": self._normalize_activity_timestamp(
                                item.get("timestamp")
                            ),
                            "market_slug": item.get("slug")
                            or item.get("eventSlug")
                            or "weather",
                            "market_title": title,
                            "city": self._infer_city(title),
                            "outcome": item.get("outcome", "Yes"),
                            "side": "BUY"
                            if str(item.get("side", "BUY")).upper() == "BUY"
                            else "SELL",
                            "price": float(item.get("price", 0.5)),
                            "size_usd": float(item.get("usdcSize", item.get("size", 50))),
                            "token_id": item.get("asset"),
                            "demo": False,
                        }
                    )
            if all_items:
                return all_items
        except httpx.HTTPError as exc:
            logger.debug("activity API unreachable (%s); using demo stream", exc)

        if rejected_429 and self._on_rate_limit is not None:
            pass
        if rejected:
            codes = ", ".join(
                f"{wallet[:10]}...={status}" for wallet, status in rejected
            )
            raise RuntimeError(f"activity API rejected wallets: {codes}")

        return self._next_demo_events(wallets)

    @staticmethod
    def _normalize_activity_timestamp(value: Any) -> str:
        """Coerce data-api timestamps (unix epoch seconds or ISO strings) to ISO-8601 UTC."""
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        text = str(value or "").strip()
        return text or datetime.now(timezone.utc).isoformat()

    async def _search_weather_condition_ids(
        self,
        max_markets: int,
    ) -> list[tuple[str, str]]:
        """Resolve active weather conditionIds via the gamma search index.

        Gamma's default active-market window is ordered by popularity and
        rarely contains daily weather markets, so discovery queries
        public-search per weather keyword instead. Falls back silently to an
        empty result on any network trouble, letting callers use the windowed
        scan. All keywords are fetched in parallel via asyncio.gather.
        """
        seen: set[str] = set()
        bucket = get_gamma_bucket()

        async def _search_keyword(keyword: str) -> list[tuple[str, str]]:
            await bucket.acquire()
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(
                        f"{self.settings.gamma_host}/public-search",
                        params={
                            "q": keyword,
                            "events_status": "active",
                            "limit_per_type": 10,
                        },
                    )
                    if resp.status_code == 429:
                        retry_after = self._record_429(
                            bucket, resp, self.settings.gamma_host
                        )
                        await self._notify_rate_limit(
                            self.settings.gamma_host, retry_after
                        )
                        logger.debug(
                            "gamma public-search throttled keyword %s (HTTP 429)",
                            keyword,
                        )
                        return []
                    if resp.status_code != 200:
                        logger.debug(
                            "gamma public-search rejected keyword %s (HTTP %d)",
                            keyword,
                            resp.status_code,
                        )
                        return []
                    body = resp.json()
            except Exception as exc:
                logger.debug(
                    "gamma public-search query %r failed (%s)", keyword, exc
                )
                return []
            if not isinstance(body, dict):
                return []
            results: list[tuple[str, str]] = []
            events = body.get("events") or []
            for event in events:
                if not isinstance(event, dict):
                    continue
                for market in event.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    condition_id = str(market.get("conditionId") or "").strip()
                    if (
                        not condition_id
                        or condition_id in seen
                        or not market.get("active")
                        or market.get("closed")
                    ):
                        continue
                    seen.add(condition_id)
                    slug = str(market.get("slug") or event.get("slug") or "weather")
                    results.append((condition_id, slug))
            return results

        try:
            results = await asyncio.gather(
                *[_search_keyword(kw) for kw in self.settings.weather_keywords],
                return_exceptions=True,
            )
        except httpx.HTTPError as exc:
            logger.debug("gamma public-search unreachable (%s)", exc)
            return []
        found: list[tuple[str, str]] = []
        for batch in results:
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
        """Scan public trades on active weather markets for candidate wallets.

        Resolves live weather markets to conditionIds via gamma public-search
        first (covering markets outside the popularity-ordered active window),
        falling back to the keyword-filtered windowed scan when search yields
        nothing. Queries the data-api public trades feed (/trades) per market
        WITHOUT a user filter so trades from any address appear; USD notional
        is derived from size * price because /trades omits usdcSize. Returns
        raw observations for ranking in engine.wallet_discovery. Raises only
        when every market query is rejected, mirroring
        fetch_target_activity's contract.
        """
        targets = await self._search_weather_condition_ids(max_markets)
        if not targets:
            markets = await self.fetch_weather_markets()
            for market in markets:
                condition_id = market.get("conditionId")
                if condition_id:
                    targets.append((str(condition_id), str(market.get("slug", "weather"))))
                if len(targets) >= max_markets:
                    break

        rejected: list[int] = []
        observations: list[dict[str, Any]] = []
        bucket = get_data_bucket()
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                for condition_id, slug in targets:
                    await bucket.acquire()
                    url = f"{self.settings.data_api_host}/trades"
                    try:
                        resp = await client.get(
                            url,
                            params={"market": condition_id, "limit": trades_per_market},
                        )
                    except httpx.HTTPError as exc:
                        logger.debug("trades feed unreachable for %s (%s)", slug, exc)
                        rejected.append(0)
                        continue
                    if resp.status_code == 429:
                        retry_after = self._record_429(
                            bucket, resp, self.settings.data_api_host
                        )
                        await self._notify_rate_limit(
                            self.settings.data_api_host, retry_after
                        )
                        rejected.append(resp.status_code)
                        logger.warning(
                            "trades feed throttled market scan %s (HTTP 429, retry_after=%.1fs)",
                            slug,
                            retry_after,
                        )
                        continue
                    if resp.status_code != 200:
                        rejected.append(resp.status_code)
                        logger.warning(
                            "trades feed rejected market scan %s (HTTP %d)",
                            slug,
                            resp.status_code,
                        )
                        continue
                    for item in resp.json():
                        wallet = str(item.get("proxyWallet", "")).strip().lower()
                        shares = float(item.get("size", 0.0) or 0.0)
                        price = float(item.get("price", 0.0) or 0.0)
                        size_usd = shares * price
                        if not wallet or size_usd <= 0:
                            continue
                        observations.append(
                            {
                                "wallet": wallet,
                                "timestamp": float(item.get("timestamp", 0.0) or 0.0),
                                "size_usd": size_usd,
                                "market_slug": str(item.get("slug", slug)),
                                "side": "BUY"
                                if str(item.get("side", "BUY")).upper() == "BUY"
                                else "SELL",
                            }
                        )
        except httpx.HTTPError as exc:
            logger.debug("discovery trades feed unreachable (%s)", exc)

        if targets and len(rejected) == len(targets):
            codes = ", ".join(str(code) for code in sorted(set(rejected)))
            raise RuntimeError(f"discovery trades feed rejected all markets: {codes}")

        return observations

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
        self._demo_cursor += 1
        if self._demo_cursor % 10 != 0:
            return []

        cities = ["New York", "London", "Tokyo", "Chicago", "Seattle", "Miami"]
        city = cities[self._demo_cursor % len(cities)]
        wallet = wallets[self._demo_cursor % len(wallets)]
        now = datetime.now(timezone.utc) - timedelta(milliseconds=int(self._rng.integers(220, 640)))

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
