#!/usr/bin/env python3
"""
Near-resolution monitor for extra matches March 17, 2026.
Serie B (19:00 kickoff), Palermo (18:00), Lanus/Newell's (22:00 kickoff).
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

WATCH = [
    # Palermo vs Juve Stabia — kickoff 18:00 UTC, game ends ~19:45 UTC
    {"name": "Palermo", "token_id": "39607423036080917125625403708620527573433229106745210207214893095586992694013", "end_date": "2026-03-17T19:45:00Z", "pre_game_price": 0.0, "question": "Will Palermo FC win on 2026-03-17?"},
    {"name": "Juve Stabia", "token_id": "88763658298836840031972921700527457528838944570283663799181828863173398833697", "end_date": "2026-03-17T19:45:00Z", "pre_game_price": 0.0, "question": "Will SS Juve Stabia win on 2026-03-17?"},
    # Serie B 19:00 UTC kickoffs, games end ~20:45 UTC
    {"name": "Spezia", "token_id": "51908224757825392923431331909058849320511152143615545833947939794502046966882", "end_date": "2026-03-17T20:45:00Z", "pre_game_price": 0.0, "question": "Will Spezia Calcio win on 2026-03-17?"},
    {"name": "Empoli", "token_id": "29014849203347663233534476982214933499475671524127390474811152368819083345592", "end_date": "2026-03-17T20:45:00Z", "pre_game_price": 0.0, "question": "Will Empoli FC win on 2026-03-17?"},
    {"name": "Reggiana", "token_id": "110845685456576469926533281033699955838625080993672260129773239944510162151066", "end_date": "2026-03-17T20:45:00Z", "pre_game_price": 0.0, "question": "Will AC Reggiana 1919 win on 2026-03-17?"},
    {"name": "Monza", "token_id": "28041656184088130910699205140130839530034401960083675948303900749479905066059", "end_date": "2026-03-17T20:45:00Z", "pre_game_price": 0.0, "question": "Will AC Monza win on 2026-03-17?"},
    # Argentine league — Lanus vs Newell's, 22:00 UTC kickoff, ends ~23:45 UTC
    {"name": "Lanus", "token_id": "93496908578751101643436946768480926063825144930841458552813170692679862657654", "end_date": "2026-03-17T23:45:00Z", "pre_game_price": 0.0, "question": "Will CA Lanús win on 2026-03-17?"},
    {"name": "Newell's", "token_id": "35454247316034561440370063454582321698598955651977394622798573874464503098586", "end_date": "2026-03-17T23:45:00Z", "pre_game_price": 0.0, "question": "Will CA Newell's Old Boys win on 2026-03-17?"},
]

MAX_SPEND_PER_TRADE = 8.0
MIN_SPEND = 2.0
MIN_PRICE_JUMP = 0.18
MIN_NEAR_RES_PRICE = 0.80
MAX_NEAR_RES_PRICE = 0.93
MAX_SPREAD = 0.08
MAX_MINS_TO_END = 25
PCT_OF_BALANCE = 0.20  # Smaller than CL — lower tier leagues
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
        try:
            price_info = client.get_price(watch["token_id"], "buy")
            price = float(price_info.get("price", 0))
            sell_info = client.get_price(watch["token_id"], "sell")
            sell_price = float(sell_info.get("price", 0))
            jump = price - watch["pre_game_price"]
            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(watch["end_date"].replace("Z", "+00:00"))
            mins_to_end = (end - now).total_seconds() / 60

            results.append({**watch, "current_buy": price, "current_sell": sell_price, "jump": jump, "mins_to_end": mins_to_end})

            spread = price - sell_price
            status = "***BUY***" if (
                price >= MIN_NEAR_RES_PRICE and price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and mins_to_end < MAX_MINS_TO_END and spread < MAX_SPREAD
            ) else ""
            print(f"  {watch['name']:14s} buy={price:.3f} sell={sell_price:.3f} spread={spread:.3f} jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")
        except Exception as e:
            print(f"  {watch['name']:14s} ERROR: {e}")
    return results


def try_buy(client, market, balance):
    tid = market["token_id"]
    name = market["name"]
    price = market["current_buy"]

    if tid in BOUGHT:
        return False

    spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
    if spend < MIN_SPEND:
        print(f"  Insufficient balance for {name}")
        return False

    print(f"\n  *** BUYING {name} YES @ {price:.3f} for ${spend:.2f} ***")
    result = place_market_buy(client, tid, spend)

    if result:
        time.sleep(1.5)
        shares = get_actual_shares(client, tid)
        state = load_state()
        pos = {
            "token_id": tid,
            "market_id": f"near-res-extra-{name.lower().replace(' ', '-')}",
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
            "research_note": f"Extra near-res: {name} price jumped {market['jump']:+.3f} from pre-game {market['pre_game_price']:.3f}",
        }
        state["positions"].append(pos)
        save_state(state)
        BOUGHT.add(tid)
        send(f"EXTRA NEAR-RES BUY: {name} YES @ {price:.3f}\n  ${spend:.2f} ({shares:.2f} shares)")
        print(f"  Success: {shares:.2f} shares")
        return True
    else:
        print(f"  BUY FAILED for {name}")
        return False


def main():
    print(f"=== Extra Near-Res Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, WATCH)

    for i in range(480):  # 8 hours
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")

        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        results = check_prices(client, WATCH)

        for r in results:
            spread = r["current_buy"] - r["current_sell"]
            if (r["jump"] >= MIN_PRICE_JUMP and r["current_buy"] >= MIN_NEAR_RES_PRICE and
                r["current_buy"] <= MAX_NEAR_RES_PRICE and r["mins_to_end"] < MAX_MINS_TO_END and
                spread < MAX_SPREAD and r["token_id"] not in BOUGHT and balance >= MIN_SPEND):
                try_buy(client, r, balance)
                balance = get_usdc_balance(client)

        # Terminate when all markets are 30+ min past end
        now_ts = datetime.now(timezone.utc)
        all_ended = all(
            (now_ts - datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))).total_seconds() > 1800
            for w in WATCH
        )
        if all_ended:
            print("\nAll extra markets ended. Stopping.")
            break
        if not results:
            print("  (API error, retrying)")

        time.sleep(60)

    print(f"\n=== Extra Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
