"""First-party P&L enrichment for discovered copy targets.

While :mod:`wallet_discovery` can only observe raw activity volume (it cannot
know a wallet's P&L from public fills), Polymarket itself exposes closed-position
realized P&L, a user-pnl timeseries, a WEATHER-category leaderboard rank, and a
lb-api overall-profit metric. :class:`WalletProfiler` pulls those into a
:class:`WalletProfile` so the promotion layer can optionally gate on realized
performance instead of pure volume.

The profiler is deliberately optional: when ``profiler_enabled`` is False (or all
of the profiler gates are 0), discovery promotes on activity heuristics exactly
as before. Each wallet is cached for ``profiler_cache_ttl_s`` and backed off for
``profiler_backoff_s`` after a failed fetch so a single dead endpoint cannot slow
down an entire discovery cycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from weather_copy_bot.config import Settings
from weather_copy_bot.polymarket.client import PolymarketClient

logger = logging.getLogger(__name__)


@dataclass
class WalletProfile:
    """Derived performance metrics for one discovered address.

    ``data_available`` distinguishes a profile that actually reached Polymarket
    (even with zero closed positions) from a placeholder returned after a fetch
    failure, so the promotion layer never promotes on missing data when a
    profiler gate is armed.
    """

    address: str
    realized_pnl: float = 0.0
    closed_positions: int = 0
    wins: int = 0
    win_rate: float = 0.0
    invested: float = 0.0
    roi_pct: float = 0.0
    weekly_variance: float = 0.0
    age_days: float = 0.0
    weather_rank: int | None = None
    overall_profit: float = 0.0
    position_value: float = 0.0
    data_available: bool = False
    fetched_at: float = 0.0


class WalletProfiler:
    """Enrich discovered wallets with Polymarket first-party performance data."""

    def __init__(
        self,
        settings: Settings,
        client: PolymarketClient | None = None,
    ):
        self.settings = settings
        self.client = client or PolymarketClient(settings)
        self._cache: dict[str, WalletProfile] = {}
        self._backoff: dict[str, float] = {}
        self._errors: dict[str, int] = {}

    async def profile_wallets(self, addresses: list[str]) -> dict[str, WalletProfile]:
        """Profile up to ``profiler_max_wallets_per_cycle`` addresses.

        Returns a lower-cased address -> profile mapping. Wallets already cached
        (or backed off) are returned from cache without a network round trip.
        """
        budget = max(self.settings.profiler_max_wallets_per_cycle, 0)
        profiles: dict[str, WalletProfile] = {}
        for address in addresses[:budget]:
            key = address.lower()
            profile = await self.profile_wallet(key)
            profiles[key] = profile
        return profiles

    async def profile_wallet(self, address: str) -> WalletProfile:
        """Fetch (or serve cached) performance metrics for a single wallet."""
        address = address.lower()
        now = time.time()
        cached = self._cache.get(address)
        if cached and (now - cached.fetched_at) < self.settings.profiler_cache_ttl_s:
            return cached
        if address in self._backoff and now < self._backoff[address]:
            return cached or WalletProfile(address=address)

        try:
            closed = await self.client.fetch_closed_positions(address)
        except Exception as exc:
            logger.warning(
                "profiler closed-positions failed for %s (%s); backing off %.0fs",
                address[:10],
                exc,
                self.settings.profiler_backoff_s,
            )
            self._backoff[address] = now + self.settings.profiler_backoff_s
            self._errors[address] = self._errors.get(address, 0) + 1
            return cached or WalletProfile(address=address)

        profile = self._build_from_closed(address, closed)

        try:
            points = await self.client.fetch_pnl_timeseries(address)
            profile.weekly_variance = self._variance(
                [p.get("value") for p in points if p.get("value") is not None]
            )
        except Exception as exc:
            logger.debug("profiler pnl timeseries failed for %s (%s)", address[:10], exc)

        try:
            profile.weather_rank = await self.client.fetch_weather_rank(address)
        except Exception as exc:
            logger.debug("profiler weather rank failed for %s (%s)", address[:10], exc)

        try:
            profile.overall_profit = await self.client.fetch_user_profit(address)
        except Exception as exc:
            logger.debug("profiler overall profit failed for %s (%s)", address[:10], exc)

        try:
            profile.position_value = await self.client.fetch_position_value(address)
        except Exception as exc:
            logger.debug("profiler position value failed for %s (%s)", address[:10], exc)

        profile.data_available = True
        profile.fetched_at = now
        self._cache[address] = profile
        self._backoff.pop(address, None)
        return profile

    @classmethod
    def _build_from_closed(
        cls,
        address: str,
        closed: list[dict[str, Any]],
    ) -> WalletProfile:
        realized = 0.0
        invested = 0.0
        wins = 0
        close_times: list[float] = []
        for pos in closed:
            pnl = float(pos.get("realized_pnl", 0.0) or 0.0)
            invested += float(pos.get("total_bought", 0.0) or 0.0)
            realized += pnl
            if pnl > 0:
                wins += 1
            ts = pos.get("timestamp")
            when = cls._parse_close_time(ts)
            if when is not None:
                close_times.append(when)
        count = len(closed)
        win_rate = (wins / count) if count else 0.0
        roi_pct = (realized / invested * 100.0) if invested else 0.0
        age_days = 0.0
        if close_times:
            age_days = max(0.0, (time.time() - min(close_times)) / 86400.0)
        return WalletProfile(
            address=address,
            realized_pnl=realized,
            closed_positions=count,
            wins=wins,
            win_rate=win_rate,
            invested=invested,
            roi_pct=roi_pct,
            age_days=age_days,
        )

    @staticmethod
    def _parse_close_time(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            if isinstance(value, datetime):
                dt = value
            else:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _variance(values: list[float]) -> float:
        vals = [float(v) for v in values]
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals) / len(vals)
