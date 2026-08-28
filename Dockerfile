FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch (~200MB instead of ~2GB CUDA)
RUN pip install --no-cache-dir torch==2.4.1+cpu --index-url https://download.pytorch.org/whl/cpu

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

CMD ["sh", "-c", "python -m uvicorn weather_copy_bot.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
