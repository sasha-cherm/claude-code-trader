#!/usr/bin/env python3
"""
Near-resolution monitor for NBA March 30 night.

7 NBA games (tipoff → near-res window UTC):
- 76ers vs Heat (23:00 → 01:10-01:30 Mar 31)
- Celtics vs Hawks (23:30 → 01:40-02:00 Mar 31)
- Bulls vs Spurs (00:00 → 02:10-02:30 Mar 31)
- T'wolves vs Mavs (00:30 → 02:40-03:00 Mar 31)
- Cavs vs Jazz (01:00 → 03:10-03:30 Mar 31)
- Pistons vs Thunder (01:30 → 03:40-04:00 Mar 31)
- Wizards vs Lakers (02:00 → 04:10-04:30 Mar 31)

Launch ~22:00 UTC. Runs until 05:00 UTC Mar 31.
Uses LIMIT ORDERS (maker, no commission).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_limit_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # === 76ers vs Heat (tipoff 23:00, end ~01:30 Mar 31) ===
    {"name": "76ers", "token_id": "71448282610788858154990159535574057094282877558978482989685024854053762815228",
     "end_date": "2026-03-31T01:30:00Z", "pre_game_price": 0.0,
     "question": "76ers vs Heat"},
    {"name": "Heat", "token_id": "25267056397162558392615153819244480211268147215221595973948595964024370882694",
     "end_date": "2026-03-31T01:30:00Z", "pre_game_price": 0.0,
     "question": "76ers vs Heat"},

    # === Celtics vs Hawks (tipoff 23:30, end ~02:00 Mar 31) ===
    {"name": "Celtics", "token_id": "36405635458314874058837552114828609391858806159062238490557539558831492160933",
     "end_date": "2026-03-31T02:00:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs Hawks"},
    {"name": "Hawks", "token_id": "55134433887169069709945058526508421213292037713447935974851019578290288712696",
     "end_date": "2026-03-31T02:00:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs Hawks"},

    # === Bulls vs Spurs (tipoff 00:00 Mar 31, end ~02:30 Mar 31) ===
    {"name": "Bulls", "token_id": "94346310750641464325629972505459399662073095543710753103135093437804989527099",
     "end_date": "2026-03-31T02:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs Spurs"},
    {"name": "Spurs", "token_id": "36619861053264232848117023024556832449773571665649424497693839028281367484889",
     "end_date": "2026-03-31T02:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs Spurs"},

    # === Timberwolves vs Mavericks (tipoff 00:30, end ~03:00 Mar 31) ===
    {"name": "Timberwolves", "token_id": "85840933269983467066483785804095753291453989488655853019619770523694178327291",
     "end_date": "2026-03-31T03:00:00Z", "pre_game_price": 0.0,
     "question": "Timberwolves vs Mavericks"},
    {"name": "Mavericks", "token_id": "77700816841891404364263447710461858773032606398637834938479783627782963729095",
     "end_date": "2026-03-31T03:00:00Z", "pre_game_price": 0.0,
     "question": "Timberwolves vs Mavericks"},

    # === Cavaliers vs Jazz (tipoff 01:00, end ~03:30 Mar 31) ===
    {"name": "Cavaliers", "token_id": "29219175555688424873252236373989973652696020671098773990009050437700684153093",
     "end_date": "2026-03-31T03:30:00Z", "pre_game_price": 0.0,
     "question": "Cavaliers vs Jazz"},
    {"name": "Jazz", "token_id": "94925509651831310769831050327803362779736775453804523268700263399684032994413",
     "end_date": "2026-03-31T03:30:00Z", "pre_game_price": 0.0,
     "question": "Cavaliers vs Jazz"},

    # === Pistons vs Thunder (tipoff 01:30, end ~04:00 Mar 31) ===
    {"name": "Pistons", "token_id": "28012372672072337603651973024371327992757432373979100281879371990519534261403",
     "end_date": "2026-03-31T04:00:00Z", "pre_game_price": 0.0,
     "question": "Pistons vs Thunder"},
    {"name": "Thunder", "token_id": "76696208778663955930814779974782076361025218549316530792455283291476012484437",
     "end_date": "2026-03-31T04:00:00Z", "pre_game_price": 0.0,
     "question": "Pistons vs Thunder"},

    # === Wizards vs Lakers (tipoff 02:00, end ~04:30 Mar 31) ===
    {"name": "Wizards", "token_id": "70491372204557274364789155968710853082960445427098513082069375413605627771025",
     "end_date": "2026-03-31T04:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs Lakers"},
    {"name": "Lakers", "token_id": "28875726395491071821474498654032729428755363825979093803866694539756547261413",
     "end_date": "2026-03-31T04:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs Lakers"},
]

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 10.0
MIN_SPEND = 0.50
PCT_OF_BALANCE = 0.50  # with $6, go big on the best signal
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
                print(f"\n  *** LIMIT BUY {w['name']} YES @ bid for ${spend:.2f} ***")
                result = place_limit_buy(client, w["token_id"], spend,
                                         max_wait_sec=60, tag=w['name'])
                if result and result.get("filled"):
                    fill_price = result["price"]
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-nba-mar30-{w['name'].lower().replace(' ', '-')}",
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
                    send(f"LIMIT BUY {w['name']} @ {fill_price:.3f} for ${spend:.2f} ({shares:.1f}sh)")
                    balance = get_usdc_balance(client)
                elif result:
                    print(f"  Order not filled for {w['name']}, skipping")
        except Exception as e:
            if "404" not in str(e):
                print(f"  {w['name']}: ERROR {e}")

check_and_buy.count = 0


def main():
    print("=== Mar 30 NBA Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens / {len(ALL_GAMES)//2} games")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print("Using LIMIT ORDERS (maker, no commission)")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    if balance < MIN_SPEND:
        print(f"Balance too low (${balance:.2f}). Will monitor anyway for settlements.")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 05:00 UTC Mar 31 (after all games end)
    end_time = datetime(2026, 3, 31, 5, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"Error in check loop: {e}")
        time.sleep(75)

    print("Monitor done.")
    send("NBA near-res monitor finished for March 30.")


if __name__ == "__main__":
    main()
