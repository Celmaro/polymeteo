from datetime import datetime, timezone

from weather_copy_bot.backtest import CopyBacktester
from weather_copy_bot.config import Settings
from weather_copy_bot.models import Side, TradeSignal


def _signal(latency_ms: int, price: float = 0.42, upstream_age_ms: int = 0) -> TradeSignal:
    now = datetime.now(timezone.utc)
    return TradeSignal(
        signal_id="t1",
        target_wallet="0xabc",
        market_slug="highest-temperature-in-tokyo",
        market_title="Highest temperature in Tokyo?",
        city="Tokyo",
        outcome="Yes",
        side=Side.BUY,
        price=price,
        size_usd=100,
        detected_at=now,
        target_filled_at=now,
        latency_ms=latency_ms,
        upstream_age_ms=upstream_age_ms,
    )


def test_stale_signal_is_rejected():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(1200))
    assert decision.should_copy is False
    assert "stale" in decision.reason


def test_stale_upstream_age_is_rejected():
    # Audit P0: an hours-old upstream timestamp must fail the upstream-age gate
    # even when the local detection latency is well within budget.
    settings = Settings(max_upstream_age_ms=60_000, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(350, upstream_age_ms=65_000))
    assert decision.should_copy is False
    assert decision.reason.startswith("stale_upstream:")


def test_fresh_upstream_stale_latency_still_rejected():
    # Audit P0: the local latency gate is independent of the upstream-age gate;
    # a fresh upstream event with a slow local decision is still stale.
    settings = Settings(
        max_upstream_age_ms=60_000,
        max_copy_latency_ms=800,
        copy_ratio=0.25,
        max_position_usd=250,
    )
    decision = CopyBacktester(settings).decide(_signal(1200, upstream_age_ms=10_000))
    assert decision.should_copy is False
    assert decision.reason.startswith("stale_signal:")


def test_fresh_signal_is_copied():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(350))
    assert decision.should_copy is True
    assert decision.copy_size_usd == 25.0


def test_thin_edge_near_mid_price_is_rejected():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(350, price=0.50))
    assert decision.should_copy is False
    assert decision.reason == "thin_edge"


def test_healthy_edge_still_copied():
    settings = Settings(max_copy_latency_ms=800, copy_ratio=0.25, max_position_usd=250)
    decision = CopyBacktester(settings).decide(_signal(350, price=0.60))
    assert decision.should_copy is True
