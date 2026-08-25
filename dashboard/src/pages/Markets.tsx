import { DashboardLayout, Panel, Badge } from "@/components/DashboardLayout";
import { formatCurrency, formatPercent } from "@/lib/utils";

const markets = [
  { id: "1", question: "Will ETH exceed $4000 by end of year?", category: "CRYPTO", probability: 0.65, volume: 125000, liquidity: 450000 },
  { id: "2", question: "Will it rain in NYC on Christmas?", category: "WEATHER", probability: 0.42, volume: 8900, liquidity: 12000 },
  { id: "3", question: "Will BTC break $100k in Q1?", category: "CRYPTO", probability: 0.38, volume: 234000, liquidity: 890000 },
  { id: "4", question: "Will Lakers make playoffs?", category: "SPORTS", probability: 0.72, volume: 45000, liquidity: 67000 },
  { id: "5", question: "Fed rate cut in March?", category: "ECONOMICS", probability: 0.55, volume: 178000, liquidity: 340000 },
];

const categories = ["All", "CRYPTO", "SPORTS", "WEATHER", "ECONOMICS", "POLITICS"];

export default function MarketsPage() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <header>
          <h1 className="text-3xl font-bold tracking-tight">Markets</h1>
          <p className="text-muted mt-1">Browse and filter active prediction markets</p>
        </header>

        <div className="flex gap-2 flex-wrap">
          {categories.map((cat) => (
            <button
              key={cat}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                cat === "All"
                  ? "bg-cyan text-bg-0"
                  : "border border-line text-muted hover:text-text"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <Panel>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wider text-muted">
                  <th className="pb-3 pr-4">Question</th>
                  <th className="pb-3 pr-4">Category</th>
                  <th className="pb-3 pr-4">Probability</th>
                  <th className="pb-3 pr-4">24h Volume</th>
                  <th className="pb-3 pr-4">Liquidity</th>
                  <th className="pb-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {markets.map((m) => (
                  <tr key={m.id} className="border-b border-line last:border-0">
                    <td className="py-3 pr-4 max-w-md truncate">{m.question}</td>
                    <td className="py-3 pr-4">
                      <Badge variant="secondary">{m.category}</Badge>
                    </td>
                    <td className="py-3 pr-4 font-mono font-semibold text-mint">
                      {formatPercent(m.probability)}
                    </td>
                    <td className="py-3 pr-4 font-mono text-muted">
                      {formatCurrency(m.volume)}
                    </td>
                    <td className="py-3 pr-4 font-mono text-muted">
                      {formatCurrency(m.liquidity)}
                    </td>
                    <td className="py-3">
                      <button className="rounded-lg bg-cyan/10 px-3 py-1 text-xs font-medium text-cyan hover:bg-cyan/20">
                        Copy Trade
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </DashboardLayout>
  );
}
