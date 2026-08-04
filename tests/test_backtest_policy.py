from datetime import datetime, timezone

from weather_copy_bot.backtest import CopyBacktester
from weather_copy_bot.config import Settings
from weather_copy_bot.models import Side, TradeSignal


def _signal(latency_ms: int) -> TradeSignal:
    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="t1",
        target_wallet="0xabc",
        market_slug="highest-temperature-in-tokyo",
        market_title="Highest temperature in Tokyo?",
        city="Tokyo",
        outcome="Yes",
        side=Side.BUY,
        price=0.42,
        size_usd=100,
        detected_at=now,
        target_filled_at=now,
        latency_ms=latency_ms,
    )


def test_stale_signal_is_rejected():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(1200))
    assert decision.should_copy is False
    assert "stale" in decision.reason


def test_fresh_signal_is_copied():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(350))
    assert decision.should_copy is True
    assert decision.copy_size_usd == 25.0
