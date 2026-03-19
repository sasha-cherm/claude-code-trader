#!/usr/bin/env python3
"""
Supplementary near-resolution monitor for March 19, 2026.
Covers markets NOT in the main soccer/bball/CS2 monitors:
- Turkish Super Lig: Besiktas (17:00 UTC kick)
- UECL: AEK Athens-Celje (17:45 UTC kick)
- UEL: Porto-Stuttgart, UECL: Betis-Panathinaikos (20:00 UTC kick)
- NCAAB: Texas-BYU (22:50 UTC tip)
- Brazilian: Flamengo, Corinthians, Gremio (22:00-00:30 UTC)
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

# Parameters — same as tightened near-res
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.94
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 15
MAX_SPEND_PER_TRADE = 9.0
MIN_SPEND = 2.0
PCT_OF_BALANCE = 0.22

ALL_GAMES = [
    # === Turkish Super Lig — 17:00 UTC kickoff, near-res ~18:30-18:45 ===
    {"name": "Besiktas", "token_id": "97860430537476561825003606577382616791365555737134994265888015237807341588108",
     "end_date": "2026-03-19T18:45:00Z", "pre_game_price": 0.0,
     "question": "Will Besiktas win on 2026-03-19?"},
    {"name": "Kasimpasa", "token_id": "101050951090285198459637282477959206947928392694399356919553088787468407857149",
     "end_date": "2026-03-19T18:45:00Z", "pre_game_price": 0.0,
     "question": "Will Kasimpasa win on 2026-03-19?"},

    # === UECL — AEK Athens vs NK Celje — 17:45 UTC kickoff ===
    {"name": "AEK Athens", "token_id": "83866950851476402713555892208785387343500333297035341282614728793850181133998",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0,
     "question": "Will AEK Athens FC win on 2026-03-19?"},
    {"name": "NK Celje", "token_id": "73923696021847837098835046506381566318945687340254614785385278323306689299531",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0,
     "question": "Will NK Celje win on 2026-03-19?"},

    # === UEL R16 — Porto vs Stuttgart — 20:00 UTC kickoff ===
    {"name": "Porto", "token_id": "58528468827297531308072011835616937612813668896505043410854314406386338097378",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will FC Porto win on 2026-03-19?"},
    {"name": "Stuttgart", "token_id": "54115893205616147373898044409410237612127339771571433917006675339415842999003",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will VfB Stuttgart win on 2026-03-19?"},

    # === UECL — Betis vs Panathinaikos — 20:00 UTC kickoff ===
    {"name": "Betis", "token_id": "41509637623877092966098743533580506212266415566863770439988077955635528597021",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will Real Betis win on 2026-03-19?"},
    {"name": "Panathinaikos", "token_id": "72134194229270382905186347433622686136700875131726551360834805288785325130030",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will Panathinaikos win on 2026-03-19?"},

    # === NCAAB March Madness — Texas vs BYU — ~22:50 UTC tipoff ===
    {"name": "Texas", "token_id": "63144697917848800663609672106238138655373294816083771082590443598632261330916",
     "end_date": "2026-03-20T01:05:00Z", "pre_game_price": 0.0,
     "question": "Texas Longhorns vs. BYU Cougars"},
    {"name": "BYU", "token_id": "88542796149786091913005525806296832252690824331219054946071533506958276686074",
     "end_date": "2026-03-20T01:05:00Z", "pre_game_price": 0.0,
     "question": "Texas Longhorns vs. BYU Cougars"},

    # === Brazilian Serie A — 22:00-00:30 UTC ===
    {"name": "Flamengo", "token_id": "36276362591929139379354748311477054844765484731132974964049703008208369797400",
     "end_date": "2026-03-19T23:45:00Z", "pre_game_price": 0.0,
     "question": "Will CR Flamengo win on 2026-03-19?"},
    {"name": "Corinthians", "token_id": "71734903288389415707668428942715047660111380856581439503588721279773371335025",
     "end_date": "2026-03-20T00:15:00Z", "pre_game_price": 0.0,
     "question": "Will SC Corinthians win on 2026-03-19?"},
    {"name": "Gremio", "token_id": "3242877794584519516003133631533713156542057636639986145846844495506033830497",
     "end_date": "2026-03-20T02:15:00Z", "pre_game_price": 0.0,
     "question": "Will Gremio FBPA win on 2026-03-19?"},
]


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        if w["pre_game_price"] == 0.0:
            try:
                bp = client.get_price(w["token_id"], "buy")
                w["pre_game_price"] = float(bp["price"])
                print(f"  Pre-game {w['name']}: {w['pre_game_price']:.3f}")
            except Exception as e:
                print(f"  Pre-game {w['name']} ERROR: {e}")


def check_and_buy(client, watch_list):
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)
    print(f"\n--- Check at {now.strftime('%H:%M:%S')} UTC ---")
    print(f"  Balance: ${balance:.2f}")

    bought = []
    for w in watch_list:
        try:
            end_dt = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins_left = (end_dt - now).total_seconds() / 60
            if mins_left < 0 or mins_left > 120:
                continue

            if w["pre_game_price"] == 0.0:
                bp_raw = client.get_price(w["token_id"], "buy")
                if float(bp_raw["price"]) > 0.01:
                    w["pre_game_price"] = float(bp_raw["price"])
                continue

            bp = client.get_price(w["token_id"], "buy")
            sp = client.get_price(w["token_id"], "sell")
            buy_price = float(bp["price"])
            sell_price = float(sp["price"])
            spread = buy_price - sell_price
            jump = buy_price - w["pre_game_price"]

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                abs(spread) < MAX_SPREAD and
                mins_left <= MAX_MINS_TO_END and
                mins_left > 0 and
                balance >= MIN_SPEND
            )

            if abs(jump) > 0.05 or buy_price >= 0.80:
                status = "*** TRIGGER ***" if trigger else ""
                print(f"  {w['name']:15s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins={mins_left:.0f} {status}")

            if trigger and w["token_id"] not in [b["token_id"] for b in bought]:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                print(f"  Result: {result}")

                time.sleep(2)
                shares = get_actual_shares(client, w["token_id"])
                state = load_state()
                state["positions"].append({
                    "token_id": w["token_id"],
                    "market_id": f"near-res-extra-{w['name'].lower().replace(' ', '-')}",
                    "question": w["question"],
                    "side": "YES",
                    "entry_price": buy_price,
                    "fair_price": sell_price,
                    "edge": jump,
                    "size_usdc": spend,
                    "shares": shares if shares > 0 else spend / buy_price,
                    "end_date": w["end_date"],
                    "days_left_at_entry": mins_left / 1440,
                    "opened_at": str(now),
                    "research_note": f"Extra near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                })
                save_state(state)
                balance = get_usdc_balance(client)
                bought.append({"token_id": w["token_id"], "name": w["name"]})
                send(f"EXTRA NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}, {mins_left:.0f} min left")

        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']:15s} ERROR: {err}")


if __name__ == "__main__":
    print(f"=== Extra Near-Res Monitor: March 19 ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M')} UTC ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}")
    print(f"        MAX_MINS={MAX_MINS_TO_END}, MAX_SPEND={MAX_SPEND_PER_TRADE}")

    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    for i in range(600):  # 10 hours
        now = datetime.now(timezone.utc)
        check_and_buy(client, ALL_GAMES)
        time.sleep(60)
