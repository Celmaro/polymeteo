.PHONY: demo api dashboard paper backtest analyze screenshots

demo:
	PYTHONPATH=src python3 scripts/generate_demo.py

api:
	PYTHONPATH=src uvicorn weather_copy_bot.api.app:app --reload --port 8000

dashboard:
	cd dashboard && npm install && npm run dev

paper:
	PYTHONPATH=src python3 -m weather_copy_bot.cli paper --seconds 20

backtest:
	PYTHONPATH=src python3 -m weather_copy_bot.cli backtest --trades 120

analyze:
	PYTHONPATH=src python3 -m weather_copy_bot.cli analyze

screenshots:
	PYTHONPATH=src python3 scripts/capture_screenshots.py
