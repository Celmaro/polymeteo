import { DashboardLayout, MetricCard, Panel, Badge } from "@/components/DashboardLayout";
import { formatCurrency, formatPercent } from "@/lib/utils";

const metrics = [
  { label: "Total P&L", value: formatCurrency(2847.32), trend: "up" as const },
  { label: "Win Rate", value: formatPercent(0.73), trend: "up" as const },
  { label: "Active Positions", value: "12", trend: "neutral" as const },
  { label: "24h Volume", value: formatCurrency(45230), trend: "up" as const },
];

const topMarkets = [
  { question: "Will ETH exceed $4000 by end of year?", probability: 0.65, volume: 125000 },
  { question: "Will it rain in NYC on Christmas?", probability: 0.42, volume: 8900 },
  { question: "Will BTC break $100k in Q1?", probability: 0.38, volume: 234000 },
];

const recentTrades = [
  { market: "ETH $4000", side: "YES", size: 250, pnl: 87.50 },
  { market: "Rain NYC Xmas", side: "NO", size: 100, pnl: -32.00 },
  { market: "BTC $100k", side: "YES", size: 500, pnl: 156.25 },
];

export default function DashboardPage() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-wider text-cyan">Weather Copy Trading</p>
            <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          </div>
          <Badge variant="primary">Live</Badge>
        </header>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {metrics.map((m) => (
            <MetricCard key={m.label} {...m} />
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          <Panel title="Top Markets" className="lg:col-span-2">
            <div className="space-y-3">
              {topMarkets.map((m) => (
                <div key={m.question} className="flex items-center justify-between rounded-lg border border-line bg-bg-0/40 p-3">
                  <div className="flex-1">
                    <p className="text-sm">{m.question}</p>
                    <p className="font-mono text-xs text-muted">{formatCurrency(m.volume)} vol</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-lg font-bold text-mint">{formatPercent(m.probability)}</p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Recent Trades">
            <div className="space-y-2">
              {recentTrades.map((t) => (
                <div key={t.market} className="flex items-center justify-between text-sm">
                  <span>{t.market}</span>
                  <span className={t.pnl >= 0 ? "text-mint font-mono" : "text-rose font-mono"}>
                    {t.pnl >= 0 ? "+" : ""}{formatCurrency(t.pnl)}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </DashboardLayout>
  );
}
