FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY dashboard/ ./dashboard/

WORKDIR /app/dashboard
RUN npm ci && npm run build

WORKDIR /app

ENV PYTHONPATH=/app:/app/src
ENV APP_ROOT=/app
ENV PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "weather_copy_bot.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
