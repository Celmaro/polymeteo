import { DashboardLayout, Panel, MetricCard } from "../components/DashboardLayout";
import { formatCurrency, formatPercent, getStatusColor } from "../lib/utils";

const performanceMetrics = [
  { label: "Total Return", value: "+24.8%", sub: "$6,234.50", trend: "up" as const },
  { label: "Sharpe Ratio", value: "2.34", sub: "Excellent", trend: "up" as const },
  { label: "Win Rate", value: "68%", sub: "127/186 trades", trend: "neutral" as const },
  { label: "Max Drawdown", value: "-8.2%", sub: "Dec 2024", trend: "down" as const },
];

const weeklyPerformance = [
  { week: "Week 1", pnl: 1234.5, trades: 12, winRate: 0.75 },
  { week: "Week 2", pnl: -234.2, trades: 8, winRate: 0.50 },
  { week: "Week 3", pnl: 1892.3, trades: 15, winRate: 0.73 },
  { week: "Week 4", pnl: 456.8, trades: 10, winRate: 0.60 },
  { week: "This Week", pnl: 2156.4, trades: 6, winRate: 0.83 },
];

const topPerformers = [
  { market: "BTC > $100K by 2025", pnl: 1234.5, return: 0.45 },
  { market: "ETH flip BTC market cap", pnl: 567.2, return: 0.23 },
  { market: "Fed rate cut March", pnl: 892.3, return: 0.18 },
  { market: "Temperature > 30°C", pnl: 234.8, return: 0.12 },
  { market: "Election result", pnl: -123.4, return: -0.08 },
];

export default function Performance() {
  const maxPnl = Math.max(...weeklyPerformance.map((w) => w.pnl));
  const totalPnl = weeklyPerformance.reduce((sum, w) => sum + w.pnl, 0);
  const maxReturn = Math.max(...topPerformers.map((t) => Math.abs(t.return)));

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-text">Performance</h1>
          <p className="text-sm text-muted">Trading performance and analytics</p>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          {performanceMetrics.map((metric) => (
            <MetricCard
              key={metric.label}
              label={metric.label}
              value={metric.value}
              sub={metric.sub}
              trend={metric.trend}
            />
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Weekly P&L">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <span className="text-xs text-muted">Total P&L</span>
                <span className={`font-mono font-bold ${getStatusColor(totalPnl)}`}>
                  {totalPnl >= 0 ? "+" : ""}
                  {formatCurrency(totalPnl)}
                </span>
              </div>
              <div className="space-y-3">
                {weeklyPerformance.map((week) => {
                  const barWidth = (Math.abs(week.pnl) / maxPnl) * 100;
                  return (
                    <div key={week.week} className="space-y-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted">{week.week}</span>
                        <span className={`font-mono ${getStatusColor(week.pnl)}`}>
                          {week.pnl >= 0 ? "+" : ""}
                          {formatCurrency(week.pnl)}
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-bg-0 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            week.pnl >= 0 ? "bg-mint" : "bg-rose"
                          }`}
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between text-xs text-muted">
                        <span>{week.trades} trades</span>
                        <span>{formatPercent(week.winRate)} win rate</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Panel>

          <Panel title="Win Rate Trend">
            <div className="space-y-4">
              {[0.75, 0.50, 0.73, 0.60, 0.83].map((rate, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className="w-16 text-xs text-muted">Week {i + 1}</span>
                  <div className="flex-1 h-4 rounded-full bg-bg-0 overflow-hidden">
                    <div
                      className="h-full bg-cyan transition-all"
                      style={{ width: `${rate * 100}%` }}
                    />
                  </div>
                  <span className="w-12 text-right font-mono text-sm text-cyan">
                    {formatPercent(rate)}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <Panel title="Top Performers">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-line">
                  <th className="text-left py-3 px-4 text-xs font-medium text-muted">
                    Market
                  </th>
                  <th className="text-right py-3 px-4 text-xs font-medium text-muted">
                    P&L
                  </th>
                  <th className="text-right py-3 px-4 text-xs font-medium text-muted">
                    Return
                  </th>
                </tr>
              </thead>
              <tbody>
                {topPerformers.map((performer, i) => (
                  <tr
                    key={i}
                    className="border-b border-line/50 hover:bg-bg-0/50 transition-colors"
                  >
                    <td className="py-3 px-4 text-sm text-text">{performer.market}</td>
                    <td className={`py-3 px-4 text-right font-mono text-sm ${getStatusColor(performer.pnl)}`}>
                      {performer.pnl >= 0 ? "+" : ""}
                      {formatCurrency(performer.pnl)}
                    </td>
                    <td className={`py-3 px-4 text-right font-mono text-sm ${getStatusColor(performer.return)}`}>
                      {performer.return >= 0 ? "+" : ""}
                      {formatPercent(performer.return)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Risk Metrics">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border border-line bg-bg-0/50 p-4">
              <span className="text-xs text-muted">Sortino Ratio</span>
              <p className="mt-1 text-xl font-bold font-mono text-mint">1.89</p>
            </div>
            <div className="rounded-lg border border-line bg-bg-0/50 p-4">
              <span className="text-xs text-muted">Calmar Ratio</span>
              <p className="mt-1 text-xl font-bold font-mono text-mint">3.02</p>
            </div>
            <div className="rounded-lg border border-line bg-bg-0/50 p-4">
              <span className="text-xs text-muted">Avg Trade Duration</span>
              <p className="mt-1 text-xl font-bold font-mono text-text">4.2h</p>
            </div>
          </div>
        </Panel>
      </div>
    </DashboardLayout>
  );
}
