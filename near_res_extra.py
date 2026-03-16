#!/usr/bin/env python3
"""
Additional near-resolution monitor for March 16 13:00 UTC session.
Covers: KHL hockey (14:00-16:30 UTC) + Romanian Liga 1 (15:30 UTC)
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

WATCH = [
    # KHL ending 14:00 UTC
    {"name": "Metallurg", "token_id": "25446417880723784668810823836564804396267102395989115841378268611503180560633",
     "end_date": "2026-03-16T14:00:00Z", "pre_game_price": 0.625,
     "question": "KHL: Metallurg Magnitogorsk vs. Avtomobilist Yekaterinburg"},
    {"name": "Traktor", "token_id": "102445348972133539075212417238270963926949038503767438724007761624279635190819",
     "end_date": "2026-03-16T14:00:00Z", "pre_game_price": 0.525,
     "question": "KHL: Traktor vs. SKA St. Petersburg"},
    {"name": "SKA", "token_id": "80900615754109075657409698701421078668959610867196613862308792487066677281142",
     "end_date": "2026-03-16T14:00:00Z", "pre_game_price": 0.475,
     "question": "KHL: Traktor vs. SKA St. Petersburg"},
    # KHL ending 14:30 UTC
    {"name": "Barys", "token_id": "88716752478830862362153289418704016721208424861266538407298835399316522988838",
     "end_date": "2026-03-16T14:30:00Z", "pre_game_price": 0.555,
     "question": "KHL: Barys Astana vs. Admiral Vladivostok"},
    {"name": "Admiral", "token_id": "15499574027760533570630800126988710966383807214656594313350455847027305722365",
     "end_date": "2026-03-16T14:30:00Z", "pre_game_price": 0.445,
     "question": "KHL: Barys Astana vs. Admiral Vladivostok"},
    # Romanian Liga 1 ending 15:30 UTC
    {"name": "Botosani", "token_id": "11966401116432503531832125121600326522865483551617447834464344148388531861973",
     "end_date": "2026-03-16T15:30:00Z", "pre_game_price": 0.63,
     "question": "Will FC Botoşani win on 2026-03-16?"},
    # KHL ending 16:00 UTC
    {"name": "Torpedo", "token_id": "67529056151897486164936441309965252669782434662984332055946438871842305059136",
     "end_date": "2026-03-16T16:00:00Z", "pre_game_price": 0.595,
     "question": "KHL: Torpedo vs. Neftekhimik Nizhnekamsk"},
    # KHL ending 16:30 UTC
    {"name": "Severstal", "token_id": "70811650733669241589466398022291460739910567200216133053116780086087182277578",
     "end_date": "2026-03-16T16:30:00Z", "pre_game_price": 0.515,
     "question": "KHL: Severstal Cherepovets vs. Ak Bars Kazan"},
    {"name": "Ak Bars", "token_id": "57694372417623885832057279166358364303586056866440525077741069260000917009144",
     "end_date": "2026-03-16T16:30:00Z", "pre_game_price": 0.485,
     "question": "KHL: Severstal Cherepovets vs. Ak Bars Kazan"},
    {"name": "Spartak Msk", "token_id": "21764918608885636308133794519022777929626619985365562657789834543282260157033",
     "end_date": "2026-03-16T16:30:00Z", "pre_game_price": 0.505,
     "question": "KHL: Spartak Moscow vs. HC Dynamo Moscow"},
    {"name": "Dynamo Msk", "token_id": "90471184570361804279738204001181651802376395949595648942986215197943031821956",
     "end_date": "2026-03-16T16:30:00Z", "pre_game_price": 0.495,
     "question": "KHL: Spartak Moscow vs. HC Dynamo Moscow"},
]

MAX_SPEND = 25.0
MIN_SPEND = 3.0
MIN_PRICE_JUMP = 0.12  # Lower threshold for hockey (shorter games, faster moves)
MIN_BUY_PRICE = 0.62
MAX_BUY_PRICE = 0.85
BOUGHT = set()


def main():
    print(f"=== Extra Near-Res Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    for i in range(200):  # ~3.3 hours
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        active = []
        for w in WATCH:
            end = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins_left = (end - now).total_seconds() / 60
            if mins_left < -30:
                continue
            active.append(w)

            try:
                buy_info = client.get_price(w["token_id"], "buy")
                buy_price = float(buy_info.get("price", 0))
                sell_info = client.get_price(w["token_id"], "sell")
                sell_price = float(sell_info.get("price", 0))
                jump = buy_price - w["pre_game_price"]

                is_signal = (
                    buy_price >= MIN_BUY_PRICE and
                    buy_price <= MAX_BUY_PRICE and
                    jump >= MIN_PRICE_JUMP and
                    mins_left < 45 and  # tighter for hockey
                    w["token_id"] not in BOUGHT
                )
                tag = "***BUY SIGNAL***" if is_signal else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"jump={jump:+.3f} mins={mins_left:.0f} {tag}")

                if is_signal and balance >= MIN_SPEND:
                    spend = min(MAX_SPEND, balance * 0.20)
                    if spend >= MIN_SPEND:
                        print(f"\n  *** BUYING {w['name']} @ {buy_price:.3f} for ${spend:.2f} ***")
                        result = place_market_buy(client, w["token_id"], spend)
                        if result:
                            time.sleep(1.5)
                            shares = get_actual_shares(client, w["token_id"])
                            state = load_state()
                            state["positions"].append({
                                "token_id": w["token_id"],
                                "market_id": f"near-res-{w['name'].lower().replace(' ', '-')}",
                                "question": w["question"],
                                "side": "YES",
                                "entry_price": buy_price,
                                "fair_price": min(buy_price + 0.15, 0.95),
                                "edge": 0.10,
                                "size_usdc": spend,
                                "shares": shares if shares > 0 else spend / buy_price,
                                "end_date": w["end_date"],
                                "days_left_at_entry": mins_left / 1440,
                                "opened_at": str(now),
                                "research_note": f"Near-res: {w['name']} price jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}",
                            })
                            save_state(state)
                            BOUGHT.add(w["token_id"])
                            send(f"NEAR-RES BUY: {w['name']} @ {buy_price:.3f}\n  ${spend:.2f} ({shares:.2f} shares)\n  Jump: {jump:+.3f}")
                            balance = get_usdc_balance(client)
                        else:
                            print(f"  BUY FAILED for {w['name']}")
            except Exception as e:
                print(f"  {w['name']:14s} ERROR: {e}")

        if not active:
            print("\nAll markets ended. Stopping.")
            break

        time.sleep(60)

    print(f"\n=== Extra Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
