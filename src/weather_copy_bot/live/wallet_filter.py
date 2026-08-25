"""Wallet filter for weather-specific trading signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from weather_copy_bot.models import TradeSignal

logger = logging.getLogger(__name__)

# Weather-related keywords for filtering
WEATHER_KEYWORDS = {
    # Temperature
    "temperature",
    "temp",
    "heat",
    "cold",
    "warm",
    "freeze",
    "frost",
    "high temp",
    "low temp",
    "max temp",
    "min temp",
    # Precipitation
    "rain",
    "snow",
    "sleet",
    "hail",
    "precipitation",
    "precip",
    "rainfall",
    "snowfall",
    "showers",
    "storm",
    # Weather events
    "hurricane",
    "typhoon",
    "cyclone",
    "tornado",
    "blizzard",
    "fog",
    "wind",
    "gust",
    "thunder",
    "lightning",
    # General
    "weather",
    "forecast",
    "climate",
    "meteorological",
    "sunny",
    "cloudy",
    "overcast",
    "partly cloudy",
    # Winter specific
    "snowstorm",
    "ice",
    "freezing",
    "winter",
    # Summer specific
    "heatwave",
    "drought",
    "wildfire",
}

# Related topics (not weather but correlated)
RELATED_TOPICS = {
    "energy",
    "electricity",
    "heating",
    "cooling",
    "agriculture",
    "solar",
    "solar power",
    "wind power",
    "renewable",
}


@dataclass
class WalletFilterConfig:
    """Configuration for wallet filtering."""

    # Keyword matching
    weather_keywords: set[str] = field(default_factory=lambda: WEATHER_KEYWORDS)
    related_topics: set[str] = field(default_factory=lambda: RELATED_TOPICS)

    # Behavior flags
    allow_related_topics: bool = False
    min_keyword_match: int = 1
    case_sensitive: bool = False

    # Performance tracking
    track_filter_stats: bool = True


@dataclass
class FilterStats:
    """Statistics for filter performance."""

    total_signals: int = 0
    allowed_signals: int = 0
    rejected_signals: int = 0

    # Rejection reasons
    no_keyword_match: int = 0
    non_weather_topic: int = 0
    liquidity_check_failed: int = 0

    def acceptance_rate(self) -> float:
        """Calculate signal acceptance rate."""
        if self.total_signals == 0:
            return 0.0
        return (self.allowed_signals / self.total_signals) * 100


class WeatherWalletFilter:
    """
    Filters wallet transactions to only replicate weather-related trades.

    This prevents copying non-weather positions from target wallets
    (e.g., politics, crypto, sports bets).

    Example:
        filter = WeatherWalletFilter()

        signal = TradeSignal(
            market_slug="weather-nyc-high-temp-2024",
            market_title="Will NYC exceed 95°F on July 15?",
            ...
        )

        should_copy, reason = filter.should_copy(signal)
    """

    def __init__(self, config: WalletFilterConfig | None = None):
        self.config = config or WalletFilterConfig()
        self._stats = FilterStats() if self.config.track_filter_stats else None

    def should_copy(self, signal: TradeSignal) -> tuple[bool, str]:
        """
        Determine if a signal should be copied based on weather relevance.

        Args:
            signal: The trading signal to evaluate

        Returns:
            Tuple of (should_copy, reason)
        """
        if self.config.track_filter_stats and self._stats:
            self._stats.total_signals += 1

        # Extract searchable text
        searchable = self._extract_searchable_text(signal)

        # Check for weather keywords
        weather_matches = self._find_weather_keywords(searchable)

        if len(weather_matches) < self.config.min_keyword_match:
            reason = f"no_weather_keyword:{searchable[:50]}"
            self._record_rejection("no_keyword_match")
            return False, reason

        # Optionally check related topics
        if self.config.allow_related_topics:
            related_matches = self._find_related_topics(searchable)
            if related_matches:
                logger.debug(f"Signal matched related topics: {related_matches}")

        reason = f"weather_match:{','.join(weather_matches)}"
        self._record_acceptance()
        return True, reason

    def _extract_searchable_text(self, signal: TradeSignal) -> str:
        """Extract text for keyword matching."""
        parts = [
            signal.market_slug,
            signal.market_title,
            signal.outcome,
            signal.city or "",
        ]

        text = " ".join(str(p) for p in parts if p)

        if not self.config.case_sensitive:
            text = text.lower()

        return text

    def _find_weather_keywords(self, text: str) -> list[str]:
        """Find weather keywords in text."""
        return [kw for kw in self.config.weather_keywords if kw in text]

    def _find_related_topics(self, text: str) -> list[str]:
        """Find related (non-weather) topics in text."""
        return [t for t in self.config.related_topics if t in text]

    def _record_acceptance(self) -> None:
        """Record an accepted signal."""
        if self._stats:
            self._stats.allowed_signals += 1

    def _record_rejection(self, reason: str) -> None:
        """Record a rejected signal."""
        if self._stats:
            self._stats.rejected_signals += 1
            if hasattr(self._stats, reason):
                setattr(self._stats, reason, getattr(self._stats, reason) + 1)

    def get_stats(self) -> FilterStats | None:
        """Get filter statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset filter statistics."""
        if self._stats:
            self._stats = FilterStats()


class MultiWalletFilter:
    """
    Filter for managing multiple wallet filters with per-wallet settings.

    Useful when different target wallets have different specialties.
    """

    def __init__(self):
        self._filters: dict[str, WeatherWalletFilter] = {}
        self._default_filter = WeatherWalletFilter()

    def add_wallet(
        self,
        wallet: str,
        config: WalletFilterConfig | None = None,
    ) -> None:
        """Add a wallet with custom filter config."""
        self._filters[wallet] = WeatherWalletFilter(config or WalletFilterConfig())

    def remove_wallet(self, wallet: str) -> None:
        """Remove a wallet from the filter."""
        self._filters.pop(wallet, None)

    def should_copy(self, signal: TradeSignal) -> tuple[bool, str]:
        """Check if signal should be copied for the given wallet."""
        wallet = signal.target_wallet
        filter_ = self._filters.get(wallet, self._default_filter)
        return filter_.should_copy(signal)

    def get_all_stats(self) -> dict[str, FilterStats | None]:
        """Get statistics for all wallets."""
        stats = {wallet: f.get_stats() for wallet, f in self._filters.items()}
        stats["_default"] = self._default_filter.get_stats()
        return stats
