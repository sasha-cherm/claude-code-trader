"""Polymarket CLOB client wrapper."""
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
from trader.config import PRIVATE_KEY, CHAIN_ID, CLOB_HOST


def get_client() -> ClobClient:
    client = ClobClient(
        host=CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=0,  # EOA
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
