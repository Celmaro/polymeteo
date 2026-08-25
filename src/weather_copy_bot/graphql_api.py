"""GraphQL API layer using Strawberry GraphQL."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

import strawberry


@strawberry.enum
class MarketCategory(Enum):
    SPORTS = "sports"
    POLITICS = "politics"
    ECONOMICS = "economics"
    WEATHER = "weather"
    CRYPTO = "crypto"
    OTHER = "other"


@strawberry.type
class PriceData:
    yes_price: float
    no_price: float
    volume: float
    updated_at: datetime


@strawberry.type
class MarketSummary:
    market_id: str
    question: str
    description: str
    category: MarketCategory
    current_price: PriceData
    liquidity: float
    volume_24h: float


@strawberry.type
class WalletPosition:
    wallet_address: str
    market_id: str
    position_size: float
    entry_price: float
    current_pnl: float
    unrealized_pnl: float


@strawberry.type
class BotPerformance:
    total_pnl: float
    win_rate: float
    total_trades: int
    avg_trade_size: float
    sharpe_ratio: float
    max_drawdown: float


@strawberry.type
class ConsensusSignal:
    market_id: str
    consensus_probability: float
    confidence: float
    num_sources: int
    weighted_sources: list[tuple[str, float]]


@strawberry.type
class Query:
    @strawberry.field
    def markets(self, category: MarketCategory | None = None) -> list[MarketSummary]:
        return []

    @strawberry.field
    def market(self, market_id: str) -> MarketSummary | None:
        return None

    @strawberry.field
    def positions(self, wallet_address: str | None = None) -> list[WalletPosition]:
        return []

    @strawberry.field
    def performance(self, wallet_address: str) -> BotPerformance | None:
        return None

    @strawberry.field
    def consensus(self, market_id: str) -> ConsensusSignal | None:
        return None


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def copy_trade(
        self,
        market_id: str,
        position_size: float,
        wallet_address: str
    ) -> WalletPosition:
        return WalletPosition(
            wallet_address=wallet_address,
            market_id=market_id,
            position_size=position_size,
            entry_price=0.5,
            current_pnl=0.0,
            unrealized_pnl=0.0,
        )

    @strawberry.mutation
    async def close_position(
        self,
        market_id: str,
        wallet_address: str
    ) -> WalletPosition:
        return WalletPosition(
            wallet_address=wallet_address,
            market_id=market_id,
            position_size=0.0,
            entry_price=0.0,
            current_pnl=0.0,
            unrealized_pnl=0.0,
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
