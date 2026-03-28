#!/usr/bin/env python3
"""
Near-resolution monitor for March 29, 2026 — Soccer friendlies + Spanish 2nd.

Games (by kickoff UTC → estimated end):
- SD Eibar vs UD Las Palmas (Spanish 2nd, ~10:15 kickoff, end ~12:00) — $4K vol
- Cultural y Deportiva vs FC Andorra (Spanish 2nd, ~12:30, end ~14:15) — $11K vol
- Lithuania vs Georgia (friendly, ~11:15, end ~13:00) — $5K vol
- Real Zaragoza vs Racing Club (Spanish 2nd, ~14:45, end ~16:30) — $8K vol
- Colombia vs France (friendly, ~17:15, end ~19:00) — $61K vol ← BEST TARGET

Near-res windows (last 20 mins):
- 11:40-12:00: Eibar-Las Palmas
- 12:40-13:00: Lithuania-Georgia
- 13:55-14:15: Cultural-Andorra
- 16:10-16:30: Zaragoza-Racing
- 18:40-19:00: Colombia-France ← BEST WINDOW

Launch at ~09:00 UTC. Runs until ~20:00 UTC.

Validated params: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_near_res_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # === Lithuania vs Georgia (kickoff ~11:15, end ~13:00) ===
    {"name": "Lithuania", "token_id": "108571577093718516308956694727543833748558467283945806936098252944305582594974",
     "end_date": "2026-03-29T13:00:00Z", "pre_game_price": 0.0,
     "question": "Lithuania vs Georgia"},
    {"name": "Georgia", "token_id": "87107390582250753053307398888249032744680342409990613309753151938057183925853",
     "end_date": "2026-03-29T13:00:00Z", "pre_game_price": 0.0,
     "question": "Lithuania vs Georgia"},
    {"name": "LIT-GEO Draw", "token_id": "98840862116511198698932040346955448996650109274741309992979794877045721317766",
     "end_date": "2026-03-29T13:00:00Z", "pre_game_price": 0.0,
     "question": "Lithuania vs Georgia Draw"},

    # === Colombia vs France (kickoff ~17:15, end ~19:00) — BEST TARGET $61K vol ===
    {"name": "Colombia", "token_id": "63705066878473381708886310664344760277086378408052366453830365010659106869730",
     "end_date": "2026-03-29T19:00:00Z", "pre_game_price": 0.0,
     "question": "Colombia vs France"},
    {"name": "France", "token_id": "84515215646041359434326735847264199438192665226784060463360814204808768288159",
     "end_date": "2026-03-29T19:00:00Z", "pre_game_price": 0.0,
     "question": "Colombia vs France"},
    {"name": "COL-FRA Draw", "token_id": "106108897987077250431468910088138744658849410518689443679498345659874193607064",
     "end_date": "2026-03-29T19:00:00Z", "pre_game_price": 0.0,
     "question": "Colombia vs France Draw"},
]
# NOTE: Spanish 2nd division games (Eibar-Las Palmas, Cultural-Andorra, Zaragoza-Racing)
# need token IDs verified at launch. Add them in the 09:00 UTC session if volumes are decent.

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 15.0
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
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins={mins_left:.0f} {status}")

            if trigger:
                # Block opponent token
                for other in watch_list:
                    if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                        BOUGHT.add(other["token_id"])

                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** NEAR-RES BUY {w['name']} YES @ ask ~{sell_price:.3f} for ${spend:.2f} ***")
                result = place_near_res_buy(client, w["token_id"], spend,
                                            tag=w['name'])
                if result and result.get("filled"):
                    fill_price = result["price"]
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-soccer-mar29-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": fill_price,
                        "fair_price": min(fill_price + 0.08, 0.99),
                        "edge": jump,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / fill_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_left / 1440,
                        "opened_at": str(now),
                        "research_note": f"Near-res: price jumped {jump:+.2f} from {w['pre_game_price']:.2f}"
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"NEAR-RES BUY {w['name']} @ {fill_price:.3f} for ${spend:.2f} ({shares:.1f}sh)")
                    balance = get_usdc_balance(client)
        except Exception as e:
            if "404" not in str(e):
                print(f"  {w['name']}: ERROR {e}")

check_and_buy.count = 0


def main():
    print("=== Soccer Mar 29 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 20:00 UTC (after Colombia-France ends)
    end_time = datetime(2026, 3, 29, 20, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"ERROR in check loop: {e}")
        time.sleep(90)

    print(f"\n=== Monitor ended at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")
    send("Soccer Mar 29 monitor ended. Check logs.")


if __name__ == "__main__":
    main()
