#!/usr/bin/env python3
"""
Near-resolution monitor for NCAAB March Madness 2nd Round — March 22, 2026.
12 games, 24 tokens. Runs alongside near_res_mar22_pm.py.

NOTE: end_date = KICKOFF + 2h15m (basketball game length).
NCAAB near-res is UNTESTED live — use tighter params (MIN_PRICE=0.88).
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
    # Wave 1: 16:00 UTC kickoff → end ~18:15 UTC
    {"name": "Texas Tech", "token_id": "59225215309188916427944200110830336195483543653081163898421203368708527905722",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Texas Tech Red Raiders vs. Alabama Crimson Tide"},
    {"name": "Alabama", "token_id": "112201305494939841914583054299554432971828381305109997042373499077388134270274",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Texas Tech Red Raiders vs. Alabama Crimson Tide"},

    {"name": "Tennessee", "token_id": "79432783456740199807436637213656588485985881010883556172124756172711055370651",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Tennessee Volunteers vs. Virginia Cavaliers"},
    {"name": "Virginia", "token_id": "75689244959277898341236032211117274245139122622096460977873312394709590336595",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Tennessee Volunteers vs. Virginia Cavaliers"},

    {"name": "Utah State", "token_id": "97375804516138919402368296257548460708782641123645973538856878198805504642693",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Utah State Aggies vs. Arizona Wildcats"},
    {"name": "Arizona", "token_id": "36807159030821860432748331861018561546226753937211485581292983482466573301303",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Utah State Aggies vs. Arizona Wildcats"},

    {"name": "Iowa", "token_id": "22982279647126304725876246383164468293958197558580061538886168962946310215031",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Iowa Hawkeyes vs. Florida Gators"},
    {"name": "Florida", "token_id": "61940465982040397744031242031058401133822591164359218772886913831781005236268",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Iowa Hawkeyes vs. Florida Gators"},

    {"name": "UCLA", "token_id": "84615354223448887296584412991783208718857888363337060090533647785527303709181",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "UCLA Bruins vs. Connecticut Huskies"},
    {"name": "UConn", "token_id": "86169909339243367001201174256105082611316917935576519594705243844553368433154",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "UCLA Bruins vs. Connecticut Huskies"},

    # Wave 2: 20:30 UTC kickoff → end ~22:45 UTC
    {"name": "Illinois St", "token_id": "42122694067077856702335256649604865762125812596953888660877576893850842521653",
     "end_date": "2026-03-22T22:45:00Z", "pre_game_price": 0.0,
     "question": "Illinois State Redbirds vs. Wake Forest Demon Deacons"},
    {"name": "Wake Forest", "token_id": "98831154940773632938499155389717105594088171622643974296336881141776173992692",
     "end_date": "2026-03-22T22:45:00Z", "pre_game_price": 0.0,
     "question": "Illinois State Redbirds vs. Wake Forest Demon Deacons"},

    # Wave 3: 21:15 UTC kickoff → end ~23:30 UTC
    {"name": "St Johns", "token_id": "48068488443929504799541214060128349541428360301712650373263604966011388230686",
     "end_date": "2026-03-22T23:30:00Z", "pre_game_price": 0.0,
     "question": "St. John's Red Storm vs. Kansas Jayhawks"},
    {"name": "Kansas", "token_id": "73540916657698057460080250711463737886661802002626636307453497280366356175445",
     "end_date": "2026-03-22T23:30:00Z", "pre_game_price": 0.0,
     "question": "St. John's Red Storm vs. Kansas Jayhawks"},

    # Wave 4: 22:30 UTC kickoff → end ~00:45 UTC Mar 23
    {"name": "Seattle", "token_id": "36167916586939346458783424946991544460154159125767726482994534304850901798626",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "Seattle Redhawks vs. Auburn Tigers"},
    {"name": "Auburn", "token_id": "83194995493126829332242019069183200241961380817449532363028815990899439384383",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "Seattle Redhawks vs. Auburn Tigers"},

    # Wave 5: 23:00 UTC kickoff → end ~01:15 UTC Mar 23
    {"name": "UNLV", "token_id": "42287963904161472101222895161857038728819394501272666140203465132343274116553",
     "end_date": "2026-03-23T01:15:00Z", "pre_game_price": 0.0,
     "question": "UNLV Runnin' Rebels vs. Tulsa Golden Hurricane"},
    {"name": "Tulsa", "token_id": "44275565770714875080879274616146823263867752323981250588764546140725552216643",
     "end_date": "2026-03-23T01:15:00Z", "pre_game_price": 0.0,
     "question": "UNLV Runnin' Rebels vs. Tulsa Golden Hurricane"},

    # Wave 6: 00:00 UTC Mar 23 kickoff → end ~02:15 UTC Mar 23
    {"name": "G Washington", "token_id": "27203303480039712259474311695109433045912657606098016796970356281184887207076",
     "end_date": "2026-03-23T02:15:00Z", "pre_game_price": 0.0,
     "question": "George Washington Revolutionaries vs. New Mexico Lobos"},
    {"name": "New Mexico", "token_id": "29921663951049043057894735736356629143302916705297672286190237055483226161355",
     "end_date": "2026-03-23T02:15:00Z", "pre_game_price": 0.0,
     "question": "George Washington Revolutionaries vs. New Mexico Lobos"},

    # Wave 7: 00:30 UTC Mar 23 kickoff → end ~02:45 UTC Mar 23
    {"name": "Wichita St", "token_id": "39724668186937519996872643809245469391143891256188613266833708738359691051152",
     "end_date": "2026-03-23T02:45:00Z", "pre_game_price": 0.0,
     "question": "Wichita State Shockers vs. Oklahoma State Cowboys"},
    {"name": "OK State", "token_id": "89302075388198737830729432683165030241515453053580324459392343590522509858776",
     "end_date": "2026-03-23T02:45:00Z", "pre_game_price": 0.0,
     "question": "Wichita State Shockers vs. Oklahoma State Cowboys"},

    # Wave 8: 01:00 UTC Mar 23 kickoff → end ~03:15 UTC Mar 23
    {"name": "St Josephs", "token_id": "112652802159217920087017782611634292594928879918358911881472187792967025233918",
     "end_date": "2026-03-23T03:15:00Z", "pre_game_price": 0.0,
     "question": "Saint Joseph's Hawks vs. California Golden Bears"},
    {"name": "California", "token_id": "22702943734666043214507328839211804832941905455681915297791708800380279575986",
     "end_date": "2026-03-23T03:15:00Z", "pre_game_price": 0.0,
     "question": "Saint Joseph's Hawks vs. California Golden Bears"},
]

# --- Parameters (TIGHTER than soccer — NCAAB near-res is untested) ---
MIN_NEAR_RES_PRICE = 0.88  # Higher threshold — basketball has more comebacks
MAX_NEAR_RES_PRICE = 0.97
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 15  # Tighter — only last 15 min of game
MIN_SPEND = 1.0
MAX_SPEND_PER_TRADE = 14.0  # Smaller since untested
PCT_OF_BALANCE = 0.22

BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        try:
            bp = float(client.get_price(w["token_id"], "buy")["price"])
            if bp > 0.01:
                w["pre_game_price"] = bp
                print(f"  {w['name']:14s} pre-game: {bp:.3f}")
        except:
            pass


def check_and_buy(client, watch_list):
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)

    print(f"\n--- NCAAB Check #{check_and_buy.count} at {now.strftime('%H:%M:%S')} UTC ---")
    print(f"  Balance: ${balance:.2f}")
    check_and_buy.count += 1

    for w in watch_list:
        if not w["token_id"] or w["token_id"] in BOUGHT:
            continue
        try:
            buy_price = float(client.get_price(w["token_id"], "buy")["price"])
            sell_price = float(client.get_price(w["token_id"], "sell")["price"])

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
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"ncaab-mar22-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"NCAAB Mar22 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"NCAAB NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']:14s} ERROR: {err}")

check_and_buy.count = 1


if __name__ == "__main__":
    print(f"=== NCAAB March Madness 2nd Round Near-Res Monitor ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"=== {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games) ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Sizing: MAX_SPEND=${MAX_SPEND_PER_TRADE}, PCT={PCT_OF_BALANCE}, "
          f"MIN_SPEND=${MIN_SPEND}")

    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run for 12 hours (covers all games through 03:15 UTC Mar 23)
    for i in range(720):
        check_and_buy(client, ALL_GAMES)
        time.sleep(60)
