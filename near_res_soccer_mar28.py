#!/usr/bin/env python3
"""
Near-resolution monitor for March 28, 2026 — International Friendlies.

7 friendlies + draw markets for close games.
Gamma end_date = kickoff. Actual end = kickoff + ~1:50.

Kickoff schedule (UTC):
- 14:00: Cote d'Ivoire vs Korea Republic ($8K)
- 16:00: Senegal vs Peru ($31K)
- 17:00: Canada vs Iceland ($10K), Hungary vs Slovenia ($10K), Scotland vs Japan ($16K)
- 19:30: USA vs Belgium ($11K)
- 01:00 Mar 29: Mexico vs Portugal ($88K) ← biggest target

Near-res windows (80th+ min):
- 15:25-15:50: CIV-KOR
- 17:25-17:50: SEN-PER
- 18:25-18:50: CAN-ISL, HUN-SVN, SCO-JPN
- 20:55-21:20: USA-BEL
- 02:25-02:50: MEX-POR

Launch at ~13:00 UTC. Runs until ~03:00 UTC Mar 29.

Validated params: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
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

ALL_GAMES = [
    # === Cote d'Ivoire vs Korea Republic (kickoff 14:00 UTC, end ~15:50) ===
    {"name": "Cote d'Ivoire", "token_id": "98252701172114405469137554943874896224780017438198662944127703920242767368975",
     "end_date": "2026-03-28T15:50:00Z", "pre_game_price": 0.0,
     "question": "Cote d'Ivoire vs Korea Republic"},
    {"name": "Korea Republic", "token_id": "13596664235738517648380047398734202867446623205366913953929788005448115341061",
     "end_date": "2026-03-28T15:50:00Z", "pre_game_price": 0.0,
     "question": "Cote d'Ivoire vs Korea Republic"},
    {"name": "CIV-KOR Draw", "token_id": "57419281444243459247397365534905390036732347105420882289192484097662830796443",
     "end_date": "2026-03-28T15:50:00Z", "pre_game_price": 0.0,
     "question": "Cote d'Ivoire vs Korea Republic Draw"},

    # === Senegal vs Peru (kickoff 16:00 UTC, end ~17:50) ===
    {"name": "Senegal", "token_id": "30447186100894502601566187180634302646548837773430344996065490040802080345004",
     "end_date": "2026-03-28T17:50:00Z", "pre_game_price": 0.0,
     "question": "Senegal vs Peru"},
    {"name": "Peru", "token_id": "12237926760710836864495509674128377856365598748626665918182578795580783789596",
     "end_date": "2026-03-28T17:50:00Z", "pre_game_price": 0.0,
     "question": "Senegal vs Peru"},
    {"name": "SEN-PER Draw", "token_id": "22188339288142146502680956938352778624531714140283307686489360278318658930501",
     "end_date": "2026-03-28T17:50:00Z", "pre_game_price": 0.0,
     "question": "Senegal vs Peru Draw"},

    # === Canada vs Iceland (kickoff 17:00 UTC, end ~18:50) ===
    {"name": "Canada", "token_id": "100251401089931464636187575723646056464953297101204290648350242068774995320229",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Canada vs Iceland"},
    {"name": "Iceland", "token_id": "85403616642999007524713676838036657378494147362302463137706491559344433937912",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Canada vs Iceland"},

    # === Hungary vs Slovenia (kickoff 17:00 UTC, end ~18:50) ===
    {"name": "Hungary", "token_id": "69696033813375010805903629975930960965789635095727426854537893493138146593260",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Hungary vs Slovenia"},
    {"name": "Slovenia", "token_id": "63883458614599465231951443403920022071310631756773893020926597537650628179108",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Hungary vs Slovenia"},

    # === Scotland vs Japan (kickoff 17:00 UTC, end ~18:50) ===
    {"name": "Scotland", "token_id": "54507425651762769851802339448044930046680455668241762264577647194234492554227",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Scotland vs Japan"},
    {"name": "Japan", "token_id": "98302330125097149258564365194582176135599083081003966907414565174115233275968",
     "end_date": "2026-03-28T18:50:00Z", "pre_game_price": 0.0,
     "question": "Scotland vs Japan"},

    # === USA vs Belgium (kickoff 19:30 UTC, end ~21:20) ===
    {"name": "USA", "token_id": "45166227132483146977918298152294119263079436388305995496244261828352129856119",
     "end_date": "2026-03-28T21:20:00Z", "pre_game_price": 0.0,
     "question": "USA vs Belgium"},
    {"name": "Belgium", "token_id": "100360230966133567318764890267706600115508557485401066724878343158031914205923",
     "end_date": "2026-03-28T21:20:00Z", "pre_game_price": 0.0,
     "question": "USA vs Belgium"},
    {"name": "USA-BEL Draw", "token_id": "13137187406794238469279254960582090966189407643442879412482753025548777678350",
     "end_date": "2026-03-28T21:20:00Z", "pre_game_price": 0.0,
     "question": "USA vs Belgium Draw"},

    # === Mexico vs Portugal (kickoff 01:00 UTC Mar 29, end ~02:50) ===
    {"name": "Mexico", "token_id": "108861107917873299653783392531951465578932918651415829765494132864311359429089",
     "end_date": "2026-03-29T02:50:00Z", "pre_game_price": 0.0,
     "question": "Mexico vs Portugal"},
    {"name": "Portugal", "token_id": "5114202296500591348983187810781922527274697362980913455748259777537384191562",
     "end_date": "2026-03-29T02:50:00Z", "pre_game_price": 0.0,
     "question": "Mexico vs Portugal"},
    {"name": "MEX-POR Draw", "token_id": "56776089786663037707522459361946706065792612605711925301372807976002063599341",
     "end_date": "2026-03-29T02:50:00Z", "pre_game_price": 0.0,
     "question": "Mexico vs Portugal Draw"},
]

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 15.0
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.28
BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        if w["pre_game_price"] == 0.0:
            try:
                info = client.get_price(w["token_id"], "buy")
                p = float(info.get("price", 0))
                if p > 0.01:
                    w["pre_game_price"] = p
                    print(f"  Pre-game {w['name']}: {p:.3f}")
            except Exception as e:
                print(f"  Pre-game {w['name']}: ERROR {e}")


def check_and_buy(client, watch_list):
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)
    print(f"\n--- Check #{check_and_buy.count} at {now.strftime('%H:%M:%S')} UTC ---")
    print(f"  Balance: ${balance:.2f}")
    check_and_buy.count += 1

    for w in watch_list:
        if not w["token_id"] or w["token_id"] in BOUGHT:
            continue
        try:
            buy_info = client.get_price(w["token_id"], "buy")
            sell_info = client.get_price(w["token_id"], "sell")
            buy_price = float(buy_info.get("price", 0))
            sell_price = float(sell_info.get("price", 0))

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
                print(f"  {w['name']:18s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins={mins_left:.0f} {status}")

            if trigger:
                # Block opponent tokens (same question)
                for other in watch_list:
                    if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                        BOUGHT.add(other["token_id"])

                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** NEAR-RES BUY {w['name']} YES @ ask ~{sell_price:.3f} for ${spend:.2f} ***")
                result = place_near_res_buy(client, w["token_id"], spend,
                                            tag=w['name'])
                if result and result.get("filled"):
                    fill_price = result["price"]
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-soccer-mar28-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": fill_price,
                        "fair_price": min(fill_price + 0.08, 0.99),
                        "edge": jump,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / fill_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_left / 1440,
                        "opened_at": str(now),
                        "research_note": f"Near-res: price jumped {jump:+.2f} from {w['pre_game_price']:.2f}"
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"NEAR-RES BUY {w['name']} @ {fill_price:.3f} for ${spend:.2f} ({shares:.1f}sh)")
                    balance = get_usdc_balance(client)
        except Exception as e:
            if "404" not in str(e):
                print(f"  {w['name']}: ERROR {e}")

check_and_buy.count = 0


def main():
    print("=== Soccer Friendlies Mar 28 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 03:00 UTC Mar 29 (after Mexico-Portugal ends)
    end_time = datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(75)

    final_bal = get_usdc_balance(client)
    print(f"\n=== Monitor ended. Final balance: ${final_bal:.2f} ===")
    send(f"Soccer Mar 28 monitor ended. Balance: ${final_bal:.2f}")


if __name__ == "__main__":
    main()
