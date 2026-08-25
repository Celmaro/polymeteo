import { DashboardLayout, Panel, MetricCard, Badge } from "@/components/DashboardLayout";
import { formatCurrency, formatPercent } from "@/lib/utils";

const positions = [
  { id: "1", market: "ETH $4000 End of Year", side: "YES", size: 250, entry: 0.62, current: 0.65, pnl: 7.50, pnlPercent: 4.8 },
  { id: "2", market: "Rain NYC Christmas", side: "NO", size: 100, entry: 0.45, current: 0.42, pnl: 7.14, pnlPercent: 15.9 },
  { id: "3", market: "BTC $100k Q1", side: "YES", size: 500, entry: 0.35, current: 0.38, pnl: 42.86, pnlPercent: 24.5 },
];

export default function PositionsPage() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <header>
          <h1 className="text-3xl font-bold tracking-tight">Positions</h1>
          <p className="text-muted mt-1">Manage your active and closed positions</p>
        </header>

        <div className="grid gap-4 md:grid-cols-3">
          <MetricCard label="Open Positions" value="3" trend="neutral" />
          <MetricCard label="Unrealized P&L" value={formatCurrency(57.50)} trend="up" />
          <MetricCard label="Total Invested" value={formatCurrency(850)} trend="neutral" />
        </div>

        <Panel title="Active Positions">
          <div className="space-y-3">
            {positions.map((p) => (
              <div key={p.id} className="rounded-xl border border-line bg-bg-0/40 p-4">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{p.market}</span>
                      <Badge variant={p.side === "YES" ? "primary" : "secondary"}>{p.side}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted">
                      Size: {formatCurrency(p.size)} | Entry: {formatPercent(p.entry)} | Current: {formatPercent(p.current)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={`font-mono text-lg font-bold ${p.pnl >= 0 ? "text-mint" : "text-rose"}`}>
                      {p.pnl >= 0 ? "+" : ""}{formatCurrency(p.pnl)}
                    </p>
                    <p className={`text-xs ${p.pnl >= 0 ? "text-mint" : "text-rose"}`}>
                      {p.pnl >= 0 ? "+" : ""}{formatPercent(p.pnlPercent / 100)}
                    </p>
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button className="rounded-lg bg-rose/10 px-3 py-1 text-xs font-medium text-rose hover:bg-rose/20">
                    Close Position
                  </button>
                  <button className="rounded-lg border border-line px-3 py-1 text-xs font-medium text-muted hover:text-text">
                    Add to Position
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </DashboardLayout>
  );
}
