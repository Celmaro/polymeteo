import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchDashboard } from './api'
import { fallbackDashboard } from './fallbackData'
import type { DashboardPayload } from './types'
import './App.css'

type CurveMode = 'paper' | 'backtest'

function money(n: number) {
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function pct(n: number) {
  return `${n.toFixed(1)}%`
}

function shortTime(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function App() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [curveMode, setCurveMode] = useState<CurveMode>('paper')

  useEffect(() => {
    let alive = true
    fetchDashboard()
      .then((payload) => {
        if (alive) setData(payload)
      })
      .catch(() => {
        if (alive) {
          setData(fallbackDashboard)
          setError('API offline — showing curated demo dataset')
        }
      })
    return () => {
      alive = false
    }
  }, [])

  const curve = useMemo(() => {
    if (!data) return []
    const source = curveMode === 'paper' ? data.equity_curve : data.backtest_equity
    return source.map((p) => ({
      ...p,
      label: shortTime(p.timestamp),
    }))
  }, [curveMode, data])

  if (!data) {
    return <div className="loading">Loading weather copy desk…</div>
  }

  const h = data.headline
  const funnelMax = Math.max(...Object.values(data.copy_funnel), 1)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-kicker">Polymarket · Weather Copy Desk</div>
          <h1>Copy the forecast edge. Skip building the model.</h1>
          <p>
            Multi-target wallet intelligence, latency-gated execution, backtests, and paper trading
            for Polymarket weather markets — engineered for sub-second copy decisions.
          </p>
        </div>
        <div className="status-chip">
          <span className="status-dot" />
          {String(data.engine_status.health)} · {String(data.engine_status.mode)} ·{' '}
          {String(data.engine_status.avg_detect_to_submit_ms)}ms avg
        </div>
      </header>

      {error && <div className="banner">{error}</div>}

      <section className="hero">
        <div className="panel pnl-hero">
          <div className="pnl-label">Net realized PnL (paper + validated copy path)</div>
          <p className="pnl-value">{money(h.total_pnl_usd)}</p>
          <div className="pnl-sub">
            {money(h.starting_balance)} → {money(h.ending_balance)} · {pct(h.total_return_pct)} return ·{' '}
            {h.trade_count} copied fills
          </div>
          <div className="metric-grid">
            <div className="metric">
              <span>Win rate</span>
              <strong>{pct(h.win_rate)}</strong>
            </div>
            <div className="metric">
              <span>Sharpe</span>
              <strong>{h.sharpe.toFixed(2)}</strong>
            </div>
            <div className="metric">
              <span>Max DD</span>
              <strong>{pct(h.max_drawdown_pct)}</strong>
            </div>
            <div className="metric">
              <span>Profit factor</span>
              <strong>{h.profit_factor.toFixed(2)}</strong>
            </div>
            <div className="metric">
              <span>Avg latency</span>
              <strong>{Math.round(h.avg_latency_ms)}ms</strong>
            </div>
            <div className="metric">
              <span>Copy edge</span>
              <strong>{Math.round(h.avg_copy_edge_bps)} bps</strong>
            </div>
          </div>
        </div>

        <div className="panel">
          <h2>Mode comparison</h2>
          <div className="compare">
            <div>
              <span>Paper</span>
              <strong className="pos">{money(data.paper.total_pnl_usd)}</strong>
              <small>
                WR {pct(data.paper.win_rate)} · Sharpe {data.paper.sharpe.toFixed(2)}
              </small>
            </div>
            <div>
              <span>Backtest</span>
              <strong className="pos">{money(data.backtest.total_pnl_usd)}</strong>
              <small>
                WR {pct(data.backtest.win_rate)} · Sharpe {data.backtest.sharpe.toFixed(2)}
              </small>
            </div>
            <div>
              <span>Targets live</span>
              <strong>{String(data.engine_status.targets_active)}</strong>
              <small>{String(data.engine_status.markets_watched)} weather markets watched</small>
            </div>
            <div>
              <span>Latency gate</span>
              <strong>{String(data.engine_status.max_copy_latency_ms)}ms</strong>
              <small>Stale signals are dropped, not chased</small>
            </div>
          </div>
        </div>
      </section>

      <section className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Equity curve</h2>
            <div className="tabs">
              <button
                className={`tab ${curveMode === 'paper' ? 'active' : ''}`}
                onClick={() => setCurveMode('paper')}
              >
                Paper
              </button>
              <button
                className={`tab ${curveMode === 'backtest' ? 'active' : ''}`}
                onClick={() => setCurveMode('backtest')}
              >
                Backtest
              </button>
            </div>
          </div>
          <div style={{ width: '100%', height: 300 }}>
            <ResponsiveContainer>
              <AreaChart data={curve}>
                <defs>
                  <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3ec7c9" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#3ec7c9" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(140,190,220,0.12)" vertical={false} />
                <XAxis dataKey="label" stroke="#8aa5b8" tick={{ fill: '#8aa5b8', fontSize: 12 }} />
                <YAxis
                  stroke="#8aa5b8"
                  tick={{ fill: '#8aa5b8', fontSize: 12 }}
                  tickFormatter={(v) => `$${Math.round(v / 1000)}k`}
                />
                <Tooltip
                  contentStyle={{
                    background: '#0c1d2e',
                    border: '1px solid rgba(140,190,220,0.2)',
                    borderRadius: 12,
                  }}
                  formatter={(value) => [money(Number(value)), 'Equity']}
                />
                <Area
                  type="monotone"
                  dataKey="equity_usd"
                  stroke="#3ec7c9"
                  fill="url(#equityFill)"
                  strokeWidth={2.5}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel">
          <h2>Copy funnel</h2>
          <div className="funnel">
            {Object.entries(data.copy_funnel).map(([key, value]) => (
              <div className="funnel-row" key={key}>
                <span>{key.replace(/_/g, ' ')}</span>
                <div className="bar">
                  <i style={{ width: `${(value / funnelMax) * 100}%` }} />
                </div>
                <strong className="mono">{value}</strong>
              </div>
            ))}
          </div>
          <p className="footer-note">
            Edge survives only when detection → decision → submit stays under the latency gate.
          </p>
        </div>
      </section>

      <section className="grid-3">
        <div className="panel" style={{ gridColumn: 'span 2' }}>
          <h2>Target wallet scorecards</h2>
          <div className="wallet-list">
            {data.wallets.map((w) => (
              <div className="wallet-card" key={w.wallet}>
                <div className="wallet-head">
                  <strong>{w.alias}</strong>
                  <span
                    className={`badge ${w.copy_recommendation === 'PRIMARY' ? 'primary' : 'satellite'}`}
                  >
                    {w.copy_recommendation}
                  </span>
                </div>
                <div className="wallet-meta">
                  <div>
                    <span>PnL</span>
                    <strong className="pos">{money(w.total_pnl_usd)}</strong>
                  </div>
                  <div>
                    <span>Win rate</span>
                    <strong>{pct(w.win_rate)}</strong>
                  </div>
                  <div>
                    <span>Sharpe</span>
                    <strong>{w.sharpe.toFixed(2)}</strong>
                  </div>
                  <div>
                    <span>Consistency</span>
                    <strong>{w.consistency_score.toFixed(1)}</strong>
                  </div>
                </div>
                <div className="cities">
                  Specialty: {w.specialty_cities.join(' · ')} · avg latency {Math.round(w.avg_latency_ms)}ms
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Latency vs edge</h2>
          <div className="latency-grid">
            {data.latency_buckets.map((b) => (
              <div className="latency-item" key={b.bucket}>
                <div>
                  <strong>{b.bucket}</strong>
                  <div className="cities">{b.trade_count} trades</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className={b.avg_pnl_usd >= 0 ? 'pos' : 'neg'}>{money(b.avg_pnl_usd)}</div>
                  <div className="cities">WR {pct(b.win_rate)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid-2">
        <div className="panel">
          <h2>City breakdown</h2>
          <div style={{ width: '100%', height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={data.city_breakdown}>
                <CartesianGrid stroke="rgba(140,190,220,0.12)" vertical={false} />
                <XAxis dataKey="city" stroke="#8aa5b8" tick={{ fill: '#8aa5b8', fontSize: 12 }} />
                <YAxis stroke="#8aa5b8" tick={{ fill: '#8aa5b8', fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    background: '#0c1d2e',
                    border: '1px solid rgba(140,190,220,0.2)',
                    borderRadius: 12,
                  }}
                />
                <Bar dataKey="pnl_usd" fill="#6fd9a4" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel">
          <h2>Recent copied fills</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Side</th>
                  <th>Latency</th>
                  <th>PnL</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_fills.slice(0, 8).map((f) => (
                  <tr key={f.fill_id}>
                    <td>
                      {f.city}
                      <div className="cities">{f.outcome}</div>
                    </td>
                    <td className="mono">
                      {f.side} @ {f.price.toFixed(2)}
                    </td>
                    <td className="mono">{f.latency_ms}ms</td>
                    <td className={f.pnl_usd >= 0 ? 'pos' : 'neg'}>{money(f.pnl_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <p className="footer-note">
        Weather Copy Bot · analysis · backtest · paper · latency-gated live path · demo metrics for
        research UX
      </p>
    </div>
  )
}
