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
DISCOVERY_FAILURE_BACKOFF_CAP_S = 300.0


def _backoff_delay(failures: int, base_interval_s: float, cap_s: float) -> float:
    doubled = base_interval_s * (2 ** min(max(failures - 1, 0), 4))
    return min(doubled, cap_s)


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

    def observe(self, *, timestamp: float, size_usd: float, market_slug: str) -> None:
        self.last_seen = max(self.last_seen, timestamp)
        self.trades_seen += 1
        self.volume_usd += size_usd
        self.markets.add(market_slug)


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
            "cycles": 0,
            "observations": 0,
            "last_cycle_at": None,
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
            record.observe(
                timestamp=float(event.get("timestamp", 0.0) or 0.0),
                size_usd=float(event.get("size_usd", 0.0) or 0.0),
                market_slug=str(event.get("market_slug", "")),
            )
            touched.add(wallet)
            accepted += 1
        if accepted:
            self.stats["observations"] += accepted
        return len(touched)

    def candidates(self) -> list[DiscoveredWallet]:
        """Wallets meeting both minimum thresholds, highest conviction first."""
        qualified = [
            w
            for w in self._wallets.values()
            if w.trades_seen >= self.settings.min_candidate_trades
            and w.volume_usd >= self.settings.min_candidate_volume_usd
        ]
        qualified.sort(key=lambda w: (w.volume_usd, w.trades_seen), reverse=True)
        return qualified

    def promoted_wallets(self, max_targets: int | None = None) -> list[str]:
        """Addresses cleared for the polling rotation this instant."""
        limit = (
            max_targets
            if max_targets is not None
            else self.settings.max_discovered_targets
        )
        return [w.address for w in self.candidates()[:limit]]

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
                touched = self.observe(events)
                consecutive_failures = 0
                self.stats["cycles"] += 1
                self.stats["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
                promoted = tuple(self.promoted_wallets())
                if promoted != self._last_promoted:
                    self._last_promoted = promoted
                    if promoted:
                        logger.info(
                            "discovery promoted targets: %s", ", ".join(promoted)
                        )
                    else:
                        logger.info("discovery promotion list now empty")
                logger.debug(
                    "discovery cycle observed=%s wallets tracked=%s",
                    touched,
                    len(self._wallets),
                )
            except Exception:
                consecutive_failures += 1
                delay = _backoff_delay(
                    consecutive_failures, interval, DISCOVERY_FAILURE_BACKOFF_CAP_S
                )
                logger.exception(
                    "discovery cycle failed consecutive=%s backing_off=%.1fs",
                    consecutive_failures,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            if duration_sec is not None and (time.time() - started) >= duration_sec:
                break
            await asyncio.sleep(interval)
        self._running = False

    def stop(self) -> None:
        self._running = False
