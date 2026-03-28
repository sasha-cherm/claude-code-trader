#!/usr/bin/env python3
"""
CS2 BLAST Open Rotterdam Semi-Finals Monitor — March 28, 2026.

Semi 1: Vitality vs Aurora — 14:00 UTC (Vitality 86.5% fav, skip)
Semi 2: NAVI vs Parivision — 17:30 UTC (COIN FLIP — best target)

Uses "make it to Grand Final" markets as proxy for semi-final winner.
No fixed end_date — CS2 BO3 matches have variable length.
Instead: buy when price >= 0.85 AND jump >= 0.20 (no time filter).

Launch at ~13:00 UTC. Runs until ~21:30 UTC.
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

TOKENS = [
    {"name": "NAVI GF", "token_id": "87229934369506113492248930745163521097189042764140382556059868275243336164685",
     "pre_game_price": 0.0, "question": "BLAST Semi NAVI vs Parivision"},
    {"name": "Parivision GF", "token_id": "29205866971203347148922098418153867936188868484015039734218937982145080082152",
     "pre_game_price": 0.0, "question": "BLAST Semi NAVI vs Parivision"},
]

MIN_PRICE = 0.85
MAX_PRICE = 0.96
MIN_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_SPEND = 8.0
MIN_SPEND = 1.0
PCT_BAL = 0.28
BOUGHT = set()


def main():
    print("=== CS2 BLAST Semi Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

    client = get_client()
    bal = get_usdc_balance(client)
    print(f"Balance: ${bal:.2f}\n")

    # Snapshot pre-game prices
    for t in TOKENS:
        try:
            info = client.get_price(t["token_id"], "buy")
            p = float(info.get("price", 0))
            if p > 0.01:
                t["pre_game_price"] = p
                print(f"  Pre-game {t['name']}: {p:.3f}")
        except Exception as e:
            print(f"  Pre-game {t['name']}: ERROR {e}")

    end_time = datetime(2026, 3, 28, 21, 30, tzinfo=timezone.utc)
    check_count = 0

    while datetime.now(timezone.utc) < end_time:
        now = datetime.now(timezone.utc)
        bal = get_usdc_balance(client)
        check_count += 1
        print(f"\n--- Check #{check_count} at {now.strftime('%H:%M:%S')} UTC | Balance: ${bal:.2f} ---")

        for t in TOKENS:
            if t["token_id"] in BOUGHT:
                continue
            try:
                buy_info = client.get_price(t["token_id"], "buy")
                sell_info = client.get_price(t["token_id"], "sell")
                buy_p = float(buy_info.get("price", 0))
                sell_p = float(sell_info.get("price", 0))

                if t["pre_game_price"] == 0.0:
                    if buy_p > 0.01:
                        t["pre_game_price"] = buy_p
                    continue

                jump = buy_p - t["pre_game_price"]
                spread = buy_p - sell_p

                trigger = (
                    buy_p >= MIN_PRICE and
                    buy_p <= MAX_PRICE and
                    jump >= MIN_JUMP and
                    abs(spread) < MAX_SPREAD and
                    bal >= MIN_SPEND
                )

                if jump > 0.05 or buy_p >= 0.80:
                    status = "***BUY***" if trigger else ""
                    print(f"  {t['name']:16s} buy={buy_p:.3f} sell={sell_p:.3f} "
                          f"spread={spread:.3f} jump={jump:+.3f} {status}")

                if trigger:
                    # Block opponent
                    for o in TOKENS:
                        if o["question"] == t["question"] and o["token_id"] != t["token_id"]:
                            BOUGHT.add(o["token_id"])

                    spend = min(MAX_SPEND, bal * PCT_BAL)
                    if spend < MIN_SPEND:
                        continue
                    print(f"\n  *** CS2 NEAR-RES BUY {t['name']} @ ~{sell_p:.3f} for ${spend:.2f} ***")
                    result = place_near_res_buy(client, t["token_id"], spend, tag=t['name'])
                    if result and result.get("filled"):
                        fp = result["price"]
                        time.sleep(2)
                        shares = get_actual_shares(client, t["token_id"])
                        state = load_state()
                        state["positions"].append({
                            "token_id": t["token_id"],
                            "market_id": f"cs2-blast-semi-{t['name'].lower().replace(' ', '-')}",
                            "question": t["question"],
                            "side": "YES",
                            "entry_price": fp,
                            "fair_price": min(fp + 0.08, 0.99),
                            "edge": jump,
                            "size_usdc": spend,
                            "shares": shares if shares > 0 else spend / fp,
                            "end_date": "2026-03-29T00:00:00Z",
                            "days_left_at_entry": 0.01,
                            "opened_at": str(now),
                            "research_note": f"CS2 near-res: price jumped {jump:+.2f} from {t['pre_game_price']:.2f}"
                        })
                        save_state(state)
                        BOUGHT.add(t["token_id"])
                        send(f"CS2 BUY {t['name']} @ {fp:.3f} for ${spend:.2f} ({shares:.1f}sh)")
                        bal = get_usdc_balance(client)
            except Exception as e:
                if "404" not in str(e):
                    print(f"  {t['name']}: ERROR {e}")

        time.sleep(90)

    final = get_usdc_balance(client)
    print(f"\n=== CS2 monitor ended. Balance: ${final:.2f} ===")
    send(f"CS2 BLAST semi monitor ended. Balance: ${final:.2f}")


if __name__ == "__main__":
    main()
