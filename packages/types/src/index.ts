export type MarketCategory =
  | "sports"
  | "politics"
  | "economics"
  | "weather"
  | "crypto"
  | "other";

export type MarketResolution = "binary" | "multiple_choice" | "range" | "scalar";

export interface PriceData {
  yes_price: number;
  no_price: number;
  volume: number;
  updated_at: string;
}

export interface MarketSummary {
  market_id: string;
  question: string;
  description: string;
  category: MarketCategory;
  current_price: PriceData;
  liquidity: number;
  volume_24h: number;
}

export interface WalletPosition {
  wallet_address: string;
  market_id: string;
  position_size: number;
  entry_price: number;
  current_pnl: number;
  unrealized_pnl: number;
}

export interface ConsensusSignal {
  market_id: string;
  consensus_probability: number;
  confidence: number;
  num_sources: number;
  sources: Array<{
    source: string;
    probability: number;
  }>;
}

export interface BotPerformance {
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  avg_trade_size: number;
  sharpe_ratio: number;
  max_drawdown: number;
}

export interface TradeSignal {
  signal_id: string;
  market_id: string;
  direction: "YES" | "NO";
  confidence: number;
  source: string;
  price: number;
  action: "BUY" | "HOLD" | "CLOSE";
  size: number;
  timestamp: string;
}

export interface RiskMetrics {
  kelly_fraction: number;
  position_size: number;
  expected_value: number;
  max_loss: number;
  liquidity_adjusted_size: number;
}
