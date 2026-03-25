#!/usr/bin/env python3
"""
Near-resolution monitor for March 26, 2026 — UEFA WCQ + FIFA Friendlies.

Matches (kickoff UTC → game end ~kickoff+1:45):
- Moldova vs Lithuania: 15:00 → end ~16:45
- Turkey vs Romania: 17:00 → end ~18:45
- Ukraine vs Sweden: 19:45 → end ~21:30  ← CLOSE GAME
- Italy vs N. Ireland: 19:45 → end ~21:30
- Poland vs Albania: 19:45 → end ~21:30
- Czechia vs Ireland: 19:45 → end ~21:30  ← CLOSE GAME
- Denmark vs N. Macedonia: 19:45 → end ~21:30
- Wales vs Bosnia: 19:45 → end ~21:30  ← CLOSE GAME
- Slovakia vs Kosovo: 19:45 → end ~21:30  ← CLOSE GAME
- Brazil vs France: 20:00 → end ~21:45  ← CLOSE GAME

Near-res windows: 16:25-16:45, 18:25-18:45, 21:10-21:45 UTC.
Launch at ~13:00-15:00 UTC to snapshot pre-game prices.

Validated params from March 22: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, place_limit_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # === Moldova vs Lithuania (15:00 kickoff, end ~16:45 UTC) ===
    {"name": "Moldova", "token_id": "97923693840687332618768980374722674984095037764542129826388616920329629619603",
     "end_date": "2026-03-26T16:45:00Z", "pre_game_price": 0.0,
     "question": "Moldova vs. Lithuania"},
    {"name": "Lithuania", "token_id": "43640547800419938437530103292956751016903022960841899659932683568902626453785",
     "end_date": "2026-03-26T16:45:00Z", "pre_game_price": 0.0,
     "question": "Moldova vs. Lithuania"},

    # === Turkey vs Romania (17:00 kickoff, end ~18:45 UTC) ===
    {"name": "Turkey", "token_id": "22018366048679221312689532353132141774118368618367535314505237811618661972779",
     "end_date": "2026-03-26T18:45:00Z", "pre_game_price": 0.0,
     "question": "Türkiye vs. Romania"},
    {"name": "Romania", "token_id": "112841215548972398611357923888853394218118688455951191579296347809654429568932",
     "end_date": "2026-03-26T18:45:00Z", "pre_game_price": 0.0,
     "question": "Türkiye vs. Romania"},

    # === Ukraine vs Sweden (19:45 kickoff, end ~21:30 UTC) — CLOSE GAME ===
    {"name": "Ukraine", "token_id": "51648038919441832529767363491921234172552410621403267516309722559126850802839",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Ukraine vs. Sweden"},
    {"name": "Sweden", "token_id": "91235421853549505515313154705985380922640511088664179396630749866887540062735",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Ukraine vs. Sweden"},

    # === Italy vs Northern Ireland (19:45 kickoff, end ~21:30 UTC) ===
    {"name": "Italy", "token_id": "105764838635404823518886560080395040173288676199569528025006252582264669638501",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Italy vs. Northern Ireland"},
    {"name": "Northern Ireland", "token_id": "86865219119205591935046652686750535286163296689324951188204675998940511533059",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Italy vs. Northern Ireland"},

    # === Poland vs Albania (19:45 kickoff, end ~21:30 UTC) ===
    {"name": "Poland", "token_id": "92350971869097216188980840054804294078808667119845664642645117979344941426493",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Poland vs. Albania"},
    {"name": "Albania", "token_id": "21370087395289801498845097052682634535911452421455768891296390588065769889508",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Poland vs. Albania"},

    # === Czechia vs Republic of Ireland (19:45 kickoff, end ~21:30 UTC) — CLOSE GAME ===
    {"name": "Czechia", "token_id": "61292659578181055317206462427958034339347491683383916001306068674350366048035",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Czechia vs. Republic of Ireland"},
    {"name": "Ireland", "token_id": "88445244396746222292585832805917431793669619605684458646566525986127500541066",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Czechia vs. Republic of Ireland"},

    # === Denmark vs North Macedonia (19:45 kickoff, end ~21:30 UTC) ===
    {"name": "Denmark", "token_id": "60359916902742682612811897544650888470638554127994153972571059108626286184241",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Denmark vs. North Macedonia"},
    {"name": "North Macedonia", "token_id": "49145734146103688552738301242696470794530826061954905356986171041067056277211",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Denmark vs. North Macedonia"},

    # === Wales vs Bosnia (19:45 kickoff, end ~21:30 UTC) — CLOSE GAME ===
    {"name": "Wales", "token_id": "38760949771854125427344891367777438346074995373259956605705707351231748622719",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Wales vs. Bosnia and Herzegovina"},
    {"name": "Bosnia", "token_id": "6164834498480963192821301915693516689313399156949918681842273458894100734604",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Wales vs. Bosnia and Herzegovina"},

    # === Slovakia vs Kosovo (19:45 kickoff, end ~21:30 UTC) — CLOSE GAME ===
    {"name": "Slovakia", "token_id": "60603129014209495902707159565432220297300635654774091902224685404406941533459",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Slovakia vs. Kosovo"},
    {"name": "Kosovo", "token_id": "104036489249777635343653471029324236801463443770741059544435504560233091847745",
     "end_date": "2026-03-26T21:30:00Z", "pre_game_price": 0.0,
     "question": "Slovakia vs. Kosovo"},

    # === Brazil vs France (20:00 kickoff, end ~21:45 UTC) — CLOSE GAME ===
    {"name": "Brazil", "token_id": "32956184720124463143248771917745518153762307040959896122703544754439210490550",
     "end_date": "2026-03-26T21:45:00Z", "pre_game_price": 0.0,
     "question": "Brazil vs. France"},
    {"name": "France", "token_id": "38298499234039796229938627084804138568691180585799099121025016397786519172841",
     "end_date": "2026-03-26T21:45:00Z", "pre_game_price": 0.0,
     "question": "Brazil vs. France"},
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
                print(f"\n  *** LIMIT BUY {w['name']} YES @ bid ~{sell_price:.3f} for ${spend:.2f} ***")
                result = place_limit_buy(client, w["token_id"], spend,
                                         max_wait_sec=30, tag=w['name'])
                if result and result.get("filled"):
                    fill_price = result["price"]
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-uefa-mar26-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"UEFA Mar26 near-res LIMIT: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"UEFA MAR26 NEAR-RES LIMIT BUY: {w['name']} YES @ {fill_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                elif result and not result.get("filled"):
                    print(f"  LIMIT order not filled for {w['name']} — bid was {result['price']:.3f}")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']}: {err}")


check_and_buy.count = 0


def main():
    print(f"=== UEFA+FIFA Mar 26 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    # Snapshot pre-game prices
    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor loop — run until 22:30 UTC Mar 26
    end_time = datetime(2026, 3, 26, 22, 30, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
