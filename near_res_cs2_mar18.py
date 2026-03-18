#!/usr/bin/env python3
"""
CS2 near-resolution monitor for BLAST Open Rotterdam — March 18, 2026.
4 BO3 matches with confirmed deep liquidity and tight spreads.

Strategy: In a BO3, when a team wins map 1 and is ahead in map 2,
their price jumps to 0.90+. Buy at that point — if they close out
map 2 (2-0 sweep), the match is over and price → 0.99+.

Key difference from soccer: CS2 match duration varies (90-180 min),
so we rely on price level + jump as the near-resolution signal,
not time-to-end.
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
    # Team Falcons vs NRG (BO3) — 16:00 UTC start, ~19:00 end
    {"name": "Falcons", "token_id": "37256457514217388714065265839817343823116978545265720025999992605906359804009",
     "end_date": "2026-03-18T19:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Team Falcons vs NRG (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "NRG", "token_id": "55259988699909122829852041261444851236126631606510456730202210384723434029116",
     "end_date": "2026-03-18T19:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Team Falcons vs NRG (BO3) - BLAST Open Rotterdam Group A"},

    # Natus Vincere vs B8 (BO3) — 18:30 UTC start, ~21:30 end
    {"name": "NAVI", "token_id": "113172389520459161197945586743799247851244534566419036705594142973162667675023",
     "end_date": "2026-03-18T21:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Natus Vincere vs B8 (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "B8", "token_id": "108505646914820231031746240664643786957889226880628487763191295516382023965434",
     "end_date": "2026-03-18T21:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Natus Vincere vs B8 (BO3) - BLAST Open Rotterdam Group A"},

    # FaZe vs Aurora Gaming (BO3) — 21:00 UTC start, ~00:00 end
    {"name": "FaZe", "token_id": "12524894422245686751729991670192515426663427416410814539861658867218124084438",
     "end_date": "2026-03-19T00:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: FaZe vs Aurora Gaming (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "Aurora", "token_id": "33653527059739629905343436724995201040153324847412874782962152628893240833271",
     "end_date": "2026-03-19T00:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: FaZe vs Aurora Gaming (BO3) - BLAST Open Rotterdam Group A"},

    # FURIA vs TYLOO (BO3) — 23:30 UTC start, ~02:30 end
    {"name": "FURIA", "token_id": "39457741763261644455805579486189997714134855427860230998554403786844381880617",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: FURIA vs TYLOO (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "TYLOO", "token_id": "42693745660363258893563092829702517992260713916474310388918303467665902349229",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: FURIA vs TYLOO (BO3) - BLAST Open Rotterdam Group A"},
]

# CS2 near-res params — stricter than soccer because losing map 2 drops you to map 3
# A team at 0.92+ in a BO3 has likely won map 1 and is dominating map 2
MIN_NEAR_RES_PRICE = 0.92     # Very high confidence — likely about to 2-0 sweep
MAX_NEAR_RES_PRICE = 0.97
MIN_PRICE_JUMP = 0.08         # For favorites starting at 0.82, +0.10 is meaningful
MAX_SPREAD = 0.03             # CS2 markets have tight 1-cent spreads
MAX_SPEND_PER_TRADE = 5.0     # Conservative sizing
MIN_SPEND = 2.0
PCT_OF_BALANCE = 0.20
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

            # Print games that have moved significantly
            if abs(jump) > 0.03 or buy_price >= 0.85:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:10s} buy={buy_price:.3f} sell={sell_price:.3f} "
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
            print(f"  {w['name']:10s} ERROR: {e}")


def main():
    print(f"=== CS2 BLAST Open Rotterdam Near-Res Monitor ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}")
    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, CS2_MATCHES)

    # Run for up to 12 hours (covers all 4 matches from 16:00 to 02:30 UTC)
    for i in range(720):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        try:
            # Re-snapshot any games that haven't started (price was 0)
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
