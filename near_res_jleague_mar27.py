#!/usr/bin/env python3
"""
Quick near-res monitor for J-League: Vissel Kobe vs Sanfrecce Hiroshima.
Kickoff 10:00 UTC Mar 27. Game end ~11:45 UTC.
Near-res window: 11:25-11:45 UTC.

Runs until 12:00 UTC then exits.
"""
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_near_res_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    {"name": "Vissel Kobe", "token_id": "104407276203320141812204194890945827206145527099854901879801853931289777694158",
     "end_date": "2026-03-27T11:45:00Z", "pre_game_price": 0.0,
     "question": "Vissel Kobe vs Sanfrecce Hiroshima"},
    {"name": "Sanfrecce", "token_id": "21921428906013484768782105534033895823142506468562300288940930758174671874719",
     "end_date": "2026-03-27T11:45:00Z", "pre_game_price": 0.0,
     "question": "Vissel Kobe vs Sanfrecce Hiroshima"},
]

# Validated params
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 5.0
PCT_OF_BALANCE = 0.20
POLL_INTERVAL = 60

def main():
    client = get_client()
    bought = set()
    bought_questions = set()
    check_num = 0

    print(f"=== J-League Near-Res Monitor ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Games: {len(ALL_GAMES)} tokens\n")

    # Store initial prices
    for g in ALL_GAMES:
        try:
            p = client.get_price(g["token_id"], "sell")
            g["pre_game_price"] = float(p.get("price", 0))
            print(f"  {g['name']}: pre-game ask={g['pre_game_price']:.3f}")
        except:
            g["pre_game_price"] = 0.50

    deadline = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)

    while datetime.now(timezone.utc) < deadline:
        check_num += 1
        now = datetime.now(timezone.utc)
        balance = get_usdc_balance(client)
        ts = now.strftime("%H:%M:%S UTC")

        print(f"\n--- Check #{check_num} at {ts} ---")
        print(f"  Balance: ${balance:.2f}")

        for g in ALL_GAMES:
            tid = g["token_id"]
            name = g["name"]
            q = g["question"]

            if tid in bought or q in bought_questions:
                continue

            try:
                end_dt = datetime.fromisoformat(g["end_date"].replace("Z", "+00:00"))
                mins_left = (end_dt - now).total_seconds() / 60.0

                buy_info = client.get_price(tid, "buy")
                sell_info = client.get_price(tid, "sell")
                buy_price = float(buy_info.get("price", 0))
                sell_price = float(sell_info.get("price", 0))
                spread = sell_price - buy_price
                jump = sell_price - g.get("pre_game_price", 0.50)

                print(f"  {name:15s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins={mins_left:.0f} ")

                if (sell_price >= MIN_NEAR_RES_PRICE and
                    sell_price <= MAX_NEAR_RES_PRICE and
                    jump >= MIN_PRICE_JUMP and
                    abs(spread) < MAX_SPREAD and
                    mins_left <= MAX_MINS_TO_END and
                    mins_left > 0 and
                    balance >= 5.0):

                    spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                    spend = max(spend, 5.0)

                    print(f"  >>> SIGNAL: {name} @ {sell_price:.3f}, spending ${spend:.2f}")
                    result = place_near_res_buy(client, tid, spend, tag=name)

                    if result:
                        bought.add(tid)
                        bought_questions.add(q)
                        send(f"J1 NEAR-RES BUY: {name} @ {result['price']:.3f}, "
                             f"${spend:.2f}, {result['shares']:.1f}sh")

                        # Track in state
                        state = load_state()
                        state["positions"].append({
                            "token_id": tid,
                            "question": q,
                            "side": "YES",
                            "entry_price": result["price"],
                            "size_usdc": spend,
                            "shares": result["shares"],
                            "opened_at": now.isoformat(),
                            "source": "jleague_near_res"
                        })
                        save_state(state)
                        balance = get_usdc_balance(client)

            except Exception as e:
                print(f"  {name}: ERROR - {e}")

        time.sleep(POLL_INTERVAL)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} ===")

if __name__ == "__main__":
    main()
