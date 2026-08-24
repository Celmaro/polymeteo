"""Order Book Imbalance (OBI) Filter for Market Microstructure Analysis.

Prevents execution when alpha has likely been arbitraged away.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class OBISignal(str, Enum):
    """OBI signal interpretation."""
    STRONG_BUY = "strong_buy"      # OBI > 0.6 (heavy ask side)
    MODERATE_BUY = "moderate_buy"  # 0.3 < OBI <= 0.6
    NEUTRAL = "neutral"            # -0.3 <= OBI <= 0.3
    MODERATE_SELL = "moderate_sell"  # -0.6 <= OBI < -0.3
    STRONG_SELL = "strong_sell"    # OBI < -0.6
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class OrderBookLevel:
    """A single level in the order book."""
    price: float
    size: float  # In USD
    
    @property
    def depth(self) -> float:
        return self.size


@dataclass
class OrderBook:
    """Simplified order book representation."""
    bids: List[OrderBookLevel]  # Buy side (sorted high to low)
    asks: List[OrderBookLevel]  # Sell side (sorted low to high)
    timestamp: float
    
    @property
    def mid_price(self) -> float:
        """Mid price between best bid and ask."""
        if not self.bids or not self.asks:
            return 0.0
        return (self.bids[0].price + self.asks[0].price) / 2
    
    @property
    def spread(self) -> float:
        """Spread between best bid and ask."""
        if not self.bids or not self.asks:
            return 0.0
        return self.asks[0].price - self.bids[0].price
    
    @property
    def spread_bps(self) -> float:
        """Spread in basis points."""
        if self.mid_price == 0:
            return 0.0
        return (self.spread / self.mid_price) * 10000


@dataclass
class OBIMetrics:
    """Order Book Imbalance metrics."""
    obi: float  # OBI value between -1 and 1
    signal: OBISignal
    vwm_price: float  # Volume Weighted Midprice
    vwm_spread: float
    book_depth_ratio: float  # Ratio of bid depth to ask depth
    top_levels_imbalance: float  # Imbalance at top N levels
    slope: float  # Book slope (depth decay rate)


@dataclass
class OBIResult:
    """Result of OBI filter check."""
    passed: bool
    reason: str
    obi: float
    signal: OBISignal
    metrics: OBIMetrics
    recommendation: str  # "execute", "skip", "adjust_size", "wait"


class OBIAnalyzer:
    """
    Order Book Imbalance analyzer for market microstructure signals.
    
    OBI = (BidDepth - AskDepth) / (BidDepth + AskDepth)
    
    Usage:
        analyzer = OBIAnalyzer(threshold=0.5)
        obi = analyzer.calculate_obi(order_book)
        
        if obi < -0.5:
            # Heavy buy pressure, likely already arbitraged
            skip_trade()
    """

    def __init__(
        self,
        obi_threshold: float = 0.5,  # Skip if OBI > 0.5 (buy pressure)
        min_levels: int = 5,  # Min levels for OBI calculation
        max_spread_bps: float = 50.0,  # Max acceptable spread
        slope_threshold: float = 0.3,  # Book slope threshold
    ):
        """
        Initialize OBI analyzer.
        
        Args:
            obi_threshold: OBI threshold to trigger skip (0-1)
            min_levels: Minimum levels for OBI calculation
            max_spread_bps: Maximum spread in basis points
            slope_threshold: Book slope threshold for rejection
        """
        self.obi_threshold = obi_threshold
        self.min_levels = min_levels
        self.max_spread = max_spread_bps
        self.slope_threshold = slope_threshold

    def calculate_obi(
        self,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        levels: int = 5,
    ) -> OBIMetrics:
        """
        Calculate OBI metrics from order book levels.
        
        Args:
            bids: List of (price, size) tuples for bids
            asks: List of (price, size) tuples for asks
            levels: Number of levels to consider
            
        Returns:
            OBIMetrics with all calculations
        """
        # Take top N levels
        bid_levels = bids[:levels]
        ask_levels = asks[:levels]
        
        if len(bid_levels) < self.min_levels or len(ask_levels) < self.min_levels:
            return OBIMetrics(
                obi=0.0,
                signal=OBISignal.INSUFFICIENT_DATA,
                vwm_price=0.0,
                vwm_spread=0.0,
                book_depth_ratio=0.0,
                top_levels_imbalance=0.0,
                slope=0.0,
            )
        
        # Calculate depths
        bid_depth = sum(size for _, size in bid_levels)
        ask_depth = sum(size for _, size in ask_levels)
        
        # OBI formula
        if bid_depth + ask_depth == 0:
            obi = 0.0
        else:
            obi = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        
        # Book depth ratio
        book_depth_ratio = bid_depth / ask_depth if ask_depth > 0 else 0.0
        
        # Volume Weighted Midprice (VWM)
        vwm_numerator = 0.0
        vwm_denominator = 0.0
        
        for price, size in bid_levels + ask_levels:
            vwm_numerator += price * size
            vwm_denominator += size
        
        vwm_price = vwm_numerator / vwm_denominator if vwm_denominator > 0 else 0.0
        
        # Top levels imbalance (just top 1-2 levels)
        top_bid = bid_levels[0][1] if bid_levels else 0
        top_ask = ask_levels[0][1] if ask_levels else 0
        top_levels_imbalance = (top_bid - top_ask) / (top_bid + top_ask) if (top_bid + top_ask) > 0 else 0.0
        
        # Book slope (depth decay rate)
        if len(bid_levels) >= 2:
            bid_slope = (bid_levels[0][1] - bid_levels[-1][1]) / (len(bid_levels) - 1)
        else:
            bid_slope = 0.0
            
        if len(ask_levels) >= 2:
            ask_slope = (ask_levels[0][1] - ask_levels[-1][1]) / (len(ask_levels) - 1)
        else:
            ask_slope = 0.0
        
        slope = (bid_slope + ask_slope) / 2
        
        # Signal interpretation
        if obi > 0.6:
            signal = OBISignal.STRONG_BUY
        elif obi > 0.3:
            signal = OBISignal.MODERATE_BUY
        elif obi < -0.6:
            signal = OBISignal.STRONG_SELL
        elif obi < -0.3:
            signal = OBISignal.MODERATE_SELL
        else:
            signal = OBISignal.NEUTRAL
        
        return OBIMetrics(
            obi=round(obi, 4),
            signal=signal,
            vwm_price=round(vwm_price, 6),
            vwm_spread=round((asks[0][0] - bids[0][0]) / vwm_price * 10000 if vwm_price > 0 else 0, 2),
            book_depth_ratio=round(book_depth_ratio, 2),
            top_levels_imbalance=round(top_levels_imbalance, 4),
            slope=round(slope, 4),
        )

    def check_order_book(
        self,
        order_book: OrderBook,
        target_side: str,  # "BUY" or "SELL"
        target_price: float,
    ) -> OBIResult:
        """
        Check if order should be executed based on order book.
        
        Args:
            order_book: Current order book state
            target_side: Side we want to trade
            target_price: Target entry price
            
        Returns:
            OBIResult with recommendation
        """
        bids = [(level.price, level.size) for level in order_book.bids]
        asks = [(level.price, level.size) for level in order_book.asks]
        
        metrics = self.calculate_obi(bids, asks)
        
        # Check spread
        if order_book.spread_bps > self.max_spread:
            return OBIResult(
                passed=False,
                reason=f"Spread too wide: {order_book.spread_bps:.1f} bps > {self.max_spread} bps",
                obi=metrics.obi,
                signal=metrics.signal,
                metrics=metrics,
                recommendation="skip",
            )
        
        # Check slope (flat book = illiquid)
        if abs(metrics.slope) < self.slope_threshold and len(bids) > 3:
            return OBIResult(
                passed=False,
                reason=f"Book slope too flat: {metrics.slope:.4f} < {self.slope_threshold}",
                obi=metrics.obi,
                signal=metrics.signal,
                metrics=metrics,
                recommendation="skip",
            )
        
        # OBI-based logic
        if target_side.upper() == "BUY":
            # For BUY, we look at asks (what we're buying)
            # High positive OBI means heavy buy pressure = good for us
            if metrics.obi > self.obi_threshold:
                return OBIResult(
                    passed=False,
                    reason=f"ASK side too thin: OBI={metrics.obi:.2f} (heavy buy pressure)",
                    obi=metrics.obi,
                    signal=metrics.signal,
                    metrics=metrics,
                    recommendation="adjust_size",
                )
            
            # Check if target price is still valid
            if order_book.asks and target_price > order_book.asks[0].price * 1.01:
                return OBIResult(
                    passed=False,
                    reason="Target price no longer valid",
                    obi=metrics.obi,
                    signal=metrics.signal,
                    metrics=metrics,
                    recommendation="skip",
                )
                
        else:  # SELL
            # For SELL, we look at bids (what we're selling)
            # High negative OBI means heavy sell pressure = good for us
            if metrics.obi < -self.obi_threshold:
                return OBIResult(
                    passed=False,
                    reason=f"BID side too thin: OBI={metrics.obi:.2f} (heavy sell pressure)",
                    obi=metrics.obi,
                    signal=metrics.signal,
                    metrics=metrics,
                    recommendation="adjust_size",
                )
            
            # Check if target price is still valid
            if order_book.bids and target_price < order_book.bids[0].price * 0.99:
                return OBIResult(
                    passed=False,
                    reason="Target price no longer valid",
                    obi=metrics.obi,
                    signal=metrics.signal,
                    metrics=metrics,
                    recommendation="skip",
                )
        
        return OBIResult(
            passed=True,
            reason="Order book conditions acceptable",
            obi=metrics.obi,
            signal=metrics.signal,
            metrics=metrics,
            recommendation="execute",
        )

    def estimate_slippage(
        self,
        order_book: OrderBook,
        side: str,
        size_usd: float,
    ) -> float:
        """
        Estimate slippage for a given order size.
        
        Args:
            order_book: Current order book
            side: BUY or SELL
            size_usd: Order size in USD
            
        Returns:
            Estimated slippage in basis points
        """
        if side.upper() == "BUY":
            levels = [(l.price, l.size) for l in order_book.asks]
        else:
            levels = [(l.price, l.size) for l in order_book.bids]
        
        if not levels:
            return 100.0  # Unknown, assume high slippage
        
        remaining = size_usd
        total_cost = 0.0
        avg_price = 0.0
        
        for price, size in levels:
            fill_size = min(remaining, size)
            total_cost += fill_size * price
            remaining -= fill_size
            avg_price += fill_size * price
            
            if remaining <= 0:
                break
        
        if remaining > 0:
            # Order too large for available liquidity
            return 100.0
        
        avg_price = total_cost / size_usd if size_usd > 0 else levels[0][0]
        reference_price = levels[0][0]
        
        slippage_bps = abs(avg_price - reference_price) / reference_price * 10000
        
        return round(slippage_bps, 2)


class OBIIntegration:
    """
    Integration layer for OBI filter with Quorum Engine.
    
    Automatically checks order book before executing quorum signals.
    """

    def __init__(
        self,
        obi_analyzer: OBIAnalyzer,
        order_book_provider: Any = None,  # Callable that returns OrderBook
        slippage_limit_bps: float = 50.0,
    ):
        """
        Initialize OBI integration.
        
        Args:
            obi_analyzer: OBIAnalyzer instance
            order_book_provider: Optional async function to get order book
            slippage_limit_bps: Maximum acceptable slippage
        """
        self.analyzer = obi_analyzer
        self.order_book_provider = order_book_provider
        self.slippage_limit = slippage_limit_bps
        
        self._stats = {
            "checks_performed": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "skipped": 0,
            "adjusted": 0,
        }

    async def check_before_execution(
        self,
        token_id: str,
        side: str,
        target_price: float,
        size_usd: float,
    ) -> OBIResult:
        """
        Check order book before execution.
        
        Args:
            token_id: Token to trade
            side: BUY or SELL
            target_price: Target entry price
            size_usd: Order size in USD
            
        Returns:
            OBIResult with recommendation
        """
        self._stats["checks_performed"] += 1
        
        # Get order book
        if self.order_book_provider:
            order_book = await self.order_book_provider(token_id)
        else:
            # Mock order book for testing
            order_book = OrderBook(
                bids=[
                    OrderBookLevel(price=0.50, size=100.0),
                    OrderBookLevel(price=0.49, size=80.0),
                    OrderBookLevel(price=0.48, size=60.0),
                ],
                asks=[
                    OrderBookLevel(price=0.51, size=100.0),
                    OrderBookLevel(price=0.52, size=80.0),
                    OrderBookLevel(price=0.53, size=60.0),
                ],
                timestamp=0.0,
            )
        
        # Check order book
        result = self.analyzer.check_order_book(order_book, side, target_price)
        
        # Check slippage
        if result.passed:
            slippage = self.analyzer.estimate_slippage(order_book, side, size_usd)
            
            if slippage > self.slippage_limit:
                result.passed = False
                result.reason = f"Slippage too high: {slippage:.1f} bps > {self.slippage_limit} bps"
                result.recommendation = "adjust_size"
                self._stats["adjusted"] += 1
            else:
                self._stats["checks_passed"] += 1
        
        if not result.passed:
            self._stats["checks_failed"] += 1
            if result.recommendation == "skip":
                self._stats["skipped"] += 1
        
        logger.info(
            f"[OBI] {token_id} {side}: OBI={result.obi:.2f}, "
            f"passed={result.passed}, rec={result.recommendation}"
        )
        
        return result

    def get_stats(self) -> Dict:
        """Get OBI integration statistics."""
        return {
            **self._stats,
            "pass_rate": (
                self._stats["checks_passed"] / max(1, self._stats["checks_performed"]) * 100
            ),
        }
