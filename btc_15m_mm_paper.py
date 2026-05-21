#!/usr/bin/env python3
"""
BTC 15-min Candle Fair-Value Market Maker — PAPER TRADING

Same logic as btc_15m_mm.py but simulates execution by checking
orderbook asks. No real orders placed.

Execution rule: if best ask <= our max price, simulate a market buy
at the ask price for PAPER_SIZE shares.

State persisted to mm_paper_state.json. Trades logged to logs/btc_15m_mm_paper.jsonl.
"""

import json
import os
import signal
import time

from mm_config import (
    POLL_SEC, TICK, ENTER_NORMAL,
    utcnow, _get_gamma,
)
from mm_discovery import find_next_candle, get_streak
from mm_clob import get_book
from mm_fair_value import (
    compute_fair_value, fetch_binance_rsi, get_current_candle_color,
    STREAK_PROB_UP, _rsi_adjustment,
)
from trader.client import get_client
from trader.notify import send

import mm_config

# ─── Config ─────────────────────────────────────────────────────────────────
INITIAL_BALANCE = 100.0
PAPER_SIZE = 5.0
STATE_FILE = "mm_paper_state.json"
TRADE_LOG = "logs/btc_15m_mm_paper.jsonl"


# ─── State persistence ──────────────────────────────────────────────────────

def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"balance": INITIAL_BALANCE, "positions": [], "traded_candles": []}


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _log_trade(entry):
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ─── Resolution ─────────────────────────────────────────────────────────────

def check_resolution(slug):
    """Check if a candle resolved. Returns 'UP', 'DN', or None."""
    try:
        r = _get_gamma(f"/events/slug/{slug}")
        if r.status_code != 200:
            return None
        mkt = r.json().get("markets", [None])[0]
        if not mkt or not mkt.get("closed"):
            return None
        outcomes = json.loads(mkt.get("outcomes", "[]"))
        prices = json.loads(mkt.get("outcomePrices", "[]"))
        if len(outcomes) < 2 or len(prices) < 2:
            return None
        up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)
        return "UP" if float(prices[up_idx]) > 0.5 else "DN"
    except Exception as e:
        print(f"[PAPER] resolution error {slug}: {e}")
        return None


def resolve_positions(state):
    """Settle any resolved positions."""
    remaining = []
    for pos in state["positions"]:
        result = check_resolution(pos["slug"])
        if result is None:
            remaining.append(pos)
            continue

        won = (pos["side"] == result)
        if won:
            state["balance"] += pos["size"]  # $1/share
        state["balance"] = round(state["balance"], 4)
        pnl = round((1.0 - pos["price"]) * pos["size"] if won else -pos["price"] * pos["size"], 4)

        tag = "WIN" if won else "LOSE"
        print(f"[PAPER] {pos['slug']} {pos['side']} → {result}: {tag} "
              f"pnl=${pnl:+.2f} bal=${state['balance']:.2f}")

        _log_trade({
            "timestamp": str(utcnow()),
            "action": "RESOLVE",
            "slug": pos["slug"],
            "side": pos["side"],
            "price": pos["price"],
            "size": pos["size"],
            "result": result,
            "won": won,
            "pnl": pnl,
            "balance": state["balance"],
        })

    state["positions"] = remaining


# ─── Paper candle ────────────────────────────────────────────────────────────

def run_candle_paper(client, candle, fair_up, fair_dn, streak_count, streak_color, rsi, state):
    """Paper trade one candle: poll asks, simulate fills."""
    up_token = candle["up_token"]
    dn_token = candle["dn_token"]
    start = candle["candle_start"]
    slug = candle["slug"]

    max_up = round(fair_up - TICK, 2)
    max_dn = round(fair_dn - TICK, 2)

    # Rationale
    if streak_count > 0 and streak_color not in (None, "NONE"):
        key = (min(streak_count, 6), streak_color)
        base = STREAK_PROB_UP.get(key, 0.50)
    else:
        base = 0.50
    rsi_adj = _rsi_adjustment(rsi)

    print(f"\n[PAPER] {'='*55}")
    print(f"[PAPER] {candle['question']}")
    print(f"[PAPER] streak={streak_count}x{streak_color} → base UP={base:.1%}")
    if rsi is not None and rsi_adj != 0:
        print(f"[PAPER] RSI={rsi:.1f} → adj {rsi_adj:+.0%}")
    print(f"[PAPER] fair: UP={fair_up:.3f} DN={fair_dn:.3f}")
    print(f"[PAPER] max buy: UP@{max_up:.2f} DN@{max_dn:.2f}")
    print(f"[PAPER] balance: ${state['balance']:.2f}")

    # Telegram rationale
    lines = [f"[PAPER] {candle['question']}"]
    if streak_count > 0 and streak_color not in (None, "NONE"):
        direction = "UP" if base > 0.50 else "DN" if base < 0.50 else "neutral"
        lines.append(f"Streak: {streak_count}x {streak_color} → base UP={base:.1%} ({direction})")
    else:
        lines.append("Streak: none → base 50/50")
    if rsi is not None and rsi_adj != 0:
        zone = "oversold, +UP" if rsi_adj > 0 else "overbought, +DN"
        lines.append(f"RSI: {rsi:.1f} ({zone}) → {rsi_adj:+.0%}")
    elif rsi is not None:
        lines.append(f"RSI: {rsi:.1f} (neutral)")
    lines.append(f"Fair: UP={fair_up:.2f} DN={fair_dn:.2f}")
    lines.append(f"Max buy: UP@{max_up:.2f} DN@{max_dn:.2f}")
    lines.append(f"Balance: ${state['balance']:.2f}")
    send("\n".join(lines))

    filled_up = False
    filled_dn = False
    fill_up_px = None
    fill_dn_px = None
    tick_count = 0

    while mm_config.running:
        tick_count += 1
        now = utcnow()
        to_start = (start - now).total_seconds()
        if to_start <= 0:
            break

        # Check UP asks
        if not filled_up and state["balance"] >= PAPER_SIZE * max_up:
            book = get_book(client, up_token)
            if book and book.get("asks"):
                best_ask = float(book["asks"][0]["price"])
                if best_ask <= max_up:
                    fill_up_px = best_ask
                    cost = round(PAPER_SIZE * fill_up_px, 4)
                    state["balance"] = round(state["balance"] - cost, 4)
                    filled_up = True
                    print(f"[PAPER] BUY UP {PAPER_SIZE:.0f}sh @ {fill_up_px:.2f} "
                          f"(ask={best_ask:.2f} <= max={max_up:.2f}) cost=${cost:.2f}")

        # Check DN asks
        if not filled_dn and state["balance"] >= PAPER_SIZE * max_dn:
            book = get_book(client, dn_token)
            if book and book.get("asks"):
                best_ask = float(book["asks"][0]["price"])
                if best_ask <= max_dn:
                    fill_dn_px = best_ask
                    cost = round(PAPER_SIZE * fill_dn_px, 4)
                    state["balance"] = round(state["balance"] - cost, 4)
                    filled_dn = True
                    print(f"[PAPER] BUY DN {PAPER_SIZE:.0f}sh @ {fill_dn_px:.2f} "
                          f"(ask={best_ask:.2f} <= max={max_dn:.2f}) cost=${cost:.2f}")

        if filled_up and filled_dn:
            break

        # Status every 10 ticks
        if tick_count % 10 == 0:
            parts = []
            if filled_up:
                parts.append(f"UP:FILLED@{fill_up_px:.2f}")
            else:
                parts.append(f"UP:waiting(max={max_up:.2f})")
            if filled_dn:
                parts.append(f"DN:FILLED@{fill_dn_px:.2f}")
            else:
                parts.append(f"DN:waiting(max={max_dn:.2f})")
            print(f"[PAPER] {' | '.join(parts)} | {to_start:.0f}s to start")

        time.sleep(POLL_SEC)

    # ── Results ──
    base_entry = {
        "timestamp": str(utcnow()),
        "slug": slug,
        "candle": candle["question"],
        "fair_up": fair_up, "fair_dn": fair_dn,
        "streak": f"{streak_count}x{streak_color}", "rsi": rsi,
    }

    if filled_up and filled_dn:
        profit = round((1.0 - fill_up_px - fill_dn_px) * PAPER_SIZE, 4)
        print(f"[PAPER] BOTH FILLED: UP@{fill_up_px:.2f} + DN@{fill_dn_px:.2f} "
              f"→ ${profit:.2f} guaranteed")
        send(f"[PAPER] BOTH filled UP@{fill_up_px:.2f}+DN@{fill_dn_px:.2f} = ${profit:.2f}")
    elif filled_up or filled_dn:
        side = "UP" if filled_up else "DN"
        px = fill_up_px if filled_up else fill_dn_px
        fair = fair_up if filled_up else fair_dn
        edge = round(fair - px, 4)
        print(f"[PAPER] {side} FILLED @ {px:.2f} (fair={fair:.3f}, edge={edge:.2f})")
        send(f"[PAPER] {side} filled @{px:.2f} (fair={fair:.2f} edge={edge:.2f})")
    else:
        print(f"[PAPER] Neither filled")

    # Record positions
    if filled_up:
        state["positions"].append({
            "slug": slug, "side": "UP", "price": fill_up_px,
            "size": PAPER_SIZE, "timestamp": str(utcnow()),
        })
        _log_trade({**base_entry, "action": "BUY", "side": "UP",
                     "price": fill_up_px, "size": PAPER_SIZE,
                     "balance": state["balance"]})

    if filled_dn:
        state["positions"].append({
            "slug": slug, "side": "DN", "price": fill_dn_px,
            "size": PAPER_SIZE, "timestamp": str(utcnow()),
        })
        _log_trade({**base_entry, "action": "BUY", "side": "DN",
                     "price": fill_dn_px, "size": PAPER_SIZE,
                     "balance": state["balance"]})

    if not filled_up and not filled_dn:
        _log_trade({**base_entry, "action": "NO_FILL",
                     "balance": state["balance"]})

    _save_state(state)
    print(f"[PAPER] Balance: ${state['balance']:.2f} | Positions: {len(state['positions'])}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"[PAPER] === BTC 15-min Fair-Value MM — PAPER TRADING ===")
    print(f"[PAPER] UTC: {utcnow()}")
    print(f"[PAPER] size={PAPER_SIZE}  poll={POLL_SEC}s")

    state = _load_state()
    print(f"[PAPER] Balance: ${state['balance']:.2f}")
    print(f"[PAPER] Open positions: {len(state['positions'])}")

    client = get_client()

    # Populate traded_candles so find_next_candle skips them
    for ts in state.get("traded_candles", []):
        mm_config.traded_candles.add(ts)

    send(f"[PAPER] MM started. Balance: ${state['balance']:.2f}")

    while mm_config.running:
        # Resolve settled positions
        resolve_positions(state)

        # Find next candle
        candle = find_next_candle()
        if not candle:
            print("[PAPER] no candle found, retry in 30s")
            time.sleep(30)
            continue

        candle_ts = int(candle["candle_start"].timestamp())
        now = utcnow()
        secs = (candle["candle_start"] - now).total_seconds()

        if secs <= 0:
            mm_config.traded_candles.add(candle_ts)
            time.sleep(2)
            continue

        # Wait for entry time
        if secs > ENTER_NORMAL:
            time.sleep(min(secs - ENTER_NORMAL, 30))
            continue

        # Wait for current candle confirmation (95%+ and <5 min left)
        current_color = None
        try:
            current_color = get_current_candle_color(client)
        except Exception as e:
            print(f"[PAPER] current candle check error: {e}")

        if current_color is None:
            print(f"[PAPER] Current candle not confirmed ({secs:.0f}s to start)")
            time.sleep(10)
            continue

        # Streak + RSI + fair value
        streak_count, streak_color = get_streak(current_candle_color=current_color)
        rsi = None
        try:
            rsi = fetch_binance_rsi()
        except Exception:
            pass
        fair_up, fair_dn = compute_fair_value(streak_count, streak_color, rsi)

        # Run paper candle
        run_candle_paper(client, candle, fair_up, fair_dn,
                         streak_count, streak_color, rsi, state)
        mm_config.traded_candles.add(candle_ts)
        state["traded_candles"] = list(mm_config.traded_candles)[-200:]
        _save_state(state)
        time.sleep(3)

    print("[PAPER] shutdown")
    send(f"[PAPER] MM stopped. Balance: ${state['balance']:.2f}")


if __name__ == "__main__":
    main()
