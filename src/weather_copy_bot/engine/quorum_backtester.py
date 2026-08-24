"""Quorum Backtester for Historical Strategy Testing.

Tests the quorum-based copy trading strategy on historical data.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Callable
from collections import defaultdict
import time

from .quorum import QuorumEngine, WalletTradeSignal, WalletCategory, QuorumResult
from ..db import DatabaseManager
from ..db.models import Signal, Decision, Fill

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for quorum backtest."""
    min_quorum_count: int = 2
    min_weighted_score: float = 2.0
    window_seconds: int = 600
    max_acceptable_price: float = 0.85
    max_slippage_bps: int = 50
    include_wallet_filter: bool = True
    min_weather_score: float = 0.3


@dataclass
class BacktestSignal:
    """A signal for backtesting."""
    signal_id: str
    wallet_address: str
    wallet_category: WalletCategory
    token_id: str
    side: str
    price: float
    timestamp: datetime
    market_title: Optional[str] = None


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    config: BacktestConfig
    start_date: datetime
    end_date: datetime
    total_signals: int
    filtered_signals: int
    quorum_hits: int
    quorum_misses: int
    orders_executed: int
    orders_profitable: int
    total_pnl_usd: float
    avg_pnl_per_trade: float
    win_rate: float
    max_consecutive_losses: int
    sharpe_ratio: float
    max_drawdown: float
    avg_latency_ms: float
    avg_quorum_time_seconds: float
    pnl_by_category: Dict[str, float]
    pnl_by_side: Dict[str, float]


class QuorumBacktester:
    """
    Backtester for quorum-based copy trading strategy.
    
    Tests how the strategy would have performed on historical signals.
    """
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        config: Optional[BacktestConfig] = None,
    ):
        """
        Initialize QuorumBacktester.
        
        Args:
            db_manager: Optional database manager for persistence
            config: Backtest configuration
        """
        self.db = db_manager
        self.config = config or BacktestConfig()
        
        # Initialize quorum engine with config
        self._quorum_engine = QuorumEngine(
            min_quorum_count=self.config.min_quorum_count,
            min_weighted_score=self.config.min_weighted_score,
            window_seconds=self.config.window_seconds,
            max_acceptable_price=self.config.max_acceptable_price,
            max_slippage_bps=self.config.max_slippage_bps,
        )
        
        # Stats
        self._stats = {
            "total_signals": 0,
            "filtered_signals": 0,
            "quorum_hits": 0,
            "quorum_misses": 0,
            "orders_executed": 0,
            "orders_profitable": 0,
            "orders_losing": 0,
            "pnl_by_category": defaultdict(float),
            "pnl_by_side": defaultdict(float),
            "latencies": [],
            "quorum_times": [],
            "consecutive_losses": 0,
            "max_consecutive_losses": 0,
        }
        
        # Running balance
        self._balance = 10000.0  # Starting with $10k
        self._peak_balance = 10000.0
        self._drawdowns = []
    
    def _create_signal(self, bt_signal: BacktestSignal) -> WalletTradeSignal:
        """Convert backtest signal to quorum signal."""
        return WalletTradeSignal(
            signal_id=bt_signal.signal_id,
            wallet_address=bt_signal.wallet_address,
            wallet_category=bt_signal.wallet_category,
            token_id=bt_signal.token_id,
            side=bt_signal.side,
            entry_price=bt_signal.price,
            timestamp=bt_signal.timestamp.timestamp(),
        )
    
    def _simulate_fill(
        self,
        consensus: QuorumResult,
        exit_price: float,
    ) -> float:
        """
        Simulate filling an order and calculate P&L.
        
        Args:
            consensus: Quorum consensus result
            exit_price: Price when position was closed
            
        Returns:
            P&L in USD
        """
        # Size per order (fixed for now)
        position_size = 100.0  # $100 per trade
        
        if consensus.side.upper() == "BUY":
            # Long position: profit if exit > entry
            pnl = position_size * (exit_price - consensus.consensus_price) / consensus.consensus_price
        else:
            # Short position: profit if exit < entry
            pnl = position_size * (consensus.consensus_price - exit_price) / consensus.consensus_price
        
        return pnl
    
    def _update_drawdown(self) -> float:
        """Update drawdown tracking. Returns current drawdown."""
        if self._balance > self._peak_balance:
            self._peak_balance = self._balance
        drawdown = (self._peak_balance - self._balance) / self._peak_balance
        self._drawdowns.append(drawdown)
        return drawdown
    
    def run(
        self,
        signals: List[BacktestSignal],
        exit_prices: Dict[str, float],  # token_id -> exit price
        get_pnl_fn: Optional[Callable] = None,  # Custom P&L calculation
    ) -> BacktestResult:
        """
        Run backtest on historical signals.
        
        Args:
            signals: List of historical signals
            exit_prices: Exit prices for each token
            get_pnl_fn: Optional custom P&L function
            
        Returns:
            BacktestResult with performance metrics
        """
        logger.info(f"[Backtest] Starting with {len(signals)} signals")
        
        # Sort signals by timestamp
        signals = sorted(signals, key=lambda s: s.timestamp)
        
        start_date = signals[0].timestamp if signals else datetime.now(timezone.utc)
        end_date = signals[-1].timestamp if signals else datetime.now(timezone.utc)
        
        for signal in signals:
            self._stats["total_signals"] += 1
            
            # Create quorum signal
            q_signal = self._create_signal(signal)
            
            # Register signal
            consensus = self._quorum_engine.register_signal(q_signal)
            
            if consensus:
                self._stats["quorum_hits"] += 1
                
                # Get exit price
                exit_price = exit_prices.get(signal.token_id, signal.price)
                
                # Calculate P&L
                if get_pnl_fn:
                    pnl = get_pnl_fn(consensus, exit_price)
                else:
                    pnl = self._simulate_fill(consensus, exit_price)
                
                # Update stats
                self._balance += pnl
                self._stats["total_pnl"] = self._balance - 10000.0
                
                if pnl > 0:
                    self._stats["orders_profitable"] += 1
                    self._stats["consecutive_losses"] = 0
                else:
                    self._stats["orders_losing"] += 1
                    self._stats["consecutive_losses"] += 1
                    self._stats["max_consecutive_losses"] = max(
                        self._stats["max_consecutive_losses"],
                        self._stats["consecutive_losses"]
                    )
                
                # P&L by category and side
                self._stats["pnl_by_category"][signal.wallet_category.value] += pnl
                self._stats["pnl_by_side"][signal.side.upper()] += pnl
                
                # Track drawdown
                drawdown = self._update_drawdown()
                
                logger.info(
                    f"[Backtest] Quorum hit: {signal.token_id} "
                    f"{signal.side} @ {consensus.consensus_price:.4f}, "
                    f"P&L: ${pnl:.2f}, Balance: ${self._balance:.2f}"
                )
            else:
                self._stats["quorum_misses"] += 1
        
        # Calculate final metrics
        total_orders = self._stats["orders_profitable"] + self._stats["orders_losing"]
        
        return BacktestResult(
            config=self.config,
            start_date=start_date,
            end_date=end_date,
            total_signals=self._stats["total_signals"],
            filtered_signals=self._stats["filtered_signals"],
            quorum_hits=self._stats["quorum_hits"],
            quorum_misses=self._stats["quorum_misses"],
            orders_executed=total_orders,
            orders_profitable=self._stats["orders_profitable"],
            total_pnl_usd=self._stats["total_pnl"],
            avg_pnl_per_trade=(
                self._stats["total_pnl"] / total_orders if total_orders > 0 else 0
            ),
            win_rate=(
                self._stats["orders_profitable"] / total_orders if total_orders > 0 else 0
            ),
            max_consecutive_losses=self._stats["max_consecutive_losses"],
            sharpe_ratio=self._calculate_sharpe(),
            max_drawdown=max(self._drawdowns) if self._drawdowns else 0,
            avg_latency_ms=sum(self._stats["latencies"]) / len(self._stats["latencies"]) if self._stats["latencies"] else 0,
            avg_quorum_time_seconds=sum(self._stats["quorum_times"]) / len(self._stats["quorum_times"]) if self._stats["quorum_times"] else 0,
            pnl_by_category=dict(self._stats["pnl_by_category"]),
            pnl_by_side=dict(self._stats["pnl_by_side"]),
        )
    
    def _calculate_sharpe(self) -> float:
        """Calculate Sharpe ratio from P&L series."""
        if len(self._drawdowns) < 2:
            return 0.0
        
        # Simplified: use drawdown as proxy for volatility
        avg_return = self._stats["total_pnl"] / 10000.0
        volatility = max(self._drawdowns) if self._drawdowns else 1.0
        
        if volatility == 0:
            return 0.0
        
        return (avg_return / volatility) * (252 ** 0.5)  # Annualized
    
    def run_parameter_sweep(
        self,
        signals: List[BacktestSignal],
        exit_prices: Dict[str, float],
        param_grid: Dict[str, List],
    ) -> List[BacktestResult]:
        """
        Run backtest with multiple parameter combinations.
        
        Args:
            signals: Historical signals
            exit_prices: Exit prices
            param_grid: Parameters to sweep
            
        Returns:
            List of BacktestResults for each parameter combination
        """
        from itertools import product
        
        results = []
        
        # Generate all combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        for values in product(*param_values):
            params = dict(zip(param_names, values))
            
            logger.info(f"[Backtest] Testing params: {params}")
            
            # Create config
            config = BacktestConfig(**params)
            
            # Run backtest
            backtester = QuorumBacktester(config=config)
            result = backtester.run(signals, exit_prices)
            
            results.append(result)
        
        # Sort by Sharpe ratio
        results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
        
        return results
    
    def get_stats(self) -> Dict:
        """Get backtest statistics."""
        return {
            **self._stats,
            "balance": self._balance,
            "peak_balance": self._peak_balance,
            "current_drawdown": self._update_drawdown(),
        }


def generate_synthetic_signals(
    num_signals: int = 100,
    num_wallets: int = 10,
    num_tokens: int = 20,
    start_date: datetime = None,
) -> List[BacktestSignal]:
    """
    Generate synthetic signals for testing.
    
    Args:
        num_signals: Number of signals to generate
        num_wallets: Number of unique wallets
        num_tokens: Number of unique tokens
        
    Returns:
        List of synthetic BacktestSignals
    """
    import random
    
    start_date = start_date or datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    wallets = [f"0x{i:040x}" for i in range(num_wallets)]
    tokens = [f"TOKEN_{i}" for i in range(num_tokens)]
    categories = list(WalletCategory)
    sides = ["BUY", "SELL"]
    
    signals = []
    base_time = start_date.timestamp()
    
    for i in range(num_signals):
        timestamp = datetime.fromtimestamp(
            base_time + random.uniform(0, 86400 * 30),  # 30 days
            tz=timezone.utc
        )
        
        signal = BacktestSignal(
            signal_id=f"SIG_{i}",
            wallet_address=random.choice(wallets),
            wallet_category=random.choice(categories),
            token_id=random.choice(tokens),
            side=random.choice(sides),
            price=random.uniform(0.1, 0.9),
            timestamp=timestamp,
            market_title="Weather market" if random.random() > 0.3 else "Non-weather market",
        )
        signals.append(signal)
    
    return sorted(signals, key=lambda s: s.timestamp)
