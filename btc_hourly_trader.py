#!/usr/bin/env python3
"""
Crypto Candle Trader — All Crypto Limit Order Sniper

Combines user-provided BTC hourly data with Bonferroni survivors across
BTC/ETH/SOL/XRP/BNB. Places limit orders at best bid, follows book up
while edge remains >= 1.9 cents. Cancels unfilled orders 5 seconds
BEFORE candle starts.

12 signals:
  BTC  1H 13:00 UTC DOWN  53.8%  (user data)
  BTC  1H 17:00 UTC UP    56.3%  (user data + Bonferroni)
  BTC  1H 21:00 UTC UP    54.9%  (user data)
  BTC  1H 22:00 UTC UP    54.0%  (user data)
  BTC  1H 23:00 UTC DOWN  54.1%  (user data)
  BNB  1H 21:00 UTC UP    56.8%  (Bonferroni p=0.0002)
  BNB  1H 22:00 UTC UP    56.0%  (Bonferroni p=0.0013)
  XRP  1H 23:00 UTC DOWN  57.2%  (Bonferroni p=0.0001)
  ETH  1H 23:00 UTC DOWN  56.5%  (Bonferroni p=0.0005)
  SOL  1H 23:00 UTC DOWN  55.8%  (Bonferroni)
  SOL  4H 12-16 UTC DOWN  56.0%  (Bonferroni p=0.0013)
  XRP  4H 20-24 UTC DOWN  56.0%  (Bonferroni p=0.0013)

Usage:
  nohup python3 -u btc_hourly_trader.py > logs/candle_$(date -u +%Y%m%d_%H%M).log 2>&1 &
"""

import json
import math
import os
import signal
import threading
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# ─── Configuration ───────────────────────────────────────────────────────────

# 8 Bonferroni survivors
# (interval, start_hour_utc, asset_1h_slug, asset_4h_slug, side, edge)
# 1H slug:  {asset_1h}-up-or-down-{month}-{day}-{year}-{h12}{ampm}-et
# 4H slug:  {asset_4h}-updown-4h-{unix_ts_of_window_start}
EDGE_CANDLES = [
    # User-provided BTC hourly data
    ("1H", 13, "bitcoin",  "btc",  "DOWN", 0.538),  # BTC 1H 13:00 DOWN 53.8%
    ("1H", 17, "bitcoin",  "btc",  "UP",   0.563),  # BTC 1H 17:00 UP   56.3%
    ("1H", 21, "bitcoin",  "btc",  "UP",   0.549),  # BTC 1H 21:00 UP   54.9%
    ("1H", 22, "bitcoin",  "btc",  "UP",   0.540),  # BTC 1H 22:00 UP   54.0%
    ("1H", 23, "bitcoin",  "btc",  "DOWN", 0.541),  # BTC 1H 23:00 DOWN 54.1%
    # Bonferroni survivors (non-BTC)
    ("1H", 21, "bnb",      "bnb",  "UP",   0.568),  # BNB 1H 21:00 UP   56.8%
    ("1H", 22, "bnb",      "bnb",  "UP",   0.560),  # BNB 1H 22:00 UP   56.0%
    ("1H", 23, "xrp",      "xrp",  "DOWN", 0.572),  # XRP 1H 23:00 DOWN 57.2%
    ("1H", 23, "ethereum", "eth",  "DOWN", 0.565),  # ETH 1H 23:00 DOWN 56.5%
    ("1H", 23, "solana",   "sol",  "DOWN", 0.558),  # SOL 1H 23:00 DOWN 55.8%
    ("4H", 12, "solana",   "sol",  "DOWN", 0.560),  # SOL 4H 12-16 DOWN 56.0%
    ("4H", 20, "xrp",      "xrp",  "DOWN", 0.560),  # XRP 4H 20-24 DOWN 56.0%
]

ORDER_SIZE_SHARES = 5.0       # Minimal size — validating multi-crypto setup
POLL_INTERVAL_SEC = 5         # orderbook poll frequency
PRE_MARKET_MINUTES = 30       # start monitoring N min before candle
CANCEL_BEFORE_SEC = 5         # Cancel unfilled orders N sec BEFORE candle starts
MIN_EDGE_CENTS     = 1.9      # min (edge% - price%) in cents to place/keep order (user: "at least 2 points")
MIN_BALANCE_USDC   = 5.0      # Reserve capital for near-res — skip candle if balance below this
MAX_BATCH_COST     = 5.0      # Max USDC to deploy per batch (limits concurrent trades)

TRADE_LOG_FILE = "logs/candle_trades.jsonl"
GAMMA_HOST     = "https://gamma-api.polymarket.com"
ET_TZ          = ZoneInfo("America/New_York")

running = True
filled_candles: set[tuple] = set()   # (interval, candle_start_str, side)
failed_candles: set[tuple] = set()   # candles where market was not found


def _sighandler(sig, _frame):
    global running
    print(f"\n[CANDLE] Signal {sig}, shutting down...")
    running = False

signal.signal(signal.SIGINT,  _sighandler)
signal.signal(signal.SIGTERM, _sighandler)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def utc_now():
    return datetime.now(timezone.utc)


def log_trade(entry: dict):
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    tag   = entry.get("asset", "?")
    price = entry.get("fill_price") or entry.get("last_price") or "—"
    print(f"[TRADE-{tag}] {entry.get('candle_utc','')} {entry.get('interval','')} "
          f"{entry.get('side','')} → {entry.get('status','')} price={price}")


# ─── Market discovery ────────────────────────────────────────────────────────

def _slug_1h(asset_1h: str, candle_start_utc: datetime) -> str:
    """e.g. bitcoin-up-or-down-march-20-2026-1pm-et"""
    et   = candle_start_utc.astimezone(ET_TZ)
    mon  = et.strftime("%B").lower()
    h12  = et.hour % 12 or 12
    ampm = "am" if et.hour < 12 else "pm"
    return f"{asset_1h}-up-or-down-{mon}-{et.day}-{et.year}-{h12}{ampm}-et"


def _slug_4h(asset_4h: str, window_start_utc: datetime) -> str:
    """e.g. sol-updown-4h-1774008000  (timestamp = UTC start of 4H window)"""
    ts = int(window_start_utc.timestamp())
    return f"{asset_4h}-updown-4h-{ts}"


def find_market(interval: str, asset_1h: str, asset_4h: str,
                candle_start_utc: datetime) -> dict | None:
    slug = (_slug_1h(asset_1h, candle_start_utc) if interval == "1H"
            else _slug_4h(asset_4h, candle_start_utc))
    tag = asset_4h.upper()
    print(f"[{tag}] Looking up: {slug}")
    try:
        r = requests.get(f"{GAMMA_HOST}/events/slug/{slug}", timeout=15)
        if r.status_code != 200:
            print(f"[{tag}] HTTP {r.status_code} — market not found")
            return None
        event   = r.json()
        markets = event.get("markets", [])
        if not markets:
            return None

        m           = markets[0]
        tokens_raw  = m.get("clobTokenIds", "[]")
        tokens      = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
        outcomes_raw = m.get("outcomes", "[]")
        outcomes    = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

        if len(tokens) < 2:
            return None

        up_idx, down_idx = 0, 1
        for i, o in enumerate(outcomes):
            if o.lower() == "up":
                up_idx = i
            elif o.lower() == "down":
                down_idx = i

        return {
            "up_token":   tokens[up_idx],
            "down_token": tokens[down_idx],
            "question":   m.get("question", ""),
            "slug":       slug,
            "asset":      tag,
        }
    except Exception as e:
        print(f"[{tag}] Market lookup error: {e}")
        return None


# ─── Order helpers ────────────────────────────────────────────────────────────

def best_bid(client, token_id, tag="") -> float | None:
    try:
        book = orderbook_to_dict(client.get_order_book(token_id))
        bids = book.get("bids", [])
        if bids:
            return float(bids[0]["price"])
    except Exception as e:
        print(f"[{tag}] Orderbook error: {e}")
    return None


def place_buy(client, token_id, price: float, size: float, tag="") -> str | None:
    price = round(price, 2)
    size  = max(5.0, math.floor(size * 100) / 100.0)
    if not (0.01 <= price <= 0.99):
        return None
    try:
        args   = OrderArgs(token_id=token_id, price=price, size=size, side=BUY)
        signed = client.create_order(args)
        resp   = client.post_order(signed, orderType=OrderType.GTC)
        oid    = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        print(f"[{tag}] BUY {size:.0f}sh @ {price:.2f}  oid={oid}")
        return oid
    except Exception as e:
        print(f"[{tag}] Order error: {e}")
        return None


def cancel_order(client, order_id, tag="") -> bool:
    try:
        client.cancel(order_id)
        print(f"[{tag}] Cancelled {order_id}")
        return True
    except Exception as e:
        print(f"[{tag}] Cancel failed: {e}")
        return False


def is_filled(client, order_id) -> bool | None:
    """True=filled, False=open, None=unknown."""
    try:
        o  = client.get_order(order_id)
        st = (o.get("status") or "").upper() if isinstance(o, dict) else ""
        if st in ("FILLED", "MATCHED"):
            return True
        if st in ("LIVE", "OPEN", "ACTIVE"):
            return False
    except Exception:
        pass
    return None


# ─── Core trade loop (one thread per candle) ─────────────────────────────────

def trade_candle(interval: str, candle_start_utc: datetime,
                 asset_1h: str, asset_4h: str, side: str, edge: float):
    global running
    tag    = asset_4h.upper()
    client = get_client()   # per-thread client instance

    market = find_market(interval, asset_1h, asset_4h, candle_start_utc)
    if market is None:
        log_trade({"candle_utc": str(candle_start_utc), "interval": interval,
                   "asset": tag, "side": side, "status": "MARKET_NOT_FOUND"})
        failed_candles.add((interval, str(candle_start_utc), side, asset_4h))
        return

    token_id  = market["up_token"] if side == "UP" else market["down_token"]

    print(f"[{tag}] === {market['question']} ===")
    print(f"[{tag}] Side={side}  Edge={edge*100:.1f}%")

    cur_oid   = None
    cur_price = None
    filled_   = False
    order_moves = 0
    cancel_deadline = candle_start_utc - timedelta(seconds=CANCEL_BEFORE_SEC)

    while running:
        now_utc = utc_now()

        # ── Cancel window: 5 seconds BEFORE candle starts ──
        if now_utc >= cancel_deadline:
            if cur_oid:
                st = is_filled(client, cur_oid)
                if st is True:
                    filled_ = True
                    print(f"[{tag}] Filled at deadline! price={cur_price:.2f}")
                else:
                    cancel_order(client, cur_oid, tag)
                    print(f"[{tag}] Cancelled 5s before candle start")
            else:
                print(f"[{tag}] No order placed — edge never sufficient")
            break

        # ── Poll orderbook ──
        bb = best_bid(client, token_id, tag)
        if bb is None:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        edge_cents = edge * 100 - bb * 100

        if cur_oid is None:
            # ── No order yet: place if edge sufficient ──
            if edge_cents >= MIN_EDGE_CENTS:
                cur_oid   = place_buy(client, token_id, bb, ORDER_SIZE_SHARES, tag)
                cur_price = bb
                print(f"[{tag}] Placed at {bb:.2f}  edge={edge_cents:.1f}c")
            else:
                secs_left = (cancel_deadline - now_utc).total_seconds()
                if int(secs_left) % 60 < POLL_INTERVAL_SEC:
                    print(f"[{tag}] bid={bb:.2f} edge={edge_cents:.1f}c < {MIN_EDGE_CENTS:.1f}c — waiting ({secs_left:.0f}s)")
        else:
            # ── Have an order: check fill, follow book ──
            st = is_filled(client, cur_oid)
            if st is True:
                filled_ = True
                print(f"[{tag}] Filled at {cur_price:.2f}!")
                break

            if bb > cur_price:
                # Book moved up — should we follow?
                if edge_cents >= MIN_EDGE_CENTS:
                    if cancel_order(client, cur_oid, tag):
                        new_oid = place_buy(client, token_id, bb, ORDER_SIZE_SHARES, tag)
                        if new_oid:
                            cur_oid   = new_oid
                            cur_price = bb
                            order_moves += 1
                            print(f"[{tag}] Moved to {bb:.2f}  edge={edge_cents:.1f}c  (move #{order_moves})")
                        else:
                            cur_oid = None
                    else:
                        if is_filled(client, cur_oid) is True:
                            filled_ = True
                            print(f"[{tag}] Filled during move at {cur_price:.2f}!")
                            break
                else:
                    print(f"[{tag}] Book at {bb:.2f} but edge only {edge_cents:.1f}c — holding at {cur_price:.2f}")

        time.sleep(POLL_INTERVAL_SEC)

    cost = round(cur_price * ORDER_SIZE_SHARES, 4) if filled_ and cur_price else 0
    log_trade({
        "time":       str(utc_now()),
        "candle_utc": str(candle_start_utc),
        "interval":   interval,
        "asset":      tag,
        "market":     market["question"],
        "side":       side,
        "edge_pct":   round(edge * 100, 1),
        "status":     "FILLED" if filled_ else "NOT_FILLED",
        "fill_price": cur_price if filled_ else None,
        "last_price": cur_price,
        "shares":     ORDER_SIZE_SHARES if filled_ else 0,
        "cost_usdc":  cost,
        "order_moves": order_moves,
    })

    if filled_:
        filled_candles.add((interval, str(candle_start_utc), side, asset_4h))
        send(f"Candle FILLED: {tag} {interval} {side} @ {cur_price:.2f} ({market['question']})")


# ─── Scheduler ───────────────────────────────────────────────────────────────

def get_schedule():
    """
    Return sorted list of (candle_start_utc, [candle_entries])
    for all upcoming edge candles (today + tomorrow), grouped by start time.
    """
    now     = utc_now()
    grouped = {}
    for days in range(2):
        base = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        for entry in EDGE_CANDLES:
            interval, hour_utc, asset_1h, asset_4h, side, edge = entry
            candle = base.replace(hour=hour_utc)
            # Cancel is BEFORE start, so skip candles that already started
            if now < candle - timedelta(seconds=CANCEL_BEFORE_SEC):
                key = (interval, str(candle), side, asset_4h)
                if key not in filled_candles and key not in failed_candles:
                    grouped.setdefault(candle, []).append(entry)
    return sorted(grouped.items())


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global running

    print(f"[CANDLE] ═══ Crypto Candle Trader — All Crypto Limit Sniper ═══")
    print(f"[CANDLE] UTC now: {utc_now()}")
    print(f"[CANDLE] Signals: {len(EDGE_CANDLES)} across BTC/ETH/SOL/XRP/BNB (1H+4H)")
    print(f"[CANDLE] Order size: {ORDER_SIZE_SHARES} shares per trade")
    print(f"[CANDLE] Cancel: {CANCEL_BEFORE_SEC}s before candle start")
    print(f"[CANDLE] Min edge: {MIN_EDGE_CENTS:.1f} cents")

    client = get_client()
    print(f"[CANDLE] Balance: ${get_usdc_balance(client):.2f}")

    while running:
        schedule = get_schedule()
        if not schedule:
            print("[CANDLE] No candles ahead. Sleeping 1h...")
            for _ in range(360):
                if not running:
                    break
                time.sleep(10)
            continue

        next_start, next_candles = schedule[0]
        monitor_start = next_start - timedelta(minutes=PRE_MARKET_MINUTES)
        wait = (monitor_start - utc_now()).total_seconds()

        if wait > 0:
            labels = [f"{c[3].upper()} {c[0]} {c[4]}" for c in next_candles]
            print(f"[CANDLE] Next: {next_start.strftime('%H:%M')} UTC — "
                  f"{', '.join(labels)}.  Monitor in {wait/60:.0f} min.")
            while wait > 0 and running:
                time.sleep(min(wait, 30))
                wait -= 30

        if not running:
            break

        # Launch candles — but check balance first and limit batch spend
        bal = get_usdc_balance(client)
        print(f"\n[CANDLE] ── {next_start.strftime('%Y-%m-%d %H:%M')} UTC batch "
              f"({len(next_candles)} signals) ── Balance: ${bal:.2f}")
        if bal < MIN_BALANCE_USDC:
            print(f"[CANDLE] Balance ${bal:.2f} < ${MIN_BALANCE_USDC:.2f} minimum — SKIPPING batch")
            time.sleep(10)
            continue

        # Limit batch to MAX_BATCH_COST worth of trades
        max_trades = max(1, int(MAX_BATCH_COST / (ORDER_SIZE_SHARES * 0.55)))
        to_launch = next_candles[:max_trades]
        if len(to_launch) < len(next_candles):
            print(f"[CANDLE] Capped to {max_trades} trades (${MAX_BATCH_COST:.0f} budget)")

        threads = []
        for entry in to_launch:
            interval, hour_utc, asset_1h, asset_4h, side, edge = entry
            t = threading.Thread(
                target=trade_candle,
                args=(interval, next_start, asset_1h, asset_4h, side, edge),
                daemon=True,
                name=f"{asset_4h.upper()}-{interval}",
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        time.sleep(10)

    print("[CANDLE] Shutdown complete.")


if __name__ == "__main__":
    main()
