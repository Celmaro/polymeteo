import { DashboardLayout, Panel, Badge, MetricCard } from "../components/DashboardLayout";
import { formatCurrency, formatPercent, getStatusColor } from "../lib/utils";

const wallets = [
  { address: "0x742d35Cc6634C0532", label: "Main Trading", balance: 12453.82, pnl: 3241.50, pnlPercent: 0.261 },
  { address: "0x8ba1f109551bD4A1", label: "Reserve Fund", balance: 50000.00, pnl: 1823.40, pnlPercent: 0.037 },
  { address: "0x3fC91A3afd71", label: "Hot Wallet", balance: 2340.12, pnl: -127.30, pnlPercent: -0.054 },
  { address: "0xa0Ee7A142d267", label: "Strategy Vault", balance: 8920.45, pnl: 1567.89, pnlPercent: 0.176 },
];

const connectedAccounts = [
  { name: "MetaMask", status: "connected", address: "0x742d...532" },
  { name: "Coinbase Wallet", status: "connected", address: "0x8ba1...A1" },
  { name: "WalletConnect", status: "disconnected", address: null },
];

export default function Wallets() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-text">Wallets</h1>
            <p className="text-sm text-muted">Manage connected wallets and addresses</p>
          </div>
          <button className="rounded-lg border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan hover:bg-cyan/20 transition-colors">
            + Add Wallet
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <MetricCard label="Total Balance" value={formatCurrency(73714.39)} trend="up" />
          <MetricCard label="Total P&L" value={formatCurrency(6505.49)} trend="up" />
          <MetricCard label="Active Wallets" value="4" sub="3 connected" />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Connected Accounts">
            <div className="space-y-3">
              {connectedAccounts.map((account) => (
                <div
                  key={account.name}
                  className="flex items-center justify-between rounded-lg border border-line bg-bg-0/50 p-3"
                >
                  <div className="flex items-center gap-3">
                    <div className={`h-3 w-3 rounded-full ${account.status === "connected" ? "bg-mint" : "bg-muted/50"}`} />
                    <div>
                      <p className="font-medium text-text">{account.name}</p>
                      <p className="font-mono text-xs text-muted">
                        {account.address || "Not connected"}
                      </p>
                    </div>
                  </div>
                  <Badge variant={account.status === "connected" ? "primary" : "default"}>
                    {account.status}
                  </Badge>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Quick Actions">
            <div className="grid gap-3">
              <button className="w-full rounded-lg border border-line bg-bg-0/50 p-3 text-left hover:bg-bg-0 transition-colors">
                <p className="font-medium text-text">Export Private Keys</p>
                <p className="text-xs text-muted">Download encrypted key backup</p>
              </button>
              <button className="w-full rounded-lg border border-line bg-bg-0/50 p-3 text-left hover:bg-bg-0 transition-colors">
                <p className="font-medium text-text">View Transaction History</p>
                <p className="text-xs text-muted">Browse all wallet transactions</p>
              </button>
              <button className="w-full rounded-lg border border-rose/30 bg-rose/10 p-3 text-left hover:bg-rose/20 transition-colors">
                <p className="font-medium text-rose">Disconnect All</p>
                <p className="text-xs text-muted/70">Remove all connected wallets</p>
              </button>
            </div>
          </Panel>
        </div>

        <Panel title="All Wallets">
          <div className="space-y-3">
            {wallets.map((wallet) => (
              <div
                key={wallet.address}
                className="flex items-center justify-between rounded-lg border border-line bg-bg-0/50 p-4"
              >
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-cyan/20">
                    <span className="font-mono text-xs text-cyan">
                      {wallet.address.slice(0, 2)}
                    </span>
                  </div>
                  <div>
                    <p className="font-medium text-text">{wallet.label}</p>
                    <p className="font-mono text-xs text-muted">{wallet.address}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-mono font-medium text-text">
                    {formatCurrency(wallet.balance)}
                  </p>
                  <p className={`font-mono text-xs ${getStatusColor(wallet.pnl)}`}>
                    {wallet.pnl >= 0 ? "+" : ""}
                    {formatCurrency(wallet.pnl)} ({formatPercent(wallet.pnlPercent)})
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </DashboardLayout>
  );
}
