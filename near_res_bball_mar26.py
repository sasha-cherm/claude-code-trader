#!/usr/bin/env python3
"""
Near-resolution monitor for March 26, 2026 — 3 NBA + 1 NCAAB Sweet 16.

NBA (tipoff 23:00 UTC / 7PM ET, end ~01:30 UTC Mar 27):
- Knicks vs Hornets (51/48 — CLOSE)
- Pelicans vs Pistons (35/64)
- Kings vs Magic (10/89 — heavy fav)

NCAAB Sweet 16 (tipoff ~04:00 UTC Mar 27, end ~06:00 UTC):
- Tennessee vs Iowa State (36/63)

NCAAB Sweet 16 (tipoff ~02:05 UTC Mar 27, end ~04:15 UTC):
- Illinois vs Houston (41/58)

Near-res windows: 01:00-01:30 UTC (NBA), 03:45-04:15 UTC (Illinois-Houston), 05:30-06:00 UTC (Tennessee-ISU).
Launch at ~21:00-23:00 UTC Mar 26.

Validated params: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_limit_buy, place_near_res_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # === Knicks vs Hornets (tipoff 23:00 UTC, end ~01:30 UTC) — CLOSE GAME ===
    {"name": "Knicks", "token_id": "101175845957085174081677730787700247847123458912177865400247406662139569237645",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs. Hornets"},
    {"name": "Hornets", "token_id": "47931932226011834479724213848451379554971117433985988913514255685319875029376",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs. Hornets"},

    # === Pelicans vs Pistons (tipoff 23:00 UTC, end ~01:30 UTC) ===
    {"name": "Pelicans", "token_id": "4473601759659346027187678581617246224408414343914363938974110238241063546608",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Pistons"},
    {"name": "Pistons", "token_id": "102198004812862135123678883551825150127312380984003835005211138290318481809998",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Pistons"},

    # === Kings vs Magic (tipoff 23:00 UTC, end ~01:30 UTC) — HEAVY FAV ===
    {"name": "Kings", "token_id": "35981904997284240954113312857654433176905466281360171797884476099669939248914",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Kings vs. Magic"},
    {"name": "Magic", "token_id": "42681689509474313921994466296825751144460520075266714195393481209429064869806",
     "end_date": "2026-03-27T01:30:00Z", "pre_game_price": 0.0,
     "question": "Kings vs. Magic"},

    # === Illinois vs Houston — NCAAB Sweet 16 (tipoff ~02:05 UTC Mar 27, end ~04:15 UTC) ===
    {"name": "Illinois", "token_id": "32808458875366467745777044160603661512817861173859925631005519080722962618453",
     "end_date": "2026-03-27T04:15:00Z", "pre_game_price": 0.0,
     "question": "Illinois vs. Houston"},
    {"name": "Houston", "token_id": "59202108327135535421172568160321982683582378216670455227255549883175903089000",
     "end_date": "2026-03-27T04:15:00Z", "pre_game_price": 0.0,
     "question": "Illinois vs. Houston"},

    # === Tennessee vs Iowa State — NCAAB Sweet 16 (tipoff ~04:00 UTC, end ~06:00 UTC) ===
    {"name": "Tennessee", "token_id": "81438783150792244592328715427303188623453352675284541060677928493725012936568",
     "end_date": "2026-03-27T06:00:00Z", "pre_game_price": 0.0,
     "question": "Tennessee vs. Iowa State"},
    {"name": "Iowa State", "token_id": "61556323625927994597831200744068971396152002448048596884917011307398621797080",
     "end_date": "2026-03-27T06:00:00Z", "pre_game_price": 0.0,
     "question": "Tennessee vs. Iowa State"},
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
                        "market_id": f"near-res-bball-mar26-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"NBA/NCAAB Mar26 near-res LIMIT: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"BBALL MAR26 NEAR-RES NEAR-RES BUY: {w['name']} YES @ {fill_price:.3f}\n"
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
    print(f"=== NBA+NCAAB Mar 26 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor until 06:30 UTC Mar 27 (for Tennessee-Iowa State)
    end_time = datetime(2026, 3, 27, 6, 30, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
