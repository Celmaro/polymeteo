"""Tests for WalletAnalyzer scoring and wallet ranking."""
from datetime import datetime, timezone

from weather_copy_bot.analysis.wallet_analyzer import WalletAnalyzer
from weather_copy_bot.models import Fill, Side


def _make_fill(
    wallet: str,
    pnl: float,
    latency_ms: int,
    city: str = "New York",
    price: float = 0.5,
    size: float = 100.0,
) -> Fill:
    now = datetime.now(timezone.utc)
    return Fill(
        fill_id=f"fill-{wallet}-{pnl}",
        signal_id=f"sig-{wallet}",
        target_wallet=wallet,
        market_slug="test-market",
        market_title="Test Market?",
        city=city,
        outcome="Yes",
        side=Side.BUY,
        price=price,
        size_usd=size,
        fee_usd=0.5,
        pnl_usd=pnl,
        latency_ms=latency_ms,
        filled_at=now,
        mode="paper",
    )


class TestWalletAnalyzerScoring:
    """Test wallet scoring logic."""

    def test_score_single_winning_wallet(self):
        analyzer = WalletAnalyzer(min_trades=3)
        fills = [
            _make_fill("0xAAA", pnl=10.0, latency_ms=300),
            _make_fill("0xAAA", pnl=15.0, latency_ms=350),
            _make_fill("0xAAA", pnl=8.0, latency_ms=280),
        ]
        cards = analyzer.score(fills)
        assert len(cards) == 1
        assert cards[0].wallet == "0xAAA"
        assert cards[0].total_pnl_usd == 33.0
        assert cards[0].win_rate == 100.0
        assert cards[0].trade_count == 3

    def test_score_single_losing_wallet(self):
        analyzer = WalletAnalyzer(min_trades=2)
        fills = [
            _make_fill("0xBBB", pnl=-5.0, latency_ms=300),
            _make_fill("0xBBB", pnl=-3.0, latency_ms=350),
        ]
        cards = analyzer.score(fills)
        assert len(cards) == 1
        assert cards[0].total_pnl_usd == -8.0
        assert cards[0].win_rate == 0.0

    def test_score_filters_by_min_trades(self):
        analyzer = WalletAnalyzer(min_trades=5)
        fills = [
            _make_fill("0xLOW", pnl=5.0, latency_ms=300),
            _make_fill("0xLOW", pnl=5.0, latency_ms=300),
        ]
        cards = analyzer.score(fills)
        assert len(cards) == 0

    def test_score_multiple_wallets_ranked(self):
        analyzer = WalletAnalyzer(min_trades=3)
        fills = [
            _make_fill("0xWIN", pnl=20.0, latency_ms=200),
            _make_fill("0xWIN", pnl=15.0, latency_ms=220),
            _make_fill("0xWIN", pnl=10.0, latency_ms=240),
            _make_fill("0xLOSE", pnl=-5.0, latency_ms=400),
            _make_fill("0xLOSE", pnl=-3.0, latency_ms=420),
            _make_fill("0xLOSE", pnl=-2.0, latency_ms=380),
        ]
        cards = analyzer.score(fills)
        assert len(cards) == 2
        assert cards[0].wallet == "0xWIN"
        assert cards[1].wallet == "0xLOSE"

    def test_profit_factor_calculation(self):
        analyzer = WalletAnalyzer(min_trades=2)
        fills = [
            _make_fill("0xPF", pnl=100.0, latency_ms=300),
            _make_fill("0xPF", pnl=-50.0, latency_ms=300),
        ]
        cards = analyzer.score(fills)
        assert cards[0].profit_factor == 2.0

    def test_profit_factor_zero_losses(self):
        analyzer = WalletAnalyzer(min_trades=2)
        fills = [
            _make_fill("0xALLWIN", pnl=100.0, latency_ms=300),
            _make_fill("0xALLWIN", pnl=50.0, latency_ms=300),
        ]
        cards = analyzer.score(fills)
        assert cards[0].profit_factor == 999.0

    def test_profit_factor_no_gains(self):
        analyzer = WalletAnalyzer(min_trades=2)
        fills = [
            _make_fill("0xALLLOSE", pnl=-10.0, latency_ms=300),
            _make_fill("0xALLLOSE", pnl=-20.0, latency_ms=300),
        ]
        cards = analyzer.score(fills)
        assert cards[0].profit_factor == 0.0


class TestWalletSpecialtyCities:
    """Test city specialty detection."""

    def test_specialty_cities_ranked_by_pnl(self):
        analyzer = WalletAnalyzer(min_trades=5)
        fills = [
            _make_fill("0xCITY", pnl=10.0, latency_ms=300, city="New York"),
            _make_fill("0xCITY", pnl=8.0, latency_ms=300, city="New York"),
            _make_fill("0xCITY", pnl=20.0, latency_ms=300, city="Tokyo"),
            _make_fill("0xCITY", pnl=15.0, latency_ms=300, city="London"),
            _make_fill("0xCITY", pnl=-5.0, latency_ms=300, city="Chicago"),
        ]
        cards = analyzer.score(fills)
        assert "Tokyo" in cards[0].specialty_cities
        assert len(cards[0].specialty_cities) == 3

    def test_max_three_specialties(self):
        analyzer = WalletAnalyzer(min_trades=20)
        cities = ["Tokyo", "London", "Paris", "Berlin", "Rome"]
        fills = [
            _make_fill("0xMULTI", pnl=float(i + 1), latency_ms=300, city=cities[i % 5])
            for i in range(25)
        ]
        cards = analyzer.score(fills)
        assert len(cards[0].specialty_cities) == 3


class TestCopyRecommendations:
    """Test copy recommendation tiers."""

    def test_recommendation_primary(self):
        analyzer = WalletAnalyzer(min_trades=3)
        fills = [
            _make_fill("0xPRIMARY", pnl=15.0, latency_ms=200)
            for _ in range(10)
        ]
        cards = analyzer.score(fills)
        assert cards[0].copy_recommendation == "PRIMARY"

    def test_recommendation_satellite(self):
        analyzer = WalletAnalyzer(min_trades=5)
        fills = [
            _make_fill("0xSAT", pnl=3.0, latency_ms=400) if i % 2 == 0 else _make_fill("0xSAT", pnl=-2.0, latency_ms=400)
            for i in range(8)
        ]
        cards = analyzer.score(fills)
        assert cards[0].copy_recommendation in ["SATELLITE", "WATCHLIST", "PRIMARY"]

    def test_recommendation_watchlist(self):
        analyzer = WalletAnalyzer(min_trades=5)
        fills = [
            _make_fill("0xWATCH", pnl=1.0, latency_ms=550) if i % 3 == 0 else _make_fill("0xWATCH", pnl=-1.5, latency_ms=550)
            for i in range(8)
        ]
        cards = analyzer.score(fills)
        assert cards[0].copy_recommendation in ["WATCHLIST", "SATELLITE", "PRIMARY"]


class TestTargetSelection:
    """Test wallet target selection."""

    def test_select_targets_respects_max(self):
        analyzer = WalletAnalyzer(min_trades=3)
        cards = [
            type("Card", (), {
                "copy_recommendation": "PRIMARY",
                "wallet": f"0x{i}",
                "alias": f"Wallet {i}",
                "total_pnl_usd": 100.0,
                "win_rate": 70.0,
                "trade_count": 50,
                "avg_latency_ms": 300.0,
                "sharpe": 1.5,
                "max_drawdown_pct": 5.0,
                "profit_factor": 2.0,
                "specialty_cities": [],
                "consistency_score": 85.0,
            })()
            for i in range(5)
        ]
        selected = analyzer.select_targets(cards, max_targets=3)
        assert len(selected) == 3

    def test_select_targets_filters_by_recommendation(self):
        analyzer = WalletAnalyzer()
        cards = [
            type("Card", (), {
                "copy_recommendation": rec,
                "wallet": f"0x{i}",
                "alias": f"Wallet {i}",
                "total_pnl_usd": 100.0,
                "win_rate": 70.0,
                "trade_count": 50,
                "avg_latency_ms": 300.0,
                "sharpe": 1.5,
                "max_drawdown_pct": 5.0,
                "profit_factor": 2.0,
                "specialty_cities": [],
                "consistency_score": 85.0,
            })()
            for i, rec in enumerate(["PRIMARY", "PRIMARY", "WATCHLIST", "PRIMARY", "SATELLITE"])
        ]
        selected = analyzer.select_targets(cards)
        assert len(selected) == 3
        assert all(c.copy_recommendation in {"PRIMARY", "SATELLITE"} for c in selected)
