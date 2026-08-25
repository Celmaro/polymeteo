"""Tests for EIP-712 signer."""

import time

from weather_copy_bot.live.signer import (
    EIP712Signer,
    Order,
    SignedOrder,
)


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        """Test creating an order."""
        order = Order(
            side=0,
            size=100_000_000,  # $100
            price=550_000,  # $0.55
            nonce=12345,
            token="0x1234567890123456789012345678901234567890",
            expiration=1234567890,
        )

        assert order.side == 0
        assert order.size == 100_000_000
        assert order.price == 550_000

    def test_order_to_typed_data(self):
        """Test converting order to EIP-712 format."""
        order = Order(
            side=1,  # SELL
            size=50_000_000,
            price=300_000,
            nonce=999,
            token="0xabcdef1234567890abcdef1234567890abcdef12",
            expiration=9999999999,
        )

        typed_data = order.to_typed_data({})

        assert typed_data["primaryType"] == "Order"
        assert typed_data["message"]["side"] == 1
        assert typed_data["message"]["size"] == 50_000_000


class TestEIP712Signer:
    """Tests for EIP712Signer."""

    def test_signer_creation(self):
        """Test creating a signer."""
        signer = EIP712Signer(
            private_key="0x" + "00" * 32,
            account_address="0x1234567890123456789012345678901234567890",
        )

        assert signer.address == "0x1234567890123456789012345678901234567890"

    def test_create_order(self):
        """Test creating an order from human values."""
        signer = EIP712Signer(private_key="0x" + "00" * 32)

        order = signer.create_order(
            side="BUY",
            size_usd=100.0,
            price=0.55,
            token="0xabcdef1234567890abcdef1234567890abcdef12",
        )

        assert order.side == 0  # BUY
        assert order.size == 100_000_000  # $100 in micro-USDC
        assert order.price == 550_000  # $0.55 in micro-USDC
        assert order.expiration > int(time.time())

    def test_sign_order(self):
        """Test signing an order."""
        signer = EIP712Signer(private_key="0x" + "00" * 32)

        order = signer.create_order(
            side="SELL",
            size_usd=50.0,
            price=0.30,
            token="0xabcdef1234567890abcdef1234567890abcdef12",
        )

        signed = signer.sign_order(order)

        assert isinstance(signed, SignedOrder)
        assert signed.signer == signer.address
        assert signed.signature.startswith("0x")
