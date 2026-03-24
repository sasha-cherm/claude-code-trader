#!/usr/bin/env python3
"""
Near-resolution monitor for March 24, 2026 — 4 NBA games.

Games (UTC):
- Kings vs Hornets: end 23:00 (tipoff ~20:30)
- Pelicans vs Knicks: end 23:30 (tipoff ~21:00)
- Magic vs Cavaliers: end 00:00 Mar 25 (tipoff ~21:30)
- Nuggets vs Suns: end 03:00 Mar 25 (tipoff ~00:30)

Near-res windows: 22:30-03:00 UTC.
Launch at ~20:00 UTC to snapshot pre-game prices.

Validated params from March 22: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # Kings vs Hornets — Hornets heavy favorite (0.92)
    {"name": "Kings", "token_id": "51791135525463219080507992997939887417481513252403101801122491757061552212488",
     "end_date": "2026-03-24T23:00:00Z", "pre_game_price": 0.0,
     "question": "Kings vs. Hornets"},
    {"name": "Hornets", "token_id": "97747274531683402808496972324286989903538719810376477370291929261366387114981",
     "end_date": "2026-03-24T23:00:00Z", "pre_game_price": 0.0,
     "question": "Kings vs. Hornets"},

    # Pelicans vs Knicks — Knicks favorite (0.77)
    {"name": "Pelicans", "token_id": "90779995750970465461958014698240804849976323944055587747499677115112890408794",
     "end_date": "2026-03-24T23:30:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Knicks"},
    {"name": "Knicks", "token_id": "56684785511292775056526874919523573033709028315047249779514026874801501110177",
     "end_date": "2026-03-24T23:30:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Knicks"},

    # Magic vs Cavaliers — Cavs favorite (0.80)
    {"name": "Magic", "token_id": "100251494888115733311088324123253034667658118564471897630404325526546624706267",
     "end_date": "2026-03-25T00:00:00Z", "pre_game_price": 0.0,
     "question": "Magic vs. Cavaliers"},
    {"name": "Cavaliers", "token_id": "82162335245384915830214727777598327360549892486286572930820029431907406804211",
     "end_date": "2026-03-25T00:00:00Z", "pre_game_price": 0.0,
     "question": "Magic vs. Cavaliers"},

    # Nuggets vs Suns — Nuggets favorite (0.66)
    {"name": "Nuggets", "token_id": "23233394988453138676453756568931964683203148302915027263468721213424953033444",
     "end_date": "2026-03-25T03:00:00Z", "pre_game_price": 0.0,
     "question": "Nuggets vs. Suns"},
    {"name": "Suns", "token_id": "96641301590558848799981015724831293565424869668527634336704268465596562110754",
     "end_date": "2026-03-25T03:00:00Z", "pre_game_price": 0.0,
     "question": "Nuggets vs. Suns"},
]

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 20.0
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.28
BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        if w["pre_game_price"] == 0.0:
            try:
                info = client.get_price(w["token_id"], "buy")
                p = float(info.get("price", 0))
                if p > 0.01:
                    w["pre_game_price"] = p
                    print(f"  Pre-game {w['name']}: {p:.3f}")
            except Exception as e:
                print(f"  Pre-game {w['name']}: ERROR {e}")


def check_and_buy(client, watch_list):
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)
    print(f"\n--- Check #{check_and_buy.count} at {now.strftime('%H:%M:%S')} UTC ---")
    print(f"  Balance: ${balance:.2f}")
    check_and_buy.count += 1

    for w in watch_list:
        if not w["token_id"] or w["token_id"] in BOUGHT:
            continue
        try:
            buy_info = client.get_price(w["token_id"], "buy")
            sell_info = client.get_price(w["token_id"], "sell")
            buy_price = float(buy_info.get("price", 0))
            sell_price = float(sell_info.get("price", 0))

            if w["pre_game_price"] == 0.0:
                if buy_price > 0.01:
                    w["pre_game_price"] = buy_price
                continue

            jump = buy_price - w["pre_game_price"]
            spread = buy_price - sell_price

            # Time-based filter
            end_str = w.get("end_date", "")
            if end_str:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                mins_left = (end_dt - now).total_seconds() / 60
            else:
                mins_left = 999

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                abs(spread) < MAX_SPREAD and
                mins_left <= MAX_MINS_TO_END and
                mins_left > 0 and
                balance >= MIN_SPEND
            )

            if abs(jump) > 0.05 or buy_price >= 0.85:
                status = "***BUY***" if trigger else ""
                mins_str = f" mins={mins_left:.0f}" if end_str else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f}{mins_str} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-nba-mar24-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.08, 0.99),
                        "edge": jump,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_left / 1440,
                        "opened_at": str(now),
                        "research_note": f"NBA Mar24 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"NBA MAR24 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']}: {err}")


check_and_buy.count = 0


def main():
    print(f"=== NBA Mar 24 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    # Snapshot pre-game prices
    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor loop — run until 04:00 UTC Mar 25
    end_time = datetime(2026, 3, 25, 4, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
