"""
CLOB helpers: orderbook, order placement, cancel, balance, market sell, settlement.
"""

import math
import time
from datetime import timedelta

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from py_clob_client.clob_types import (
    OrderArgs, OrderType, BalanceAllowanceParams, AssetType, OpenOrderParams,
)
from py_clob_client.order_builder.constants import BUY, SELL

from mm_config import _retry, utcnow, MIN_SIZE, TICK


def get_book(client, token_id):
    try:
        return _retry(lambda: orderbook_to_dict(client.get_order_book(token_id)),
                       retries=2, delay=1, tag="BOOK")
    except Exception as e:
        print(f"[MM] book error: {e}")
        return None


def bid_depth(book, levels=5):
    """Sum bid volume across top N levels."""
    if not book or not book.get("bids"):
        return 0.0
    total = 0.0
    for b in book["bids"][:levels]:
        total += float(b.get("size", 0))
    return total


def find_support_price(book, max_levels=4):
    """Find buy price just above the fattest bid level in top N levels.

    The fattest level is a support wall. Placing one tick above it means
    we fill just as price reaches support, with the wall protecting us.
    """
    bids = book.get("bids", [])[:max_levels]
    if not bids:
        return None

    fattest_idx = 0
    fattest_size = 0
    for i, b in enumerate(bids):
        size = float(b.get("size", 0))
        if size > fattest_size:
            fattest_size = size
            fattest_idx = i

    fattest_price = float(bids[fattest_idx]["price"])

    if fattest_idx == 0:
        # Fattest IS best bid — place at bb + tick (ahead of it)
        return round(fattest_price + TICK, 2)
    else:
        # Place one tick above the wall
        return round(fattest_price + TICK, 2)


def pick_side(client, up_token, dn_token, current_side=None, hysteresis=0.2):
    """Pick the token with stronger bid support. Sticky: only switch if >20% advantage."""
    up_book = get_book(client, up_token)
    dn_book = get_book(client, dn_token)
    up_depth = bid_depth(up_book)
    dn_depth = bid_depth(dn_book)

    # If already on a side, require significant advantage to switch
    if current_side == "UP" and dn_depth <= up_depth * (1 + hysteresis):
        return up_token, "UP"
    if current_side == "DN" and up_depth <= dn_depth * (1 + hysteresis):
        return dn_token, "DN"

    if up_depth >= dn_depth:
        if current_side != "UP":
            print(f"[MM] Side: UP (bid depth UP={up_depth:.0f} vs DN={dn_depth:.0f})")
        return up_token, "UP"
    else:
        if current_side != "DN":
            print(f"[MM] Side: DN (bid depth DN={dn_depth:.0f} vs UP={up_depth:.0f})")
        return dn_token, "DN"


def get_token_balance(client, token_id):
    """Get how many shares of a conditional token we hold."""
    try:
        def _do():
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
            )
            resp = client.get_balance_allowance(params)
            raw = float(resp.get("balance", 0))
            return raw / 1e6
        return _retry(_do, retries=2, delay=1, tag="BAL")
    except Exception as e:
        print(f"[MM] token balance error: {e}")
        return 0.0


def place_order(client, token_id, price, size, side, tag=""):
    price = round(price, 2)
    if side == BUY:
        size = round(max(MIN_SIZE, size), 2)
    else:
        size = round(size, 2)   # SELL: use actual size, don't inflate
    if size < 0.01 or not (0.01 <= price <= 0.99):
        return None
    try:
        def _do():
            args = OrderArgs(token_id=token_id, price=price, size=size, side=side)
            signed = client.create_order(args)
            return client.post_order(signed, orderType=OrderType.GTC)
        resp = _retry(_do, retries=2, delay=2, tag=tag)
        oid = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        side_str = "BUY" if side == BUY else "SELL"
        print(f"[{tag}] {side_str} {size:.0f}sh @ {price:.2f}  oid={oid}")
        return oid
    except Exception as e:
        print(f"[{tag}] place error: {e}")
        return None


def cancel_ord(client, oid, tag=""):
    try:
        _retry(lambda: client.cancel(oid), retries=2, delay=1, tag=tag)
        print(f"[{tag}] cancelled {oid[:16]}...")
        return True
    except Exception as e:
        print(f"[{tag}] cancel fail: {e}")
        return False


def order_filled(client, oid):
    """Return (is_fully_filled, filled_size)."""
    try:
        o = _retry(lambda: client.get_order(oid), retries=2, delay=1, tag="ORD")
        if not isinstance(o, dict):
            return False, 0
        st = (o.get("status") or "").upper()
        filled = float(o.get("size_matched") or o.get("sizeMatched") or 0)
        return st in ("FILLED", "MATCHED"), filled
    except:
        return False, 0


def market_sell(client, token_id, size, tag=""):
    """FOK SELL to dump position. Checks fill value >= $1 (CLOB minimum)."""
    size = round(size, 2)
    if size <= 0:
        return None
    # Check if fill value meets $1 minimum: size × best_bid >= $1
    try:
        book = _retry(lambda: orderbook_to_dict(client.get_order_book(token_id)),
                       retries=2, delay=1, tag=tag)
        best_bid = float(book["bids"][0]["price"]) if book and book.get("bids") else 0
    except Exception:
        best_bid = 0.50  # estimate
    fill_value = size * best_bid
    if fill_value < 1.0:
        print(f"[{tag}] FOK skip: {size}sh × ${best_bid:.2f} = ${fill_value:.2f} < $1 min")
        return {"too_small": True}
    try:
        def _do():
            args = OrderArgs(token_id=token_id, price=0.01, size=size, side=SELL)
            signed = client.create_order(args)
            return client.post_order(signed, orderType=OrderType.FOK)
        resp = _retry(_do, retries=2, delay=2, tag=tag)
        print(f"[{tag}] MARKET SELL {size}sh => {resp}")
        return resp
    except Exception as e:
        err_str = str(e)
        if "sum of matched orders" in err_str or "sum of active orders" in err_str:
            print(f"[{tag}] tokens locked by pending order, waiting for settlement...")
            return {"pending_settlement": True}
        print(f"[{tag}] market sell fail: {e}")
        return None


def cancel_all_token_orders(client, token_id, tag=""):
    """Cancel all open orders for a given token."""
    try:
        orders = _retry(lambda: client.get_orders(OpenOrderParams(asset_id=token_id)),
                        retries=4, delay=2, tag=tag)
        if not orders:
            return
        oids = [o.get("id") or o.get("orderID") for o in orders if isinstance(o, dict)]
        oids = [o for o in oids if o]
        if oids:
            print(f"[{tag}] Cancelling {len(oids)} open orders for token")
            try:
                _retry(lambda: client.cancel_orders(oids), retries=2, delay=1, tag=tag)
            except Exception as e:
                print(f"[{tag}] bulk cancel error: {e}")
    except Exception as e:
        print(f"[{tag}] list orders error: {e}")


def wait_for_settlement(client, token_id, timeout=15, tag=""):
    """Wait up to timeout seconds for token balance to drop (sell to settle)."""
    deadline = utcnow() + timedelta(seconds=timeout)
    initial_bal = get_token_balance(client, token_id)
    while utcnow() < deadline:
        time.sleep(2)
        bal = get_token_balance(client, token_id)
        if bal < 1.0:
            print(f"[{tag}] Settlement confirmed: bal={bal:.2f}")
            return True
        if bal < initial_bal - 0.5:
            print(f"[{tag}] Partial settlement: {initial_bal:.2f} → {bal:.2f}")
            initial_bal = bal
    print(f"[{tag}] Settlement timeout after {timeout}s, bal={get_token_balance(client, token_id):.2f}")
    return False


def close_position(client, token_id, tag="CLOSE"):
    """Aggressively close a token position. Returns True if position closed."""
    cancel_all_token_orders(client, token_id, tag)
    time.sleep(1)

    bal = get_token_balance(client, token_id)
    if bal < 0.5:
        return True

    size = math.floor(bal * 100) / 100
    if size < 0.01:
        return True

    book = get_book(client, token_id)
    best_bid = float(book["bids"][0]["price"]) if book and book.get("bids") else 0

    # Method 1: GTC limit sell at best_bid (crosses spread, fills instantly)
    # Works for any size the CLOB accepts — no $1 minimum
    if size >= 1.0 and best_bid >= 0.02:
        print(f"[{tag}] GTC sell {size:.2f}sh @ {best_bid:.2f} (at bid)")
        oid = place_order(client, token_id, best_bid, size, SELL, tag)
        if oid:
            # Wait for fill
            for _ in range(10):
                time.sleep(2)
                nb = get_token_balance(client, token_id)
                if nb < 0.5:
                    print(f"[{tag}] Closed via GTC, bal={nb:.2f}")
                    return True
            # Didn't fill — cancel and try FOK
            cancel_ord(client, oid, tag)
            time.sleep(1)

    # Method 2: FOK market sell (needs fill value >= $1)
    bal = get_token_balance(client, token_id)
    size = math.floor(bal * 100) / 100
    if size >= 0.01:
        resp = market_sell(client, token_id, size, tag)
        if resp and (resp.get("success") or resp.get("pending_settlement")):
            wait_for_settlement(client, token_id, timeout=15, tag=tag)
            return get_token_balance(client, token_id) < 0.5

    return get_token_balance(client, token_id) < 0.5
