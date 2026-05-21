#!/usr/bin/env python3
"""
BTC 15-min Candle Fair-Value Market Maker

Two-sided market maker that places BUY orders on BOTH UP and DN tokens,
priced around statistically-derived fair value.

How it works:
  1. Compute fair value from streak mean reversion + Binance RSI
  2. Place BUY UP at min(market_level, fair_up - tick)
  3. Place BUY DN at min(market_level, fair_dn - tick)
  4. If BOTH fill: guaranteed profit = 1 - up_cost - dn_cost (per share)
  5. If ONE fills: hold through resolution with statistical edge
  6. If NONE fill: no harm, try next candle

Fair value shifts WHERE orders sit — asymmetric when streaks exist:
  - 50/50 fair value: symmetric orders, classic spread capture
  - 35/65 after 4-green streak: UP order far below market (rarely fills),
    DN order near market (fills often) — DN held with 15c edge if single-fill

Usage:
  nohup python3 -u btc_15m_mm.py > logs/btc_15m_mm_$(date -u +%Y%m%d_%H%M).log 2>&1 &
"""

import math
import time
from datetime import timedelta

from trader.client import get_client, get_usdc_balance
from trader.notify import send
from py_clob_client.order_builder.constants import BUY, SELL

from mm_config import (
    ORDER_SIZE, POLL_SEC, TICK, MIN_BALANCE, MAKER_FEE,
    ENTER_NORMAL,
    running, traded_candles, utcnow, log_trade, _retry, kill_other_instances,
)
from mm_discovery import find_next_candle, get_streak
from mm_clob import (
    get_book, get_token_balance, place_order,
    cancel_ord, order_filled,
    cancel_all_token_orders, find_support_price,
    close_position,
)
from mm_fair_value import (
    compute_fair_value, fetch_binance_rsi, get_current_candle_color,
)

import mm_config


# ─── Leg management helpers ─────────────────────────────────────────────────

def _compute_target(book, max_price):
    """Compute target BUY price for one leg: follow market but cap at max_price."""
    if not book or not book.get("bids") or not book.get("asks"):
        return None, None, None

    bb = float(book["bids"][0]["price"])
    ba = float(book["asks"][0]["price"])

    support = find_support_price(book)
    tgt = min(support or round(bb + TICK, 2), round(ba - TICK, 2))
    tgt = min(tgt, max_price)  # never exceed fair value

    if tgt < 0.01 or tgt > 0.99:
        print(f"[MM] target {tgt:.2f} out of range (bb={bb:.2f} ba={ba:.2f})")
        return None, bb, ba

    return tgt, bb, ba


def _check_leg_fill(client, leg):
    """Check if a leg's order filled (by balance or order status).
    Returns True if fully filled. Partial fills keep the order alive."""
    if leg["filled"]:
        return True

    bal = get_token_balance(client, leg["token"])
    if bal >= ORDER_SIZE - 0.5:
        # Full fill confirmed by balance
        leg["filled"] = True
        leg["fill_px"] = leg["px"] or 0.50
        leg["bal"] = bal
        if leg["oid"]:
            cancel_ord(client, leg["oid"], leg["label"])
            leg["oid"] = None
        print(f"[MM] {leg['label']} filled: {bal:.1f}sh @ {leg['fill_px']:.2f}")
        return True

    if bal >= 1.0:
        # Partial fill — keep order alive for remaining shares
        if not leg.get("partial"):
            print(f"[MM] {leg['label']} partial: {bal:.1f}/{ORDER_SIZE:.0f}sh, keeping order")
        leg["partial"] = bal
        return False

    if leg["oid"]:
        full, _ = order_filled(client, leg["oid"])
        if full:
            # CLOB confirmed fill — trust it, tokens will settle
            leg["filled"] = True
            leg["fill_px"] = leg["px"]
            leg["bal"] = ORDER_SIZE
            leg["oid"] = None
            print(f"[MM] {leg['label']} filled (CLOB confirmed) @ {leg['fill_px']:.2f}")
            return True

    return False


def _place_or_update(client, leg, tgt):
    """Place or re-quote a BUY order for one leg."""
    if leg["oid"] is None:
        leg["oid"] = place_order(client, leg["token"], tgt, ORDER_SIZE, BUY, leg["label"])
        leg["px"] = tgt
    elif abs(tgt - leg["px"]) >= TICK:
        if not cancel_ord(client, leg["oid"], leg["label"]):
            return
        # Check if fill happened during cancel
        nb = get_token_balance(client, leg["token"])
        if nb >= 1.0:
            leg["filled"] = True
            leg["fill_px"] = leg["px"]
            leg["bal"] = nb
            leg["oid"] = None
            print(f"[MM] {leg['label']} filled during re-quote @ {leg['fill_px']:.2f}")
            return
        leg["oid"] = place_order(client, leg["token"], tgt, ORDER_SIZE, BUY, leg["label"])
        leg["px"] = tgt


# ─── Telegram rationale ─────────────────────────────────────────────────────

def _send_rationale(candle, fair_up, fair_dn, max_up, max_dn,
                    streak_count, streak_color, rsi):
    """Send fair value rationale to Telegram."""
    from mm_fair_value import STREAK_PROB_UP, _rsi_adjustment

    lines = [f"🕯 {candle['question']}"]

    # Streak contribution
    if streak_count == 0 or streak_color in (None, "NONE"):
        lines.append(f"Streak: none → base 50/50")
    else:
        key = (min(streak_count, 6), streak_color)
        base = STREAK_PROB_UP.get(key, 0.50)
        direction = "UP" if base > 0.50 else "DN" if base < 0.50 else "neutral"
        lines.append(f"Streak: {streak_count}x {streak_color} → base UP={base:.1%} ({direction} bias)")

    # RSI contribution
    if rsi is not None:
        adj = _rsi_adjustment(rsi)
        if adj != 0:
            sign = "+" if adj > 0 else ""
            zone = ("oversold, +UP" if adj > 0 else "overbought, +DN")
            lines.append(f"RSI: {rsi:.1f} ({zone}) → {sign}{adj:.0%}")
        else:
            lines.append(f"RSI: {rsi:.1f} (neutral, no adj)")
    else:
        lines.append(f"RSI: unavailable")

    # Fair values and max prices
    lines.append(f"Fair: UP={fair_up:.2f} DN={fair_dn:.2f}")
    lines.append(f"Max buy: UP@{max_up:.2f} DN@{max_dn:.2f}")

    send("\n".join(lines))


# ─── Main loop for one candle ────────────────────────────────────────────────

def run_candle(candle, fair_up, fair_dn, streak_count, streak_color, rsi):
    """Two-sided market maker for one candle, priced around fair value."""
    client = get_client()
    up_token = candle["up_token"]
    dn_token = candle["dn_token"]
    start = candle["candle_start"]

    # Max buy prices: fair - 1 tick per side
    # Guarantees: max_up + max_dn = (fair_up - tick) + (fair_dn - tick) = 0.98
    # So if BOTH fill, profit >= 2c per share
    max_up = round(fair_up - TICK, 2)
    max_dn = round(fair_dn - TICK, 2)

    print(f"\n[MM] {'='*55}")
    print(f"[MM] {candle['question']}")
    print(f"[MM] start={start.isoformat()}")
    print(f"[MM] streak={streak_count}x{streak_color} RSI={rsi}")
    print(f"[MM] fair: UP={fair_up:.3f} DN={fair_dn:.3f}")
    print(f"[MM] max:  UP={max_up:.2f}  DN={max_dn:.2f}  "
          f"(both fill → {(1 - max_up - max_dn)*100:.0f}c+ profit/sh)")

    # ── Telegram rationale ──
    _send_rationale(candle, fair_up, fair_dn, max_up, max_dn,
                    streak_count, streak_color, rsi)

    track_candle_tokens(up_token, dn_token)
    candle_ts = int(start.timestamp())
    traded_candles.add(candle_ts)

    # ── Check balance ──
    try:
        bal = _retry(lambda: get_usdc_balance(client), retries=2, delay=2, tag="MM")
    except Exception:
        bal = 0
    print(f"[MM] Balance: ${bal:.2f}")

    up_cost = ORDER_SIZE * max_up
    dn_cost = ORDER_SIZE * max_dn
    both_cost = up_cost + dn_cost

    # Decide how many legs to place based on balance
    place_up = True
    place_dn = True
    if bal < MIN_BALANCE:
        print(f"[MM] Balance too low, skipping.")
        log_trade({"candle": candle["question"], "start": str(start),
                    "action": "SKIP_LOW_BAL", "bal": bal})
        return
    elif bal < both_cost:
        # Can only afford one leg — pick cheaper side (lower cost, same EV per share)
        if max_up <= max_dn:
            place_dn = False
            print(f"[MM] Balance ${bal:.2f} < ${both_cost:.2f}, placing UP only (cheaper)")
        else:
            place_up = False
            print(f"[MM] Balance ${bal:.2f} < ${both_cost:.2f}, placing DN only (cheaper)")

    # ── Check for existing positions ──
    up_bal = get_token_balance(client, up_token)
    dn_bal = get_token_balance(client, dn_token)

    if up_bal >= 1.0 or dn_bal >= 1.0:
        sides = []
        if up_bal >= 1.0:
            sides.append(f"UP:{up_bal:.0f}sh")
        if dn_bal >= 1.0:
            sides.append(f"DN:{dn_bal:.0f}sh")
        print(f"[MM] Existing position {', '.join(sides)} — ensuring sell orders")
        # Place sell orders at $0.99 for any existing positions without one
        for token, token_bal, label in [(up_token, up_bal, "UP"), (dn_token, dn_bal, "DN")]:
            if token_bal >= 1.0:
                size = math.floor(token_bal * 100) / 100
                if size >= 1.0:
                    place_order(client, token, 0.99, size, SELL, f"SELL-{label}")
        log_trade({"candle": candle["question"], "start": str(start),
                    "action": "EXISTING_HOLD", "up_bal": up_bal, "dn_bal": dn_bal})
        return

    # ── Leg state ──
    legs = {}
    if place_up:
        legs["UP"] = {
            "label": "UP", "token": up_token, "max": max_up, "fair": fair_up,
            "oid": None, "px": None, "filled": False, "fill_px": None, "bal": 0.0,
        }
    if place_dn:
        legs["DN"] = {
            "label": "DN", "token": dn_token, "max": max_dn, "fair": fair_dn,
            "oid": None, "px": None, "filled": False, "fill_px": None, "bal": 0.0,
        }

    result = {
        "candle": candle["question"], "start": str(start),
        "fair_up": fair_up, "fair_dn": fair_dn,
        "streak": f"{streak_count}x{streak_color}", "rsi": rsi,
    }

    # ────────────────────────────────────────────────────────────────────
    # MAIN LOOP: manage both legs simultaneously
    # ────────────────────────────────────────────────────────────────────
    tick_count = 0
    while mm_config.running:
        tick_count += 1
        now = utcnow()
        to_start = (start - now).total_seconds()

        # ── Candle started → cancel unfilled legs, keep filled ──
        if to_start <= 0:
            for leg in legs.values():
                if leg["oid"] and not leg["filled"]:
                    cancel_ord(client, leg["oid"], leg["label"])
                    leg["oid"] = None
            # One last balance check
            time.sleep(1)
            for leg in legs.values():
                if not leg["filled"]:
                    nb = get_token_balance(client, leg["token"])
                    if nb >= 1.0:
                        leg["filled"] = True
                        leg["fill_px"] = leg["px"] or 0.50
                        leg["bal"] = nb
                        print(f"[MM] {leg['label']} filled at deadline: {nb:.1f}sh @ {leg['fill_px']:.2f}")
            break

        # ── Check fills ──
        for leg in legs.values():
            if not leg["filled"]:
                _check_leg_fill(client, leg)

        # Both filled → profit locked, no need to continue
        if all(l["filled"] for l in legs.values()) and len(legs) == 2:
            break

        # ── Update orders for unfilled legs ──
        for leg in legs.values():
            if leg["filled"] or leg.get("partial"):
                continue

            book = get_book(client, leg["token"])
            tgt, bb, ba = _compute_target(book, leg["max"])
            if tgt is None:
                continue

            _place_or_update(client, leg, tgt)

        # ── Periodic status ──
        if tick_count % 10 == 0:
            parts = []
            for side, leg in legs.items():
                if leg["filled"]:
                    parts.append(f"{side}:FILLED@{leg['fill_px']:.2f}")
                elif leg.get("partial"):
                    parts.append(f"{side}:PARTIAL {leg['partial']:.1f}/{ORDER_SIZE:.0f}sh@{leg['px']:.2f}")
                elif leg["px"]:
                    parts.append(f"{side}:BUY@{leg['px']:.2f}(max={leg['max']:.2f})")
                else:
                    parts.append(f"{side}:PENDING")
            print(f"[MM] {' | '.join(parts)} | {to_start:.0f}s to start")

        time.sleep(POLL_SEC)

    # ────────────────────────────────────────────────────────────────────
    # RESULT: log what happened
    # ────────────────────────────────────────────────────────────────────
    up_leg = legs.get("UP")
    dn_leg = legs.get("DN")
    up_filled = up_leg and up_leg["filled"]
    dn_filled = dn_leg and dn_leg["filled"]

    if up_filled and dn_filled:
        # BOTH LEGS — guaranteed profit (minus maker fees)
        gross = round(1.0 - up_leg["fill_px"] - dn_leg["fill_px"], 4)
        fees_per_sh = round((up_leg["fill_px"] + dn_leg["fill_px"]) * MAKER_FEE, 4)
        profit_per_share = round(gross - fees_per_sh, 4)
        total_profit = round(profit_per_share * ORDER_SIZE, 4)
        print(f"\n[MM] ╔══════════════════════════════════════════════╗")
        print(f"[MM] ║  BOTH LEGS FILLED — PROFIT LOCKED")
        print(f"[MM] ║  UP: {up_leg['bal']:.0f}sh @ {up_leg['fill_px']:.2f}")
        print(f"[MM] ║  DN: {dn_leg['bal']:.0f}sh @ {dn_leg['fill_px']:.2f}")
        print(f"[MM] ║  Spread captured: {profit_per_share*100:.1f}c/sh → ${total_profit:.2f}")
        print(f"[MM] ╚══════════════════════════════════════════════╝")
        result["action"] = "BOTH_FILLED"
        result["up_px"] = up_leg["fill_px"]
        result["dn_px"] = dn_leg["fill_px"]
        result["profit"] = total_profit
        send(f"BTC 15m MM: BOTH filled UP@{up_leg['fill_px']:.2f}+DN@{dn_leg['fill_px']:.2f} "
             f"= ${total_profit:.2f} profit")

    elif up_filled or dn_filled:
        # ONE LEG — hold through resolution with statistical edge
        leg = up_leg if up_filled else dn_leg
        side = leg["label"]
        edge = round(leg["fair"] - leg["fill_px"], 4)
        profit_if_win = round((1.0 - leg["fill_px"]) * leg["bal"], 4)
        loss_if_lose = round(leg["fill_px"] * leg["bal"], 4)
        ev = round(leg["fair"] * (1.0 - leg["fill_px"]) - (1 - leg["fair"]) * leg["fill_px"], 4)
        ev_total = round(ev * leg["bal"], 4)

        print(f"\n[MM] ╔══════════════════════════════════════════════╗")
        print(f"[MM] ║  {side} FILLED — holding through resolution")
        print(f"[MM] ║  {leg['bal']:.0f}sh @ {leg['fill_px']:.2f}  (fair={leg['fair']:.3f})")
        print(f"[MM] ║  Edge: {edge*100:.1f}c  |  EV/sh: {ev*100:.1f}c  → ${ev_total:.3f}")
        print(f"[MM] ║  Win: +${profit_if_win:.2f}  |  Lose: -${loss_if_lose:.2f}")
        print(f"[MM] ╚══════════════════════════════════════════════╝")
        result["action"] = "ONE_FILLED"
        result["filled_side"] = side
        result["fill_px"] = leg["fill_px"]
        result["size"] = leg["bal"]
        result["edge"] = edge
        result["ev"] = ev_total
        send(f"BTC 15m {side}: {leg['bal']:.0f}sh@{leg['fill_px']:.2f} "
             f"(fair={leg['fair']:.2f} edge={edge:.2f} EV=${ev_total:.3f})")

    else:
        # NEITHER — no fills
        print(f"[MM] Neither leg filled.")
        result["action"] = "NO_FILL"

    log_trade(result)

    # ── Place sell orders at $0.99 for filled positions ──
    for leg in legs.values():
        if leg["filled"]:
            actual_bal = get_token_balance(client, leg["token"])
            if actual_bal >= 1.0:
                size = math.floor(actual_bal * 100) / 100
                place_order(client, leg["token"], 0.99, size, SELL, f"SELL-{leg['label']}")


# ─── Orphan scanner ──────────────────────────────────────────────────────────

# token_id → (label, added_timestamp)
_orphan_tokens: dict[str, tuple[str, float]] = {}

_ORPHAN_AGE = 1800   # only scan tokens older than 30 min (2 candles)
_ORPHAN_MAX = 20     # max tracked tokens


def track_candle_tokens(up_token, dn_token):
    """Remember tokens so orphan scanner can check them."""
    now = time.time()
    for t, label in [(up_token, "UP"), (dn_token, "DN")]:
        _orphan_tokens[t] = (label, now)
    # Evict oldest if too many
    if len(_orphan_tokens) > _ORPHAN_MAX:
        by_age = sorted(_orphan_tokens.items(), key=lambda x: x[1][1])
        for token_id, _ in by_age[:len(_orphan_tokens) - _ORPHAN_MAX]:
            del _orphan_tokens[token_id]


def close_orphans(client):
    """Check tracked tokens for stuck positions from old candles.

    With fair-value MM we hold through resolution, so skip recent tokens.
    Only act on tokens older than 30 minutes (2+ candles ago).
    """
    if not _orphan_tokens:
        return
    now = time.time()
    for t, (label, added) in list(_orphan_tokens.items()):
        if now - added < _ORPHAN_AGE:
            continue  # too recent, skip
        try:
            bal = get_token_balance(client, t)
            if bal >= 0.5:
                book = get_book(client, t)
                if book and book.get("bids"):
                    best_bid = float(book["bids"][0]["price"])
                    if best_bid < 0.05:
                        continue  # worthless, ignore
                    if best_bid > 0.90:
                        continue  # winning, wait for auto-redeem
                print(f"[ORPHAN] {label} {bal:.1f}sh stuck, closing...")
                close_position(client, t, f"ORPHAN-{label}")
        except Exception:
            continue


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    kill_other_instances()

    print(f"[MM] === BTC 15-min Fair-Value Market Maker ===")
    print(f"[MM] UTC: {utcnow()}")
    print(f"[MM] size={ORDER_SIZE}  poll={POLL_SEC}s")

    client = get_client()
    bal = _retry(lambda: get_usdc_balance(client), retries=3, delay=2, tag="MM")
    print(f"[MM] Balance: ${bal:.2f}")
    send(f"BTC 15m fair-value MM started. Balance: ${bal:.2f}")

    loop_iter = 0
    while mm_config.running:
        loop_iter += 1
        print(f"\n[MM] --- main loop #{loop_iter} @ {utcnow().strftime('%H:%M:%S')} UTC ---")

        # Check for orphaned positions from old candles
        try:
            close_orphans(client)
        except Exception as e:
            print(f"[MM] orphan scan error: {e}")

        # ── Find next candle ──
        candle = find_next_candle()
        if not candle:
            print("[MM] no candle found, retry in 30s")
            time.sleep(30)
            continue

        now = utcnow()
        secs = (candle["candle_start"] - now).total_seconds()

        if secs <= 0:
            print(f"[MM] {candle['slug']} already started, skipping")
            traded_candles.add(int(candle["candle_start"].timestamp()))
            time.sleep(2)
            continue

        # ── Wait for current candle confirmation (95%+ and <5 min left) ──
        current_color = None
        try:
            current_color = get_current_candle_color(client)
        except Exception as e:
            print(f"[MM] current candle check error: {e}")

        if current_color is None:
            print(f"[MM] Current candle not confirmed, waiting... ({secs:.0f}s to start)")
            time.sleep(10)
            continue

        # ── Get streak (with confirmed current candle) ──
        streak_count, streak_color = get_streak(current_candle_color=current_color)
        print(f"[MM] Streak: {streak_count}x {streak_color} (current={current_color})")

        # ── Fetch Binance RSI ──
        rsi = None
        try:
            rsi = fetch_binance_rsi()
        except Exception as e:
            print(f"[MM] RSI fetch error: {e}")

        # ── Compute fair value ──
        fair_up, fair_dn = compute_fair_value(streak_count, streak_color, rsi)
        print(f"[MM] Fair value: UP={fair_up:.3f}  DN={fair_dn:.3f}  RSI={rsi}")

        # ── Wait until entry time ──
        enter_before = ENTER_NORMAL
        if secs > enter_before:
            wait = min(secs - enter_before, 600)
            print(f"[MM] next: {candle['question']} in {secs:.0f}s, "
                  f"fair UP={fair_up:.3f} DN={fair_dn:.3f}, waiting {wait:.0f}s")
            while wait > 0 and mm_config.running:
                time.sleep(min(wait, 30))
                wait -= 30
            continue

        # ── Check balance ──
        try:
            bal = _retry(lambda: get_usdc_balance(client), retries=2, delay=2, tag="MM")
        except Exception:
            bal = 0
        if bal < MIN_BALANCE:
            print(f"[MM] Balance ${bal:.2f} < ${MIN_BALANCE}, waiting...")
            time.sleep(30)
            continue

        # ── Run the candle ──
        run_candle(candle, fair_up, fair_dn, streak_count, streak_color, rsi)
        time.sleep(3)

    print("[MM] shutdown")
    send("BTC 15m fair-value MM stopped.")


if __name__ == "__main__":
    main()
