#!/usr/bin/env python3
"""
FIXED near-resolution monitor for NBA Monday March 17, 2026.
End times corrected to actual game END times (not tipoff times).

NBA games are ~2.5h long. WBC baseball ~3h.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

# Corrected end times: tipoff + 2.5h for NBA, tipoff + 3h for WBC
ALL_GAMES = [
    # Early NBA (7pm ET tipoff = 23:00 UTC, end ~01:30 UTC)
    {"name": "Heat",     "token_id": "6087401712754856840770710788808797544168435146436671864529302588463415816366",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Heat vs. Hornets"},
    {"name": "Hornets",  "token_id": "1809681482951707674012395356212140615234154334581743465339144085976054396593",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Heat vs. Hornets"},
    {"name": "Pistons",  "token_id": "82790834489296792548001754818893068269706014238351914889123814624040902456072",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Pistons vs. Wizards"},
    {"name": "Wizards",  "token_id": "17099481025837246885779189828657260235952615421316280987531483773805113695816",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Pistons vs. Wizards"},
    {"name": "Thunder",  "token_id": "88536762430284806618501517499086969073586167153112020992659151202063177650409",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Thunder vs. Magic"},
    {"name": "Magic",    "token_id": "67157385670249294994199439700858827590636077799054551741558747573219806661042",
     "end_date": "2026-03-18T01:30:00Z", "pre_game_price": 0.0, "question": "Thunder vs. Magic"},
    # Knicks/Pacers (7:30pm ET = 23:30 UTC, end ~02:00 UTC)
    {"name": "Knicks",   "token_id": "48913018712744652147761122907336875899748540751417363008067660746220309136543",
     "end_date": "2026-03-18T02:00:00Z", "pre_game_price": 0.0, "question": "Pacers vs. Knicks"},
    {"name": "Pacers",   "token_id": "1679112624969420181923996019121447562057381977286350555544211427951161455439",
     "end_date": "2026-03-18T02:00:00Z", "pre_game_price": 0.0, "question": "Pacers vs. Knicks"},
    # Suns/TWolves + Cavs/Bucks (8pm ET = 00:00 UTC, end ~02:30 UTC)
    {"name": "T-Wolves", "token_id": "26286884867755304434249902063185317489810829034431393315833232083825319762413",
     "end_date": "2026-03-18T02:30:00Z", "pre_game_price": 0.0, "question": "Suns vs. Timberwolves"},
    {"name": "Suns",     "token_id": "40787386264766693992685437646585609288278675850761087200834438575462138132923",
     "end_date": "2026-03-18T02:30:00Z", "pre_game_price": 0.0, "question": "Suns vs. Timberwolves"},
    {"name": "Cavaliers","token_id": "46440330975859580393340282172990358197170670732251031556467708289612450987806",
     "end_date": "2026-03-18T02:30:00Z", "pre_game_price": 0.0, "question": "Cavaliers vs. Bucks"},
    {"name": "Bucks",    "token_id": "64341170344191134568512415672650723351060471127659473427491129766132576743246",
     "end_date": "2026-03-18T02:30:00Z", "pre_game_price": 0.0, "question": "Cavaliers vs. Bucks"},
    # WBC Final (8pm ET = 00:00 UTC, baseball ~3h, end ~03:00 UTC)
    {"name": "USA (WBC)", "token_id": "74703519327710712757553592788004847524143089285144132580937499588474411589292",
     "end_date": "2026-03-18T03:30:00Z", "pre_game_price": 0.0, "question": "Will USA win the 2026 World Baseball Classic?"},
    {"name": "Venezuela (WBC)", "token_id": "46211170528412621902777844924399001591628628991357980873756319774571327094924",
     "end_date": "2026-03-18T03:30:00Z", "pre_game_price": 0.0, "question": "Will Venezuela win the 2026 World Baseball Classic?"},
    # Late NBA (10pm ET = 02:00 UTC, end ~04:30 UTC)
    {"name": "Spurs",    "token_id": "40006445388185338955358702887295798674861557428409114926293823097294095633717",
     "end_date": "2026-03-18T04:30:00Z", "pre_game_price": 0.0, "question": "Spurs vs. Kings"},
    {"name": "Kings",    "token_id": "54902179503132446102225555939609907716122360741752524195755710176925031129640",
     "end_date": "2026-03-18T04:30:00Z", "pre_game_price": 0.0, "question": "Spurs vs. Kings"},
    {"name": "Nuggets",  "token_id": "34327481997639022172875618434237183296228497020847891588188641734820895853462",
     "end_date": "2026-03-18T04:30:00Z", "pre_game_price": 0.0, "question": "76ers vs. Nuggets"},
    {"name": "76ers",    "token_id": "44821680511644120493004277882643103748901075608173589443724801389401638901128",
     "end_date": "2026-03-18T04:30:00Z", "pre_game_price": 0.0, "question": "76ers vs. Nuggets"},
]

MAX_SPEND_PER_TRADE = 8.0
MIN_SPEND = 2.0
MIN_PRICE_JUMP = 0.18
MIN_NEAR_RES_PRICE = 0.78
MAX_NEAR_RES_PRICE = 0.93
MAX_SPREAD = 0.08
MAX_MINS_TO_END = 35
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

            status = "***BUY***" if trigger else ""
            print(f"  {w['name']:18s} buy={buy_price:.3f} sell={sell_price:.3f} "
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
                        "market_id": f"near-res-nba-{w['name'].lower().replace(' ', '-').replace('(wbc)', 'wbc')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.15, 0.95),
                        "edge": 0.10,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_to_end / 1440,
                        "opened_at": str(now),
                        "research_note": f"Near-res: {w['name']} price jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"NBA NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}, {mins_to_end:.0f}min left")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            print(f"  {w['name']:18s} ERROR: {e}")


def main():
    print(f"=== NBA FIXED Near-Res Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    client = get_client()

    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run for up to 6 hours (covers all games through late NBA)
    for i in range(360):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        check_and_buy(client, ALL_GAMES)

        # Stop when all games ended 30+ min ago
        all_ended = all(
            (now - datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))).total_seconds() > 1800
            for w in ALL_GAMES
        )
        if all_ended:
            print("\nAll games ended 30+ min ago. Stopping.")
            break
        time.sleep(60)

    print(f"\n=== NBA FIXED Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
