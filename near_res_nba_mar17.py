#!/usr/bin/env python3
"""
Near-resolution monitor for NBA Monday March 17, 2026.

4 games:
  Early (tipoff ~21:30 UTC, near-res ~23:30 UTC):
    - Suns vs. Timberwolves (T-Wolves fav 0.605, $42.9K vol)
    - Cavaliers vs. Bucks (Cavs fav 0.785, $25.7K vol)
  Late (tipoff ~23:30 UTC, near-res ~01:30 UTC Mar 18):
    - Spurs vs. Kings ($30.7K vol)
    - 76ers vs. Nuggets (Nuggets fav 0.85, $13.3K vol)

Usage:
  python3 near_res_nba_mar17.py          # All 4 games
  python3 near_res_nba_mar17.py --late   # Only late games (Spurs/Kings, 76ers/Nuggets)
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

EARLY_GAMES = [
    {
        "name": "T-Wolves",
        "token_id": "26286884867755304434249902063185317489810829034431393315833232083825319762413",
        "end_date": "2026-03-18T00:00:00Z",
        "pre_game_price": 0.0,
        "question": "Suns vs. Timberwolves",
    },
    {
        "name": "Suns",
        "token_id": "40787386264766693992685437646585609288278675850761087200834438575462138132923",
        "end_date": "2026-03-18T00:00:00Z",
        "pre_game_price": 0.0,
        "question": "Suns vs. Timberwolves",
    },
    {
        "name": "Cavaliers",
        "token_id": "46440330975859580393340282172990358197170670732251031556467708289612450987806",
        "end_date": "2026-03-18T00:00:00Z",
        "pre_game_price": 0.0,
        "question": "Cavaliers vs. Bucks",
    },
    {
        "name": "Bucks",
        "token_id": "64341170344191134568512415672650723351060471127659473427491129766132576743246",
        "end_date": "2026-03-18T00:00:00Z",
        "pre_game_price": 0.0,
        "question": "Cavaliers vs. Bucks",
    },
]

LATE_GAMES = [
    {
        "name": "Spurs",
        "token_id": "40006445388185338955358702887295798674861557428409114926293823097294095633717",
        "end_date": "2026-03-18T02:00:00Z",
        "pre_game_price": 0.0,
        "question": "Spurs vs. Kings",
    },
    {
        "name": "Kings",
        "token_id": "54902179503132446102225555939609907716122360741752524195755710176925031129640",
        "end_date": "2026-03-18T02:00:00Z",
        "pre_game_price": 0.0,
        "question": "Spurs vs. Kings",
    },
    {
        "name": "Nuggets",
        "token_id": "34327481997639022172875618434237183296228497020847891588188641734820895853462",
        "end_date": "2026-03-18T02:00:00Z",
        "pre_game_price": 0.0,
        "question": "76ers vs. Nuggets",
    },
    {
        "name": "76ers",
        "token_id": "44821680511644120493004277882643103748901075608173589443724801389401638901128",
        "end_date": "2026-03-18T02:00:00Z",
        "pre_game_price": 0.0,
        "question": "76ers vs. Nuggets",
    },
]

MAX_SPEND_PER_TRADE = 20.0
MIN_SPEND = 3.0
MIN_PRICE_JUMP = 0.15
MIN_NEAR_RES_PRICE = 0.62
MAX_NEAR_RES_PRICE = 0.85
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


def check_prices(client, watch_list):
    results = []
    for watch in watch_list:
        if not watch["token_id"]:
            continue
        try:
            price_info = client.get_price(watch["token_id"], "buy")
            price = float(price_info.get("price", 0))
            sell_info = client.get_price(watch["token_id"], "sell")
            sell_price = float(sell_info.get("price", 0))
            jump = price - watch["pre_game_price"]
            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(watch["end_date"].replace("Z", "+00:00"))
            mins_to_end = (end - now).total_seconds() / 60

            results.append({
                **watch,
                "current_buy": price,
                "current_sell": sell_price,
                "jump": jump,
                "mins_to_end": mins_to_end,
            })

            status = "***BUY SIGNAL***" if (
                price >= MIN_NEAR_RES_PRICE and
                price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                mins_to_end < 60
            ) else ""

            print(f"  {watch['name']:14s} buy={price:.3f} sell={sell_price:.3f} "
                  f"jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")
        except Exception as e:
            print(f"  {watch['name']:14s} ERROR: {e}")
    return results


def try_buy(client, market, balance):
    tid = market["token_id"]
    name = market["name"]
    price = market["current_buy"]

    if tid in BOUGHT:
        print(f"  Already bought {name}, skipping")
        return False

    spend = min(MAX_SPEND_PER_TRADE, balance * 0.20)
    if spend < MIN_SPEND:
        print(f"  Insufficient balance for {name} (need ${MIN_SPEND}, have ${balance:.2f})")
        return False

    print(f"\n  *** BUYING {name} YES @ {price:.3f} for ${spend:.2f} ***")
    result = place_market_buy(client, tid, spend)

    if result:
        time.sleep(1.5)
        shares = get_actual_shares(client, tid)

        state = load_state()
        pos = {
            "token_id": tid,
            "market_id": f"near-res-nba-{name.lower().replace(' ', '-')}",
            "question": market["question"],
            "side": "YES",
            "entry_price": price,
            "fair_price": min(price + 0.15, 0.95),
            "edge": 0.10,
            "size_usdc": spend,
            "shares": shares if shares > 0 else spend / price,
            "end_date": market["end_date"],
            "days_left_at_entry": market["mins_to_end"] / 1440,
            "opened_at": str(datetime.now(timezone.utc)),
            "research_note": f"NBA Near-resolution: {name} price jumped {market['jump']:+.3f} from pre-game {market['pre_game_price']:.3f}",
        }
        state["positions"].append(pos)
        save_state(state)

        BOUGHT.add(tid)
        send(f"NBA NEAR-RES BUY: {name} YES @ {price:.3f}\n  ${spend:.2f} ({shares:.2f} shares)\n  Jump: {market['jump']:+.3f}, {market['mins_to_end']:.0f} min to market end")
        print(f"  Success: {shares:.2f} shares")
        return True
    else:
        print(f"  BUY FAILED for {name}")
        return False


def main():
    if "--late" in sys.argv:
        watch = LATE_GAMES
        label = "NBA Late: Spurs/Kings + 76ers/Nuggets"
    else:
        watch = EARLY_GAMES + LATE_GAMES
        label = "NBA All 4 Monday games"

    print(f"=== NBA Near-Res Monitor ({label}) Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, watch)

    max_iterations = 300  # 5 hours
    for i in range(max_iterations):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")

        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        results = check_prices(client, watch)

        for r in results:
            if (r["jump"] >= MIN_PRICE_JUMP and
                r["current_buy"] >= MIN_NEAR_RES_PRICE and
                r["current_buy"] <= MAX_NEAR_RES_PRICE and
                r["mins_to_end"] < 60 and
                r["token_id"] not in BOUGHT and
                balance >= MIN_SPEND):

                try_buy(client, r, balance)
                balance = get_usdc_balance(client)

        active = [r for r in results if r["mins_to_end"] > -30]
        if not active:
            print("\nAll monitored games ended. Stopping.")
            break

        time.sleep(60)

    print(f"\n=== NBA Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
