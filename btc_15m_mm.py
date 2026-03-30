#!/usr/bin/env python3
"""
BTC 15-min Candle Spread Scalper

Strategy:
  1. Pre-candle: Place BUY limit in spread on Up token (never cross ask)
  2. When BUY fills: Place SELL limit in spread (or at buy price if book moved against)
  3. 3 seconds after candle starts: if SELL not filled, cancel + market sell to close

Usage:
  nohup python3 -u btc_15m_mm.py > logs/btc_15m_mm_$(date -u +%Y%m%d_%H%M).log 2>&1 &
"""

import json
import os
import signal
import subprocess
import math
import time
from datetime import datetime, timezone, timedelta

import requests


def kill_other_instances():
    """Kill any other btc_15m_mm.py processes before starting."""
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "btc_15m_mm.py"], text=True
        ).strip()
        for line in out.splitlines():
            pid = int(line)
            if pid != my_pid:
                print(f"[MM] Killing old instance PID {pid}")
                os.kill(pid, signal.SIGKILL)
    except subprocess.CalledProcessError:
        pass  # no other instances

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL

# ─── Config ──────────────────────────────────────────────────────────────────
ORDER_SIZE = 6.0
POLL_SEC = 1.0
GAMMA = "https://gamma-api.polymarket.com"
TRADE_LOG = "logs/btc_15m_mm_trades.jsonl"
MIN_SIZE = 5.0
TICK = 0.01
MIN_BALANCE = 3.0         # only need one leg
SELL_DEADLINE = 15         # seconds after candle starts — more time for limit sell to fill

running = True
traded_candles: set[int] = set()


def _sig(s, _):
    global running
    print(f"\n[MM] Signal {s}, stopping...")
    running = False

signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


def utcnow():
    return datetime.now(timezone.utc)


def log_trade(entry):
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ─── Market discovery ────────────────────────────────────────────────────────

def find_next_candle():
    """Return info dict for the next unstarted 15-min BTC candle, or None."""
    now_ts = int(utcnow().timestamp())
    base = ((now_ts // 900) + 1) * 900

    for i in range(6):
        ts = base + i * 900
        if ts in traded_candles:
            continue
        slug = f"btc-updown-15m-{ts}"
        try:
            r = requests.get(f"{GAMMA}/events/slug/{slug}", timeout=10)
            if r.status_code != 200:
                continue
            mkt = r.json().get("markets", [None])[0]
            if not mkt:
                continue
            tokens = json.loads(mkt.get("clobTokenIds", "[]"))
            outcomes = json.loads(mkt.get("outcomes", "[]"))
            if len(tokens) < 2:
                continue
            up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)
            dn_idx = 1 - up_idx
            return {
                "up_token": tokens[up_idx],
                "dn_token": tokens[dn_idx],
                "candle_start": datetime.fromtimestamp(ts, tz=timezone.utc),
                "question": mkt.get("question", slug),
                "slug": slug,
            }
        except Exception as e:
            print(f"[MM] discovery {slug}: {e}")
    return None


# ─── CLOB helpers ─────────────────────────────────────────────────────────────

def get_book(client, token_id):
    try:
        return orderbook_to_dict(client.get_order_book(token_id))
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


def pick_side(client, up_token, dn_token):
    """Pick the token with stronger bid support (less likely to drop)."""
    up_book = get_book(client, up_token)
    dn_book = get_book(client, dn_token)
    up_depth = bid_depth(up_book)
    dn_depth = bid_depth(dn_book)
    if up_depth >= dn_depth:
        print(f"[MM] Side: UP (bid depth UP={up_depth:.0f} vs DN={dn_depth:.0f})")
        return up_token, "UP"
    else:
        print(f"[MM] Side: DN (bid depth DN={dn_depth:.0f} vs UP={up_depth:.0f})")
        return dn_token, "DN"


def get_token_balance(client, token_id):
    """Get how many shares of a conditional token we hold."""
    try:
        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id,
        )
        resp = client.get_balance_allowance(params)
        raw = float(resp.get("balance", 0))
        return raw / 1e6
    except Exception as e:
        print(f"[MM] token balance error: {e}")
        return 0.0


def place_order(client, token_id, price, size, side, tag=""):
    price = round(price, 2)
    size = round(max(MIN_SIZE, size), 2)
    if not (0.01 <= price <= 0.99):
        return None
    try:
        args = OrderArgs(token_id=token_id, price=price, size=size, side=side)
        signed = client.create_order(args)
        resp = client.post_order(signed, orderType=OrderType.GTC)
        oid = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        side_str = "BUY" if side == BUY else "SELL"
        print(f"[{tag}] {side_str} {size:.0f}sh @ {price:.2f}  oid={oid}")
        return oid
    except Exception as e:
        print(f"[{tag}] place error: {e}")
        return None


def cancel_ord(client, oid, tag=""):
    try:
        client.cancel(oid)
        print(f"[{tag}] cancelled {oid[:16]}...")
        return True
    except Exception as e:
        print(f"[{tag}] cancel fail: {e}")
        return False


def order_filled(client, oid):
    """Return (is_fully_filled, filled_size)."""
    try:
        o = client.get_order(oid)
        if not isinstance(o, dict):
            return False, 0
        st = (o.get("status") or "").upper()
        filled = float(o.get("size_matched") or o.get("sizeMatched") or 0)
        return st in ("FILLED", "MATCHED"), filled
    except:
        return False, 0


def market_sell(client, token_id, size, tag=""):
    """FOK SELL at 0.01 to dump position immediately."""
    try:
        args = OrderArgs(token_id=token_id, price=0.01, size=round(size, 2), side=SELL)
        signed = client.create_order(args)
        resp = client.post_order(signed, orderType=OrderType.FOK)
        print(f"[{tag}] MARKET SELL {size:.0f}sh => {resp}")
        return resp
    except Exception as e:
        print(f"[{tag}] market sell fail: {e}")
        return None


# ─── Main loop for one candle ────────────────────────────────────────────────

def run_candle(candle):
    global running

    client = get_client()
    up_token = candle["up_token"]
    dn_token = candle["dn_token"]
    start = candle["candle_start"]
    sell_deadline = start + timedelta(seconds=SELL_DEADLINE)

    print(f"\n[MM] {'='*50}")
    print(f"[MM] {candle['question']}")
    print(f"[MM] start={start.isoformat()}  sell_deadline=+{SELL_DEADLINE}s")

    token, side = pick_side(client, up_token, dn_token)
    print(f"[MM] Trading {side} token={token[:20]}...")

    candle_ts = int(start.timestamp())
    traded_candles.add(candle_ts)

    bal = get_usdc_balance(client)
    print(f"[MM] Balance: ${bal:.2f}")
    if bal < MIN_BALANCE:
        print(f"[MM] Balance too low, skipping.")
        log_trade({"candle": candle["question"], "start": str(start),
                    "events": [{"a": "SKIP_LOW_BAL", "bal": bal}]})
        return

    result = {"candle": candle["question"], "start": str(start), "events": []}
    rounds = 0

    while running:
        # ── Reset state for new BUY→SELL round ──
        buy_oid = None
        buy_px = None
        buy_fill_px = None
        sell_oid = None
        sell_px = None
        rounds += 1
        # Re-pick side each round (depth changes)
        if rounds > 1:
            token, side = pick_side(client, up_token, dn_token)
        print(f"[MM] --- Round {rounds} ({side}) ---")

        # ────────────────────────────────────────────────────────────────
        # PHASE 1: BUY — place limit in spread, cancel at candle start
        # ────────────────────────────────────────────────────────────────
        bought = False
        while running and not bought:
            now = utcnow()
            to_start = (start - now).total_seconds()

            if to_start <= 0:
                if buy_oid:
                    cancel_ord(client, buy_oid, "BUY")
                    full, _ = order_filled(client, buy_oid)
                    if full:
                        buy_fill_px = buy_px
                        print(f"[MM] BUY filled on cancel @ {buy_fill_px:.2f}")
                        bought = True
                        break
                print("[MM] Candle started, BUY not filled. Done.")
                result["events"].append({"a": "NO_FILL"})
                log_trade(result)
                return

            if buy_oid:
                full, _ = order_filled(client, buy_oid)
                if full:
                    buy_fill_px = buy_px
                    print(f"[MM] BUY FILLED @ {buy_fill_px:.2f}")
                    bought = True
                    break

            # Re-evaluate which side to trade (pick_side reads both books)
            new_token, new_side = pick_side(client, up_token, dn_token)
            need_switch = new_token != token

            # Read book for target token
            book = get_book(client, new_token)
            if not book or not book.get("bids") or not book.get("asks"):
                time.sleep(POLL_SEC)
                continue
            bb = float(book["bids"][0]["price"])
            ba = float(book["asks"][0]["price"])
            spread = round(ba - bb, 2)

            tgt = min(round(bb + TICK, 2), round(ba - TICK, 2))

            if buy_oid is None:
                token, side = new_token, new_side
                buy_oid = place_order(client, token, tgt, ORDER_SIZE, BUY, "BUY")
                buy_px = tgt
            elif need_switch or abs(tgt - buy_px) >= TICK:
                if not cancel_ord(client, buy_oid, "BUY"):
                    full, _ = order_filled(client, buy_oid)
                    if full:
                        buy_fill_px = buy_px
                        bought = True
                        break
                    time.sleep(POLL_SEC)
                    continue  # cancel failed, keep old order
                full, _ = order_filled(client, buy_oid)
                if full:
                    buy_fill_px = buy_px
                    print(f"[MM] BUY filled during re-quote @ {buy_fill_px:.2f}")
                    bought = True
                    break
                token, side = new_token, new_side
                buy_oid = place_order(client, token, tgt, ORDER_SIZE, BUY, "BUY")
                buy_px = tgt

            if int(to_start) % 10 < POLL_SEC + 0.5:
                print(f"[MM] bb={bb:.2f} ba={ba:.2f} sp={spread:.2f} | "
                      f"BUY@{buy_px or '-'} | {to_start:.0f}s to start")

            time.sleep(POLL_SEC)

        if not bought or not running:
            break

        # ────────────────────────────────────────────────────────────────
        # PHASE 2a: Wait for token balance to settle (up to 30s)
        # ────────────────────────────────────────────────────────────────
        token_bal = 0.0
        settle_deadline = utcnow() + timedelta(seconds=30)
        while running:
            now = utcnow()
            to_start = (start - now).total_seconds()
            to_settle = (settle_deadline - now).total_seconds()

            token_bal = get_token_balance(client, token)
            if token_bal >= ORDER_SIZE - 0.1:
                print(f"[MM] Token balance settled: {token_bal:.2f} shares")
                break

            if to_start <= 0 or to_settle <= 0:
                print(f"[MM] Settlement timeout. Balance: {token_bal:.2f}, needed: {ORDER_SIZE}")
                if token_bal >= MIN_SIZE:
                    print(f"[MM] Partial balance, will sell {token_bal:.2f}")
                    break
                # Not enough for limit sell — cleanup phase will handle it
                print(f"[MM] Not enough for limit sell, cleanup will handle")
                result["events"].append({"a": "NO_SETTLE", "bal": token_bal})
                break  # fall through to cleanup

            print(f"[MM] Waiting for settlement... bal={token_bal:.2f} ({to_settle:.0f}s left)")
            time.sleep(2)

        sell_size = min(ORDER_SIZE, math.floor(token_bal * 100) / 100)  # round DOWN

        # Phantom fill: order reported filled but no tokens arrived
        if token_bal < 1.0:
            print(f"[MM] Phantom fill — BUY showed filled but no tokens ({token_bal:.2f}). Skipping SELL.")
            result["events"].append({"a": "PHANTOM_FILL", "bal": token_bal})
            break  # skip to cleanup

        # ────────────────────────────────────────────────────────────────
        # PHASE 2b: SELL — limit in spread, market sell at deadline
        # ────────────────────────────────────────────────────────────────
        sold = False
        while running and not sold:
            now = utcnow()
            to_sell_dl = (sell_deadline - now).total_seconds()

            # DEADLINE: cancel + market sell
            if to_sell_dl <= 0:
                print(f"[MM] SELL DEADLINE ({SELL_DEADLINE}s after start)")
                if sell_oid:
                    cancel_ord(client, sell_oid, "SELL")
                    full, _ = order_filled(client, sell_oid)
                    if full:
                        profit = round((sell_px - buy_fill_px) * sell_size, 4)
                        print(f"[MM] SELL filled on cancel @ {sell_px:.2f}  profit=${profit}")
                        result["events"].append({"a": "SELL_FILLED",
                            "buy": buy_fill_px, "sell": sell_px, "profit": profit})
                        sold = True
                        break
                # DON'T force market sell — holding through resolution is EV-neutral (50/50),
                # which is better than guaranteed loss from selling at resting bid (0.01-0.44).
                print(f"[MM] HOLDING through resolution (bought @ {buy_fill_px:.2f}) — better than forced sell loss")
                result["events"].append({"a": "HOLD_THROUGH", "buy": buy_fill_px, "sz": sell_size})
                break

            book = get_book(client, token)
            if not book or not book.get("bids") or not book.get("asks"):
                time.sleep(POLL_SEC)
                continue

            bb = float(book["bids"][0]["price"])
            ba = float(book["asks"][0]["price"])

            if sell_oid:
                full, _ = order_filled(client, sell_oid)
                if full:
                    profit = round((sell_px - buy_fill_px) * sell_size, 4)
                    print(f"[MM] SELL FILLED @ {sell_px:.2f}  profit=${profit}")
                    result["events"].append({"a": "SELL_FILLED",
                        "buy": buy_fill_px, "sell": sell_px, "profit": profit})
                    sold = True
                    break

            tgt_sell = max(round(buy_fill_px + TICK, 2), round(ba - TICK, 2), round(bb + TICK, 2))

            if sell_oid is None:
                sell_oid = place_order(client, token, tgt_sell, sell_size, SELL, "SELL")
                if sell_oid is None:
                    print(f"[MM] SELL limit failed, cleanup will handle")
                    result["events"].append({"a": "SELL_FAIL", "buy": buy_fill_px})
                    break
                sell_px = tgt_sell
            elif abs(tgt_sell - sell_px) >= TICK and tgt_sell < sell_px:
                if not cancel_ord(client, sell_oid, "SELL"):
                    full, _ = order_filled(client, sell_oid)
                    if full:
                        profit = round((sell_px - buy_fill_px) * sell_size, 4)
                        result["events"].append({"a": "SELL_FILLED",
                            "buy": buy_fill_px, "sell": sell_px, "profit": profit})
                        sold = True
                        break
                    time.sleep(POLL_SEC)
                    continue
                full, _ = order_filled(client, sell_oid)
                if full:
                    profit = round((sell_px - buy_fill_px) * sell_size, 4)
                    print(f"[MM] SELL filled during re-quote @ {sell_px:.2f}  profit=${profit}")
                    result["events"].append({"a": "SELL_FILLED",
                        "buy": buy_fill_px, "sell": sell_px, "profit": profit})
                    sold = True
                    break
                sell_oid = place_order(client, token, tgt_sell, sell_size, SELL, "SELL")
                if sell_oid is None:
                    print(f"[MM] SELL re-quote failed, cleanup will handle")
                    result["events"].append({"a": "SELL_FAIL", "buy": buy_fill_px})
                    break
                sell_px = tgt_sell

            print(f"[MM] bb={bb:.2f} ba={ba:.2f} | SELL@{sell_px or '-'} "
                  f"bought@{buy_fill_px:.2f} | {to_sell_dl:.1f}s left")

            time.sleep(POLL_SEC)

        # SELL filled and there's still time before candle → loop for another round
        if sold and (start - utcnow()).total_seconds() > 5:
            # Wait for SELL settlement before next round
            print(f"[MM] Round {rounds} done, waiting for sell settlement...")
            while running:
                tb = get_token_balance(client, token)
                if tb < 1.0:
                    print(f"[MM] Sell settled (bal={tb:.2f}), ready for next round")
                    break
                if (start - utcnow()).total_seconds() <= 5:
                    print(f"[MM] No time for next round, sell still settling")
                    break
                time.sleep(2)
            if (start - utcnow()).total_seconds() <= 5:
                break
            continue
        else:
            break

    # ────────────────────────────────────────────────────────────────────
    # NO CLEANUP: Let positions resolve naturally. Winning shares auto-redeem.
    # Forced market sells at resting bids are guaranteed losses.
    # ────────────────────────────────────────────────────────────────────
    for tok_id, label in [(up_token, "UP"), (dn_token, "DN")]:
        tb = get_token_balance(client, tok_id)
        if tb >= 1.0:
            print(f"[MM] Holding {label}: {tb:.2f}sh through resolution (auto-redeems if wins)")

    log_trade(result)
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global running

    kill_other_instances()

    print(f"[MM] === BTC 15-min Spread Scalper ===")
    print(f"[MM] UTC: {utcnow()}")
    print(f"[MM] size={ORDER_SIZE}  sell_deadline=+{SELL_DEADLINE}s  poll={POLL_SEC}s")

    client = get_client()
    bal = get_usdc_balance(client)
    print(f"[MM] Balance: ${bal:.2f}")
    send(f"BTC 15m scalper started. Balance: ${bal:.2f}")

    while running:
        candle = find_next_candle()
        if not candle:
            print("[MM] no candle found, retry in 30s")
            time.sleep(30)
            continue

        now = utcnow()
        secs = (candle["candle_start"] - now).total_seconds()

        if secs > 900:
            wait = secs - 900
            print(f"[MM] next: {candle['question']} in {secs:.0f}s, sleeping {wait:.0f}s")
            while wait > 0 and running:
                time.sleep(min(wait, 30))
                wait -= 30
            continue

        if secs <= 0:
            print(f"[MM] {candle['slug']} already started, skipping")
            traded_candles.add(int(candle["candle_start"].timestamp()))
            time.sleep(2)
            continue

        bal = get_usdc_balance(client)
        if bal < MIN_BALANCE:
            print(f"[MM] Balance ${bal:.2f} < ${MIN_BALANCE}, waiting...")
            time.sleep(30)
            continue

        run_candle(candle)
        time.sleep(3)

    print("[MM] shutdown")
    send("BTC 15m scalper stopped.")


if __name__ == "__main__":
    main()
