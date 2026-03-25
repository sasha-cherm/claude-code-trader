#!/usr/bin/env python3
"""
BTC Hourly Candle — Limit Order Sniper

Statistically proven BTC hourly candle signals (user-provided data):
  17:00 UTC  56.3% UP
  21:00 UTC  54.9% UP
  22:00 UTC  54.0% UP
  23:00 UTC  54.1% DOWN
  13:00 UTC  53.8% DOWN

Strategy:
  - 30 min before each candle, look up the market on Gamma API
  - Poll orderbook and place a limit BUY at the best bid price
  - Follow the book up: if best bid rises and edge still >= MIN_EDGE, cancel+repost
  - If book moves so high that edge < MIN_EDGE, keep existing order at lower price
  - Cancel unfilled orders 5 seconds BEFORE the candle starts
  - Log all fills and non-fills to logs/btc_hourly_limit.jsonl

Usage:
  nohup python3 -u btc_hourly_limit.py > logs/btc_limit_$(date -u +%Y%m%d_%H%M).log 2>&1 &
"""

import json
import math
import os
import signal
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# ─── Configuration ───────────────────────────────────────────────────────────

# BTC hourly candle signals: (hour_utc, side, edge_probability)
BTC_SIGNALS = [
    (13, "DOWN", 0.538),  # 13:00 UTC  53.8% DOWN
    (17, "UP",   0.563),  # 17:00 UTC  56.3% UP
    (21, "UP",   0.549),  # 21:00 UTC  54.9% UP
    (22, "UP",   0.540),  # 22:00 UTC  54.0% UP
    (23, "DOWN", 0.541),  # 23:00 UTC  54.1% DOWN
]

ORDER_SIZE_SHARES = 5.0      # Minimal size to validate script works
POLL_INTERVAL_SEC = 5        # Orderbook poll frequency
PRE_MARKET_MINUTES = 30      # Start monitoring N min before candle
CANCEL_BEFORE_SEC = 5        # Cancel unfilled orders N sec before candle starts
MIN_EDGE = 0.019             # Min edge to place/move order (1.9 cents — user example)

TRADE_LOG_FILE = "logs/btc_hourly_limit.jsonl"
GAMMA_HOST = "https://gamma-api.polymarket.com"
ET_TZ = ZoneInfo("America/New_York")

running = True
filled_candles: set[str] = set()


def _sighandler(sig, _frame):
    global running
    print(f"\n[BTC-H] Signal {sig}, shutting down gracefully...")
    running = False

signal.signal(signal.SIGINT, _sighandler)
signal.signal(signal.SIGTERM, _sighandler)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def utc_now():
    return datetime.now(timezone.utc)


def log_trade(entry: dict):
    """Append one JSON line per trade attempt to the log file."""
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    status = entry.get("status", "?")
    price = entry.get("fill_price") or entry.get("last_order_price") or "—"
    side = entry.get("side", "?")
    hour = entry.get("hour_utc", "?")
    print(f"[TRADE] {entry.get('candle_utc','')} BTC 1H {side} @ {hour}:00 UTC "
          f"→ {status} price={price}")


# ─── Market discovery ────────────────────────────────────────────────────────

def slug_1h(candle_start_utc: datetime) -> str:
    """Build Polymarket slug. e.g. bitcoin-up-or-down-march-25-2026-5pm-et"""
    et = candle_start_utc.astimezone(ET_TZ)
    mon = et.strftime("%B").lower()
    h12 = et.hour % 12 or 12
    ampm = "am" if et.hour < 12 else "pm"
    return f"bitcoin-up-or-down-{mon}-{et.day}-{et.year}-{h12}{ampm}-et"


def find_market(candle_start_utc: datetime) -> dict | None:
    """Look up BTC hourly UP/DOWN market via Gamma API."""
    slug = slug_1h(candle_start_utc)
    print(f"[BTC-H] Looking up: {slug}")
    try:
        r = requests.get(f"{GAMMA_HOST}/events/slug/{slug}", timeout=15)
        if r.status_code != 200:
            print(f"[BTC-H] HTTP {r.status_code} — market not found for {slug}")
            return None
        event = r.json()
        markets = event.get("markets", [])
        if not markets:
            print(f"[BTC-H] No markets in event for {slug}")
            return None

        m = markets[0]
        tokens_raw = m.get("clobTokenIds", "[]")
        tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
        outcomes_raw = m.get("outcomes", "[]")
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

        if len(tokens) < 2:
            print(f"[BTC-H] <2 tokens for {slug}")
            return None

        up_idx, down_idx = 0, 1
        for i, o in enumerate(outcomes):
            if o.lower() == "up":
                up_idx = i
            elif o.lower() == "down":
                down_idx = i

        return {
            "up_token": tokens[up_idx],
            "down_token": tokens[down_idx],
            "question": m.get("question", ""),
            "slug": slug,
        }
    except Exception as e:
        print(f"[BTC-H] Market lookup error: {e}")
        return None


# ─── Order helpers ───────────────────────────────────────────────────────────

def get_best_bid(client, token_id) -> float | None:
    """Return highest resting bid price, or None."""
    try:
        book = orderbook_to_dict(client.get_order_book(token_id))
        bids = book.get("bids", [])
        if bids:
            return float(bids[0]["price"])
    except Exception as e:
        print(f"[BTC-H] Orderbook error: {e}")
    return None


def place_buy(client, token_id, price: float, size: float) -> str | None:
    """Place a GTC limit buy order. Returns order ID or None."""
    price = round(price, 2)
    size = max(5.0, math.floor(size * 100) / 100.0)
    if not (0.01 <= price <= 0.99):
        print(f"[BTC-H] Price {price} out of range, skipping")
        return None
    try:
        args = OrderArgs(token_id=token_id, price=price, size=size, side=BUY)
        signed = client.create_order(args)
        resp = client.post_order(signed, orderType=OrderType.GTC)
        oid = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        print(f"[BTC-H] BUY {size:.0f}sh @ {price:.2f}  oid={oid}")
        return oid
    except Exception as e:
        print(f"[BTC-H] Order error: {e}")
        return None


def cancel_order(client, order_id) -> bool:
    """Cancel an order. Returns True if cancel succeeded."""
    try:
        client.cancel(order_id)
        print(f"[BTC-H] Cancelled {order_id}")
        return True
    except Exception as e:
        print(f"[BTC-H] Cancel failed: {e}")
        return False


def check_order_status(client, order_id) -> str:
    """Return 'FILLED', 'OPEN', or 'UNKNOWN'."""
    try:
        o = client.get_order(order_id)
        st = (o.get("status") or "").upper() if isinstance(o, dict) else ""
        if st in ("FILLED", "MATCHED"):
            return "FILLED"
        if st in ("LIVE", "OPEN", "ACTIVE"):
            return "OPEN"
    except Exception:
        pass
    return "UNKNOWN"


# ─── Core trade loop ────────────────────────────────────────────────────────

def trade_candle(candle_start_utc: datetime, side: str, edge: float):
    """
    Monitor orderbook and manage limit order for one BTC hourly candle.
    Cancel 5 seconds before candle starts if not filled.
    """
    global running
    client = get_client()
    hour_utc = candle_start_utc.hour

    market = find_market(candle_start_utc)
    if market is None:
        log_trade({
            "time": str(utc_now()),
            "candle_utc": str(candle_start_utc),
            "hour_utc": hour_utc,
            "side": side,
            "edge_pct": round(edge * 100, 1),
            "status": "MARKET_NOT_FOUND",
        })
        return

    token_id = market["up_token"] if side == "UP" else market["down_token"]
    print(f"[BTC-H] === {market['question']} ===")
    print(f"[BTC-H] Side={side}  Edge={edge*100:.1f}%")

    cur_oid = None       # current order ID
    cur_price = None     # current order price
    filled_ = False
    cancel_deadline = candle_start_utc - timedelta(seconds=CANCEL_BEFORE_SEC)
    order_moves = 0      # track how many times we moved the order

    while running:
        now_utc = utc_now()

        # ── Cancel window: 5 seconds before candle starts ──
        if now_utc >= cancel_deadline:
            if cur_oid:
                st = check_order_status(client, cur_oid)
                if st == "FILLED":
                    filled_ = True
                    print(f"[BTC-H] Filled at deadline! price={cur_price:.2f}")
                else:
                    cancel_order(client, cur_oid)
                    print(f"[BTC-H] Cancelled 5s before candle start")
            else:
                print(f"[BTC-H] No order placed — edge never sufficient")
            break

        # ── Poll orderbook ──
        bb = get_best_bid(client, token_id)
        if bb is None:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        edge_gap = edge - bb  # how much edge we have at current best bid

        if cur_oid is None:
            # ── No order yet: place if edge is sufficient ──
            if edge_gap >= MIN_EDGE:
                cur_oid = place_buy(client, token_id, bb, ORDER_SIZE_SHARES)
                cur_price = bb
                print(f"[BTC-H] Placed at {bb:.2f}  edge_gap={edge_gap*100:.1f}c")
            else:
                secs_left = (cancel_deadline - now_utc).total_seconds()
                if int(secs_left) % 60 < POLL_INTERVAL_SEC:
                    print(f"[BTC-H] Best bid={bb:.2f}  edge_gap={edge_gap*100:.1f}c "
                          f"< {MIN_EDGE*100:.1f}c — waiting ({secs_left:.0f}s left)")
        else:
            # ── Have an order: check fill, follow book ──
            st = check_order_status(client, cur_oid)
            if st == "FILLED":
                filled_ = True
                print(f"[BTC-H] Filled at {cur_price:.2f}!")
                break

            if bb > cur_price:
                # Book moved up — should we follow?
                if edge_gap >= MIN_EDGE:
                    # Still enough edge at new top — move order up
                    if cancel_order(client, cur_oid):
                        new_oid = place_buy(client, token_id, bb, ORDER_SIZE_SHARES)
                        if new_oid:
                            cur_oid = new_oid
                            cur_price = bb
                            order_moves += 1
                            print(f"[BTC-H] Moved to {bb:.2f}  edge_gap={edge_gap*100:.1f}c  "
                                  f"(move #{order_moves})")
                        else:
                            # Place failed — lost our order
                            cur_oid = None
                            print(f"[BTC-H] Failed to repost after cancel!")
                    else:
                        # Cancel failed — check if it filled during cancel attempt
                        st2 = check_order_status(client, cur_oid)
                        if st2 == "FILLED":
                            filled_ = True
                            print(f"[BTC-H] Filled during move attempt at {cur_price:.2f}!")
                            break
                else:
                    # Edge too thin at new best bid — keep order at lower price
                    print(f"[BTC-H] Book at {bb:.2f} but edge only {edge_gap*100:.1f}c "
                          f"— holding at {cur_price:.2f}")
            # else: book same or lower — just wait

        time.sleep(POLL_INTERVAL_SEC)

    # ── Log result ──
    cost = round(cur_price * ORDER_SIZE_SHARES, 4) if filled_ and cur_price else 0
    log_trade({
        "time": str(utc_now()),
        "candle_utc": str(candle_start_utc),
        "hour_utc": hour_utc,
        "side": side,
        "edge_pct": round(edge * 100, 1),
        "market": market["question"],
        "slug": market["slug"],
        "status": "FILLED" if filled_ else "NOT_FILLED",
        "fill_price": cur_price if filled_ else None,
        "last_order_price": cur_price,
        "shares": ORDER_SIZE_SHARES if filled_ else 0,
        "cost_usdc": cost,
        "order_moves": order_moves,
    })

    if filled_:
        key = f"{candle_start_utc.isoformat()}_{side}"
        filled_candles.add(key)
        send(f"BTC-H FILLED: {side} @ {cur_price:.2f} ({market['question']})")


# ─── Scheduler ───────────────────────────────────────────────────────────────

def get_next_signal():
    """Return next upcoming (candle_start_utc, side, edge) or None."""
    now = utc_now()
    for days in range(2):
        base = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        for hour_utc, side, edge in sorted(BTC_SIGNALS, key=lambda x: x[0]):
            candle = base.replace(hour=hour_utc)
            key = f"{candle.isoformat()}_{side}"
            if key in filled_candles:
                continue
            if now >= candle:  # candle already started
                continue
            return candle, side, edge
    return None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global running

    print(f"[BTC-H] ═══ BTC Hourly Limit Order Sniper ═══")
    print(f"[BTC-H] UTC now:  {utc_now()}")
    print(f"[BTC-H] Signals:  {len(BTC_SIGNALS)} hours "
          f"({', '.join(f'{h}:00 {s} {e*100:.1f}%' for h, s, e in BTC_SIGNALS)})")
    print(f"[BTC-H] Order size: {ORDER_SIZE_SHARES} shares")
    print(f"[BTC-H] Min edge:   {MIN_EDGE*100:.1f} cents")
    print(f"[BTC-H] Cancel:     {CANCEL_BEFORE_SEC}s before candle start")

    client = get_client()
    print(f"[BTC-H] Balance: ${get_usdc_balance(client):.2f}")

    while running:
        nxt = get_next_signal()
        if nxt is None:
            print("[BTC-H] No upcoming signals. Sleeping 1h...")
            for _ in range(360):
                if not running:
                    break
                time.sleep(10)
            continue

        candle_start, side, edge = nxt
        monitor_start = candle_start - timedelta(minutes=PRE_MARKET_MINUTES)
        wait = (monitor_start - utc_now()).total_seconds()

        if wait > 0:
            print(f"[BTC-H] Next: {candle_start.strftime('%H:%M')} UTC — "
                  f"BTC {side} ({edge*100:.1f}%).  Monitor in {wait/60:.0f} min.")
            while wait > 0 and running:
                time.sleep(min(wait, 30))
                wait -= 30

        if not running:
            break

        print(f"\n[BTC-H] ── Monitoring {candle_start.strftime('%Y-%m-%d %H:%M')} UTC "
              f"— BTC {side} ({edge*100:.1f}%) ──")
        trade_candle(candle_start, side, edge)
        time.sleep(5)

    print("[BTC-H] Shutdown complete.")


if __name__ == "__main__":
    main()
