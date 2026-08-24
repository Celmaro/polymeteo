"""Tests for Quorum Engine."""

import pytest
import time

from weather_copy_bot.engine.quorum import (
    QuorumEngine,
    WalletTradeSignal,
    WalletCategory,
)


class TestQuorumEngine:
    """Tests for QuorumEngine."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = QuorumEngine(
            min_quorum_count=2,
            min_weighted_score=2.0,
            window_seconds=600,
        )
        
        assert engine.min_quorum_count == 2
        assert engine.min_weighted_score == 2.0
        assert engine.window_seconds == 600

    def test_single_signal_no_quorum(self):
        """Test that single signal doesn't trigger quorum."""
        engine = QuorumEngine(min_quorum_count=2)
        
        signal = WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        )
        
        result = engine.register_signal(signal)
        assert result is None
        assert engine.get_stats()["signals_buffered"] == 1

    def test_quorum_reached(self):
        """Test quorum is reached with enough signals."""
        engine = QuorumEngine(min_quorum_count=2)
        
        signal1 = WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        )
        
        signal2 = WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.WHALE,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.52,
        )
        
        result1 = engine.register_signal(signal1)
        assert result1 is None  # Not enough signals
        
        result2 = engine.register_signal(signal2)
        assert result2 is not None
        assert result2.quorum_size == 2
        assert result2.token_id == "TOKEN1"
        assert result2.side == "BUY"
        assert len(result2.wallets) == 2

    def test_weighted_quorum(self):
        """Test weighted quorum calculation."""
        engine = QuorumEngine(
            min_quorum_count=2,
            min_weighted_score=2.5,  # Require 2.5 weight
        )
        
        # Two regular wallets (1.0 + 1.0 = 2.0) should NOT reach quorum
        engine.reset()
        
        for i, addr in enumerate(["0x111", "0x222"]):
            signal = WalletTradeSignal(
                wallet_address=addr,
                wallet_category=WalletCategory.REGULAR,
                token_id="TOKEN1",
                side="BUY",
                entry_price=0.50,
            )
            engine.register_signal(signal)
        
        # Should NOT reach quorum (2.0 < 2.5)
        status = engine.get_buffer_status("TOKEN1", "BUY")
        assert status["executed"] is False
        
        # Add smart bot (1.0 + 1.0 + 1.5 = 3.5 >= 2.5)
        engine.reset()
        
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.REGULAR,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        result = engine.register_signal(WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.SMART_BOT,  # Weight 1.5
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.52,
        ))
        
        assert result is not None
        assert result.weighted_score == 2.5

    def test_duplicate_wallet_rejected(self):
        """Test that same wallet can't signal twice."""
        engine = QuorumEngine(min_quorum_count=2)
        
        signal1 = WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        )
        
        signal2 = WalletTradeSignal(
            wallet_address="0x111",  # Same wallet!
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.52,
        )
        
        engine.register_signal(signal1)
        engine.register_signal(signal2)
        
        # Only one signal should be buffered
        status = engine.get_buffer_status("TOKEN1", "BUY")
        assert status["signal_count"] == 1
        assert engine.get_stats()["duplicate_signals"] == 1

    def test_idempotency(self):
        """Test that executed token can't trigger again."""
        engine = QuorumEngine(min_quorum_count=2)
        
        # First set of signals
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.52,
        ))
        
        # Try to add more signals after quorum
        result = engine.register_signal(WalletTradeSignal(
            wallet_address="0x333",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.54,
        ))
        
        assert result is None
        assert engine.get_stats()["quorum_reached"] == 1

    def test_price_rejection(self):
        """Test rejection when price too high."""
        engine = QuorumEngine(
            min_quorum_count=2,
            max_acceptable_price=0.60,
        )
        
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        # Price 0.75 > max_acceptable_price 0.60
        result = engine.register_signal(WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.75,
        ))
        
        assert result is None
        assert engine.get_stats()["quorum_rejected"] == 1

    def test_different_sides(self):
        """Test that BUY and SELL are tracked separately."""
        engine = QuorumEngine(min_quorum_count=2)
        
        # BUY signals
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        # SELL signals (different side)
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="SELL",
            entry_price=0.50,
        ))
        
        # Each side should have only 1 signal
        buy_status = engine.get_buffer_status("TOKEN1", "BUY")
        sell_status = engine.get_buffer_status("TOKEN1", "SELL")
        
        assert buy_status["signal_count"] == 1
        assert sell_status["signal_count"] == 1

    def test_signal_expiration(self):
        """Test that old signals expire."""
        engine = QuorumEngine(window_seconds=1)  # 1 second window
        
        signal1 = WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
            timestamp=time.time() - 10,  # 10 seconds ago
        )
        
        engine.register_signal(signal1)
        
        # Add fresh signal
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x222",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.52,
        ))
        
        # Should not reach quorum (only fresh signal counts)
        status = engine.get_buffer_status("TOKEN1", "BUY")
        assert status["signal_count"] == 1

    def test_reset(self):
        """Test engine reset."""
        engine = QuorumEngine(min_quorum_count=2)
        
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        engine.reset()
        
        assert engine.get_stats()["signals_buffered"] == 0
        assert engine.get_stats()["executed_count"] == 0

    def test_get_stats(self):
        """Test stats reporting."""
        engine = QuorumEngine(min_quorum_count=2)
        
        engine.register_signal(WalletTradeSignal(
            wallet_address="0x111",
            wallet_category=WalletCategory.SMART_BOT,
            token_id="TOKEN1",
            side="BUY",
            entry_price=0.50,
        ))
        
        stats = engine.get_stats()
        assert stats["signals_received"] == 1
        assert stats["signals_buffered"] == 1
        assert stats["buffer_size"] == 1


class TestWalletTradeSignal:
    """Tests for WalletTradeSignal."""

    def test_weight_assignment(self):
        """Test weight assignment by category."""
        smart_bot = WalletTradeSignal(
            wallet_category=WalletCategory.SMART_BOT,
            wallet_address="0x111",
            token_id="T1",
            side="BUY",
            entry_price=0.5,
        )
        assert smart_bot.weight == 1.5
        
        whale = WalletTradeSignal(
            wallet_category=WalletCategory.WHALE,
            wallet_address="0x111",
            token_id="T1",
            side="BUY",
            entry_price=0.5,
        )
        assert whale.weight == 0.8
        
        smart_trader = WalletTradeSignal(
            wallet_category=WalletCategory.SMART_TRADER,
            wallet_address="0x111",
            token_id="T1",
            side="BUY",
            entry_price=0.5,
        )
        assert smart_trader.weight == 1.2
        
        regular = WalletTradeSignal(
            wallet_category=WalletCategory.REGULAR,
            wallet_address="0x111",
            token_id="T1",
            side="BUY",
            entry_price=0.5,
        )
        assert regular.weight == 1.0
