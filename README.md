<p align="center">
  <img src="dashboard/public/favicon.svg" width="72" alt="Weather Copy Bot" />
</p>

<h1 align="center">Polymarket Weather Copy Trading Bot</h1>

<p align="center">
  <strong>Copy elite weather traders on Polymarket — without building your own prediction model.</strong>
</p>

<p align="center">
  Latency-gated multi-wallet copy engine · wallet intelligence · backtest · paper trading · research dashboard
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/quick%20start-2%20commands-3ec7c9?style=for-the-badge" alt="Quick start" /></a>
  <a href="#live-trading-contribution"><img src="https://img.shields.io/badge/live%20trading-contribution%20open-6fd9a4?style=for-the-badge" alt="Live trading" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-e2b15a?style=for-the-badge" alt="MIT" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Polymarket-Weather%20Markets-0c1d2e?style=flat-square" alt="Polymarket weather" />
  <img src="https://img.shields.io/badge/Copy%20Trading-Multi%20Target-12283d?style=flat-square" alt="Copy trading" />
  <img src="https://img.shields.io/badge/Latency%20Gate-%3C800ms-183248?style=flat-square" alt="Latency" />
  <img src="https://img.shields.io/badge/Modes-Backtest%20%7C%20Paper%20%7C%20Live-07131f?style=flat-square" alt="Modes" />
  <img src="https://img.shields.io/badge/Stack-Python%20%2B%20FastAPI%20%2B%20React-3ec7c9?style=flat-square" alt="Stack" />
</p>

---

## Why this exists

In prediction markets, the **model is the edge**.

For Polymarket weather markets, building that model means temperature distributions, city microclimates, forecast revisions, settlement quirks, and timing — a research project before you ever place a trade.

Meanwhile, some wallets already express a strong weather model through their fills. They are profitable, stable, and specialized by city.

**This bot does not reinvent their model.**  
It treats their fills as the signal, then races the only variable you still control: **copy latency**.

Typical Polymarket copy latency in practice is around **~1000ms**. Edge decays fast. This project is built around detecting target activity, rejecting stale signals, sizing safely, and proving the path in **backtest + paper** before live capital.

---

## Dashboard (demo results)

Curated research dashboard showing analysis, backtest, and paper-trading performance for weather-market copy paths.

### Overview — strong PnL & risk profile

![Overview PnL dashboard](docs/screenshots/01-overview-pnl.png)

| Metric | Demo result |
| --- | ---: |
| Net realized PnL | **+$47,832** |
| Return on $10k | **+478%** |
| Win rate | **68.4%** |
| Sharpe | **2.41** |
| Max drawdown | **8.2%** |
| Avg copy latency | **412ms** |

### Equity curve + copy funnel

![Equity curve and copy funnel](docs/screenshots/02-equity-funnel.png)

The funnel is the product:

`signals detected → filters → latency gate → copied`

Stale and risk-rejected signals are skipped on purpose. Chasing late weather fills is how copy bots donate edge.

### Target wallet intelligence

![Wallet analysis scorecards](docs/screenshots/03-wallet-analysis.png)

Scorecards rank wallets by consistency, specialty cities, latency-sensitive expectancy, and copy recommendation (`PRIMARY` / `SATELLITE`).

### City breakdown + recent fills

![City breakdown and recent fills](docs/screenshots/04-city-fills.png)

---

## Core idea

```text
Profitable weather wallets  →  signal source (their "model")
Latency + risk gates        →  decide if the fill is still copyable
Backtest / paper            →  prove expectancy before live
Dashboard                   →  inspect wallets, curves, funnel, fills
```

You can run **multiple targets** at once. The engine sizes with `COPY_RATIO`, caps position risk, and drops anything slower than `MAX_COPY_LATENCY_MS`.

---

## Features

- **Multi-target copy trading** for Polymarket weather / temperature markets
- **Wallet analyzer** with specialty cities, Sharpe, drawdown, consistency score
- **Latency-aware backtester** (markout decays as detection lag grows)
- **Paper trader** with the same decision policy as live
- **Live path scaffold** gated by `DRY_RUN` + credentials
- **Research dashboard** for PnL, equity, funnel, latency buckets, city breakdown
- **CLI** for analyze / backtest / paper / API serve

---

## Quick start

```bash
git clone https://github.com/fxfx122344/polymarket-weather-copy-trading-bot.git
cd polymarket-weather-copy-trading-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

export PYTHONPATH=src
python scripts/generate_demo.py
uvicorn weather_copy_bot.api.app:app --reload --port 8000
```

In another terminal:

```bash
cd dashboard
npm install
npm run dev
```

Open **http://localhost:5173**

Useful CLI:

```bash
PYTHONPATH=src python -m weather_copy_bot.cli dashboard-data
PYTHONPATH=src python -m weather_copy_bot.cli analyze
PYTHONPATH=src python -m weather_copy_bot.cli backtest --trades 120
PYTHONPATH=src python -m weather_copy_bot.cli paper --seconds 20
```

---

## Project structure

```text
.
├── src/weather_copy_bot/
│   ├── analysis/          # target wallet scoring & selection
│   ├── api/               # FastAPI dashboard + control plane
│   ├── backtest/          # latency-aware event backtester
│   ├── engine/            # live/paper copy loop
│   ├── paper/             # paper ledger & fills
│   ├── polymarket/        # Gamma / Data API adapters + demo stream
│   ├── cli.py             # operator commands
│   ├── config.py          # env-driven settings
│   ├── demo_data.py       # curated dashboard dataset
│   ├── metrics.py         # Sharpe, Sortino, DD, profit factor
│   └── models.py          # shared domain models
├── dashboard/             # React + Vite research UI
├── data/demo/             # exported dashboard JSON
├── docs/screenshots/      # README visuals
├── scripts/               # demo export, screenshot, dev helpers
├── .env.example
└── requirements.txt
```

---

## Engineering

```mermaid
flowchart LR
  A[Target wallets] --> B[Activity poll / stream]
  B --> C{Weather market?}
  C -->|no| X[Ignore]
  C -->|yes| D[Build TradeSignal + latency_ms]
  D --> E{latency <= gate?}
  E -->|no| S[Skip stale]
  E -->|yes| F{Risk + size OK?}
  F -->|no| R[Skip risk]
  F -->|yes| G[Paper fill or live CLOB order]
  G --> H[Dashboard metrics]
  A --> I[Wallet analyzer]
  I --> H
  D --> J[Backtester]
  J --> H
```

### Decision policy

1. Detect target fill as early as possible  
2. Measure `now - target_filled_at`  
3. Drop if slower than `MAX_COPY_LATENCY_MS` (default **800ms**)  
4. Size with `COPY_RATIO`, clamp by `MAX_POSITION_USD`  
5. Enforce `MAX_DAILY_LOSS_USD`  
6. Paper by default (`DRY_RUN=true`)  
7. Live only when credentials exist and dry-run is disabled  

### Why latency is the product

Weather markets reprice quickly after informed flow. A copy at **350ms** and a copy at **1000ms** are not the same trade. The dashboard’s latency buckets exist so you can see where expectancy survives.

---

## Configuration

Copy `.env.example` → `.env`:

| Variable | Meaning |
| --- | --- |
| `TARGET_WALLETS` | Comma-separated wallets to copy |
| `COPY_RATIO` | Fraction of target size to mirror |
| `MAX_POSITION_USD` | Hard per-order cap |
| `MAX_COPY_LATENCY_MS` | Stale-signal kill switch |
| `MAX_DAILY_LOSS_USD` | Daily circuit breaker |
| `MARKET_FILTER` | Default `weather` |
| `DRY_RUN` | `true` for paper / safe mode |
| `PAPER_STARTING_BALANCE` | Paper ledger start |

---

## GitHub About (SEO)

Use this on the repository **About** panel so people searching for Polymarket trading bots can find you:

**Description**
```text
Low-latency Polymarket weather prediction market copy trading bot — multi-wallet analysis, backtest, paper trading, and research dashboard.
```

**Topics**
```text
polymarket
polymarket-bot
copy-trading
trading-bot
prediction-market
weather-trading
backtesting
paper-trading
fastapi
react
crypto-trading
algorithmic-trading
```

Suggested Google-facing phrases already embedded in this README:

- polymarket trading bot  
- polymarket copy trading  
- weather prediction market bot  
- polymarket weather markets  
- prediction market copy bot  

---

## Disclaimer

This repository is for research and education. Demo dashboard figures are curated showcase metrics for UX/analysis review — **not a promise of future live performance**. Prediction market trading can lose money. You are responsible for keys, compliance, and risk.

---

## Live trading contribution

This stack is already strong for research, wallet selection, backtests, and paper validation.

For **real trading**, it becomes a serious weapon when the live path is production-hardened:

- websocket-speed target detection  
- signed CLOB execution with partial-fill handling  
- venue-specific weather market filters  
- capital controls and incident kill switches  
- alerting when latency or hit-rate degrades  

If you want this bot fighting for fills in live Polymarket weather markets, contribute to the live execution path.

👉 **Start here:** [CONTRIBUTING.md](CONTRIBUTING.md)

PRs that reduce detect→submit time, improve fill quality, or harden risk controls are first-class.

---

## License

[MIT](LICENSE)
