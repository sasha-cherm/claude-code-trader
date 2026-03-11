"""Polymarket CLOB client wrapper."""
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
from trader.config import PRIVATE_KEY, PROXY_ADDRESS, CHAIN_ID, CLOB_HOST


def orderbook_to_dict(book) -> dict:
    """Convert OrderBookSummary object (or dict) to consistent dict format."""
    if book is None:
        return {}
    if isinstance(book, dict):
        return book
    # OrderBookSummary object: .bids and .asks are lists of OrderSummary with .price and .size
    # Normalize to standard order: bids descending (best bid first), asks ascending (best ask first)
    def conv(orders, descending: bool):
        result = []
        for o in (orders or []):
            try:
                result.append({"price": str(o.price), "size": str(o.size)})
            except Exception:
                pass
        result.sort(key=lambda x: float(x["price"]), reverse=descending)
        return result
    return {
        "bids": conv(getattr(book, "bids", []), descending=True),
        "asks": conv(getattr(book, "asks", []), descending=False),
        "min_order_size": getattr(book, "min_order_size", "1"),
        "tick_size": getattr(book, "tick_size", "0.01"),
        "last_trade_price": getattr(book, "last_trade_price", None),
    }


def get_client() -> ClobClient:
    client = ClobClient(
        host=CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,  # proxy wallet (Polymarket magic/embedded wallet)
        funder=PROXY_ADDRESS or None,
    )
    # Derive API credentials from private key
    try:
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
    except Exception as e:
        print(f"[CLIENT] Could not derive API creds: {e}")
    return client


def get_usdc_balance(client: ClobClient) -> float:
    """Return USDC balance in the CLOB collateral wallet (in USDC, 6-decimal adjusted)."""
    try:
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.get_balance_allowance(params)
        raw = result.get("balance", "0") or "0"
        # USDC has 6 decimals on Polygon
        return float(raw) / 1_000_000
    except Exception as e:
        print(f"[BALANCE] Error: {e}")
        return 0.0
