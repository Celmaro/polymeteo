"""Quorum Engine: Sliding Window Consensus for Copy Trading.

Implements a consensus-based signal aggregation system that waits for
multiple wallets to agree on a trade before executing.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class WalletCategory(str, Enum):
    """Categories for wallet weighting."""
    SMART_BOT = "smart_bot"      # Weight: 1.5
    WHALE = "whale"              # Weight: 0.8
    SMART_TRADER = "smart_trader"  # Weight: 1.2
    REGULAR = "regular"          # Weight: 1.0


@dataclass
class WalletTradeSignal:
    """A trade signal from a target wallet."""
    signal_id: str = field(default_factory=lambda: str(uuid4()))
    wallet_address: str = ""
    wallet_category: WalletCategory = WalletCategory.REGULAR
    token_id: str = ""
    side: str = ""  # BUY or SELL
    entry_price: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    @property
    def weight(self) -> float:
        """Get weight based on wallet category."""
        weights = {
            WalletCategory.SMART_BOT: 1.5,
            WalletCategory.WHALE: 0.8,
            WalletCategory.SMART_TRADER: 1.2,
            WalletCategory.REGULAR: 1.0,
        }
        return weights.get(self.wallet_category, 1.0)


@dataclass
class QuorumResult:
    """Result when quorum is reached."""
    token_id: str
    side: str
    quorum_size: int
    weighted_score: float
    wallets: List[str]
    categories: List[WalletCategory]
    avg_price: float
    consensus_price: float


class QuorumEngine:
    """Sliding window consensus engine for copy trading signals."""
    
    def __init__(
        self,
        min_quorum_count: int = 2,
        min_weighted_score: float = 2.0,
        window_seconds: int = 600,  # 10 minutes
        max_acceptable_price: float = 0.85,
        max_slippage_bps: int = 50,  # 0.5%
    ):
        """
        Initialize QuorumEngine.
        
        Args:
            min_quorum_count: Minimum number of unique wallets required
            min_weighted_score: Minimum sum of weights to reach consensus
            window_seconds: Time window for signal aggregation
            max_acceptable_price: Don't execute if price above this
            max_slippage_bps: Max acceptable slippage in basis points
        """
        self.min_quorum_count = min_quorum_count
        self.min_weighted_score = min_weighted_score
        self.window_seconds = window_seconds
        self.max_acceptable_price = max_acceptable_price
        self.max_slippage_bps = max_slippage_bps
        
        # Signal buffer: {(token_id, side): [WalletTradeSignal, ...]}
        self._buffer: Dict[str, List[WalletTradeSignal]] = defaultdict(list)
        
        # Executed tokens (idempotency)
        self._executed: Set[str] = set()
        
        # Stats
        self._stats = {
            "signals_received": 0,
            "signals_buffered": 0,
            "signals_expired": 0,
            "quorum_reached": 0,
            "quorum_rejected": 0,
            "duplicate_signals": 0,
        }
    
    def _make_key(self, token_id: str, side: str) -> str:
        """Create buffer key."""
        return f"{token_id}_{side.upper()}"
    
    def _cleanup_expired(self, key: str, current_time: float) -> int:
        """Remove expired signals from buffer."""
        before = len(self._buffer[key])
        self._buffer[key] = [
            sig for sig in self._buffer[key]
            if current_time - sig.timestamp <= self.window_seconds
        ]
        expired = before - len(self._buffer[key])
        self._stats["signals_expired"] += expired
        return expired
    
    def _cleanup_all_expired(self, current_time: float) -> None:
        """Clean up all expired signals."""
        for key in list(self._buffer.keys()):
            self._cleanup_expired(key, current_time)
    
    def register_signal(self, signal: WalletTradeSignal) -> Optional[QuorumResult]:
        """
        Register a wallet signal and check for quorum.
        
        Args:
            signal: The wallet trade signal to register
            
        Returns:
            QuorumResult if quorum is reached, None otherwise
        """
        self._stats["signals_received"] += 1
        current_time = time.time()
        
        key = self._make_key(signal.token_id, signal.side)
        
        # Check idempotency
        if key in self._executed:
            self._stats["duplicate_signals"] += 1
            logger.debug(f"Signal rejected: already executed for {key}")
            return None
        
        # Cleanup expired signals
        self._cleanup_expired(key, current_time)
        
        # Check for duplicate wallet
        existing_wallets = {s.wallet_address for s in self._buffer[key]}
        if signal.wallet_address in existing_wallets:
            self._stats["duplicate_signals"] += 1
            logger.debug(f"Signal rejected: duplicate wallet {signal.wallet_address[:8]}")
            return None
        
        # Add signal to buffer
        self._buffer[key].append(signal)
        self._stats["signals_buffered"] += 1
        
        signals = self._buffer[key]
        
        logger.info(
            f"[Quorum] {len(signals)}/{self.min_quorum_count} signals for {key} "
            f"({signal.wallet_category.value} - {signal.wallet_address[:8]}...)"
        )
        
        # Check quorum conditions
        if self._check_quorum(key, signals):
            result = self._create_consensus(key, signals)
            self._executed.add(key)
            self._stats["quorum_reached"] += 1
            
            logger.info(
                f"[Quorum] ✅ CONSENSUS REACHED! {result.quorum_size} wallets, "
                f"score={result.weighted_score:.2f}, price={result.consensus_price:.4f}"
            )
            return result
        
        return None
    
    def _check_quorum(self, key: str, signals: List[WalletTradeSignal]) -> bool:
        """Check if quorum conditions are met."""
        # Condition 1: Minimum number of unique wallets
        if len(signals) < self.min_quorum_count:
            return False
        
        # Condition 2: Minimum weighted score
        weighted_sum = sum(s.weight for s in signals)
        if weighted_sum < self.min_weighted_score:
            logger.debug(f"Weighted score {weighted_sum:.2f} < {self.min_weighted_score}")
            return False
        
        # Condition 3: Price check
        avg_price = sum(s.entry_price for s in signals) / len(signals)
        if avg_price > self.max_acceptable_price:
            logger.warning(f"Quorum reached but price too high: {avg_price:.4f}")
            self._stats["quorum_rejected"] += 1
            return False
        
        return True
    
    def _create_consensus(
        self, 
        key: str, 
        signals: List[WalletTradeSignal]
    ) -> QuorumResult:
        """Create consensus result from signals."""
        avg_price = sum(s.entry_price for s in signals) / len(signals)
        weighted_score = sum(s.weight for s in signals)
        
        return QuorumResult(
            token_id=signals[0].token_id,
            side=signals[0].side,
            quorum_size=len(signals),
            weighted_score=weighted_score,
            wallets=[s.wallet_address for s in signals],
            categories=[s.wallet_category for s in signals],
            avg_price=avg_price,
            consensus_price=avg_price,
        )
    
    def get_buffer_status(self, token_id: str, side: str) -> Dict:
        """Get current buffer status for a token/side."""
        key = self._make_key(token_id, side)
        signals = self._buffer.get(key, [])
        
        return {
            "token_id": token_id,
            "side": side,
            "signal_count": len(signals),
            "weighted_score": sum(s.weight for s in signals),
            "min_required": self.min_quorum_count,
            "weight_required": self.min_weighted_score,
            "executed": key in self._executed,
            "time_remaining": max(
                0, 
                self.window_seconds - (time.time() - signals[0].timestamp)
            ) if signals else self.window_seconds,
        }
    
    def reset(self) -> None:
        """Reset the engine state."""
        self._buffer.clear()
        self._executed.clear()
        logger.info("[Quorum] Engine reset")
    
    def get_stats(self) -> Dict:
        """Get engine statistics."""
        return {
            **self._stats,
            "buffer_size": sum(len(v) for v in self._buffer.values()),
            "executed_count": len(self._executed),
        }
    
    async def run_cleanup_task(self, interval: int = 60) -> None:
        """Background task to cleanup expired signals."""
        while True:
            await asyncio.sleep(interval)
            self._cleanup_all_expired(time.time())
            logger.debug(f"[Quorum] Cleanup: {self.get_stats()}")
