"""Polymarket CLOB client wrapper (V2 — CTF Exchange V2)."""
from py_clob_client_v2 import ClobClient, BalanceAllowanceParams, AssetType
from trader.config import PRIVATE_KEY, PROXY_ADDRESS, CHAIN_ID, CLOB_HOST


def orderbook_to_dict(book) -> dict:
    """Convert orderbook (dict or OrderBookSummary) to consistent format.

    V2 returns a dict with bids/asks as ascending/descending lists of
    {price, size}; V1 returned an OrderBookSummary with .bids/.asks of
    OrderSummary objects. Always returns:
      bids descending (best bid = highest price first)
      asks ascending  (best ask = lowest price first)
    """
    if book is None:
        return {}

    def normalize(o):
        if isinstance(o, dict):
            return {"price": str(o.get("price")), "size": str(o.get("size"))}
        return {"price": str(getattr(o, "price", "")), "size": str(getattr(o, "size", ""))}

    if isinstance(book, dict):
        raw_bids = book.get("bids") or []
        raw_asks = book.get("asks") or []
        meta_min = book.get("min_order_size", "1")
        meta_tick = book.get("tick_size", "0.01")
        meta_last = book.get("last_trade_price")
    else:
        raw_bids = getattr(book, "bids", []) or []
        raw_asks = getattr(book, "asks", []) or []
        meta_min = getattr(book, "min_order_size", "1")
        meta_tick = getattr(book, "tick_size", "0.01")
        meta_last = getattr(book, "last_trade_price", None)

    bids = [normalize(o) for o in raw_bids]
    asks = [normalize(o) for o in raw_asks]
    bids.sort(key=lambda x: float(x["price"]) if x["price"] else 0, reverse=True)
    asks.sort(key=lambda x: float(x["price"]) if x["price"] else 0, reverse=False)
    return {
        "bids": bids,
        "asks": asks,
        "min_order_size": meta_min,
        "tick_size": meta_tick,
        "last_trade_price": meta_last,
    }


def get_client() -> ClobClient:
    client = ClobClient(
        host=CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,  # proxy wallet (Polymarket magic/embedded wallet)
        funder=PROXY_ADDRESS or None,
    )
    # Derive API credentials from private key (V2: create_or_derive_api_key)
    try:
        creds = client.create_or_derive_api_key()
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
