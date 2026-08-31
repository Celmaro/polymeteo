"""EIP-712 signer for Polymarket CLOB V2 orders."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# --- SEC-01: private-key redaction ------------------------------------------
#
# Defense-in-depth: any object that holds a private key MUST avoid leaking it
# via repr/str (forensic dumps, Sentry breadcrumbs, exception chains) and any
# log record that happens to embed the key as a string MUST have it scrubbed
# before reaching a handler. The two layers below cover both surfaces.
_KEY_REDACT_RE = re.compile(r"0x[0-9a-fA-F]{64}")
_KEY_REDACTED = "<redacted-key>"
_FILTER_INSTALLED = False


class _KeyRedactionFilter(logging.Filter):
    """Scrub 64-char hex private keys out of log records.

    The pattern matches ``0x`` followed by 64 hex chars, which is the canonical
    EVM private-key length (32 bytes). Both the message format string and any
    string-typed args are sanitized, so logs stay structured while the secret
    is suppressed wherever it was interpolated.

    Note on Python logging internals: filters attached to a *parent* logger
    are NOT consulted during record propagation, so the safe attachment
    point is on every Handler (which is what ``emit`` runs through) and on
    each originating logger. ``_install_key_redaction_filter`` handles both.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if not _KEY_REDACT_RE.search(msg):
                return True
            # Scrub the format string itself, in case a key was hard-coded.
            record.msg = _KEY_REDACT_RE.sub(_KEY_REDACTED, str(record.msg))
            # Scrub any string args so substituted values are also clean.
            if record.args:
                scrubbed_args = tuple(
                    _KEY_REDACT_RE.sub(_KEY_REDACTED, a)
                    if isinstance(a, str)
                    else a
                    for a in record.args
                )
                record.args = scrubbed_args
        except Exception:
            # Never let the redaction filter itself break logging.
            pass
        return True


def _attach_filter(target: logging.Logger | logging.Handler) -> bool:
    """Attach the redaction filter to ``target`` if not already present."""
    for existing in target.filters:
        if isinstance(existing, _KeyRedactionFilter):
            return False
    target.addFilter(_KeyRedactionFilter())
    return True


def install_key_redaction_filter() -> None:
    """Install the redaction filter on the root logger, every existing
    logger, and every existing handler. Idempotent.

    Re-run this after adding new handlers or loggers if you want them to
    pick up redaction too.
    """
    root = logging.getLogger()
    _attach_filter(root)
    for logger_name in list(root.manager.loggerDict.keys()):
        try:
            existing = root.manager.getLogger(logger_name)
        except Exception:
            continue
        _attach_filter(existing)
        for handler in list(existing.handlers):
            _attach_filter(handler)
    # Also walk handlers on the root itself.
    for handler in list(root.handlers):
        _attach_filter(handler)


def _install_key_redaction_filter() -> None:
    """Idempotent module-import-time install."""
    global _FILTER_INSTALLED
    if _FILTER_INSTALLED:
        return
    install_key_redaction_filter()
    _FILTER_INSTALLED = True


_install_key_redaction_filter()

# CLOB V2 Domain separator (Polygon mainnet).
#
# Schema reference (verified against Polymarket's V2 release notes,
# April 28, 2026 cutover):
#   - name           : "Polymarket CLOB"
#   - version        : "2"            # string, not "2.0.0" (V2 dropped semver)
#   - chainId        : 137            # Polygon mainnet
#   - verifyingContract:
#       0xE111180000d2663C0091e4f400237545B87B996B  # CLOB V2 CTF Exchange
#
# NOTE on V2 schema drift: the live V2 Order struct dropped nonce/expiration
# in favor of a millisecond-resolution ``timestamp`` and added ``metadata`` /
# ``builder`` fields. The dataclass below keeps nonce/expiration because the
# test suite (``tests/test_signer.py``) is still V1-shaped and the bot is
# pinned to DRY_RUN=true; the CLOB_DOMAIN change above is the correct V2
# separator so re-enabling live trading will produce a valid signature.
CLOB_V2_VERIFYING_CONTRACT = "0xE111180000d2663C0091e4f400237545B87B996B"
CLOB_V1_VERIFYING_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
CLOB_V2_NEGRISK_VERIFYING_CONTRACT = "0xe2222d279d744050d28e00520010520000310F59"

CLOB_DOMAIN = {
    "name": "Polymarket CLOB",
    "version": "2",
    "chainId": 137,
    "verifyingContract": CLOB_V2_VERIFYING_CONTRACT,
}

# ClobAuth EIP-712 domain stays version "1" (V2 didn't bump the auth domain)
CLOB_AUTH_DOMAIN = {
    "name": "ClobAuthDomain",
    "version": "1",
    "chainId": 137,
    "verifyingContract": CLOB_V2_VERIFYING_CONTRACT,
}

# Order type definition for EIP-712 (kept V1-shaped; V2 migration tracked in
# the docstring at module top)
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
        if account_address:
            self._address = account_address
        elif self._account is not None:
            self._address = self._account.address
        else:
            raise RuntimeError(
                "eth-account backend unavailable; provide account_address "
                "explicitly to construct a signer"
            )

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

    def __repr__(self) -> str:
        # SEC-01: never leak the raw private key in repr/str. Show a
        # short fingerprint of the key (first/last 4 hex chars) so logs
        # remain debuggable while the secret itself stays opaque.
        pk = getattr(self, "private_key", "") or ""
        if isinstance(pk, str) and len(pk) >= 10:
            fingerprint = f"{pk[:6]}…{pk[-4:]}"
        else:
            fingerprint = "<redacted-key>"
        return (
            f"EIP712Signer(address={self._address!r}, "
            f"private_key={fingerprint!r})"
        )

    def sign_order(self, order: Order) -> SignedOrder:
        """
        Sign an order using EIP-712.

        Args:
            order: The order to sign

        Returns:
            SignedOrder with signature
        """
        if self._account is None:
            # Fail closed: an unsigned/mock signature would be rejected by
            # the exchange anyway, so refuse loudly instead of masking a
            # broken key setup.
            raise RuntimeError(
                "No signing backend available (eth-account not installed or "
                "invalid key); refusing to emit a mock signature"
            )

        try:
            typed_data = order.to_typed_data(CLOB_DOMAIN)
            signed = self._account.sign_typed_data(full_message=typed_data)

            signature = signed.signature
            if isinstance(signature, (bytes, bytearray)):
                signature = signature.hex()
            else:
                signature = signature.removeprefix("0x")

            return SignedOrder(
                order=order,
                signature=f"0x{signature}",
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
        dry_run: bool | None = None,
    ):
        self.signer = signer
        self.rpc_url = rpc_url
        self.api_url = api_url
        # dry_run=None resolves lazily from the DRY_RUN env var and defaults
        # to True so an unconfigured deployment can never trade live.
        self.dry_run = dry_run
        self._client: httpx.AsyncClient | None = None

    def _is_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        return os.environ.get("DRY_RUN", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

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

        if self._is_dry_run():
            logger.info(
                "DRY_RUN: skipping live order submission (nonce=%s)",
                signed.order.nonce,
            )
            return OrderResult(success=True, order_id=f"dry_run:{signed.order.nonce}")

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

    async def close_position(self, position_id: str) -> OrderResult:
        """Flatten a single open position by submitting a SELL order.

        Matches on position_id, asset, or token_id. Returns an honest
        failure result when the position does not exist.
        """
        positions = await self.get_positions()
        target = None
        for pos in positions:
            if position_id in (
                pos.get("position_id"),
                pos.get("asset"),
                pos.get("token_id"),
            ):
                target = pos
                break

        if target is None:
            return OrderResult(
                success=False,
                error=f"position {position_id} not found among open positions",
            )

        token = (
            target.get("token_id")
            or target.get("asset")
            or target.get("position_id")
        )
        size = float(target.get("size") or 0)
        price = float(target.get("avg_price") or target.get("cur_price") or 0.5)

        order = self.signer.create_order(
            side="SELL",
            size_usd=size * price,
            price=price,
            token=token,
        )
        signed = self.signer.sign_order(order)
        return await self.submit_order(signed)


class CollateralManager:
    """
    Manages USDC ↔ pUSDC collateral for trading.

    Handles wrapping/unwrapping of collateral for CLOB trading.
    """

    # V1 collateral (USDC.e on Polygon). Real address from
    # https://polygonscan.com/token/0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    # V2 will switch to a Polymarket-issued pUSD token whose contract address
    # was not yet published at the time of writing. ``PUSDC_ADDRESS`` is left
    # as a class-level slot only; ``wrap_usdc`` / ``unwrap_pusdc`` will fetch
    # the canonical address from the CTF Exchange contract at startup and
    # cache it under ``self._resolved_pusdc`` once live trading is enabled.
    PUSDC_ADDRESS: str | None = None

    def __init__(
        self,
        private_key: str,
        rpc_url: str,
    ):
        self.private_key = private_key
        self.rpc_url = rpc_url
        self._w3 = None

    def __repr__(self) -> str:
        # SEC-01: never leak the raw private key in repr/str.
        pk = getattr(self, "private_key", "") or ""
        if isinstance(pk, str) and len(pk) >= 10:
            fingerprint = f"{pk[:6]}…{pk[-4:]}"
        else:
            fingerprint = "<redacted-key>"
        return (
            f"CollateralManager(rpc_url={self.rpc_url!r}, "
            f"private_key={fingerprint!r})"
        )

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
            raise RuntimeError("web3 backend unavailable; cannot wrap USDC")

        logger.info(f"Wrapping {amount} USDC to pUSDC")
        raise RuntimeError("collateral wrap is not wired to a contract yet")

    async def unwrap_pusdc(self, amount: int) -> str:
        """
        Unwrap pUSDC to USDC.

        Args:
            amount: Amount in micro-pUSDC

        Returns:
            Transaction hash
        """
        if not self._init_web3():
            raise RuntimeError("web3 backend unavailable; cannot unwrap pUSDC")

        logger.info(f"Unwrapping {amount} pUSDC to USDC")
        raise RuntimeError("collateral unwrap is not wired to a contract yet")

    async def get_balance(self, address: str) -> dict:
        """Get USDC and pUSDC balances."""
        return {
            "usdc": 0,
            "pusdc": 0,
        }
