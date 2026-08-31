"""Automatic target-wallet discovery from public weather-market activity.

The copy engine polls a rotation built from two sources:
1. Static TARGET_WALLETS from settings (always present).
2. Wallets discovered by scanning recent public trades on active weather
   markets and promoted once they pass observable-activity thresholds.

Pre-copy PnL is unknowable, so promotion uses volume/trade-count heuristics;
post-copy scoring stays with analysis.wallet_analyzer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from weather_copy_bot.config import Settings
from weather_copy_bot.polymarket.client import PolymarketClient

logger = logging.getLogger(__name__)

# Discovery polls a sidecar feed on a ~30s cadence, so failures back off far
# slower than the trading poll loop (whose cap is 5s).
DISCOVERY_FAILURE_BACKOFF_CAP_S = None

# How many addresses to surface in the ``promoted`` log line. The full list
# can be 90+ wallets after a successful cycle; dumping every address makes a
# 4-5 KB log line that is hostile to operators scrolling the dashboard.
_PROMOTED_LOG_SAMPLE = 3


def _backoff_delay(failures: int, base_interval_s: float, cap_s: float | None) -> float:
    doubled = base_interval_s * (2 ** min(max(failures - 1, 0), 4))
    return min(doubled, cap_s) if cap_s is not None else doubled


def _short_addr(addr: str) -> str:
    """Render ``addr`` as ``0x6a8b…7542`` for compact log output.

    Falls back to the raw string when the address is too short to truncate
    meaningfully (test/demo wallets).
    """
    if len(addr) <= 12:
        return addr
    return f"{addr[:6]}…{addr[-4:]}"


def _format_promoted_sample(promoted: Sequence[str]) -> str:
    """Return a compact ``0x…, 0x…, …`` representation of ``promoted``.

    Always shows the first ``_PROMOTED_LOG_SAMPLE`` and the last
    ``_PROMOTED_LOG_SAMPLE`` when the list is long enough, with an ellipsis
    between the two groups. Operators get the count separately so the sample
    is purely for cross-referencing known wallets.
    """
    n = len(promoted)
    if n == 0:
        return ""
    if n <= _PROMOTED_LOG_SAMPLE * 2:
        return ", ".join(_short_addr(a) for a in promoted)
    head = list(promoted[:_PROMOTED_LOG_SAMPLE])
    tail = list(promoted[-_PROMOTED_LOG_SAMPLE:])
    return f"{', '.join(_short_addr(a) for a in head)}, …, {', '.join(_short_addr(a) for a in tail)}"


class MergedTargetProvider:
    """Resolve the polling rotation: static wallets first, discovered appended."""

    def __init__(
        self,
        static_wallets: Sequence[str],
        discovery: WalletDiscovery | None = None,
    ):
        self.static = [w.strip() for w in static_wallets if w.strip()]
        self.discovery = discovery

    def current(self) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        promoted = self.discovery.promoted_wallets() if self.discovery else []
        for wallet in [*self.static, *promoted]:
            key = wallet.lower()
            if key not in seen:
                seen.add(key)
                merged.append(wallet)
        return merged


@dataclass
class DiscoveredWallet:
    """Aggregated public-activity stats for one candidate address."""

    address: str
    first_seen: float
    last_seen: float
    trades_seen: int = 0
    volume_usd: float = 0.0
    markets: set[str] = field(default_factory=set)
    weather_trades: int = 0
    # UTC date (YYYY-MM-DD) -> trade count, used for the per-day spam/HFT gate.
    trades_by_day: dict[str, int] = field(default_factory=dict)
    # Distinct markets observed that were NOT weather; used for the generalist
    # "dispersion" guard that keeps crypto/politics/sports wallets out.
    non_weather_markets: set[str] = field(default_factory=set)

    @property
    def weather_share(self) -> float:
        if self.trades_seen <= 0:
            return 0.0
        return self.weather_trades / self.trades_seen

    @property
    def max_trades_per_day(self) -> int:
        """Highest single-UTC-day trade count observed."""
        return max(self.trades_by_day.values(), default=0)

    def observe(
        self,
        *,
        timestamp: float,
        size_usd: float,
        market_slug: str,
        is_weather: bool = True,
    ) -> None:
        self.last_seen = max(self.last_seen, timestamp)
        self.trades_seen += 1
        self.volume_usd += size_usd
        self.markets.add(market_slug)
        if is_weather:
            self.weather_trades += 1
        else:
            self.non_weather_markets.add(market_slug)
        day_key = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            if timestamp
            else None
        )
        if day_key:
            self.trades_by_day[day_key] = self.trades_by_day.get(day_key, 0) + 1


class WalletDiscovery:
    """Observe cross-wallet activity on weather markets and promote candidates."""

    def __init__(
        self,
        settings: Settings,
        client: PolymarketClient | None = None,
    ):
        self.settings = settings
        self.client = client or PolymarketClient(settings)
        # Static targets and offline demo wallets never re-enter promotion;
        # dedup against them would otherwise be pointless churn.
        self._excluded = {w.lower() for w in self.client.default_demo_wallets()} | {
            w.lower() for w in settings.target_wallets
        }
        self._wallets: dict[str, DiscoveredWallet] = {}
        self._last_promoted: tuple[str, ...] = ()
        self._running = False
        self.stats: dict[str, Any] = {
            "discovery_cycles": 0,
            "observations": 0,
            "last_cycle_at": None,
            "consecutive_failures": 0,
            "last_error": None,
            "discovery_last_error_at": None,
        }

    def observe(self, events: Iterable[dict[str, Any]]) -> int:
        """Fold raw activity observations into the registry; return wallets touched."""
        touched: set[str] = set()
        now = time.time()
        accepted = 0
        for event in events:
            wallet = str(event.get("wallet", "")).strip().lower()
            if not wallet or wallet in self._excluded:
                continue
            record = self._wallets.get(wallet)
            if record is None:
                record = DiscoveredWallet(address=wallet, first_seen=now, last_seen=now)
                self._wallets[wallet] = record
            market_slug = str(event.get("market_slug", ""))
            title = str(event.get("market_title") or event.get("title") or "")
            haystack = f"{market_slug} {title}".lower().strip()
            # Events without any market metadata come from the weather-market
            # discovery pipeline itself; count them as weather. Only identifiable
            # non-weather markets drag the share down.
            is_weather = not haystack or any(
                k in haystack for k in self.settings.weather_keywords
            )
            record.observe(
                timestamp=float(event.get("timestamp", 0.0) or 0.0),
                size_usd=float(event.get("size_usd", 0.0) or 0.0),
                market_slug=market_slug,
                is_weather=is_weather,
            )
            touched.add(wallet)
            accepted += 1
        if accepted:
            self.stats["observations"] += accepted
        return len(touched)

    def candidates(self) -> list[DiscoveredWallet]:
        """Wallets meeting every promotion gate, highest conviction first."""
        ttl_cutoff = time.time() - self.settings.candidate_ttl_hours * 3600.0
        max_trades_day = self.settings.max_candidate_trades_per_day
        max_non_weather = self.settings.max_non_weather_markets
        qualified = [
            w
            for w in self._wallets.values()
            if w.trades_seen >= self.settings.min_candidate_trades
            and w.volume_usd >= self.settings.min_candidate_volume_usd
            and w.last_seen >= ttl_cutoff
            and w.weather_share >= self.settings.min_weather_share
            and (max_trades_day <= 0 or w.max_trades_per_day <= max_trades_day)
            and (max_non_weather <= 0 or len(w.non_weather_markets) <= max_non_weather)
        ]
        qualified.sort(key=lambda w: (w.volume_usd, w.trades_seen), reverse=True)
        return qualified

    def promoted_wallets(self, max_targets: int | None = None) -> list[str]:
        """Addresses cleared for the polling rotation this instant.

        Promotion is uncapped by default; ``max_registry_size`` bounds the
        registry and ``candidate_ttl_hours`` evicts stale wallets, so the
        rotation cannot grow without bound. An explicit ``max_targets`` may be
        passed to cap the result for a particular call site.
        """
        qualified = self.candidates()
        if max_targets is None:
            return [w.address for w in qualified]
        return [w.address for w in qualified[:max_targets]]

    def status(self) -> dict[str, Any]:
        """Snapshot for the /api/discovery/status endpoint."""
        top = [
            {
                "address": w.address,
                "trades_seen": w.trades_seen,
                "volume_usd": round(w.volume_usd, 2),
                "markets": len(w.markets),
            }
            for w in self.candidates()[:5]
        ]
        return {
            "enabled": True,
            **self.stats,
            "tracked": len(self._wallets),
            "top_candidates": top,
            "promoted_wallets": self.promoted_wallets(),
        }

    async def run(self, duration_sec: float | None = None) -> None:
        self._running = True
        interval = self.settings.discovery_interval_s
        consecutive_failures = 0
        started = time.time()
        logger.info(
            "WalletDiscovery starting interval=%ss max_markets=%s "
            "trades_per_market=%s min_trades=%s min_volume=$%.0f",
            interval,
            self.settings.discovery_max_markets,
            self.settings.discovery_trades_per_market,
            self.settings.min_candidate_trades,
            self.settings.min_candidate_volume_usd,
        )
        while self._running:
            try:
                events = await self.client.discover_weather_wallets(
                    max_markets=self.settings.discovery_max_markets,
                    trades_per_market=self.settings.discovery_trades_per_market,
                )
                if not events:
                    logger.info(
                        "discovery cycle: zero markets/observations; skipping"
                    )
                touched = self.observe(events)
                consecutive_failures = 0
                self.stats["consecutive_failures"] = 0
                self.stats["last_error"] = None
                self.stats["discovery_last_error_at"] = None
                self.stats["discovery_cycles"] += 1
                self.stats["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
                promoted = tuple(self.promoted_wallets())
                if promoted != self._last_promoted:
                    self._last_promoted = promoted
                    if promoted:
                        logger.info(
                            "discovery promoted targets N=%d (sample: %s)",
                            len(promoted),
                            _format_promoted_sample(promoted),
                        )
                    else:
                        logger.info("discovery promotion list now empty")
                logger.debug(
                    "discovery cycle observed=%s wallets tracked=%s",
                    touched,
                    len(self._wallets),
                )
            except Exception as exc:
                consecutive_failures += 1
                self.stats["consecutive_failures"] = consecutive_failures
                self.stats["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
                self.stats["discovery_last_error_at"] = datetime.now(timezone.utc).isoformat()
                delay = _backoff_delay(
                    consecutive_failures, interval, DISCOVERY_FAILURE_BACKOFF_CAP_S
                )
                logger.exception(
                    "discovery cycle failed consecutive=%s backing_off=%.1fs",
                    consecutive_failures,
                    delay,
                )
                # Bounded runs must terminate even when every cycle fails;
                # check the budget before sleeping so a large backoff does not
                # overshoot the requested duration.
                if duration_sec is not None and (time.time() - started) >= duration_sec:
                    break
                await asyncio.sleep(delay)
                continue
            if duration_sec is not None and (time.time() - started) >= duration_sec:
                break
            await asyncio.sleep(interval)
        self._running = False

    def stop(self) -> None:
        self._running = False
