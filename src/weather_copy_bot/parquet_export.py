"""Parquet data export for historical market data."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class MarketDataSchema:
    """Schema for market data export."""

    market_id: str = ""
    question: str = ""
    volume_usd: float = 0.0
    liquidity: float = 0.0
    created_at: datetime | None = None


@dataclass
class TradeDataSchema:
    """Schema for trade data export."""

    trade_id: str = ""
    market_id: str = ""
    price: float = 0.0
    size: float = 0.0
    side: str = ""
    timestamp: datetime | None = None


@dataclass
class PriceHistorySchema:
    """Schema for price history export."""

    market_id: str = ""
    timestamp: int = 0
    bid: float = 0.0
    ask: float = 0.0
    volume: float = 0.0


class ParquetExporter:
    """Export market data to Parquet format for efficient storage and analytics."""

    def __init__(self, output_dir: str | None = None) -> None:
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), "data", "parquet")
        self.output_dir = output_dir
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        """Ensure output directory exists."""
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def get_parquet_path(self, table_name: str) -> str:
        """Get the path for a parquet file."""
        return os.path.join(self.output_dir, f"{table_name}.parquet")

    async def export_markets(self, markets: list[MarketDataSchema]) -> str:
        """Export markets to Parquet format."""
        import pandas as pd

        data = [
            {
                "market_id": m.market_id,
                "question": m.question,
                "volume_usd": m.volume_usd,
                "liquidity": m.liquidity,
                "created_at": m.created_at,
            }
            for m in markets
        ]
        df = pd.DataFrame(data)
        path = self.get_parquet_path("markets")
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    async def export_trades(self, trades: list[TradeDataSchema]) -> str:
        """Export trades to Parquet format."""
        import pandas as pd

        data = [
            {
                "trade_id": t.trade_id,
                "market_id": t.market_id,
                "price": t.price,
                "size": t.size,
                "side": t.side,
                "timestamp": t.timestamp,
            }
            for t in trades
        ]
        df = pd.DataFrame(data)
        path = self.get_parquet_path("trades")
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    async def export_price_history(self, history: list[PriceHistorySchema]) -> str:
        """Export price history to Parquet format."""
        import pandas as pd

        data = [
            {
                "market_id": h.market_id,
                "timestamp": h.timestamp,
                "bid": h.bid,
                "ask": h.ask,
                "volume": h.volume,
            }
            for h in history
        ]
        df = pd.DataFrame(data)
        path = self.get_parquet_path("price_history")
        df.to_parquet(path, engine="pyarrow", index=False)
        return path
