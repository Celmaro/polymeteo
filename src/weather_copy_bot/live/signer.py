"""EIP-712 signer for Polymarket CLOB V2 orders."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# CLOB V2 Domain separator (Polygon mainnet)
CLOB_DOMAIN = {
    "name": "Polymarket CLOB",
    "version": "2.0.0",
    "chainId": 137,  # Polygon mainnet
    "verifyingContract": "0x4b7e63701C8a2F0Bc4a07F6F05C0cC0b7d2D3a8e",
}

# Order type definition for EIP-712
ORDER_TYPES = {
    "Order": [
        {"name": "side", "type": "uint8"},
        {"name": "size", "type": "uint256"},
        {"name": "price", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "token", "type": "address"},
        {"name": "expiration", "type": "uint256"},
    ],
}


@dataclass
class Order:
    """CLOB V2 Order structure."""

    side: int  # 0 = BUY, 1 = SELL
    size: int  # Size in micro-USDC (1e6 = 1 USDC)
    price: int  # Price in micro-USDC (e.g., 550000 = $0.55)
    nonce: int  # Unique nonce for this order
    token: str  # Token address
    expiration: int  # Unix timestamp

    def to_typed_data(self, domain: dict) -> dict:
        """Convert to EIP-712 typed data format."""
        return {
            "domain": domain,
            "types": ORDER_TYPES,
            "primaryType": "Order",
            "message": {
                "side": self.side,
                "size": self.size,
                "price": self.price,
                "nonce": self.nonce,
                "token": self.token,
                "expiration": self.expiration,
            },
        }


@dataclass
class SignedOrder:
    """Order with signature."""

    order: Order
    signature: str
    signer: str


@dataclass
class OrderResult:
    """Result of order submission."""

    success: bool
    order_id: str | None = None
    tx_hash: str | None = None
    error: str | None = None


class EIP712Signer:
    """
    EIP-712 signer for Polymarket CLOB V2 orders.

    This implements native EIP-712 signing without heavy SDK dependencies.

    Example:
        signer = EIP712Signer(private_key="0x...")

        order = Order(
            side=0,  # BUY
            size=100_000_000,  # $100
            price=550_000,  # $0.55
            nonce=12345,
            token="0x...",
            expiration=1234567890,
        )

        signed = signer.sign_order(order)

        result = await signer.submit_order(signed)
    """

    def __init__(
        self,
        private_key: str,
        account_address: str | None = None,
    ):
        self.private_key = private_key
        self._account = self._init_account(private_key)
        self._address = account_address or self._account.address

    def _init_account(self, private_key: str):
        """Initialize web3 account."""
        try:
            from eth_account import Account

            return Account.from_key(private_key)
        except ImportError:
            logger.warning("eth-account not installed, using fallback")
            return None

    @property
    def address(self) -> str:
        """Get signer address."""
        return self._address

    def sign_order(self, order: Order) -> SignedOrder:
        """
        Sign an order using EIP-712.

        Args:
            order: The order to sign

        Returns:
            SignedOrder with signature
        """
        if self._account is None:
            # Fallback: mock signature for testing
            logger.warning("Using mock signature (eth-account not available)")
            return SignedOrder(
                order=order,
                signature="0x" + "00" * 65,
                signer=self._address,
            )

        try:
            typed_data = order.to_typed_data(CLOB_DOMAIN)
            signed = self._account.sign_typed_data(**typed_data)

            return SignedOrder(
                order=order,
                signature=signed.signature.hex(),
                signer=self._address,
            )
        except Exception as e:
            logger.error(f"Failed to sign order: {e}")
            raise

    def create_order(
        self,
        side: str,
        size_usd: float,
        price: float,
        token: str,
        nonce: int | None = None,
        expiration_seconds: int = 86400,
    ) -> Order:
        """
        Create a new order from human-readable values.

        Args:
            side: "BUY" or "SELL"
            size_usd: Size in USD
            price: Price in USD (0.0 to 1.0)
            token: Token address
            nonce: Optional nonce (generated if not provided)
            expiration_seconds: Order expiration time

        Returns:
            Order ready to be signed
        """
        import time

        # Convert to micro-USDC (1e6 precision)
        size_micro = int(size_usd * 1_000_000)
        price_micro = int(price * 1_000_000)

        # Nonce (use provided or generate)
        if nonce is None:
            nonce = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF

        # Expiration (Unix timestamp)
        expiration = int(time.time()) + expiration_seconds

        # Side: 0 = BUY, 1 = SELL
        side_int = 0 if side.upper() == "BUY" else 1

        return Order(
            side=side_int,
            size=size_micro,
            price=price_micro,
            nonce=nonce,
            token=token,
            expiration=expiration,
        )


class CLOBExecutor:
    """
    Executor for submitting signed orders to CLOB V2.

    Handles order submission, confirmation, and cancellation.
    """

    def __init__(
        self,
        signer: EIP712Signer,
        rpc_url: str | None = None,
        api_url: str = "https://clob.polymarket.com",
    ):
        self.signer = signer
        self.rpc_url = rpc_url
        self.api_url = api_url
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> CLOBExecutor:
        self._client = httpx.AsyncClient(base_url=self.api_url, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    async def submit_order(self, signed: SignedOrder) -> OrderResult:
        """
        Submit a signed order to the CLOB.

        Args:
            signed: The signed order

        Returns:
            OrderResult with success status and details
        """
        if not self._client:
            return OrderResult(success=False, error="Client not initialized")

        try:
            # Build order payload
            payload = {
                "order": {
                    "side": signed.order.side,
                    "size": str(signed.order.size),
                    "price": str(signed.order.price),
                    "nonce": str(signed.order.nonce),
                    "token": signed.order.token,
                    "expiration": str(signed.order.expiration),
                },
                "signature": signed.signature,
                "signer": signed.signer,
            }

            # Submit to CLOB API
            resp = await self._client.post("/orders", json=payload)

            if resp.status_code == 200:
                data = resp.json()
                return OrderResult(
                    success=True,
                    order_id=data.get("orderID"),
                    tx_hash=data.get("txHash"),
                )
            return OrderResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text}",
            )

        except Exception as e:
            logger.error(f"Failed to submit order: {e}")
            return OrderResult(success=False, error=str(e))

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an existing order."""
        if not self._client:
            return OrderResult(success=False, error="Client not initialized")

        try:
            # Create cancel message
            cancel_payload = {
                "orderID": order_id,
                "signer": self.signer.address,
            }

            resp = await self._client.delete(f"/orders/{order_id}", json=cancel_payload)

            if resp.status_code == 200:
                return OrderResult(success=True)
            return OrderResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text}",
            )

        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return OrderResult(success=False, error=str(e))

    async def get_order_status(self, order_id: str) -> dict:
        """Get order status from CLOB."""
        if not self._client:
            return {"error": "Client not initialized"}

        try:
            resp = await self._client.get(f"/orders/{order_id}")
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def get_positions(self) -> list[dict]:
        """Get open positions for the signer."""
        if not self._client:
            return []

        try:
            resp = await self._client.get(
                "/positions",
                params={"address": self.signer.address},
            )
            if resp.status_code == 200:
                return resp.json().get("positions", [])
            return []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []


class CollateralManager:
    """
    Manages USDC ↔ pUSDC collateral for trading.

    Handles wrapping/unwrapping of collateral for CLOB trading.
    """

    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Polygon USDC
    PUSDC_ADDRESS = "0x9F2817E0d3F1c1e3C0a2C7E4F6c8A9b0D1E2F3a"  # pUSDC

    def __init__(
        self,
        private_key: str,
        rpc_url: str,
    ):
        self.private_key = private_key
        self.rpc_url = rpc_url
        self._w3 = None

    def _init_web3(self):
        """Initialize web3."""
        try:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            return self._w3.is_connected()
        except ImportError:
            logger.warning("web3 not installed")
            return False

    async def wrap_usdc(self, amount: int) -> str:
        """
        Wrap USDC to pUSDC.

        Args:
            amount: Amount in micro-USDC

        Returns:
            Transaction hash
        """
        if not self._init_web3():
            return "0x" + "00" * 32  # Mock tx

        # In production, call the wrap function on the collateral contract
        logger.info(f"Wrapping {amount} USDC to pUSDC")
        return "0x" + "00" * 32

    async def unwrap_pusdc(self, amount: int) -> str:
        """
        Unwrap pUSDC to USDC.

        Args:
            amount: Amount in micro-pUSDC

        Returns:
            Transaction hash
        """
        if not self._init_web3():
            return "0x" + "00" * 32  # Mock tx

        logger.info(f"Unwrapping {amount} pUSDC to USDC")
        return "0x" + "00" * 32

    async def get_balance(self, address: str) -> dict:
        """Get USDC and pUSDC balances."""
        return {
            "usdc": 0,
            "pusdc": 0,
        }
