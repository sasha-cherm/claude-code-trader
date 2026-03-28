#!/usr/bin/env python3
"""
Near-resolution monitor for March 29, 2026 — 9 NBA games + NCAAB Elite 8.

Games (by tipoff UTC → estimated end):
- Clippers vs Bucks (19:30, end ~22:00) — Clippers 83.5% fav, $16K vol
- Heat vs Pacers (21:00, end ~23:30) — Heat 77.5%, $25K vol
- Kings vs Nets (22:00, end ~00:30) — COIN FLIP 51.5/48.5, $28K vol ← TARGET
- Celtics vs Hornets (22:00, end ~00:30) — COIN FLIP 52.5/47.5, $58K vol ← TARGET
- Magic vs Raptors (22:00, end ~00:30) — Raptors 57.5%, $36K vol
- Wizards vs Trail Blazers (22:00, end ~00:30) — Blazers 89.5%, $10K vol
- Rockets vs Pelicans (23:00, end ~01:30) — Rockets 69%, $23K vol
- Knicks vs Thunder (23:30, end ~02:00) — Thunder 76%, $27K vol
- Warriors vs Nuggets (02:00 Mar 30, end ~04:30) — Nuggets 81%, $14K vol

Near-res windows (last 20 mins of game):
- 21:40-22:00 UTC: Clippers-Bucks
- 23:10-23:30 UTC: Heat-Pacers
- 00:10-00:30 UTC: Kings-Nets + Celtics-Hornets + Magic-Raptors + Wizards-Blazers (4 overlapping!)
- 01:10-01:30 UTC: Rockets-Pelicans
- 01:40-02:00 UTC: Knicks-Thunder
- 04:10-04:30 UTC: Warriors-Nuggets

Launch at ~18:00 UTC. Runs until ~05:00 UTC Mar 30.

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
    # === Clippers vs Bucks (tipoff 19:30, end ~22:00) ===
    {"name": "Clippers", "token_id": "14601167560606426917718331855347642051223131748556197437271063122555636628254",
     "end_date": "2026-03-29T22:00:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs Bucks"},
    {"name": "Bucks", "token_id": "36209974969270005929478913409127766361788224769548192629896274601121703735484",
     "end_date": "2026-03-29T22:00:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs Bucks"},

    # === Heat vs Pacers (tipoff 21:00, end ~23:30) ===
    {"name": "Heat", "token_id": "54268772394696508593449064098275296195610727610315674125039764021346976776532",
     "end_date": "2026-03-29T23:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs Pacers"},
    {"name": "Pacers", "token_id": "30737869522084583250787348761921807424436212950877429392167290854319537675093",
     "end_date": "2026-03-29T23:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs Pacers"},

    # === Kings vs Nets (tipoff 22:00, end ~00:30 Mar 30) — COIN FLIP ===
    {"name": "Kings", "token_id": "32218104176927886479094054791215039383439201412126676759926564161259425928171",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Kings vs Nets"},
    {"name": "Nets", "token_id": "71703344853726352606227286727477156747988497265261389572258926895688500924890",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Kings vs Nets"},

    # === Celtics vs Hornets (tipoff 22:00, end ~00:30 Mar 30) — COIN FLIP ===
    {"name": "Celtics", "token_id": "57490801281206654852018729936736026755861016869364825432770952173135027532030",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs Hornets"},
    {"name": "Hornets", "token_id": "115188286692673541878141556629858441876946797209792642837550526323278552751048",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs Hornets"},

    # === Magic vs Raptors (tipoff 22:00, end ~00:30 Mar 30) ===
    {"name": "Magic", "token_id": "34264767528799095092721184890314240284913433712903162694603714880864452578901",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Magic vs Raptors"},
    {"name": "Raptors", "token_id": "8358691472058530639821447384002385942665528799389136840096744984014672693361",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Magic vs Raptors"},

    # === Wizards vs Trail Blazers (tipoff 22:00, end ~00:30 Mar 30) ===
    {"name": "Wizards", "token_id": "73825077151789743621109686158106183247921951320330568595421120222482239611866",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs Trail Blazers"},
    {"name": "Trail Blazers", "token_id": "78887580442619691321808019311514174730774054977588456230020613247014939017059",
     "end_date": "2026-03-30T00:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs Trail Blazers"},

    # === Rockets vs Pelicans (tipoff 23:00, end ~01:30 Mar 30) ===
    {"name": "Rockets", "token_id": "27628343019234996563184508808595312021741521549637156976363468307325922182226",
     "end_date": "2026-03-30T01:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs Pelicans"},
    {"name": "Pelicans", "token_id": "90983988591044836812677395940939974740533245529447154489588830380422092094064",
     "end_date": "2026-03-30T01:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs Pelicans"},

    # === Knicks vs Thunder (tipoff 23:30, end ~02:00 Mar 30) ===
    {"name": "Knicks", "token_id": "46074053027504456980838139439071668463534417342542986769475437075526685360542",
     "end_date": "2026-03-30T02:00:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs Thunder"},
    {"name": "Thunder", "token_id": "19706500110584865903942193800551413107099767942836722978619381262426287734543",
     "end_date": "2026-03-30T02:00:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs Thunder"},

    # === Warriors vs Nuggets (tipoff 02:00 Mar 30, end ~04:30) ===
    {"name": "Warriors", "token_id": "53258696700130508595443221744296719185974344918382674767203601812931065213093",
     "end_date": "2026-03-30T04:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs Nuggets"},
    {"name": "Nuggets", "token_id": "21341380303690007692832055295311560631168332650882032609807142350179251549791",
     "end_date": "2026-03-30T04:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs Nuggets"},

    # === NCAAB Elite 8 — ADD WHEN MARKETS CREATED ===
    # Purdue vs Arizona (~01:00 UTC tipoff?) — check day-of
    # Duke vs Houston — check day-of
    # Auburn vs Michigan State — check day-of
    # Florida vs St. Johns — check day-of
]

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
                        "market_id": f"near-res-bball-mar29-{w['name'].lower().replace(' ', '-')}",
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
    print("=== NBA Mar 29 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 05:00 UTC Mar 30 (after last game ends)
    end_time = datetime(2026, 3, 30, 5, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"ERROR in check loop: {e}")
        time.sleep(90)

    print(f"\n=== Monitor ended at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")
    send("NBA Mar 29 monitor ended. Check logs.")


if __name__ == "__main__":
    main()
