#!/usr/bin/env python3
"""
Near-resolution monitor for March 24, 2026 — Euroleague Basketball + CS2.

Euroleague games (KICKOFF → actual END times UTC):
- Maccabi Tel Aviv vs Fenerbahce: kick 17:30 → end 19:15
- Monaco vs Olimpia Milano: kick 18:00 → end 19:45
- Zalgiris Kaunas vs Bayern Munich: kick 18:00 → end 19:45
- BC Dubai vs Panathinaikos: kick 18:30 → end 20:15
- Barcelona vs Anadolu Efes: kick 19:30 → end 21:15
- Valencia vs Olympiacos: kick 19:30 → end 21:15
- Real Madrid vs Hapoel Tel Aviv: kick 20:00 → end 21:45

Women's soccer (UWCL):
- Arsenal WFC vs Chelsea FC: kick 20:00 → end 21:45

CS2:
- Inner Circle vs OG (BO1): resolved (ICE won)

IMPORTANT: Gamma API end_date = KICKOFF time. Added +1:45 for basketball, +1:45 for soccer.
Near-res windows: 18:55-21:45 UTC.
Using same validated params as NBA: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
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
    # Maccabi Tel Aviv vs Fenerbahce — Fener favorite (0.58)
    # Kickoff 17:30 UTC → actual end ~19:15 UTC
    {"name": "Maccabi", "token_id": "66560916628049162020950736438975876094112150861375654180592586120188265935849",
     "end_date": "2026-03-24T19:15:00Z", "pre_game_price": 0.41,
     "question": "Maccabi Tel Aviv vs. Fenerbahce"},
    {"name": "Fenerbahce", "token_id": "84730326742994565233869126028249225312001361005388617858732802388027225543063",
     "end_date": "2026-03-24T19:15:00Z", "pre_game_price": 0.58,
     "question": "Maccabi Tel Aviv vs. Fenerbahce"},

    # Monaco vs Olimpia Milano — Monaco favorite (0.55)
    # Kickoff 18:00 UTC → actual end ~19:45 UTC
    {"name": "Monaco", "token_id": "30298161304759783693103337098095553451761279166113626932172745399638532125471",
     "end_date": "2026-03-24T19:45:00Z", "pre_game_price": 0.55,
     "question": "Monaco vs. Olimpia Milano"},
    {"name": "Olimpia Milano", "token_id": "66469208982472331191711089111748396019855262500009128666670954075651009316134",
     "end_date": "2026-03-24T19:45:00Z", "pre_game_price": 0.43,
     "question": "Monaco vs. Olimpia Milano"},

    # Zalgiris Kaunas vs Bayern Munich — Zalgiris favorite (0.73)
    # Kickoff 18:00 UTC → actual end ~19:45 UTC
    {"name": "Zalgiris", "token_id": "36124922780474066360665905012926429094758523207451909996623869440967050893378",
     "end_date": "2026-03-24T19:45:00Z", "pre_game_price": 0.73,
     "question": "Zalgiris Kaunas vs. FC Bayern Munchen"},
    {"name": "Bayern", "token_id": "74445622413742581969428964195329871390934829876986732369770021587825867611492",
     "end_date": "2026-03-24T19:45:00Z", "pre_game_price": 0.26,
     "question": "Zalgiris Kaunas vs. FC Bayern Munchen"},

    # BC Dubai vs Panathinaikos — Pana favorite (0.56)
    # Kickoff 18:30 UTC → actual end ~20:15 UTC
    {"name": "BC Dubai", "token_id": "107455021965223360644100804313718509332337703482630332517229329011362399365420",
     "end_date": "2026-03-24T20:15:00Z", "pre_game_price": 0.43,
     "question": "BC Dubai vs. Panathinaikos"},
    {"name": "Panathinaikos", "token_id": "33207116919083067040742241430677074294332312913056390797621317028767729393820",
     "end_date": "2026-03-24T20:15:00Z", "pre_game_price": 0.56,
     "question": "BC Dubai vs. Panathinaikos"},

    # Barcelona vs Anadolu Efes — Barca favorite (0.73)
    # Kickoff 19:30 UTC → actual end ~21:15 UTC
    {"name": "Barcelona", "token_id": "92274938411304302907734089612428099971561293009462721176734437256926060335128",
     "end_date": "2026-03-24T21:15:00Z", "pre_game_price": 0.73,
     "question": "Barcelona vs. Anadolu Efes"},
    {"name": "Efes", "token_id": "96540571109717054415566876539900569029829371283066213732513373636001380979343",
     "end_date": "2026-03-24T21:15:00Z", "pre_game_price": 0.25,
     "question": "Barcelona vs. Anadolu Efes"},

    # Valencia vs Olympiacos
    # Kickoff 19:30 UTC → actual end ~21:15 UTC
    {"name": "Valencia", "token_id": "105803612063809081140324915530991937648734644420885636977309413408788806497681",
     "end_date": "2026-03-24T21:15:00Z", "pre_game_price": 0.47,
     "question": "Valencia vs. Olympiacos B.C."},
    {"name": "Olympiacos", "token_id": "87743347261924572332968469068155353695008448678629377452881575667419014290109",
     "end_date": "2026-03-24T21:15:00Z", "pre_game_price": 0.52,
     "question": "Valencia vs. Olympiacos B.C."},

    # Real Madrid vs Hapoel Tel Aviv — Real Madrid heavy favorite (0.68)
    # Kickoff 20:00 UTC → actual end ~21:45 UTC
    {"name": "Real Madrid", "token_id": "6218780877953177616942422798198498551299930240078304019474854403882155884876",
     "end_date": "2026-03-24T21:45:00Z", "pre_game_price": 0.68,
     "question": "Real Madrid vs. Hapoel Tel Aviv"},
    {"name": "Hapoel", "token_id": "22179804346307810434690366756559148424865944156210301054282845434104616395197",
     "end_date": "2026-03-24T21:45:00Z", "pre_game_price": 0.31,
     "question": "Real Madrid vs. Hapoel Tel Aviv"},

    # Women's UWCL: Wolfsburg vs Lyon
    # Kickoff 17:45 UTC → actual end ~19:30 UTC
    {"name": "Wolfsburg", "token_id": "106618152048464176937334207165727237109929328102665496604269274644283156535077",
     "end_date": "2026-03-24T19:30:00Z", "pre_game_price": 0.11,
     "question": "Will VfL Wolfsburg win on 2026-03-24?"},
    {"name": "OL Lyon", "token_id": "107795523387106099619493906679674670112922723590094187118357034148433865151845",
     "end_date": "2026-03-24T19:30:00Z", "pre_game_price": 0.71,
     "question": "Will OL Lyonnes win on 2026-03-24?"},

    # Women's UWCL: Arsenal WFC vs Chelsea FC
    # Kickoff 20:00 UTC → actual end ~21:45 UTC
    {"name": "Arsenal WFC", "token_id": "39388498378303498227495163234545085115485930150243668222870888402102004091165",
     "end_date": "2026-03-24T21:45:00Z", "pre_game_price": 0.465,
     "question": "Will Arsenal WFC win on 2026-03-24?"},
    {"name": "Chelsea FC", "token_id": "83964524542461270991348658810341387581028300718607666127490744814539360451605",
     "end_date": "2026-03-24T21:45:00Z", "pre_game_price": 0.285,
     "question": "Will Chelsea FC win on 2026-03-24?"},
]

# === Params (validated Mar 22: 8/8 wins on NBA/soccer) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 15.0  # Conservative — first time on Euroleague
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.20  # Conservative — first test
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
                        "market_id": f"near-res-euro-mar24-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Euro/CS2 Mar24 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"EURO MAR24 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
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
    print(f"=== Euroleague + CS2 Mar 24 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    # Snapshot pre-game prices
    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor loop — run until 22:00 UTC (after last game ends ~21:45)
    end_time = datetime(2026, 3, 24, 22, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
