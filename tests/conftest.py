"""Shared pytest fixtures and configuration."""

from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset settings cache before each test."""
    from weather_copy_bot.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def sandbox_app_root(tmp_path, monkeypatch):
    """Redirect APP_ROOT so tests never write to a real application root."""
    monkeypatch.setenv("APP_ROOT", str(tmp_path))


@pytest.fixture
def sample_trade_signal():
    """Create a sample trade signal for testing."""
    from weather_copy_bot.models import Side, TradeSignal

    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="test-sig-1",
        target_wallet="0xtest123",
        market_slug="highest-temperature-in-tokyo",
        market_title="Highest temperature in Tokyo?",
        city="Tokyo",
        outcome="Yes",
        side=Side.BUY,
        price=0.55,
        size_usd=100.0,
        detected_at=now,
        target_filled_at=now,
        latency_ms=350,
    )


@pytest.fixture
def sample_fill():
    """Create a sample fill for testing."""
    from weather_copy_bot.models import Fill, Side

    now = datetime.now(timezone.utc)
    return Fill(
        fill_id="test-fill-1",
        signal_id="test-sig-1",
        target_wallet="0xtest123",
        market_slug="highest-temperature-in-tokyo",
        market_title="Highest temperature in Tokyo?",
        city="Tokyo",
        outcome="Yes",
        side=Side.BUY,
        price=0.55,
        size_usd=100.0,
        fee_usd=0.25,
        pnl_usd=15.5,
        latency_ms=350,
        filled_at=now,
        mode="paper",
    )


@pytest.fixture
def sample_settings():
    """Create sample settings for testing."""
    from weather_copy_bot.config import Settings

    return Settings(
        max_copy_latency_ms=800,
        copy_ratio=0.25,
        max_position_usd=250.0,
        dry_run=True,
    )
