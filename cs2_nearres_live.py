#!/usr/bin/env python3
"""
CS2-specific near-res monitor with NO time filter.
CS2 BO3 end times are unpredictable — a 2-0 sweep can end in 1 hour.
Uses higher price threshold (0.90+) since we can't verify map score.
Signal: price >= 0.90 with jump >= 0.25 from pre-game = team almost certainly winning.
"""
import os, sys, time, json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

GAMES = [
    # Falcons vs FURIA (ongoing)
    {"name": "Falcons", "token_id": "96152515631371174532926937362487917853962795752690359835130985596332646922176",
     "pre_game_price": 0.61, "question": "Counter-Strike: Team Falcons vs FURIA (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "FURIA", "token_id": "2116715792897421481852255923916932431938704579218893739317900084278762591545",
     "pre_game_price": 0.38, "question": "Counter-Strike: Team Falcons vs FURIA (BO3) - BLAST Open Rotterdam Group A"},
    # PARIVISION vs Vitality (starts ~18:00 UTC)
    {"name": "PARIVISION", "token_id": "7014938091910369633169807904150657321623381419444222440101393386125116555217",
     "pre_game_price": 0.16, "question": "Counter-Strike: PARIVISION vs Vitality (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "Vitality", "token_id": "10141557233740063570433717403369411773881426926727499858134434191781902173105",
     "pre_game_price": 0.83, "question": "Counter-Strike: PARIVISION vs Vitality (BO3) - BLAST Open Rotterdam Group B"},
]

MIN_PRICE = 0.90
MIN_JUMP = 0.25
MAX_SPEND = 14.0
PCT_BALANCE = 0.28
BOUGHT = set()

def run():
    client = get_client()
    print(f"=== CS2 Near-Res (no time filter) started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"Params: MIN_PRICE={MIN_PRICE}, MIN_JUMP={MIN_JUMP}, MAX_SPEND=${MAX_SPEND}")

    check = 0
    while True:
        now = datetime.now(timezone.utc)
        # Stop after 22:00 UTC (all CS2 matches done by then)
        if now.hour >= 22:
            print("22:00 UTC — CS2 matches done. Exiting.")
            break

        balance = get_usdc_balance(client)
        check += 1
        print(f"\n--- CS2 Check #{check} at {now.strftime('%H:%M:%S')} UTC | Balance: ${balance:.2f} ---")

        for g in GAMES:
            if g["token_id"] in BOUGHT:
                continue
            try:
                buy_info = client.get_price(g["token_id"], "buy")
                sell_info = client.get_price(g["token_id"], "sell")
                bp = float(buy_info.get("price", 0))
                sp = float(sell_info.get("price", 0))
                jump = bp - g["pre_game_price"]
                spread = bp - sp

                if bp >= 0.50 or abs(jump) > 0.10:
                    print(f"  {g['name']:12s} buy={bp:.3f} sell={sp:.3f} jump={jump:+.3f} spread={spread:.3f}")

                if bp >= MIN_PRICE and jump >= MIN_JUMP and abs(spread) < 0.04 and balance >= 1.0:
                    spend = min(MAX_SPEND, balance * PCT_BALANCE)
                    print(f"\n  *** CS2 BUY {g['name']} @ {bp:.3f} for ${spend:.2f} ***")
                    result = place_market_buy(client, g["token_id"], spend)
                    if result:
                        time.sleep(2)
                        shares = get_actual_shares(client, g["token_id"])
                        state = load_state()
                        state["positions"].append({
                            "token_id": g["token_id"],
                            "market_id": f"cs2-nearres-{g['name'].lower()}",
                            "question": g["question"],
                            "side": "YES",
                            "entry_price": bp,
                            "fair_price": min(bp + 0.05, 0.99),
                            "edge": jump,
                            "size_usdc": spend,
                            "shares": shares if shares > 0 else spend / bp,
                            "end_date": "2026-03-23T22:00:00Z",
                            "days_left_at_entry": 0.1,
                            "opened_at": str(now),
                            "research_note": f"CS2 near-res: {g['name']} @ {bp:.3f}, jump {jump:+.3f}",
                        })
                        save_state(state)
                        BOUGHT.add(g["token_id"])
                        for other in GAMES:
                            if other["question"] == g["question"] and other["token_id"] != g["token_id"]:
                                BOUGHT.add(other["token_id"])
                        balance = get_usdc_balance(client)
                        send(f"CS2 BUY: {g['name']} @ {bp:.3f}, ${spend:.2f} ({shares:.1f}sh)")
            except Exception as e:
                if "404" not in str(e):
                    print(f"  {g['name']:12s} ERROR: {str(e)[:60]}")

        time.sleep(30)

if __name__ == "__main__":
    run()
