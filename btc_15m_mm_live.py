#!/usr/bin/env python3
"""
BTC 15-min Candle Fair-Value MM — LIVE TRADING (maker-only).

Same fair-value logic as the paper bot, but places real GTC limit BUY
orders on Polymarket. Designed to be a strict maker:

  • places at target price (= fair_value - 1 tick)
  • only places if target < best_ask  → never crosses the spread
  • checks fills via order_filled() + token balance fallback
  • cancels unfilled orders right before the candle starts
  • does NOT place sell orders — user resolves positions manually
  • winning shares auto-redeem after settlement

Trade log: logs/btc_15m_mm_live.jsonl
"""

import json
import os
import signal
import subprocess
import time

from py_clob_client_v2 import Side
BUY = Side.BUY

from mm_config import (
    POLL_SEC, TICK, ENTER_NORMAL, MIN_SIZE,
    utcnow, cancel_all_open_orders,
)
from mm_discovery import find_next_candle, get_streak
from mm_clob import (
    get_book, place_order, cancel_ord, order_filled,
    get_token_balance,
)
from mm_fair_value import (
    compute_fair_value, fetch_binance_rsi, get_current_candle_color,
    STREAK_PROB_UP, _rsi_adjustment,
)
from mm_redeem import init_relayer, redeem_all, wrap_pending_deposit
from trader.client import get_client, get_usdc_balance
from trader.notify import send

import mm_config

# ─── Config ─────────────────────────────────────────────────────────────────
PRICE_IMPROVE = 0.00  # no price improvement
TRADE_LOG = "logs/btc_15m_mm_live.jsonl"


# ─── Logging ────────────────────────────────────────────────────────────────

def _log(entry):
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ─── Single-instance guard ──────────────────────────────────────────────────

def _kill_other_live_instances():
    """Kill other btc_15m_mm_live.py processes and cancel any orphan orders."""
    my_pid = os.getpid()
    found = False
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "btc_15m_mm_live.py"], text=True
        ).strip()
        for line in out.splitlines():
            pid = int(line)
            if pid != my_pid:
                print(f"[LIVE] Killing old instance PID {pid}")
                os.kill(pid, signal.SIGKILL)
                found = True
    except subprocess.CalledProcessError:
        pass
    if found:
        time.sleep(1)
    # Always clean stale orders on startup
    cancel_all_open_orders()


# ─── Telegram rationale ─────────────────────────────────────────────────────

def _send_rationale(candle, fair_up, fair_dn, streak_count, streak_color, rsi, balance, order_size):
    max_up = round(fair_up - TICK - PRICE_IMPROVE, 2)
    max_dn = round(fair_dn - TICK - PRICE_IMPROVE, 2)

    if streak_count > 0 and streak_color not in (None, "NONE"):
        key = (min(streak_count, 6), streak_color)
        base = STREAK_PROB_UP.get(key, 0.50)
    else:
        base = 0.50
    rsi_adj = _rsi_adjustment(rsi)

    lines = [f"[LIVE] {candle['question']}"]
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
    lines.append(f"Target buy: UP@{max_up:.2f} DN@{max_dn:.2f}")
    lines.append(f"USDC: ${balance:.2f} | Size: {order_size}")
    send("\n".join(lines))


# ─── Live candle execution ──────────────────────────────────────────────────

def run_candle_live(client, candle, fair_up, fair_dn, streak_count, streak_color, rsi):
    """Place maker-only limit buys on UP and DN tokens until candle starts."""
    up_token = candle["up_token"]
    dn_token = candle["dn_token"]
    start = candle["candle_start"]
    slug = candle["slug"]

    max_up = round(fair_up - TICK - PRICE_IMPROVE, 2)
    max_dn = round(fair_dn - TICK - PRICE_IMPROVE, 2)

    balance = get_usdc_balance(client)
    
    # Dynamic order size: base 5 for $100, +1 for every additional $20
    order_size = float(max(5.0, 5.0 + (max(0.0, balance - 100.0) // 20.0)))

    print(f"\n[LIVE] {'='*55}")
    print(f"[LIVE] {candle['question']}")
    print(f"[LIVE] streak={streak_count}x{streak_color}  rsi={rsi}")
    print(f"[LIVE] fair: UP={fair_up:.3f} DN={fair_dn:.3f}")
    print(f"[LIVE] target: UP@{max_up:.2f} DN@{max_dn:.2f} (improve={PRICE_IMPROVE})")
    print(f"[LIVE] USDC: ${balance:.2f} | Size: {order_size}")
    
    _send_rationale(candle, fair_up, fair_dn, streak_count, streak_color, rsi, balance, order_size)

    legs = [
        {"label": "UP", "token": up_token, "target": max_up,
         "oid": None, "filled": False, "fill_px": None, "ever_placed": False,
         "place_px": None},
        {"label": "DN", "token": dn_token, "target": max_dn,
         "oid": None, "filled": False, "fill_px": None, "ever_placed": False,
         "place_px": None},
    ]

    def try_place(leg):
        """Place a maker-only GTC limit BUY at min(target, best_ask - tick)."""
        if leg["filled"] or leg["oid"]:
            return
        target = leg["target"]
        if target <= 0 or target >= 1.0:
            return

        book = get_book(client, leg["token"])
        if not book or not book.get("asks"):
            return
        best_ask = float(book["asks"][0]["price"])

        max_maker_px = round(best_ask - TICK, 2)
        place_px = min(target, max_maker_px)
        if place_px <= 0 or place_px >= 1.0:
            return

        cost = place_px * order_size
        bal = get_usdc_balance(client)
        if cost > bal:
            print(f"[LIVE] {leg['label']} skip — cost ${cost:.2f} > balance ${bal:.2f}")
            return

        oid = place_order(client, leg["token"], place_px, order_size, BUY, leg["label"])
        if oid:
            leg["oid"] = oid
            leg["ever_placed"] = True
            leg["place_px"] = place_px
            improved = " (improved)" if place_px < target else ""
            print(f"[LIVE] {leg['label']} placed @ {place_px:.2f}  "
                  f"(target={target:.2f}, best_ask={best_ask:.2f}){improved}")
            _log({
                "timestamp": str(utcnow()),
                "action": "PLACE",
                "slug": slug,
                "side": leg["label"],
                "price": place_px,
                "target": target,
                "size": order_size,
                "best_ask": best_ask,
                "oid": oid,
                "streak": f"{streak_count}x{streak_color}",
                "rsi": rsi,
            })

    def check_fill(leg, tick):
        """Check if a placed order has been filled."""
        if leg["filled"] or not leg["oid"]:
            return
        full, _ = order_filled(client, leg["oid"])
        if full:
            for attempt in range(4):
                bal = get_token_balance(client, leg["token"])
                if bal >= order_size - 0.5:
                    break
                time.sleep(2)
            if bal < order_size - 0.5:
                print(f"[LIVE] {leg['label']} MATCHED but no tokens (bal={bal:.2f}) — phantom fill")
                return
            leg["filled"] = True
            leg["fill_px"] = leg["place_px"] or leg["target"]
            print(f"[LIVE] {leg['label']} FILLED @ {leg['fill_px']:.2f}")
            _log({
                "timestamp": str(utcnow()),
                "action": "BUY",
                "slug": slug,
                "side": leg["label"],
                "price": leg["fill_px"],
                "target": leg["target"],
                "size": order_size,
                "oid": leg["oid"],
                "streak": f"{streak_count}x{streak_color}",
                "rsi": rsi,
            })

    tick = 0
    while mm_config.running:
        tick += 1
        now = utcnow()
        to_start = (start - now).total_seconds()
        if to_start <= 0:
            break

        for leg in legs:
            try_place(leg)
        for leg in legs:
            check_fill(leg, tick)

        if all(leg["filled"] for leg in legs):
            break

        if tick % 10 == 0:
            parts = []
            for leg in legs:
                if leg["filled"]:
                    parts.append(f"{leg['label']}:FILLED@{leg['fill_px']:.2f}")
                elif leg["oid"]:
                    parts.append(f"{leg['label']}:open@{leg['place_px']:.2f}")
                else:
                    parts.append(f"{leg['label']}:waiting(target={leg['target']:.2f})")
            print(f"[LIVE] {' | '.join(parts)} | {to_start:.0f}s to start")

        time.sleep(POLL_SEC)

    # ── Candle starts: final fill check + cancel unfilled ──
    for leg in legs:
        check_fill(leg, tick + 1)

    for leg in legs:
        if leg["oid"] and not leg["filled"]:
            cancel_ord(client, leg["oid"], leg["label"])
            _log({
                "timestamp": str(utcnow()),
                "action": "CANCEL",
                "slug": slug,
                "side": leg["label"],
                "price": leg["place_px"],
                "target": leg["target"],
                "oid": leg["oid"],
            })

    # ── Per-leg result entries (one per leg, every candle, for fill-rate analysis) ──
    for leg in legs:
        if leg["filled"]:
            status = "FILLED"
        elif leg["ever_placed"]:
            status = "PLACED_UNFILLED"
        else:
            status = "NEVER_PLACED"
        _log({
            "timestamp": str(utcnow()),
            "action": "RESULT",
            "slug": slug,
            "side": leg["label"],
            "status": status,
            "filled": leg["filled"],
            "ever_placed": leg["ever_placed"],
            "target": leg["target"],
            "place_px": leg["place_px"],
            "fill_px": leg["fill_px"],
            "streak": f"{streak_count}x{streak_color}",
            "rsi": rsi,
        })

    fills = [f"{l['label']}@{l['fill_px']:.2f}" for l in legs if l["filled"]]
    summary = " + ".join(fills) if fills else "no fills"
    print(f"[LIVE] candle done: {summary}")
    if fills:
        send(f"[LIVE] {candle['question']}: {summary}")


# ─── Main loop ──────────────────────────────────────────────────────────────

def main():
    print(f"[LIVE] === BTC 15-min Fair-Value MM — LIVE TRADING ===")
    print(f"[LIVE] UTC: {utcnow()}")
    print(f"[LIVE] size=dynamic (min 5, +1 per $20 > $100)  poll={POLL_SEC}s  maker-only  improve={PRICE_IMPROVE}")
    print(f"[LIVE] No sell orders will be placed — user resolves manually")

    _kill_other_live_instances()

    client = get_client()
    bal = get_usdc_balance(client)
    print(f"[LIVE] USDC balance: ${bal:.2f}")
    send(f"[LIVE] MM started. USDC: ${bal:.2f}")

    # Gas-free CTF redemption via Polymarket V2 relayer
    REDEEM_ENABLED = True
    relay_client = init_relayer() if REDEEM_ENABLED else None
    last_redeem_ts = 0
    REDEEM_INTERVAL = 1800  # 30 min between scans

    def _maybe_redeem():
        nonlocal last_redeem_ts
        if relay_client is None or time.time() - last_redeem_ts <= REDEEM_INTERVAL:
            return
        try:
            n = redeem_all(relay_client)
            if n:
                new_bal = get_usdc_balance(client)
                send(f"[LIVE] Redeemed {n} markets. USDC: ${new_bal:.2f}")
        except Exception as e:
            print(f"[LIVE] redeem sweep error: {e}")
        # After redemption, wrap any USDC.e in the proxy → pUSD (auto "confirm deposit")
        try:
            wrapped = wrap_pending_deposit(relay_client)
            if wrapped > 0:
                send(f"[LIVE] Wrapped ${wrapped:.2f} USDC.e → pUSD")
        except Exception as e:
            print(f"[LIVE] wrap sweep error: {e}")
        last_redeem_ts = time.time()

    while mm_config.running:
        _maybe_redeem()

        candle = find_next_candle()
        if not candle:
            print("[LIVE] no candle found, retry in 30s")
            time.sleep(30)
            continue

        candle_ts = int(candle["candle_start"].timestamp())
        if candle_ts in mm_config.traded_candles:
            time.sleep(5)
            continue

        now = utcnow()
        secs = (candle["candle_start"] - now).total_seconds()
        if secs <= 0:
            mm_config.traded_candles.add(candle_ts)
            time.sleep(2)
            continue

        if secs > ENTER_NORMAL:
            time.sleep(min(secs - ENTER_NORMAL, 30))
            continue

        # Wait for current candle to be effectively resolved (≥95% bid, <5 min left)
        try:
            current_color = get_current_candle_color(client)
        except Exception as e:
            print(f"[LIVE] current candle check error: {e}")
            current_color = None

        if current_color is None:
            print(f"[LIVE] Current candle not confirmed ({secs:.0f}s to start)")
            time.sleep(10)
            continue

        # Streak + RSI + fair value
        streak_count, streak_color = get_streak(current_candle_color=current_color)

        # Skip candles where we have no statistically-valid streak entry (< 900 samples)
        if streak_count >= 1 and (streak_count, streak_color) not in STREAK_PROB_UP:
            print(f"[LIVE] No signal for {streak_count}x{streak_color} (not in table) — skip")
            send(f"[LIVE] {candle['question']}\nStreak: {streak_count}x{streak_color} — no reliable fair value (<900 samples in backtest). Skipping.")
            mm_config.traded_candles.add(candle_ts)
            continue

        rsi = None
        try:
            rsi = fetch_binance_rsi()
        except Exception:
            pass
        fair_up, fair_dn = compute_fair_value(streak_count, streak_color, rsi)

        run_candle_live(client, candle, fair_up, fair_dn, streak_count, streak_color, rsi)
        mm_config.traded_candles.add(candle_ts)

        time.sleep(3)

    print("[LIVE] shutdown")
    bal = get_usdc_balance(client)
    send(f"[LIVE] MM stopped. USDC: ${bal:.2f}")


if __name__ == "__main__":
    main()
