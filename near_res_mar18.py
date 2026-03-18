#!/usr/bin/env python3
"""
Near-resolution monitor for March 18, 2026.
Covers: Europa (Braga), CL (Barca-Newcastle), Serie B, Brazilian league.
Run from 13:00 UTC, covers games through ~00:00 UTC March 19.
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
    # Europa League: Braga vs Ferencvaros (15:30 UTC kickoff, end ~17:15)
    {"name": "Braga", "token_id": "39702381409408353908861837430423076975783146876234338133101520974386705068967",
     "end_date": "2026-03-18T17:15:00Z", "pre_game_price": 0.0, "question": "Will SC Braga win on 2026-03-18?"},
    {"name": "Ferencvaros", "token_id": "61511499204689227838135973769792315543921665685214650542819886441739747537802",
     "end_date": "2026-03-18T17:15:00Z", "pre_game_price": 0.0, "question": "Will Ferencvarosi TC win on 2026-03-18?"},

    # CL: Barcelona vs Newcastle (17:45 UTC kickoff, end ~19:30)
    {"name": "Barcelona", "token_id": "25845698069276681239322469386443883416410519536634919674407031744557375519521",
     "end_date": "2026-03-18T19:30:00Z", "pre_game_price": 0.0, "question": "Will FC Barcelona win on 2026-03-18?"},
    {"name": "Newcastle", "token_id": "30909379099359904747245604913983590810498426007022367682132051536234269899376",
     "end_date": "2026-03-18T19:30:00Z", "pre_game_price": 0.0, "question": "Will Newcastle United FC win on 2026-03-18?"},

    # Serie B: Frosinone vs Bari (18:00 UTC kickoff, end ~19:45)
    {"name": "Frosinone", "token_id": "62618445002370891231902414718962161299662292789184767129617882435672692817173",
     "end_date": "2026-03-18T19:45:00Z", "pre_game_price": 0.0, "question": "Will Frosinone Calcio win on 2026-03-18?"},
    {"name": "Bari", "token_id": "24555474017283601842870917848789441747197216316356145412504138070923476939448",
     "end_date": "2026-03-18T19:45:00Z", "pre_game_price": 0.0, "question": "Will SSC Bari win on 2026-03-18?"},

    # Serie B: Carrarese vs Sampdoria (19:00 UTC kickoff, end ~20:45)
    {"name": "Carrarese", "token_id": "50676796217511961401214696700488268883223977624994017275914826237810055598679",
     "end_date": "2026-03-18T20:45:00Z", "pre_game_price": 0.0, "question": "Will Carrarese Calcio win on 2026-03-18?"},
    {"name": "Sampdoria", "token_id": "83189122246612054006113862630107369467458143451007923157785771175808056367092",
     "end_date": "2026-03-18T20:45:00Z", "pre_game_price": 0.0, "question": "Will UC Sampdoria win on 2026-03-18?"},

    # Brazilian Serie A (22:00 UTC kickoff, end ~23:45)
    {"name": "Palmeiras", "token_id": "36108519024502447424056492311689862615627129755422509453746007382639548207985",
     "end_date": "2026-03-18T23:45:00Z", "pre_game_price": 0.0, "question": "Will SE Palmeiras win on 2026-03-18?"},
    {"name": "Botafogo", "token_id": "47260613571639066162078600633240485486358994340946575860571897548212048158338",
     "end_date": "2026-03-18T23:45:00Z", "pre_game_price": 0.0, "question": "Will Botafogo FR win on 2026-03-18?"},
    {"name": "Mineiro", "token_id": "55522789309629405203183723932430295905407806433892179066656526554851396378420",
     "end_date": "2026-03-19T00:45:00Z", "pre_game_price": 0.0, "question": "Will CA Mineiro win on 2026-03-18?"},
    {"name": "Sao Paulo", "token_id": "97954427294990543664966225521594476252765193559899783311047814646135852856229",
     "end_date": "2026-03-19T00:45:00Z", "pre_game_price": 0.0, "question": "Will Sao Paulo FC win on 2026-03-18?"},
    {"name": "Paranaense", "token_id": "88670427589650889462127420272390845460960511196741954418136034474962291047725",
     "end_date": "2026-03-18T23:45:00Z", "pre_game_price": 0.0, "question": "Will CA Paranaense win on 2026-03-18?"},
    {"name": "Cruzeiro", "token_id": "98671698174358104834458706355249743185522854030346390518352262143106937028969",
     "end_date": "2026-03-18T23:45:00Z", "pre_game_price": 0.0, "question": "Will Cruzeiro EC win on 2026-03-18?"},
]

# Stricter params — raised MIN_PRICE to 0.80 for better win rate
MAX_SPEND_PER_TRADE = 8.0
MIN_SPEND = 2.0
MIN_PRICE_JUMP = 0.18
MIN_NEAR_RES_PRICE = 0.80
MAX_NEAR_RES_PRICE = 0.93
MAX_SPREAD = 0.06  # Tighter spread check
MAX_MINS_TO_END = 30  # Only last 30 min
PCT_OF_BALANCE = 0.25
BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        if w["pre_game_price"] == 0.0:
            try:
                info = client.get_price(w["token_id"], "buy")
                w["pre_game_price"] = float(info.get("price", 0))
                print(f"  Pre-game {w['name']}: {w['pre_game_price']:.3f}")
            except Exception as e:
                print(f"  Pre-game {w['name']}: ERROR {e}")


def check_and_buy(client, watch_list):
    balance = get_usdc_balance(client)
    print(f"  Balance: ${balance:.2f}")

    for w in watch_list:
        if not w["token_id"] or w["token_id"] in BOUGHT:
            continue
        try:
            buy_price = float(client.get_price(w["token_id"], "buy").get("price", 0))
            sell_price = float(client.get_price(w["token_id"], "sell").get("price", 0))
            jump = buy_price - w["pre_game_price"]
            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins_to_end = (end - now).total_seconds() / 60
            spread = buy_price - sell_price

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                mins_to_end <= MAX_MINS_TO_END and
                mins_to_end > 0 and
                abs(spread) < MAX_SPREAD and
                balance >= MIN_SPEND
            )

            # Only print games that are within 60 min of end or have moved
            if mins_to_end <= 60 or abs(jump) > 0.05:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(1.5)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-{w['name'].lower()}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.12, 0.95),
                        "edge": 0.10,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_to_end / 1440,
                        "opened_at": str(now),
                        "research_note": f"Near-res: {w['name']} jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}, {mins_to_end:.0f}min left")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            print(f"  {w['name']:14s} ERROR: {e}")


def main():
    print(f"=== Mar18 Near-Res Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    client = get_client()

    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run for up to 12 hours (covers all games from 13:00 to 01:00 UTC)
    for i in range(720):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        try:
            # Re-snapshot any games that haven't started yet (price was 0)
            for w in ALL_GAMES:
                if w["pre_game_price"] == 0.0:
                    try:
                        info = client.get_price(w["token_id"], "buy")
                        w["pre_game_price"] = float(info.get("price", 0))
                    except:
                        pass
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  ERROR in check: {e}")
        time.sleep(60)

    print(f"\n=== Mar18 Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
