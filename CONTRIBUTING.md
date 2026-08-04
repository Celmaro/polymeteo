# Contributing

Thanks for helping make weather-market copy trading on Polymarket faster and safer.

## Where help matters most

Live trading is where this project becomes powerful. The paper path is complete; production edge comes from contributors who harden:

1. **Detection latency** — faster target-fill ingestion (websocket / indexed activity)
2. **Execution quality** — CLOB signing, partial fills, retry/backoff, kill switches
3. **Risk controls** — per-city exposure, correlated market caps, daily loss circuit breakers
4. **Wallet intelligence** — better specialty detection, regime filters, decay of cold targets
5. **Dashboard UX** — live fills stream, alert rules, multi-account views

If you can improve any of those for real capital, open a PR.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python scripts/generate_demo.py
uvicorn weather_copy_bot.api.app:app --reload --port 8000

# separate terminal
cd dashboard && npm install && npm run dev
```

## Pull request checklist

- Keep `DRY_RUN=true` as the default
- Never commit private keys or `.env`
- Add/adjust tests or a short CLI repro for engine changes
- Update README screenshots if dashboard UX changes materially

## Security

Report key-handling or order-routing issues privately when possible. Do not open public issues that include secrets, signed payloads, or live wallet credentials.
