#!/usr/bin/env python3
"""
BTC 15-min Candle Spread Scalper

Strategy:
  1. Pre-candle: Place BUY limit in spread on stronger side (by bid depth)
  2. When BUY fills: Place SELL limit at buy_price + 1 tick
  3. At candle start: if SELL not filled, cancel + market sell to close
  4. Repeat BUY→SELL rounds if time remains

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
    ORDER_SIZE, POLL_SEC, MIN_SIZE, TICK, MIN_BALANCE,
    SELL_DEADLINE, ENTER_NORMAL, ENTER_STREAK,
    running, traded_candles, utcnow, log_trade, _retry, kill_other_instances,
)
from mm_discovery import find_next_candle, get_streak
from mm_clob import (
    get_book, pick_side, get_token_balance, place_order,
    cancel_ord, order_filled, market_sell,
    cancel_all_token_orders, wait_for_settlement, close_position,
    find_support_price,
)

# Re-import running as module-level ref (mutated via mm_config signals)
import mm_config


# ─── Main loop for one candle ────────────────────────────────────────────────

def run_candle(candle):
    client = get_client()
    up_token = candle["up_token"]
    dn_token = candle["dn_token"]
    start = candle["candle_start"]
    sell_deadline = start + timedelta(seconds=SELL_DEADLINE)

    print(f"\n[MM] {'='*50}")
    print(f"[MM] {candle['question']}")
    print(f"[MM] start={start.isoformat()}  sell_deadline=+{SELL_DEADLINE}s")

    track_candle_tokens(up_token, dn_token)
    token, side = pick_side(client, up_token, dn_token)
    print(f"[MM] Trading {side} token={token[:20]}...")

    candle_ts = int(start.timestamp())
    traded_candles.add(candle_ts)

    try:
        bal = _retry(lambda: get_usdc_balance(client), retries=2, delay=2, tag="MM")
    except Exception:
        bal = 0
    print(f"[MM] Balance: ${bal:.2f}")

    result = {"candle": candle["question"], "start": str(start), "events": []}
    rounds = 0

    while mm_config.running:
        # ── Reset state for new round ──
        buy_oid = None
        buy_px = None
        buy_fill_px = None
        sell_oid = None
        sell_px = None
        sell_placed_size = 0
        rounds += 1

        # ────────────────────────────────────────────────────────────────
        # STATE CHECK: do we already have tokens? (orphaned from phantom sell)
        # ────────────────────────────────────────────────────────────────
        up_bal = get_token_balance(client, up_token)
        dn_bal = get_token_balance(client, dn_token)
        have_position = False
        token_bal = 0.0

        if up_bal >= 1.0 or dn_bal >= 1.0:
            # Orphaned position — skip BUY, go straight to SELL
            if up_bal >= dn_bal:
                token, side = up_token, "UP"
                token_bal = up_bal
            else:
                token, side = dn_token, "DN"
                token_bal = dn_bal
            # Cancel any existing orders for this token before we place ours
            cancel_all_token_orders(client, token, "ORPHAN")
            time.sleep(1)
            # Estimate buy price from orderbook midpoint
            book = get_book(client, token)
            if book and book.get("bids") and book.get("asks"):
                bb = float(book["bids"][0]["price"])
                ba = float(book["asks"][0]["price"])
                buy_fill_px = round((bb + ba) / 2, 2)
            else:
                buy_fill_px = 0.50
            have_position = True
            print(f"[MM] --- Round {rounds} ({side}) EXISTING POSITION: {token_bal:.2f}sh, est buy@{buy_fill_px:.2f} ---")
            result["events"].append({"a": "EXISTING_POS", "side": side, "bal": token_bal})
        else:
            # No position — need to BUY first
            if bal < MIN_BALANCE and rounds == 1:
                print(f"[MM] Balance too low, skipping.")
                log_trade({"candle": candle["question"], "start": str(start),
                            "events": [{"a": "SKIP_LOW_BAL", "bal": bal}]})
                return

            if rounds > 1:
                token, side = pick_side(client, up_token, dn_token)
            print(f"[MM] --- Round {rounds} ({side}) ---")

            # ────────────────────────────────────────────────────────────
            # PHASE 1: BUY (STATE-DRIVEN — checks balance each tick)
            # ────────────────────────────────────────────────────────────
            bought = False
            buy_tick = 0
            while mm_config.running and not bought:
                buy_tick += 1
                now = utcnow()
                to_start = (start - now).total_seconds()

                # ── Check ACTUAL on-chain balance first ──
                token_bal = get_token_balance(client, token)
                if token_bal >= 1.0:
                    # Cancel remaining BUY order (may be partial fill)
                    if buy_oid:
                        cancel_ord(client, buy_oid, "BUY")
                        buy_oid = None
                    buy_fill_px = buy_px or 0.50
                    print(f"[MM] BUY confirmed by balance: {token_bal:.2f}sh (price est {buy_fill_px:.2f})")
                    bought = True
                    break

                # Also check the other side
                other_token = dn_token if token == up_token else up_token
                other_bal = get_token_balance(client, other_token)
                if other_bal >= 1.0:
                    # Cancel remaining BUY order on current side
                    if buy_oid:
                        cancel_ord(client, buy_oid, "BUY")
                        buy_oid = None
                    token = other_token
                    side = "DN" if token == dn_token else "UP"
                    token_bal = other_bal
                    buy_fill_px = buy_px or 0.50
                    print(f"[MM] BUY landed on {side}: {token_bal:.2f}sh")
                    bought = True
                    break

                # Candle started — cancel and check one last time
                if to_start <= 0:
                    if buy_oid:
                        cancel_ord(client, buy_oid, "BUY")
                        buy_oid = None
                    time.sleep(1)
                    token_bal = get_token_balance(client, token)
                    if token_bal >= 1.0:
                        buy_fill_px = buy_px or 0.50
                        print(f"[MM] BUY filled at deadline @ {buy_fill_px:.2f}")
                        bought = True
                        break
                    print("[MM] Candle started, no position. Done.")
                    result["events"].append({"a": "NO_FILL"})
                    break

                # ── Check order status ──
                if buy_oid:
                    full, _ = order_filled(client, buy_oid)
                    if full:
                        buy_fill_px = buy_px
                        print(f"[MM] BUY reported filled @ {buy_fill_px:.2f}, waiting for settlement...")
                        settle_dl = utcnow() + timedelta(seconds=30)
                        while mm_config.running:
                            token_bal = get_token_balance(client, token)
                            if token_bal >= 1.0:
                                print(f"[MM] Settlement confirmed: {token_bal:.2f}sh")
                                bought = True
                                break
                            if utcnow() > settle_dl:
                                print(f"[MM] Settlement timeout, bal={token_bal:.2f}")
                                break
                            time.sleep(2)
                        if bought:
                            break
                        print(f"[MM] Phantom BUY — no tokens after 30s. Re-placing...")
                        result["events"].append({"a": "PHANTOM_BUY", "bal": token_bal})
                        buy_oid = None

                # Re-evaluate side every ~10s (not every tick)
                if buy_tick % 10 == 1 or buy_oid is None:
                    new_token, new_side = pick_side(client, up_token, dn_token, current_side=side)
                else:
                    new_token, new_side = token, side
                need_switch = new_token != token

                book = get_book(client, new_token)
                if not book or not book.get("bids") or not book.get("asks"):
                    time.sleep(POLL_SEC)
                    continue
                bb = float(book["bids"][0]["price"])
                ba = float(book["asks"][0]["price"])
                spread = round(ba - bb, 2)

                # Place behind the fattest bid wall (support level)
                support = find_support_price(book)
                tgt = min(support or round(bb + TICK, 2), round(ba - TICK, 2))

                if buy_oid is None:
                    token, side = new_token, new_side
                    buy_oid = place_order(client, token, tgt, ORDER_SIZE, BUY, "BUY")
                    buy_px = tgt
                elif need_switch or abs(tgt - buy_px) >= TICK:
                    if not cancel_ord(client, buy_oid, "BUY"):
                        time.sleep(POLL_SEC)
                        continue
                    token_bal = get_token_balance(client, token)
                    if token_bal >= 1.0:
                        buy_fill_px = buy_px
                        print(f"[MM] BUY filled during re-quote @ {buy_fill_px:.2f}")
                        bought = True
                        break
                    token, side = new_token, new_side
                    buy_oid = place_order(client, token, tgt, ORDER_SIZE, BUY, "BUY")
                    buy_px = tgt

                if int(to_start) % 10 < POLL_SEC + 0.5:
                    print(f"[MM] bb={bb:.2f} ba={ba:.2f} sp={spread:.2f} support={support or '-'} | "
                          f"BUY@{buy_px or '-'} | bal={token_bal:.2f} | {to_start:.0f}s to start")

                time.sleep(POLL_SEC)

            if not bought or not mm_config.running:
                break

            # Safety: cancel ALL orders for this token before entering SELL
            # Retry aggressively — if cancel fails, SELL will be blocked
            for _attempt in range(5):
                try:
                    cancel_all_token_orders(client, token, "PRE-SELL")
                    break
                except Exception as e:
                    print(f"[PRE-SELL] cancel retry {_attempt+1}: {e}")
                    time.sleep(2)
            have_position = True

        # ────────────────────────────────────────────────────────────────
        # PHASE 2b: SELL (STATE-DRIVEN — checks actual balance each tick)
        # ────────────────────────────────────────────────────────────────
        if not have_position or not mm_config.running:
            break

        sold = False
        pending_sell = False
        averaged = False
        avg_sell_floor = None   # set after averaging — minimum sell price
        while mm_config.running and not sold:
            now = utcnow()
            to_sell_dl = (sell_deadline - now).total_seconds()

            # ── Check ACTUAL on-chain position ──
            token_bal = get_token_balance(client, token)
            actual_size = math.floor(token_bal * 100) / 100

            # Position is gone → sell landed
            if token_bal < 1.0:
                print(f"[MM] Position closed (bal={token_bal:.2f})")
                if sell_px and buy_fill_px:
                    profit = round((sell_px - buy_fill_px) * sell_placed_size, 4)
                    print(f"[MM] Profit: ${profit}")
                    result["events"].append({"a": "SELL_FILLED",
                        "buy": buy_fill_px, "sell": sell_px, "profit": profit})
                else:
                    result["events"].append({"a": "POS_CLOSED", "buy": buy_fill_px})
                sold = True
                break

            # If sell is pending settlement, just wait
            if pending_sell:
                print(f"[MM] Sell pending settlement... bal={token_bal:.2f}")
                time.sleep(3)
                continue

            # DEADLINE: cancel all orders + market sell
            if to_sell_dl <= 0:
                print(f"[MM] SELL DEADLINE (bought @ {buy_fill_px:.2f})")
                cancel_all_token_orders(client, token, "DEADLINE")
                if sell_oid:
                    cancel_ord(client, sell_oid, "SELL")
                    sell_oid = None
                time.sleep(3)
                token_bal = get_token_balance(client, token)
                if token_bal < 1.0:
                    print(f"[MM] Position closed after cancel")
                    sold = True
                    break
                actual_size = math.floor(token_bal * 100) / 100
                if actual_size < 0.01:
                    break
                print(f"[MM] Market selling {actual_size:.2f}sh")
                resp = market_sell(client, token, actual_size, "CLOSE")
                if resp and resp.get("too_small"):
                    print(f"[MM] Position too small to sell via FOK, will resolve naturally")
                    result["events"].append({"a": "TOO_SMALL", "buy": buy_fill_px, "bal": token_bal})
                    break
                if resp and resp.get("pending_settlement"):
                    pending_sell = True
                    continue
                result["events"].append({"a": "MKT_SELL", "buy": buy_fill_px,
                    "sz": actual_size, "resp": str(resp)})
                if resp and resp.get("success"):
                    pending_sell = True
                    continue
                break

            # ── Check sell order state ──
            if sell_oid:
                filled, filled_sz = order_filled(client, sell_oid)
                if filled:
                    print(f"[MM] SELL matched, waiting for settlement... bal={token_bal:.2f}")
                    pending_sell = True
                    continue

                # Log partial fills but keep the order alive
                if filled_sz > 0:
                    remaining = sell_placed_size - filled_sz
                    if int(abs(to_sell_dl)) % 10 < POLL_SEC + 0.5:
                        print(f"[MM] Partial: {filled_sz:.2f}/{sell_placed_size:.2f} sold, "
                              f"{remaining:.2f} remaining on order")

            book = get_book(client, token)
            if not book or not book.get("bids") or not book.get("asks"):
                time.sleep(POLL_SEC)
                continue

            bb = float(book["bids"][0]["price"])
            ba = float(book["asks"][0]["price"])

            # ────────────────────────────────────────────────────────────
            # AVERAGING: if market drops 3+ cents, buy more to lower avg
            # ────────────────────────────────────────────────────────────
            if not averaged and bb <= buy_fill_px - 0.03 and to_sell_dl > 30:
                try:
                    usdc = _retry(lambda: get_usdc_balance(client), retries=2, delay=1, tag="MM")
                except Exception:
                    usdc = 0
                avg_cost = round(bb * ORDER_SIZE, 2)
                if usdc >= avg_cost + 0.5:
                    drop = round((buy_fill_px - bb) * 100)
                    print(f"[MM] AVERAGING: market dropped {drop}¢ "
                          f"(bought@{buy_fill_px:.2f}, bb={bb:.2f})")
                    # Cancel current SELL — must not have BUY+SELL at same time
                    if sell_oid:
                        cancel_ord(client, sell_oid, "AVG")
                        sell_oid = None
                    # Place averaging BUY at the bid
                    avg_buy_px = bb
                    avg_oid = place_order(client, token, avg_buy_px, ORDER_SIZE, BUY, "AVG-BUY")
                    if avg_oid:
                        avg_dl = utcnow() + timedelta(seconds=45)
                        avg_filled = False
                        orig_size = actual_size
                        while mm_config.running and utcnow() < avg_dl:
                            nb = get_token_balance(client, token)
                            if nb >= orig_size + ORDER_SIZE - 1.0:
                                avg_filled = True
                                token_bal = nb
                                actual_size = math.floor(nb * 100) / 100
                                break
                            full, _ = order_filled(client, avg_oid)
                            if full:
                                time.sleep(3)
                                continue
                            time.sleep(POLL_SEC)
                        if not avg_filled:
                            cancel_ord(client, avg_oid, "AVG-BUY")
                            # Check if partial fill landed
                            time.sleep(1)
                            nb = get_token_balance(client, token)
                            if nb > orig_size + 0.5:
                                new_shares = nb - orig_size
                                old_cost = buy_fill_px * orig_size
                                new_cost = avg_buy_px * new_shares
                                buy_fill_px = round((old_cost + new_cost) / nb, 4)
                                actual_size = math.floor(nb * 100) / 100
                                token_bal = nb
                                avg_sell_floor = round(math.ceil(buy_fill_px * 100) / 100, 2)
                                print(f"[MM] PARTIAL AVG: +{new_shares:.1f}sh@{avg_buy_px:.2f}, "
                                      f"avg={buy_fill_px:.4f}, sell floor={avg_sell_floor:.2f}")
                                result["events"].append({"a": "AVG_DOWN",
                                    "avg_px": buy_fill_px, "new_size": actual_size,
                                    "avg_buy": avg_buy_px})
                            else:
                                print(f"[MM] AVG buy didn't fill, continuing normal sell")
                        else:
                            new_shares = actual_size - orig_size
                            old_cost = buy_fill_px * orig_size
                            new_cost = avg_buy_px * new_shares
                            buy_fill_px = round((old_cost + new_cost) / actual_size, 4)
                            avg_sell_floor = round(math.ceil(buy_fill_px * 100) / 100, 2)
                            print(f"[MM] AVERAGED: {actual_size:.0f}sh, "
                                  f"avg@{buy_fill_px:.4f}, sell@{avg_sell_floor:.2f}")
                            result["events"].append({"a": "AVG_DOWN",
                                "avg_px": buy_fill_px, "new_size": actual_size,
                                "avg_buy": avg_buy_px})
                    averaged = True
                    continue  # re-enter loop to place new SELL
                else:
                    print(f"[MM] Would average but USDC ${usdc:.2f} too low "
                          f"(need ${avg_cost+0.5:.2f})")
                    averaged = True

            # ── Calculate sell target ──
            # Follow market: undercut ask, stay above bid
            market_tgt = round(ba - TICK, 2)
            if market_tgt <= bb:
                market_tgt = round(bb + TICK, 2)
            market_tgt = min(market_tgt, round(ba, 2))

            # Never sell below buy price via limit order
            # If averaged, use avg floor; otherwise use buy+tick
            min_sell = avg_sell_floor if avg_sell_floor is not None else round(buy_fill_px + TICK, 2)
            tgt_sell = max(market_tgt, min_sell)

            if sell_oid is None:
                if actual_size < MIN_SIZE:
                    # Partial BUY fill — FOK sell now if >= $1 value
                    fill_value = actual_size * bb
                    if fill_value >= 1.0:
                        print(f"[MM] Partial position {actual_size:.2f}sh, "
                              f"FOK selling (${fill_value:.2f})")
                        resp = market_sell(client, token, actual_size, "PARTIAL")
                        if resp and (resp.get("success") or resp.get("pending_settlement")):
                            pending_sell = True
                            continue
                    # Too small even for FOK
                    if int(abs(to_sell_dl)) % 30 < POLL_SEC + 0.5:
                        print(f"[MM] bal={actual_size:.2f} too small to sell "
                              f"(${fill_value:.2f} < $1), waiting ({to_sell_dl:.0f}s)")
                    time.sleep(POLL_SEC)
                    continue
                sell_oid = place_order(client, token, tgt_sell, actual_size, SELL, "SELL")
                if sell_oid is None:
                    # Cancel any blocking orders (active orders lock tokens)
                    print(f"[MM] SELL place failed, cancelling blocking orders...")
                    cancel_all_token_orders(client, token, "UNBLOCK")
                    time.sleep(3)
                    continue
                sell_px = tgt_sell
                sell_placed_size = actual_size
            elif abs(tgt_sell - sell_px) >= TICK:
                # Re-quote to follow market
                if not cancel_ord(client, sell_oid, "SELL"):
                    time.sleep(POLL_SEC)
                    continue
                sell_oid = place_order(client, token, tgt_sell, actual_size, SELL, "SELL")
                if sell_oid:
                    sell_px = tgt_sell
                    sell_placed_size = actual_size

            profit_est = round((sell_px - buy_fill_px) * sell_placed_size, 4) if sell_px else 0
            tag = "PROFIT" if profit_est > 0 else "LOSS"
            print(f"[MM] bb={bb:.2f} ba={ba:.2f} | SELL@{sell_px or '-'} "
                  f"bought@{buy_fill_px:.2f} {tag}:{profit_est:+.2f} | bal={token_bal:.2f} | {to_sell_dl:.1f}s left")

            time.sleep(POLL_SEC)

        # Round done — check if time for another
        if sold and (start - utcnow()).total_seconds() > 5:
            print(f"[MM] Round {rounds} done, verifying position closed...")
            if not wait_for_settlement(client, token, timeout=15, tag="ROUND"):
                pass
            if (start - utcnow()).total_seconds() <= 5:
                break
            continue
        else:
            break

    # ────────────────────────────────────────────────────────────────────
    # CLEANUP: at candle start, close any leftover positions
    # ────────────────────────────────────────────────────────────────────
    for tok_id, label in [(up_token, "UP"), (dn_token, "DN")]:
        tb = get_token_balance(client, tok_id)
        if tb >= 0.5:
            print(f"[MM] CLEANUP {label}: {tb:.2f}sh remaining")
            closed = close_position(client, tok_id, f"CLEANUP-{label}")
            if closed:
                result["events"].append({"a": f"CLEANUP_{label}", "sz": tb})
            else:
                print(f"[MM] CLEANUP {label}: failed, orphan scanner will retry")

    log_trade(result)
    return result


# ─── Orphan scanner ──────────────────────────────────────────────────────────

_orphan_tokens: list[tuple[str, str]] = []  # (token_id, label) from recent candles


def track_candle_tokens(up_token, dn_token):
    """Remember tokens so orphan scanner can check them without API calls."""
    for t, label in [(up_token, "UP"), (dn_token, "DN")]:
        if (t, label) not in _orphan_tokens:
            _orphan_tokens.append((t, label))
    # Keep only last 8 entries (4 candles × 2 tokens)
    while len(_orphan_tokens) > 8:
        _orphan_tokens.pop(0)


def close_orphans(client):
    """Fast check: scan tracked tokens for leftover positions."""
    if not _orphan_tokens:
        return
    for t, label in _orphan_tokens:
        try:
            bal = get_token_balance(client, t)
            if bal >= 0.5:
                print(f"[ORPHAN] Found {label} {bal:.2f}sh, closing...")
                close_position(client, t, f"ORPHAN-{label}")
        except Exception:
            continue


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    kill_other_instances()

    print(f"[MM] === BTC 15-min Spread Scalper ===")
    print(f"[MM] UTC: {utcnow()}")
    print(f"[MM] size={ORDER_SIZE}  sell_deadline=+{SELL_DEADLINE}s  poll={POLL_SEC}s")

    client = get_client()
    bal = _retry(lambda: get_usdc_balance(client), retries=3, delay=2, tag="MM")
    print(f"[MM] Balance: ${bal:.2f}")
    send(f"BTC 15m scalper started. Balance: ${bal:.2f}")

    loop_iter = 0
    while mm_config.running:
        loop_iter += 1
        print(f"[MM] --- main loop #{loop_iter} @ {utcnow().strftime('%H:%M:%S')} UTC ---")

        # Always check for orphaned positions from previous candles
        try:
            close_orphans(client)
        except Exception as e:
            print(f"[MM] orphan scan error: {e}")

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

        # Decide entry timing based on streak
        streak_count, streak_color = get_streak()
        enter_before = ENTER_STREAK if streak_count > 2 else ENTER_NORMAL
        print(f"[MM] Streak: {streak_count}x {streak_color} → enter {enter_before}s before start")

        if secs > enter_before:
            wait = min(secs - enter_before, 600)  # cap wait at 10 min
            print(f"[MM] next: {candle['question']} in {secs:.0f}s, waiting {wait:.0f}s")
            while wait > 0 and mm_config.running:
                time.sleep(min(wait, 30))
                wait -= 30
            continue

        try:
            bal = _retry(lambda: get_usdc_balance(client), retries=2, delay=2, tag="MM")
        except Exception:
            bal = 0
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
