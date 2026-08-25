"""Weather Tag Filter for Wallet Activity.

Filters target wallet transactions to only copy weather-related trades.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

from .quorum import WalletCategory, WalletTradeSignal

logger = logging.getLogger(__name__)


@dataclass
class WeatherTagFilter:
    """Filter for weather-related market activity."""

    # Weather-related keywords
    WEATHER_TAGS: set[str] = None

    def __post_init__(self):
        if self.WEATHER_TAGS is None:
            self.WEATHER_TAGS = {
                # Temperature
                "temperature",
                "temp",
                "hot",
                "cold",
                "heat",
                "freeze",
                "frost",
                "warm",
                "cool",
                "celsius",
                "fahrenheit",
                "degree",
                # Precipitation
                "rain",
                "rainfall",
                "rainy",
                "snow",
                "snowfall",
                "sleet",
                "hail",
                "drizzle",
                "precipitation",
                "shower",
                "storm",
                # Weather events
                "hurricane",
                "typhoon",
                "cyclone",
                "tornado",
                "blizzard",
                "flood",
                "drought",
                "wildfire",
                "lightning",
                "thunder",
                "thunderstorm",
                "monsoon",
                "avalanche",
                # General weather
                "weather",
                "forecast",
                "climate",
                "atmospheric",
                "meteorological",
                "el_nino",
                "la_nina",
                "el niño",
                "la niña",
                # Cities and regions (for weather markets)
                "nyc",
                "new york",
                "los angeles",
                "chicago",
                "miami",
                "houston",
                "phoenix",
                "seoul",
                "tokyo",
                "london",
                "paris",
                "berlin",
                "sydney",
                "singapore",
                "dubai",
                # Seasons
                "summer",
                "winter",
                "spring",
                "autumn",
                "fall",
            }


@dataclass
class WalletMetadata:
    """Metadata for a tracked wallet."""

    address: str
    category: WalletCategory
    name: str | None = None
    tags: set[str] = None
    first_seen: datetime = None
    trades_count: int = 0
    weather_trades_count: int = 0

    def __post_init__(self):
        if self.tags is None:
            self.tags = set()
        if self.first_seen is None:
            self.first_seen = datetime.now(timezone.utc)



class WeatherWalletFilter:
    """Filter for identifying weather-related wallet activity."""

    EXCLUDED_PATTERNS: ClassVar[list[str]] = [
        r"^POLITICS",
        r"^POLI",
        r"^CRYPTO",
        r"^BTC",
        r"^ETH",
        r"^SPORTS",
        r"^ENTERTAINMENT",
        r"^STOCK",
    ]

    def __init__(self, min_weather_score: float = 0.3):
        """
        Initialize WeatherWalletFilter.

        Args:
            min_weather_score: Minimum score to classify as weather trade (0-1)
        """
        self.min_weather_score = min_weather_score
        self.tag_filter = WeatherTagFilter()

        # Tracked wallets
        self._wallets: dict[str, WalletMetadata] = {}

        # Stats
        self._stats = {
            "total_trades": 0,
            "weather_trades": 0,
            "excluded_trades": 0,
        }

    def register_wallet(
        self,
        address: str,
        category: WalletCategory,
        name: str | None = None,
        tags: set[str] | None = None,
    ) -> WalletMetadata:
        """Register a wallet to track."""
        metadata = WalletMetadata(
            address=address.lower(),
            category=category,
            name=name,
            tags=tags or set(),
        )
        self._wallets[address.lower()] = metadata
        logger.info(f"[Filter] Registered wallet: {address[:8]}... ({category.value})")
        return metadata

    def unregister_wallet(self, address: str) -> bool:
        """Unregister a wallet."""
        address = address.lower()
        if address in self._wallets:
            del self._wallets[address]
            return True
        return False

    def is_wallet_tracked(self, address: str) -> bool:
        """Check if a wallet is tracked."""
        return address.lower() in self._wallets

    def classify_signal(
        self,
        signal: WalletTradeSignal,
        market_title: str | None = None,
        token_id: str | None = None,
    ) -> bool:
        """
        Classify if a signal is weather-related.

        Args:
            signal: The wallet trade signal
            market_title: Optional market title for scoring
            token_id: Optional token ID for pattern matching

        Returns:
            True if signal is weather-related
        """
        self._stats["total_trades"] += 1

        # Get wallet metadata
        wallet = self._wallets.get(signal.wallet_address.lower())

        # Score based on multiple factors
        score = 0.0
        reasons = []

        # 1. Wallet category weight
        if wallet:
            category_scores = {
                WalletCategory.SMART_BOT: 0.4,
                WalletCategory.SMART_TRADER: 0.3,
                WalletCategory.WHALE: 0.2,
                WalletCategory.REGULAR: 0.1,
            }
            score += category_scores.get(wallet.category, 0.1)
            reasons.append(f"category:{wallet.category.value}")

        # 2. Market title keyword matching
        if market_title:
            title_lower = market_title.lower()
            matched_tags = self.tag_filter.WEATHER_TAGS.intersection(set(title_lower.split()))
            if matched_tags:
                tag_bonus = min(len(matched_tags) * 0.15, 0.45)
                score += tag_bonus
                reasons.append(f"tags:{matched_tags}")

        # 3. Token ID pattern matching
        if token_id:
            token_lower = token_id.lower()
            for pattern in self.EXCLUDED_PATTERNS:
                if re.search(pattern, token_lower, re.IGNORECASE):
                    score -= 0.5
                    reasons.append("excluded_pattern")
                    break

        # 4. Side-based adjustment (temp markets often have clear direction)
        if signal.side.upper() in ["BUY", "SELL"]:
            score += 0.05

        # Classify
        is_weather = score >= self.min_weather_score

        if is_weather:
            self._stats["weather_trades"] += 1
            if wallet:
                wallet.weather_trades_count += 1
            logger.info(f"[Filter] ✅ Weather trade: score={score:.2f} ({', '.join(reasons)})")
        else:
            self._stats["excluded_trades"] += 1
            logger.debug(
                f"[Filter] ❌ Non-weather trade: score={score:.2f} < {self.min_weather_score}"
            )

        if wallet:
            wallet.trades_count += 1

        return is_weather

    def filter_signal(
        self,
        signal: WalletTradeSignal,
        market_title: str | None = None,
        token_id: str | None = None,
    ) -> WalletTradeSignal | None:
        """
        Filter a signal and return it if weather-related, None otherwise.
        """
        if self.is_wallet_tracked(signal.wallet_address) and self.classify_signal(signal, market_title, token_id):
                return signal
        return None

    def get_wallet_stats(self, address: str) -> dict | None:
        """Get statistics for a wallet."""
        wallet = self._wallets.get(address.lower())
        if not wallet:
            return None

        return {
            "address": wallet.address,
            "category": wallet.category.value,
            "name": wallet.name,
            "trades_count": wallet.trades_count,
            "weather_trades_count": wallet.weather_trades_count,
            "weather_ratio": (
                wallet.weather_trades_count / wallet.trades_count if wallet.trades_count > 0 else 0
            ),
            "first_seen": wallet.first_seen.isoformat(),
        }

    def get_stats(self) -> dict:
        """Get filter statistics."""
        return {
            **self._stats,
            "tracked_wallets": len(self._wallets),
            "weather_ratio": (
                self._stats["weather_trades"] / self._stats["total_trades"]
                if self._stats["total_trades"] > 0
                else 0
            ),
        }

    def get_tracked_wallets(self) -> list[WalletMetadata]:
        """Get all tracked wallets."""
        return list(self._wallets.values())
