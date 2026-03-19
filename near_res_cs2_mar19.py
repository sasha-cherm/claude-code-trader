#!/usr/bin/env python3
"""
CS2 near-resolution monitor for BLAST Open Rotterdam Group B — March 19, 2026.
4 BO3 matches. Strategy: buy when a team wins map 1 and leads map 2 (price 0.92+).
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

CS2_MATCHES = [
    # PARIVISION vs NIP (BO3) — ~16:00 UTC start, ~19:00 end
    {"name": "PARIVISION", "token_id": "113008433113230105947013984297397493271706363061080351095559172103146900012538",
     "end_date": "2026-03-19T19:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: PARIVISION vs NIP (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "NIP", "token_id": "54975756741700526651182388742103546205551522433650567751050274150295578589722",
     "end_date": "2026-03-19T19:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: PARIVISION vs NIP (BO3) - BLAST Open Rotterdam Group B"},

    # Spirit vs Liquid (BO3) — ~18:30 UTC start, ~21:30 end
    {"name": "Spirit", "token_id": "114669676407805460971698922652742498488387915573275983788800351522266462485372",
     "end_date": "2026-03-19T21:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Spirit vs Liquid (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "Liquid", "token_id": "38609193713454205875538035119899422736318755832346286717308480891545960530398",
     "end_date": "2026-03-19T21:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Spirit vs Liquid (BO3) - BLAST Open Rotterdam Group B"},

    # MOUZ vs TheMongolz (BO3) — ~21:00 UTC start, ~00:00 end
    {"name": "MOUZ", "token_id": "24285588022052945923996431490851892393743393159314189575979559612414828440951",
     "end_date": "2026-03-20T00:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: MOUZ vs TheMongolz (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "TheMongolz", "token_id": "56815819747865972453156498886447841957725665840438707133814970840628338530619",
     "end_date": "2026-03-20T00:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: MOUZ vs TheMongolz (BO3) - BLAST Open Rotterdam Group B"},

    # Vitality vs 9z (BO3) — ~23:30 UTC start, ~02:30 end
    {"name": "Vitality", "token_id": "54126564405132614762593512892960192968964543114251475689182967725921987635651",
     "end_date": "2026-03-20T02:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Vitality vs 9z (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "9z", "token_id": "17171783884498377954208329546430684553687602313155553444946527121256726438154",
     "end_date": "2026-03-20T02:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Vitality vs 9z (BO3) - BLAST Open Rotterdam Group B"},
]

# CS2 near-res params — same as Mar 18
MIN_NEAR_RES_PRICE = 0.92
MAX_NEAR_RES_PRICE = 0.97
MIN_PRICE_JUMP = 0.08
MAX_SPREAD = 0.03
MAX_SPEND_PER_TRADE = 8.0
MIN_SPEND = 2.0
PCT_OF_BALANCE = 0.22
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
            buy_info = client.get_price(w["token_id"], "buy")
            sell_info = client.get_price(w["token_id"], "sell")
            buy_price = float(buy_info.get("price", 0))
            sell_price = float(sell_info.get("price", 0))
            jump = buy_price - w["pre_game_price"]
            spread = buy_price - sell_price

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                abs(spread) < MAX_SPREAD and
                balance >= MIN_SPEND
            )

            if abs(jump) > 0.03 or buy_price >= 0.85:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:12s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                now = datetime.now(timezone.utc)
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(1.5)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-cs2-{w['name'].lower()}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.08, 0.99),
                        "edge": 0.08,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": 0,
                        "opened_at": str(now),
                        "research_note": f"CS2 near-res: {w['name']} price jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}. BO3 likely near 2-0 sweep.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"CS2 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            print(f"  {w['name']:12s} ERROR: {e}")


def main():
    print(f"=== CS2 BLAST Open Rotterdam Group B Near-Res Monitor ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}")
    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, CS2_MATCHES)

    for i in range(720):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        try:
            for w in CS2_MATCHES:
                if w["pre_game_price"] == 0.0:
                    try:
                        info = client.get_price(w["token_id"], "buy")
                        w["pre_game_price"] = float(info.get("price", 0))
                    except:
                        pass
            check_and_buy(client, CS2_MATCHES)
        except Exception as e:
            print(f"  ERROR in check: {e}")
        time.sleep(60)

    print(f"\n=== CS2 Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
