"""Market metadata enrichment for Polymarket data."""
from __future__ import annotations

from dataclasses import dataclass, field

from weather_copy_bot.config._settings import get_settings


@dataclass
class MarketMetadata:
    """Enriched market metadata with derived metrics."""

    volume_trend_24h: float = 0.0
    creator_reputation: float = 0.5
    liquidity_usd: float = 0.0
    market_age_hours: int = 0
    social_sentiment: float | None = None


@dataclass
class LiquidityMetrics:
    """Liquidity metrics for a market."""

    bid_ask_spread_bps: float = field(default=0.0)
    depth_score: float = field(default=0.5)


@dataclass
class VolumeTrend:
    """Volume trend data."""

    percent_change_24h: float = 0.0


class MarketMetadataEnricher:
    """Enriches market data with derived metadata."""

    def __init__(self, settings: object | None = None) -> None:
        self.settings = settings or get_settings()

    async def enrich_market(self, market: dict) -> MarketMetadata:
        """Enrich a market with derived metadata."""
        volume_trend = await self.get_volume_trend(market)
        creator_address = market.get("creator", "")
        creator_reputation = self._calculate_creator_reputation(creator_address)
        liquidity = self._extract_liquidity(market)
        age_hours = self._calculate_market_age(market)

        return MarketMetadata(
            volume_trend_24h=volume_trend.percent_change_24h,
            creator_reputation=creator_reputation,
            liquidity_usd=liquidity,
            market_age_hours=age_hours,
            social_sentiment=None,
        )

    async def get_volume_trend(self, market: dict) -> VolumeTrend:
        """Calculate volume trend for a market."""
        volume_24hr_str = market.get("volume24hr", "0")
        volume_str = market.get("volume", "0")

        try:
            volume_24hr = float(volume_24hr_str) if volume_24hr_str else 0.0
        except (ValueError, TypeError):
            volume_24hr = 0.0

        try:
            volume_total = float(volume_str) if volume_str else 0.0
        except (ValueError, TypeError):
            volume_total = 0.0

        percent_change = (volume_24hr / volume_total) * 100 if volume_total > 0 else 0.0

        return VolumeTrend(percent_change_24h=percent_change)

    def _calculate_creator_reputation(self, creator_address: str) -> float:
        """Calculate creator reputation score (0-1)."""
        if not creator_address:
            return 0.5

        known_creators = {
            "0x1234567890abcdef1234567890abcdef12345678": 0.9,
            "0xabcdef1234567890abcdef1234567890abcdef12": 0.85,
        }

        return known_creators.get(creator_address, 0.6)

    def _extract_liquidity(self, market: dict) -> float:
        """Extract liquidity value from market data."""
        liquidity_str = market.get("liquidity", "0")
        try:
            return float(liquidity_str) if liquidity_str else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _calculate_market_age(self, market: dict) -> int:
        """Calculate market age in hours."""
        created_at = market.get("createdAt")
        if not created_at:
            return 0

        try:
            from datetime import datetime, timezone

            if isinstance(created_at, str):
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                dt = created_at

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            age_delta = now - dt
            return int(age_delta.total_seconds() / 3600)
        except (ValueError, TypeError, AttributeError):
            return 0

    async def get_liquidity_metrics(self, market: dict) -> LiquidityMetrics:
        """Get liquidity metrics for a market."""
        liquidity = self._extract_liquidity(market)

        bid_ask_spread = 50.0
        depth_score = 0.5

        if liquidity > 1000000:
            bid_ask_spread = 15.0
            depth_score = 0.9
        elif liquidity > 500000:
            bid_ask_spread = 25.0
            depth_score = 0.75
        elif liquidity > 100000:
            bid_ask_spread = 35.0
            depth_score = 0.6

        return LiquidityMetrics(
            bid_ask_spread_bps=bid_ask_spread,
            depth_score=depth_score,
        )
