"""
Gas-free CTF position redemption via Polymarket V2 Builder Relayer.

Queries data-api for redeemable positions on the proxy wallet, batches the
redemption calls per conditionId, and submits a single signed PROXY relayer
transaction. No gas fees because the relayer's hub pays.
"""

import time
import requests
from eth_utils import keccak
from eth_abi import encode

from trader.config import (
    PRIVATE_KEY, PROXY_ADDRESS, CHAIN_ID, RELAYER_URL, RPC_URL,
    BUILDER_API_KEY, BUILDER_SECRET, BUILDER_PASS_PHRASE,
)

# Polygon CTF / Polymarket V2 contracts
USDC_ADDR    = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
PUSD_ADDR    = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"  # Polymarket pUSD
CTF_ADDR     = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
ONRAMP_ADDR  = "0x93070a847efEf7F70739046A929D47a521F5B8ee"  # USDC.e → pUSD wrapper

DATA_API = "https://data-api.polymarket.com"
DEFAULT_RPC = "https://polygon.drpc.org"

WRAP_THRESHOLD = 1.0  # don't bother wrapping less than $1


def _selector(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def _encode_redeem_positions(condition_id: str) -> str:
    """ABI-encode CTF.redeemPositions(USDC, 0x0..0, conditionId, [1,2])."""
    sel = _selector("redeemPositions(address,bytes32,bytes32,uint256[])")
    cid_bytes = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)
    args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [USDC_ADDR, b"\x00" * 32, cid_bytes, [1, 2]],
    )
    return "0x" + (sel + args).hex()


def _encode_wrap(asset: str, to: str, amount: int) -> str:
    """ABI-encode CollateralOnramp.wrap(asset, to, amount)."""
    sel = _selector("wrap(address,address,uint256)")
    args = encode(["address", "address", "uint256"], [asset, to, amount])
    return "0x" + (sel + args).hex()


def _erc20_balance(token: str, owner: str, rpc_url: str = None) -> int:
    """Read ERC20 balanceOf(owner) directly via eth_call. Returns raw uint."""
    rpc_url = rpc_url or RPC_URL or DEFAULT_RPC
    sel = "0x70a08231"  # balanceOf(address)
    data = sel + "000000000000000000000000" + owner[2:].lower()
    try:
        r = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "method": "eth_call",
            "params": [{"to": token, "data": data}, "latest"], "id": 1,
        }, timeout=8)
        return int(r.json().get("result", "0x0"), 16)
    except Exception as e:
        print(f"[REDEEM] erc20 balance error: {e}")
        return 0


def wrap_pending_deposit(relay_client, proxy_address: str = None) -> float:
    """Wrap any USDC.e in the proxy wallet into pUSD (gas-free).

    The Polymarket UI shows 'Confirm pending deposit' when USDC.e sits in the
    proxy unwrapped. This automates that confirmation by calling the
    CollateralOnramp.wrap(). Allowance is assumed MAX (set once, persists).

    Returns the USDC amount wrapped, or 0.0 if nothing to do.
    """
    if relay_client is None:
        return 0.0
    proxy_address = proxy_address or PROXY_ADDRESS
    if not proxy_address:
        return 0.0

    raw = _erc20_balance(USDC_ADDR, proxy_address)
    amount = raw / 1_000_000
    if amount < WRAP_THRESHOLD:
        return 0.0

    from py_builder_relayer_client.models import Transaction

    txns = [Transaction(
        to=ONRAMP_ADDR,
        data=_encode_wrap(USDC_ADDR, proxy_address, raw),
        value="0",
    )]
    print(f"[REDEEM] Wrapping ${amount:.4f} USDC.e → pUSD via Onramp")
    try:
        resp = relay_client.execute(txns, metadata=f"wrap ${amount:.2f}")
        tx_hash = getattr(resp, "transaction_hash", None) or getattr(resp, "transactionHash", None)
        print(f"[REDEEM] wrap submitted tx={tx_hash[:18] if tx_hash else '?'}..")
        return amount
    except Exception as e:
        print(f"[REDEEM] wrap error: {e}")
        return 0.0


def get_redeemable(proxy_address: str, limit: int = 100) -> list[dict]:
    """Return list of redeemable positions for the proxy wallet."""
    try:
        r = requests.get(
            f"{DATA_API}/positions",
            params={"user": proxy_address, "limit": limit, "redeemable": "true"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return [p for p in r.json() if p.get("redeemable")]
    except Exception as e:
        print(f"[REDEEM] data-api error: {e}")
        return []


def init_relayer():
    """Initialize the Polymarket relayer client. Returns None if creds missing."""
    if not (BUILDER_API_KEY and BUILDER_SECRET and BUILDER_PASS_PHRASE):
        print("[REDEEM] Builder relayer creds incomplete — skipping init")
        print("         Set BUILDER_API_KEY, BUILDER_SECRET, BUILDER_PASS_PHRASE in .env")
        return None
    try:
        from py_builder_relayer_client.client import RelayClient
        from py_builder_relayer_client.models import RelayerTxType
        from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

        creds = BuilderApiKeyCreds(
            key=BUILDER_API_KEY,
            secret=BUILDER_SECRET,
            passphrase=BUILDER_PASS_PHRASE,
        )
        cfg = BuilderConfig(local_builder_creds=creds)
        # signature_type=1 (POLY_PROXY) → relay via PROXY tx type
        client = RelayClient(
            relayer_url=RELAYER_URL,
            chain_id=CHAIN_ID,
            private_key=PRIVATE_KEY,
            builder_config=cfg,
            relay_tx_type=RelayerTxType.PROXY,
            rpc_url=RPC_URL,
        )
        print(f"[REDEEM] Relayer ready (PROXY tx type, key={BUILDER_API_KEY[:8]}...)")
        return client
    except Exception as e:
        print(f"[REDEEM] init error: {e}")
        return None


REDEEM_BATCH_SIZE = 3  # max conditionIds per relayer tx (proxy-call gas limit)


def redeem_all(relay_client, proxy_address: str = None) -> int:
    """Find all redeemable positions and submit batched relayer txs.

    Returns total number of unique conditionIds for which redemption was submitted.
    Splits into batches of REDEEM_BATCH_SIZE to stay under proxy-call gas limits.
    """
    if relay_client is None:
        return 0
    proxy_address = proxy_address or PROXY_ADDRESS
    if not proxy_address:
        print("[REDEEM] no proxy address configured")
        return 0

    positions = get_redeemable(proxy_address)
    if not positions:
        return 0

    # Dedupe by conditionId — both UP and DN positions share the same conditionId
    by_cond = {}
    for p in positions:
        cid = p.get("conditionId")
        if not cid: continue
        by_cond.setdefault(cid, []).append(p)

    if not by_cond:
        return 0

    from py_builder_relayer_client.models import Transaction

    cond_ids = list(by_cond.keys())
    total_value = sum(float(p.get("currentValue", 0)) for p in positions)
    print(f"[REDEEM] Found {len(cond_ids)} conditionIds, {len(positions)} positions, "
          f"~${total_value:.2f} payout. Batching into groups of {REDEEM_BATCH_SIZE}.")

    submitted = 0
    for i in range(0, len(cond_ids), REDEEM_BATCH_SIZE):
        batch = cond_ids[i:i + REDEEM_BATCH_SIZE]
        txns = [Transaction(to=CTF_ADDR, data=_encode_redeem_positions(cid), value="0")
                for cid in batch]
        try:
            resp = relay_client.execute(txns, metadata=f"redeem batch {i//REDEEM_BATCH_SIZE+1}")
            tx_id = getattr(resp, "transaction_id", None) or getattr(resp, "transactionID", None)
            tx_hash = getattr(resp, "transaction_hash", None) or getattr(resp, "transactionHash", None)
            print(f"[REDEEM] batch {i//REDEEM_BATCH_SIZE+1}: {len(batch)} cids submitted "
                  f"tx={tx_hash[:18] if tx_hash else '?'}")
            submitted += len(batch)
            time.sleep(2)  # avoid hammering relayer
        except Exception as e:
            print(f"[REDEEM] batch {i//REDEEM_BATCH_SIZE+1} error: {e}")
    return submitted
