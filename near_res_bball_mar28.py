#!/usr/bin/env python3
"""
Near-resolution monitor for March 28, 2026 — 6 NBA games + 1 NCAAB Elite 8.

Gamma end_date = tipoff. Actual end = tipoff + ~2:30 (NBA), ~2:00 (NCAAB).

Games (by tipoff UTC):
- Spurs vs Bucks (19:00 UTC tipoff, end ~21:30) — Spurs 91% fav
- Pistons vs Timberwolves (21:30 UTC, end ~00:00) — COIN FLIP, $567K vol ← BEST TARGET
- 76ers vs Hornets (22:00 UTC, end ~00:30) — Hornets 68% fav
- **Illinois vs Iowa (NCAAB Elite 8)** (22:09 UTC tipoff, end ~00:09) — Illinois 73%, $760K vol
- Kings vs Hawks (23:30 UTC, end ~02:00) — Hawks 87% fav
- Bulls vs Grizzlies (00:00 Mar 29, end ~02:30) — Bulls 61%
- Jazz vs Suns (02:00 Mar 29, end ~04:30) — Suns 90%

Near-res windows (last 20 mins of game):
- 21:10-21:30 UTC: Spurs-Bucks
- 23:40-00:00 UTC: Pistons-TWolves + Illinois-Iowa (OVERLAPPING!)
- 00:10-00:30 UTC: 76ers-Hornets
- 01:40-02:00 UTC: Kings-Hawks
- 02:10-02:30 UTC: Bulls-Grizzlies
- 04:10-04:30 UTC: Jazz-Suns

Launch at ~18:00 UTC. Runs until ~05:00 UTC Mar 29.

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
    # === Spurs vs Bucks (tipoff 19:00 UTC, end ~21:30) ===
    {"name": "Spurs", "token_id": "29950489035650776944637857495608923659285559520543605944359984119443817993935",
     "end_date": "2026-03-28T21:30:00Z", "pre_game_price": 0.930,
     "question": "Spurs vs Bucks"},
    {"name": "Bucks", "token_id": "51467971543044391490562153161794632172931862580956295609766286623443587927797",
     "end_date": "2026-03-28T21:30:00Z", "pre_game_price": 0.060,
     "question": "Spurs vs Bucks"},

    # === Pistons vs Timberwolves (tipoff 21:30, end ~00:00 Mar 29) — COIN FLIP ===
    {"name": "Pistons", "token_id": "95411093744734370915792410998151956108686985086137534199369379281549794538611",
     "end_date": "2026-03-29T00:00:00Z", "pre_game_price": 0.530,
     "question": "Pistons vs Timberwolves"},
    {"name": "Timberwolves", "token_id": "49164064820177403051176734322968533773346472121558748796183619121394153010608",
     "end_date": "2026-03-29T00:00:00Z", "pre_game_price": 0.460,
     "question": "Pistons vs Timberwolves"},

    # === 76ers vs Hornets (tipoff 22:00, end ~00:30 Mar 29) ===
    {"name": "76ers", "token_id": "31032354366533293355668238476117231416828391966974430070047166314019592915724",
     "end_date": "2026-03-29T00:30:00Z", "pre_game_price": 0.310,
     "question": "76ers vs Hornets"},
    {"name": "Hornets", "token_id": "101775132695058782295092513974354689556361470165033001112394714177373535106738",
     "end_date": "2026-03-29T00:30:00Z", "pre_game_price": 0.680,
     "question": "76ers vs Hornets"},

    # === Kings vs Hawks (tipoff 23:30, end ~02:00 Mar 29) ===
    {"name": "Kings", "token_id": "21150148414312899009913397598767905385126229079397555468537126424075956087411",
     "end_date": "2026-03-29T02:00:00Z", "pre_game_price": 0.110,
     "question": "Kings vs Hawks"},
    {"name": "Hawks", "token_id": "59659558999551574376327890231148977468461925241962629072949038607122208133954",
     "end_date": "2026-03-29T02:00:00Z", "pre_game_price": 0.880,
     "question": "Kings vs Hawks"},

    # === Bulls vs Grizzlies (tipoff 00:00 Mar 29, end ~02:30) ===
    {"name": "Bulls", "token_id": "49675008083918171505137582837949064531166050861222917473777213367353739315061",
     "end_date": "2026-03-29T02:30:00Z", "pre_game_price": 0.620,
     "question": "Bulls vs Grizzlies"},
    {"name": "Grizzlies", "token_id": "78146383566212769129869114601977346963972569693982905884008997406170312559153",
     "end_date": "2026-03-29T02:30:00Z", "pre_game_price": 0.370,
     "question": "Bulls vs Grizzlies"},

    # === Jazz vs Suns (tipoff 02:00 Mar 29, end ~04:30) ===
    {"name": "Jazz", "token_id": "55011611825902966608881846768720360730743421878581112757231431155715068566038",
     "end_date": "2026-03-29T04:30:00Z", "pre_game_price": 0.070,
     "question": "Jazz vs Suns"},
    {"name": "Suns", "token_id": "96664996099704822974415975516126061506215054046704379673445993793396400000228",
     "end_date": "2026-03-29T04:30:00Z", "pre_game_price": 0.920,
     "question": "Jazz vs Suns"},

    # === NCAAB Elite 8: Illinois vs Iowa (tipoff 22:09 UTC, end ~00:09 Mar 29) — $760K vol ===
    {"name": "Illinois", "token_id": "51016507619180924665597559307500966371300359990730628147295374239685630001225",
     "end_date": "2026-03-29T00:09:00Z", "pre_game_price": 0.730,
     "question": "Illinois vs Iowa"},
    {"name": "Iowa", "token_id": "94447182302194482310220356455575365299769150002438081485821221492788471804424",
     "end_date": "2026-03-29T00:09:00Z", "pre_game_price": 0.260,
     "question": "Illinois vs Iowa"},
]

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 15.0
MIN_SPEND = 0.50
PCT_OF_BALANCE = 0.45
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
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins={mins_left:.0f} {status}")

            if trigger:
                # Block opponent token
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
                        "market_id": f"near-res-bball-mar28-{w['name'].lower().replace(' ', '-')}",
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
    print("=== NBA Mar 28 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 05:00 UTC Mar 29 (after last game ends)
    end_time = datetime(2026, 3, 29, 5, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(75)

    final_bal = get_usdc_balance(client)
    print(f"\n=== Monitor ended. Final balance: ${final_bal:.2f} ===")
    send(f"NBA Mar 28 monitor ended. Balance: ${final_bal:.2f}")


if __name__ == "__main__":
    main()
