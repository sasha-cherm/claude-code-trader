#!/usr/bin/env python3
"""
BTC Hourly Candle Trader.

Places limit orders on Polymarket BTC Up/Down hourly markets based on
statistically proven edge data for specific UTC hours.

Edge data (UTC candle start hours):
  17:00  56.3% UP
  21:00  54.9% UP
  22:00  54.0% UP
  23:00  54.1% DOWN
  13:00  53.8% DOWN

Strategy:
  - 30 min before candle: start monitoring orderbook
  - Place limit BUY at top-of-book (best bid) for the edge side (UP or DOWN token)
  - Follow best bid upward as long as (edge - price) >= MIN_EDGE_CENTS
  - Cancel 5 seconds before candle starts if not filled
  - Log all trades and non-fills

Usage:
  nohup python3 -u btc_hourly_trader.py > logs/btc_hourly_$(date -u +%Y%m%d_%H%M).log 2>&1 &
"""

import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# ─── Configuration ───────────────────────────────────────────────────────────

# Statistical edge by UTC hour: (side_to_buy, true_probability)
EDGE_HOURS_UTC = {
    17: ("UP",   0.563),   # 56.3% UP
    21: ("UP",   0.549),   # 54.9% UP
    22: ("UP",   0.540),   # 54.0% UP
    23: ("DOWN", 0.541),   # 54.1% DOWN
    13: ("DOWN", 0.538),   # 53.8% DOWN
}

ORDER_SIZE_SHARES = 5.0       # CLOB minimum; start small to verify
POLL_INTERVAL_SEC = 5         # seconds between orderbook polls
PRE_MARKET_MINUTES = 30       # start monitoring N min before candle
CANCEL_BEFORE_SEC = 5         # cancel unfilled order N sec before candle
MIN_EDGE_CENTS = 1.0          # minimum (edge_cents - price_cents) to keep order
TICK = 0.01                   # price tick size

TRADE_LOG_FILE = "logs/btc_hourly_trades.jsonl"
GAMMA_HOST = "https://gamma-api.polymarket.com"
ET_TZ = ZoneInfo("America/New_York")

running = True


def _sighandler(sig, _frame):
    global running
    print(f"\n[BTC-H] Signal {sig}, shutting down gracefully...")
    running = False

signal.signal(signal.SIGINT,  _sighandler)
signal.signal(signal.SIGTERM, _sighandler)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def utc_now():
    return datetime.now(timezone.utc)


def log_trade(entry: dict):
    """Append one JSON line to the trade log file."""
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    status = entry.get("status", "")
    price  = entry.get("fill_price") or entry.get("last_price") or "—"
    print(f"[TRADE] {entry.get('candle_utc','')} {entry.get('side','')} "
          f"status={status} price={price}")


# ─── Market discovery ────────────────────────────────────────────────────────

def _build_slug(candle_start_utc: datetime) -> str:
    """
    Derive the Gamma-API event slug for a BTC hourly candle.

    Slug format: bitcoin-up-or-down-{month}-{day}-{year}-{hour}{am/pm}-et
    The "hour" in the slug is the ET hour when the candle STARTS.
    """
    et = candle_start_utc.astimezone(ET_TZ)
    month = et.strftime("%B").lower()          # "march"
    day   = et.day                              # no zero-pad
    year  = et.year
    h12   = et.hour % 12 or 12
    ampm  = "am" if et.hour < 12 else "pm"
    return f"bitcoin-up-or-down-{month}-{day}-{year}-{h12}{ampm}-et"


def find_market(candle_start_utc: datetime) -> dict | None:
    """
    Look up the Polymarket event for a given BTC hourly candle.
    Returns dict with up_token, down_token, end_date, question  — or None.
    """
    slug = _build_slug(candle_start_utc)
    print(f"[BTC-H] Fetching market slug: {slug}")
    try:
        r = requests.get(f"{GAMMA_HOST}/events/slug/{slug}", timeout=15)
        if r.status_code != 200:
            print(f"[BTC-H] Slug {slug}: HTTP {r.status_code}")
            return None
        event = r.json()
        markets = event.get("markets", [])
        if not markets:
            return None

        m = markets[0]
        tokens_raw = m.get("clobTokenIds", "[]")
        tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
        outcomes_raw = m.get("outcomes", "[]")
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

        if len(tokens) < 2 or len(outcomes) < 2:
            return None

        # Map "Up"→index, "Down"→index
        up_idx, down_idx = 0, 1
        for i, o in enumerate(outcomes):
            if o.lower() == "up":
                up_idx = i
            elif o.lower() == "down":
                down_idx = i

        return {
            "up_token":   tokens[up_idx],
            "down_token":  tokens[down_idx],
            "end_date":    m.get("endDate", ""),
            "question":    m.get("question", ""),
            "slug":        slug,
        }
    except Exception as e:
        print(f"[BTC-H] Market lookup error: {e}")
        return None


# ─── Orderbook helpers ───────────────────────────────────────────────────────

def best_bid_price(client, token_id) -> float | None:
    """Return best (highest) bid price, or None if empty."""
    try:
        book = orderbook_to_dict(client.get_order_book(token_id))
        bids = book.get("bids", [])
        if bids:
            return float(bids[0]["price"])
    except Exception as e:
        print(f"[BTC-H] Orderbook error: {e}")
    return None


# ─── Order management ────────────────────────────────────────────────────────

def place_buy(client, token_id, price: float, size: float) -> str | None:
    """Place a GTC limit BUY.  Returns order_id or None."""
    price = round(price, 2)
    size  = math.floor(size * 100) / 100.0
    if size < 5.0:
        size = 5.0
    if price < 0.01 or price > 0.99:
        print(f"[BTC-H] Price {price} out of range")
        return None
    try:
        args = OrderArgs(token_id=token_id, price=price, size=size, side=BUY)
        signed = client.create_order(args)
        resp = client.post_order(signed, orderType=OrderType.GTC)
        oid = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        print(f"[BTC-H] BUY {size:.0f}sh @ {price:.2f}  order_id={oid}")
        return oid
    except Exception as e:
        print(f"[BTC-H] Order error: {e}")
        return None


def cancel(client, order_id) -> bool:
    try:
        client.cancel(order_id)
        print(f"[BTC-H] Cancelled {order_id}")
        return True
    except Exception as e:
        print(f"[BTC-H] Cancel failed {order_id}: {e}")
        return False


def is_order_filled(client, order_id) -> bool | None:
    """True = filled, False = still open, None = unknown."""
    try:
        o = client.get_order(order_id)
        if isinstance(o, dict):
            st = (o.get("status") or "").upper()
            if st in ("FILLED", "MATCHED"):
                return True
            if st in ("LIVE", "OPEN", "ACTIVE"):
                return False
        return None
    except Exception:
        return None


# ─── Core trading loop for one candle ────────────────────────────────────────

def trade_candle(client, candle_start_utc: datetime, side: str, edge: float):
    """Monitor orderbook and manage a single limit order for one hourly candle."""
    global running

    market = find_market(candle_start_utc)
    if market is None:
        log_trade({"candle_utc": str(candle_start_utc), "side": side,
                    "edge": edge, "status": "MARKET_NOT_FOUND"})
        return

    token_id = market["up_token"] if side == "UP" else market["down_token"]
    # Max price we're willing to pay (edge minus ~1 tick guarantees positive EV)
    max_price = math.floor((edge - 0.01) * 100) / 100.0

    print(f"[BTC-H] === {market['question']} ===")
    print(f"[BTC-H] Side={side}  Edge={edge*100:.1f}%  MaxPrice={max_price:.2f}")
    print(f"[BTC-H] Token={token_id[:30]}...")

    cur_oid   = None   # current resting order id
    cur_price = None   # current order price
    filled    = False

    while running:
        now = utc_now()
        secs_to_candle = (candle_start_utc - now).total_seconds()

        # ── Cancel window: 5 sec before candle start ──
        if secs_to_candle <= CANCEL_BEFORE_SEC:
            if cur_oid:
                chk = is_order_filled(client, cur_oid)
                if chk is True:
                    filled = True
                    print(f"[BTC-H] Filled just before candle!")
                else:
                    cancel(client, cur_oid)
            break

        # ── Poll orderbook ──
        bb = best_bid_price(client, token_id)
        if bb is None:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # Target price: join the best bid, but cap at max_price
        target = min(bb, max_price)

        # Check edge is sufficient
        edge_cents = edge * 100 - target * 100
        if edge_cents < MIN_EDGE_CENTS:
            # Not enough edge at this price; keep existing order if any
            if cur_oid is None:
                print(f"[BTC-H] Best bid {bb:.2f} too high (edge {edge_cents:.1f}¢). Waiting...")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # ── Place or adjust order ──
        if cur_oid is None:
            # First placement
            cur_oid = place_buy(client, token_id, target, ORDER_SIZE_SHARES)
            cur_price = target

        elif target > cur_price:
            # Book moved up — follow it (cancel + re-place)
            chk = is_order_filled(client, cur_oid)
            if chk is True:
                filled = True
                print(f"[BTC-H] Filled at {cur_price:.2f}!")
                break

            if cancel(client, cur_oid):
                cur_oid = place_buy(client, token_id, target, ORDER_SIZE_SHARES)
                cur_price = target if cur_oid else cur_price
            else:
                # Cancel failed — maybe filled
                chk2 = is_order_filled(client, cur_oid)
                if chk2 is True:
                    filled = True
                    break
        else:
            # Price same or lower — check if filled
            chk = is_order_filled(client, cur_oid)
            if chk is True:
                filled = True
                print(f"[BTC-H] Filled at {cur_price:.2f}!")
                break

        time.sleep(POLL_INTERVAL_SEC)

    # ── Log result ──
    cost = round(cur_price * ORDER_SIZE_SHARES, 4) if filled and cur_price else 0
    log_trade({
        "time":         str(utc_now()),
        "candle_utc":   str(candle_start_utc),
        "market":       market["question"],
        "side":         side,
        "edge_pct":     round(edge * 100, 1),
        "status":       "FILLED" if filled else "NOT_FILLED",
        "fill_price":   cur_price if filled else None,
        "last_price":   cur_price,
        "shares":       ORDER_SIZE_SHARES if filled else 0,
        "cost_usdc":    cost,
        "max_price":    max_price,
        "token":        token_id[:40],
    })

    label = f"{'FILLED' if filled else 'NOT_FILLED'} {side} @ {cur_price}"
    send(f"BTC Hourly: {label} for {market['question']}")


# ─── Scheduling ──────────────────────────────────────────────────────────────

def next_edge_candle():
    """
    Return (candle_start_utc, side, edge) for the next tradeable candle,
    or None if nothing left today/tomorrow.
    """
    now = utc_now()
    for days in range(2):
        base = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        for h in sorted(EDGE_HOURS_UTC):
            side, edge = EDGE_HOURS_UTC[h]
            candle = base.replace(hour=h)
            # Must be before the cancel deadline
            if now < candle - timedelta(seconds=CANCEL_BEFORE_SEC):
                return candle, side, edge
    return None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global running

    print(f"[BTC-H] ═══ BTC Hourly Candle Trader started ═══")
    print(f"[BTC-H] UTC now:  {utc_now()}")
    print(f"[BTC-H] Edge hours (UTC): {sorted(EDGE_HOURS_UTC.keys())}")
    print(f"[BTC-H] Order size: {ORDER_SIZE_SHARES} shares")

    client = get_client()
    bal = get_usdc_balance(client)
    print(f"[BTC-H] Balance: ${bal:.2f}")

    while running:
        nxt = next_edge_candle()
        if nxt is None:
            print("[BTC-H] No edge candles ahead. Sleeping 1h...")
            for _ in range(360):      # 360 × 10s = 1h
                if not running:
                    break
                time.sleep(10)
            continue

        candle_start, side, edge = nxt
        monitor_start = candle_start - timedelta(minutes=PRE_MARKET_MINUTES)
        wait = (monitor_start - utc_now()).total_seconds()

        if wait > 0:
            et_str = candle_start.astimezone(ET_TZ).strftime("%-I%p ET")
            print(f"[BTC-H] Next candle: {candle_start.strftime('%H:%M')} UTC "
                  f"({et_str}) — {side} {edge*100:.1f}%.  "
                  f"Monitor in {wait/60:.0f} min.")
            while wait > 0 and running:
                s = min(wait, 30)
                time.sleep(s)
                wait -= s
            if not running:
                break

        print(f"\n[BTC-H] ── Trading candle {candle_start.strftime('%Y-%m-%d %H:%M')} UTC "
              f"({side} {edge*100:.1f}%) ──")
        trade_candle(client, candle_start, side, edge)

        # Brief pause before looking for next candle
        time.sleep(10)

    print("[BTC-H] Shutdown complete.")


if __name__ == "__main__":
    main()
