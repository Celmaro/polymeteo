import { DashboardLayout, Panel, Badge } from "../components/DashboardLayout";
import { formatPercent, formatCurrency } from "../lib/utils";

const signals = [
  {
    id: "SIG-001",
    market: "Will BTC hit $100K by end of 2025?",
    direction: "YES",
    confidence: 0.85,
    source: "Bayesian Consensus",
    price: 0.72,
    action: "BUY",
    size: 500,
    status: "active",
    timestamp: "2025-01-15T10:30:00Z",
  },
  {
    id: "SIG-002",
    market: "Will ETH flip BTC market cap?",
    direction: "NO",
    confidence: 0.62,
    source: "Multi-Source Fusion",
    price: 0.15,
    action: "CLOSE",
    size: 200,
    status: "pending",
    timestamp: "2025-01-15T09:15:00Z",
  },
  {
    id: "SIG-003",
    market: "Temperature above 30°C tomorrow?",
    direction: "YES",
    confidence: 0.78,
    source: "Weather AI",
    price: 0.45,
    action: "HOLD",
    size: 1000,
    status: "active",
    timestamp: "2025-01-15T08:00:00Z",
  },
  {
    id: "SIG-004",
    market: "Fed rate cut in March 2025?",
    direction: "YES",
    confidence: 0.91,
    source: "Bayesian Consensus",
    price: 0.68,
    action: "BUY",
    size: 1500,
    status: "filled",
    timestamp: "2025-01-14T16:45:00Z",
  },
];

const signalStats = [
  { label: "Active Signals", value: "2" },
  { label: "Pending", value: "1" },
  { label: "Filled Today", value: "3" },
  { label: "Win Rate", value: "78%" },
];

export default function Signals() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-text">Trading Signals</h1>
            <p className="text-sm text-muted">AI-generated signals from consensus engines</p>
          </div>
          <div className="flex gap-2">
            <button className="rounded-lg border border-line bg-bg-0/50 px-3 py-2 text-sm text-muted hover:bg-bg-0 transition-colors">
              Filter
            </button>
            <button className="rounded-lg border border-line bg-bg-0/50 px-3 py-2 text-sm text-muted hover:bg-bg-0 transition-colors">
              Export
            </button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          {signalStats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-line bg-bg-1/50 p-4"
            >
              <span className="text-xs text-muted">{stat.label}</span>
              <p className="mt-1 text-2xl font-bold font-mono text-text">{stat.value}</p>
            </div>
          ))}
        </div>

        <Panel title="Signal Feed">
          <div className="space-y-3">
            {signals.map((signal) => (
              <div
                key={signal.id}
                className="rounded-lg border border-line bg-bg-0/50 p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge
                        variant={
                          signal.action === "BUY"
                            ? "primary"
                            : signal.action === "CLOSE"
                            ? "secondary"
                            : "default"
                        }
                      >
                        {signal.action}
                      </Badge>
                      <Badge variant="default">{signal.source}</Badge>
                      <Badge
                        variant={
                          signal.status === "active"
                            ? "primary"
                            : signal.status === "pending"
                            ? "secondary"
                            : "default"
                        }
                      >
                        {signal.status}
                      </Badge>
                    </div>
                    <p className="text-sm font-medium text-text line-clamp-1">
                      {signal.market}
                    </p>
                    <p className="text-xs text-muted mt-1">Signal {signal.id}</p>
                  </div>
                  <div className="text-right ml-4">
                    <div
                      className={`inline-flex items-center justify-center rounded-lg px-3 py-1 text-sm font-bold ${
                        signal.direction === "YES"
                          ? "bg-mint/20 text-mint"
                          : "bg-rose/20 text-rose"
                      }`}
                    >
                      {signal.direction}
                    </div>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-4 gap-4 border-t border-line pt-3">
                  <div>
                    <span className="text-xs text-muted">Confidence</span>
                    <p className="font-mono text-sm text-text">
                      {formatPercent(signal.confidence)}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-muted">Current Price</span>
                    <p className="font-mono text-sm text-text">
                      {formatPercent(signal.price)}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-muted">Position Size</span>
                    <p className="font-mono text-sm text-text">
                      {formatCurrency(signal.size)}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-muted">Time</span>
                    <p className="font-mono text-sm text-text">
                      {new Date(signal.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </DashboardLayout>
  );
}
