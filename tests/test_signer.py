"""Tests for EIP-712 signer."""

import json
import time

import httpx
import pytest

from weather_copy_bot.live.signer import (
    CLOBExecutor,
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
            private_key="0x" + "01" * 32,
            account_address="0x1234567890123456789012345678901234567890",
        )

        assert signer.address == "0x1234567890123456789012345678901234567890"

    def test_create_order(self):
        """Test creating an order from human values."""
        signer = EIP712Signer(
            private_key="0x" + "01" * 32,
            account_address="0x1234567890123456789012345678901234567890",
        )

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
        pytest.importorskip("eth_account")
        signer = EIP712Signer(private_key="0x" + "01" * 32)

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


class TestSignerFailClosed:
    """A signer without a working key backend must refuse to sign."""

    def test_sign_order_without_backend_raises(self):
        signer = EIP712Signer(
            private_key="0x" + "01" * 32,
            account_address="0x1234567890123456789012345678901234567890",
        )
        signer._account = None
        order = Order(
            side=0,
            size=100_000_000,
            price=550_000,
            nonce=1,
            token="0xabcdef1234567890abcdef1234567890abcdef12",
            expiration=int(time.time()) + 60,
        )
        with pytest.raises(RuntimeError):
            signer.sign_order(order)


class TestExecutorSafety:
    """CLOBExecutor must default to dry-run and gate live network traffic."""

    def _make_executor(self, handler, dry_run=None) -> CLOBExecutor:
        signer = EIP712Signer(
            private_key="0x" + "01" * 32,
            account_address="0x1234567890123456789012345678901234567890",
        )
        # Executor routing tests are hermetic: signing correctness is covered
        # elsewhere, so stub it to avoid depending on eth_account availability.
        signer.sign_order = lambda order: SignedOrder(
            order=order,
            signature="0x" + "22" * 65,
            signer=signer.address,
        )
        executor = CLOBExecutor(
            signer=signer,
            api_url="https://clob.example.com",
            dry_run=dry_run,
        )
        executor._client = httpx.AsyncClient(
            base_url="https://clob.example.com",
            transport=httpx.MockTransport(handler),
            timeout=30.0,
        )
        return executor

    def _signed(self) -> SignedOrder:
        order = Order(
            side=0,
            size=10_000_000,
            price=500_000,
            nonce=42,
            token="0xtoken",
            expiration=int(time.time()) + 60,
        )
        return SignedOrder(
            order=order,
            signature="0x" + "11" * 65,
            signer="0x1234567890123456789012345678901234567890",
        )

    @pytest.mark.asyncio
    async def test_dry_run_submit_never_hits_network(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"orderID": "live-1"})

        executor = self._make_executor(handler, dry_run=True)
        result = await executor.submit_order(self._signed())
        await executor._client.aclose()

        assert result.success is True
        assert result.order_id.startswith("dry_run:")
        assert calls == []

    @pytest.mark.asyncio
    async def test_dry_run_defaults_true_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={})

        executor = self._make_executor(handler)
        result = await executor.submit_order(self._signed())
        await executor._client.aclose()

        assert result.order_id.startswith("dry_run:")
        assert calls == []

    @pytest.mark.asyncio
    async def test_live_submit_posts_signed_payload(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["payload"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"orderID": "live-77", "txHash": "0xtx"})

        executor = self._make_executor(handler, dry_run=False)
        result = await executor.submit_order(self._signed())
        await executor._client.aclose()

        assert result.success is True
        assert result.order_id == "live-77"
        assert seen["path"] == "/orders"
        assert seen["payload"]["signature"].startswith("0x")

    @pytest.mark.asyncio
    async def test_close_position_sells_known_position(self):
        routes = []

        def handler(request):
            routes.append((request.method, request.url.path))
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "positions": [
                            {
                                "position_id": "p1",
                                "token_id": "0xtoken",
                                "size": 25.0,
                                "avg_price": 0.55,
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"orderID": "close-1"})

        executor = self._make_executor(handler, dry_run=False)
        result = await executor.close_position("p1")
        await executor._client.aclose()

        assert result.success is True
        assert result.order_id == "close-1"
        assert routes == [("GET", "/positions"), ("POST", "/orders")]

    @pytest.mark.asyncio
    async def test_close_unknown_position_reports_not_found(self):
        def handler(request):
            return httpx.Response(200, json={"positions": []})

        executor = self._make_executor(handler, dry_run=False)
        result = await executor.close_position("missing")
        await executor._client.aclose()

        assert result.success is False
        assert "not found" in (result.error or "").lower()


class TestCollateralManager:
    """Collateral ops must refuse instead of returning fabricated tx hashes."""

    @pytest.mark.asyncio
    async def test_wrap_without_web3_raises(self):
        from weather_copy_bot.live.signer import CollateralManager

        manager = CollateralManager(
            private_key="0x" + "01" * 32, rpc_url="http://127.0.0.1:1"
        )
        with pytest.raises(RuntimeError):
            await manager.wrap_usdc(1000)

    @pytest.mark.asyncio
    async def test_unwrap_without_web3_raises(self):
        from weather_copy_bot.live.signer import CollateralManager

        manager = CollateralManager(
            private_key="0x" + "01" * 32, rpc_url="http://127.0.0.1:1"
        )
        with pytest.raises(RuntimeError):
            await manager.unwrap_pusdc(1000)
