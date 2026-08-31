"""Consensus engine aggregating wallet trades into copy decisions.

Every tracked wallet is smart money by definition, so all votes carry equal
weight; trade notional (``size_usd``) only shapes the consensus entry price
(VWAP), never the vote count. A consensus fires exactly once per
``(token_id, side)`` key when ``min_quorum_count`` distinct wallets agree
inside ``window_seconds`` at a size-weighted average price at or below
``max_acceptable_price``.
"""

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class WalletTradeSignal:
    """A single observed wallet trade acting as one consensus vote."""

    signal_id: str = field(default_factory=lambda: str(uuid4()))
    wallet_address: str = ""
    token_id: str = ""
    side: str = ""
    entry_price: float = 0.0
    size_usd: float = 0.0  # Notional of the vote; drives VWAP, not vote count
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class QuorumResult:
    """Consensus outcome for one ``(token_id, side)`` key."""

    token_id: str = ""
    side: str = ""
    quorum_size: int = 0
    wallets: tuple[str, ...] = ()
    vwap_price: float = 0.0
    total_size_usd: float = 0.0
    window_start: float = 0.0


class QuorumEngine:
    """Buffers equal-weight votes per ``(token_id, side)`` and emits consensuses.

    The clock is injectable so replays can drive windows deterministically
    without waiting real time.
    """

    def __init__(
        self,
        min_quorum_count: int = 2,
        window_seconds: float = 600.0,
        max_acceptable_price: float = 0.85,
        clock: Callable[[], float] | None = None,
        consensus_window_seconds: float | None = None,
    ) -> None:
        self.min_quorum_count = min_quorum_count
        self.window_seconds = window_seconds
        self.max_acceptable_price = max_acceptable_price
        self.consensus_window_seconds = consensus_window_seconds
        self._clock: Callable[[], float] = clock or time.time

        self._buffers: dict[str, list[WalletTradeSignal]] = defaultdict(list)
        # Executed-key map is TTL-pruned so idempotency memory stays bounded.
        self._executed: dict[str, float] = {}
        # Buffer size at last price rejection; prevents double counting the
        # same composition on every re-evaluation.
        self._price_reject_len: dict[str, int] = {}
        self._stats: dict[str, int] = self._empty_stats()
        self._cleanup_task: asyncio.Task | None = None

    def register_signal(self, signal: WalletTradeSignal) -> QuorumResult | None:
        """Buffer one vote; return a QuorumResult exactly once per key."""
        self._stats["signals_received"] += 1
        now = self._clock()
        key = f"{signal.token_id}:{signal.side}"

        # Prune first so freshly-aged-out execution locks release promptly.
        self._expire_stale(now)

        if key in self._executed:
            self._stats["duplicate_signals"] += 1
            return None

        buffer = self._buffers[key]
        if any(vote.wallet_address == signal.wallet_address for vote in buffer):
            self._stats["duplicate_signals"] += 1
            return None

        buffer.append(signal)
        self._stats["signals_buffered"] += 1

        effective = buffer
        if self.consensus_window_seconds is not None:
            consensus_cutoff = now - self.consensus_window_seconds
            effective = [v for v in buffer if v.timestamp >= consensus_cutoff]

        if len(effective) < self.min_quorum_count:
            return None

        result = self._evaluate(effective)
        if result is not None:
            self._buffers.pop(key, None)
            self._price_reject_len.pop(key, None)
            self._executed[key] = now
            self._stats["quorum_reached"] += 1
            return result

        # Count each distinct buffer composition's price failure once.
        if self._price_reject_len.get(key) != len(buffer):
            self._price_reject_len[key] = len(buffer)
            self._stats["quorum_rejected"] += 1
        return None

    def start_cleanup_task(self, interval: float = 60.0) -> None:
        """Spawn the background expiry loop if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self.run_cleanup_task(interval))

    async def stop_cleanup_task(self) -> None:
        """Cancel the background expiry loop, if running."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

    async def run_cleanup_task(self, interval: float = 60.0) -> None:
        """Periodically expire stale buffers using the injected clock."""
        while True:
            await asyncio.sleep(interval)
            self._expire_stale(self._clock())

    def get_stats(self) -> dict[str, int]:
        """Return cumulative counters plus bounded-map sizes."""
        return {**self._stats, "executed_keys": len(self._executed)}

    def get_buffer_status(self) -> list[dict]:
        """Snapshot pending buffers; injected clock keeps replays consistent."""
        now = self._clock()
        status = []
        for _key, votes in sorted(self._buffers.items()):
            oldest = min(v.timestamp for v in votes)
            status.append(
                {
                    "token_id": votes[0].token_id,
                    "side": votes[0].side,
                    "votes": len(votes),
                    "vwap_price": round(self._vwap(votes), 6),
                    "total_size_usd": round(sum(v.size_usd for v in votes), 2),
                    "time_remaining_seconds": max(
                        0.0, round(oldest + self.window_seconds - now, 3)
                    ),
                }
            )
        return status

    def _evaluate(self, votes: list[WalletTradeSignal]) -> QuorumResult | None:
        """Apply the price gate; the count condition is checked by the caller."""
        vwap = self._vwap(votes)
        if vwap <= 0 or vwap > self.max_acceptable_price:
            return None
        return QuorumResult(
            token_id=votes[0].token_id,
            side=votes[0].side,
            quorum_size=len(votes),
            wallets=tuple(v.wallet_address for v in votes),
            vwap_price=round(vwap, 6),
            total_size_usd=round(sum(v.size_usd for v in votes), 2),
            window_start=min(v.timestamp for v in votes),
        )

    @staticmethod
    def _vwap(votes: list[WalletTradeSignal]) -> float:
        """Size-weighted average entry; plain mean when sizes are unknown."""
        total_size = sum(v.size_usd for v in votes)
        if total_size > 0:
            return sum(v.entry_price * v.size_usd for v in votes) / total_size
        return sum(v.entry_price for v in votes) / len(votes)

    def _expire_stale(self, now: float) -> None:
        """Drop expired votes and prune the executed-key map."""
        cutoff = now - self.window_seconds
        expired = 0
        for key in list(self._buffers):
            fresh = [v for v in self._buffers[key] if v.timestamp >= cutoff]
            expired += len(self._buffers[key]) - len(fresh)
            if fresh:
                self._buffers[key] = fresh
            else:
                del self._buffers[key]
        if expired:
            self._stats["signals_expired"] += expired

        exec_cutoff = now - self.window_seconds * 2
        for key in [k for k, ts in self._executed.items() if ts < exec_cutoff]:
            del self._executed[key]
            self._price_reject_len.pop(key, None)

    @staticmethod
    def _empty_stats() -> dict[str, int]:
        return {
            "signals_received": 0,
            "signals_buffered": 0,
            "signals_expired": 0,
            "quorum_reached": 0,
            "quorum_rejected": 0,
            "duplicate_signals": 0,
        }
