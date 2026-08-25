import { DashboardLayout, Panel, MetricCard } from "@/components/DashboardLayout";
import { formatCurrency, formatPercent } from "@/lib/utils";

const performanceMetrics = [
  { label: "Total P&L", value: formatCurrency(2847.32), trend: "up" },
  { label: "Win Rate", value: formatPercent(0.73), trend: "up" },
  { label: "Sharpe Ratio", value: "2.34", trend: "up" },
  { label: "Max Drawdown", value: "-12.5%", trend: "down" },
];

const pnlHistory = [
  { date: "2024-01", value: 450 },
  { date: "2024-02", value: 620 },
  { date: "2024-03", value: -180 },
  { date: "2024-04", value: 890 },
  { date: "2024-05", value: 450 },
  { date: "2024-06", value: 617 },
];

export default function AnalyticsPage() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <header>
          <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
          <p className="text-muted mt-1">Performance metrics and trading insights</p>
        </header>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {performanceMetrics.map((m) => (
            <MetricCard key={m.label} label={m.label} value={m.value} trend={m.trend as "up" | "down" | "neutral"} />
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="P&L History">
            <div className="h-48 flex items-end justify-between gap-2">
              {pnlHistory.map((p) => (
                <div key={p.date} className="flex flex-1 flex-col items-center gap-1">
                  <div
                    className={`w-full rounded-t ${
                      p.value >= 0 ? "bg-mint/60" : "bg-rose/60"
                    }`}
                    style={{ height: `${Math.abs(p.value) / 10}%` }}
                  />
                  <span className="text-xs text-muted">{p.date}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Category Performance">
            <div className="space-y-3">
              {[
                { category: "CRYPTO", pnl: 1450, trades: 24, winRate: 0.78 },
                { category: "SPORTS", pnl: 680, trades: 12, winRate: 0.67 },
                { category: "WEATHER", pnl: 420, trades: 8, winRate: 0.75 },
                { category: "ECONOMICS", pnl: 297, trades: 6, winRate: 0.83 },
              ].map((c) => (
                <div key={c.category} className="flex items-center justify-between rounded-lg border border-line bg-bg-0/40 p-3">
                  <div>
                    <span className="font-medium">{c.category}</span>
                    <span className="ml-2 text-xs text-muted">{c.trades} trades</span>
                  </div>
                  <div className="text-right">
                    <p className={`font-mono font-bold ${c.pnl >= 0 ? "text-mint" : "text-rose"}`}>
                      {formatCurrency(c.pnl)}
                    </p>
                    <span className="text-xs text-muted">WR: {formatPercent(c.winRate)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </DashboardLayout>
  );
}
