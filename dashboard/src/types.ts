export interface PerformanceSummary {
  mode: string
  starting_balance: number
  ending_balance: number
  total_pnl_usd: number
  total_return_pct: number
  win_rate: number
  trade_count: number
  avg_latency_ms: number
  median_latency_ms: number
  sharpe: number
  sortino: number
  max_drawdown_pct: number
  profit_factor: number
  best_trade_usd: number
  worst_trade_usd: number
  avg_copy_edge_bps: number
}

export interface WalletScorecard {
  wallet: string
  alias: string
  total_pnl_usd: number
  win_rate: number
  trade_count: number
  avg_latency_ms: number
  sharpe: number
  max_drawdown_pct: number
  profit_factor: number
  specialty_cities: string[]
  consistency_score: number
  copy_recommendation: string
}

export interface EquityPoint {
  timestamp: string
  equity_usd: number
  pnl_usd: number
  drawdown_pct: number
}

export interface Fill {
  fill_id: string
  target_wallet: string
  market_title: string
  city: string
  outcome: string
  side: string
  price: number
  size_usd: number
  pnl_usd: number
  latency_ms: number
  filled_at: string
  mode: string
}

export interface CityBreakdown {
  city: string
  trade_count: number
  pnl_usd: number
  win_rate: number
}

export interface LatencyBucket {
  bucket: string
  trade_count: number
  avg_pnl_usd: number
  win_rate: number
}

export interface DashboardPayload {
  generated_at: string
  headline: PerformanceSummary
  paper: PerformanceSummary
  backtest: PerformanceSummary
  wallets: WalletScorecard[]
  equity_curve: EquityPoint[]
  paper_equity: EquityPoint[]
  backtest_equity: EquityPoint[]
  recent_fills: Fill[]
  city_breakdown: CityBreakdown[]
  latency_buckets: LatencyBucket[]
  copy_funnel: Record<string, number>
  engine_status: Record<string, string | number>
}
