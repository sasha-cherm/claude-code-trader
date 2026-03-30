#!/usr/bin/env python3
"""
Near-resolution monitor for March 30, 2026 — Soccer friendlies + NBA.

Games (kickoff → estimated end time UTC):
Soccer:
- Saudi Arabia vs Serbia (14:00 → ~15:45) — $4.5K vol
- Cyprus vs Moldova (16:00 → ~17:45) — $4.7K vol
- Egypt vs Spain (16:00 → ~17:45) — $15.5K vol ← BEST soccer target
- Germany vs Ghana (18:45 → ~20:30) — $12.3K vol

NBA (tipoff → estimated end):
- 76ers vs Heat (23:00 → ~01:30 Mar 31) — $273K vol
- Celtics vs Hawks (23:30 → ~02:00 Mar 31) — $158K vol ← COIN FLIP best target
- Mavericks vs Bucks (00:00 Mar 31 → ~02:30) — $2.4M vol

Near-res windows (last 20 mins):
- 15:25-15:45: Saudi Arabia-Serbia
- 17:25-17:45: Cyprus-Moldova + Egypt-Spain (overlap!)
- 20:10-20:30: Germany-Ghana
- 01:10-01:30 Mar 31: 76ers-Heat
- 01:40-02:00 Mar 31: Celtics-Hawks ← BEST target (coin flip)
- 02:10-02:30 Mar 31: Mavericks-Bucks

Launch at ~12:00 UTC. Runs until ~03:30 UTC Mar 31.

**COMMISSIONS ACTIVE** — uses place_limit_buy() (maker, no commission).
Validated params: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
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
    # === Saudi Arabia vs Serbia (kickoff 14:00, end ~15:45 UTC) ===
    {"name": "Saudi Arabia", "token_id": "102438120042131204835405604500831178907956525508617316868219551425557658847669",
     "end_date": "2026-03-30T15:45:00Z", "pre_game_price": 0.0,
     "question": "Saudi Arabia vs Serbia"},
    {"name": "Serbia", "token_id": "115447560797225528784265560582706039063425755952010442680275735247039176161345",
     "end_date": "2026-03-30T15:45:00Z", "pre_game_price": 0.0,
     "question": "Saudi Arabia vs Serbia"},
    {"name": "KSA-SER Draw", "token_id": "80664757806962015982959593940833376368281307854259336717952530491056290613966",
     "end_date": "2026-03-30T15:45:00Z", "pre_game_price": 0.0,
     "question": "Saudi Arabia vs Serbia Draw"},

    # === Cyprus vs Moldova (kickoff 16:00, end ~17:45 UTC) ===
    {"name": "Cyprus", "token_id": "2488999212860361518082286600727272168033718328840547100659034454678458261092",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Cyprus vs Moldova"},
    {"name": "Moldova", "token_id": "85508472109083543526809046092385711314439737214712848415417942667805827217608",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Cyprus vs Moldova"},
    {"name": "CYP-MOL Draw", "token_id": "80289109061685050763480849060662104478882537095249058783071337975118398861802",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Cyprus vs Moldova Draw"},

    # === Egypt vs Spain (kickoff 16:00, end ~17:45 UTC) ===
    {"name": "Egypt", "token_id": "11301324041046874441224626898008215309947915206499895675148516949504647806074",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Egypt vs Spain"},
    {"name": "Spain", "token_id": "61468494203813144973651399918553760050651514563967836538381711814685908620996",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Egypt vs Spain"},
    {"name": "EGY-ESP Draw", "token_id": "29532723573706358474270597300527366249770489432441704204071675234837355724457",
     "end_date": "2026-03-30T17:45:00Z", "pre_game_price": 0.0,
     "question": "Egypt vs Spain Draw"},

    # === Germany vs Ghana (kickoff 18:45, end ~20:30 UTC) ===
    {"name": "Germany", "token_id": "114960100158481376913447023952852449624582527418006026341439383102417854902185",
     "end_date": "2026-03-30T20:30:00Z", "pre_game_price": 0.0,
     "question": "Germany vs Ghana"},
    {"name": "Ghana", "token_id": "57970351191623034000076169446396173073805272526834540615039332420026887023836",
     "end_date": "2026-03-30T20:30:00Z", "pre_game_price": 0.0,
     "question": "Germany vs Ghana"},
    {"name": "GER-GHA Draw", "token_id": "64207670557380055760297729795828668547983393727729834130401902490165104703010",
     "end_date": "2026-03-30T20:30:00Z", "pre_game_price": 0.0,
     "question": "Germany vs Ghana Draw"},

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

    # === Mavericks vs Bucks (tipoff ~00:00 Mar 31, end ~02:30 Mar 31) ===
    {"name": "Mavericks", "token_id": "50131916083478714089157285423693376797182456085548292513709998194690842470740",
     "end_date": "2026-03-31T02:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs Bucks"},
    {"name": "Bucks", "token_id": "96683032224604836029172601859566946636160305460570852527789623822324107002992",
     "end_date": "2026-03-31T02:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs Bucks"},

    # === LoL: AL vs TES (BO3, start 17:00 UTC, end ~19:30) ===
    {"name": "AL (LoL)", "token_id": "1865429348916734759218507591352601113998807583254785071819661788655191186631",
     "end_date": "2026-03-30T19:30:00Z", "pre_game_price": 0.0,
     "question": "LoL AL vs TES"},
    {"name": "TES", "token_id": "66896829922764835710904702147264528708415351187748439964794820784010016594623",
     "end_date": "2026-03-30T19:30:00Z", "pre_game_price": 0.0,
     "question": "LoL AL vs TES"},

    # === LoL: NAVI vs SK Gaming (BO3, start 21:00 UTC, end ~23:30) ===
    {"name": "NAVI (LoL)", "token_id": "13359436583581556269349338421304213770941716977392109781993731240500114225792",
     "end_date": "2026-03-30T23:30:00Z", "pre_game_price": 0.0,
     "question": "LoL NAVI vs SK"},
    {"name": "SK Gaming", "token_id": "110807212466400540019176694601393576452708079199264124259993147178138401929714",
     "end_date": "2026-03-30T23:30:00Z", "pre_game_price": 0.0,
     "question": "LoL NAVI vs SK"},
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
                        "market_id": f"near-res-mar30-{w['name'].lower().replace(' ', '-')}",
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
    print("=== Mar 30 Near-Res Monitor (Soccer + NBA) ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print("Using LIMIT ORDERS (maker, no commission)")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 03:30 UTC Mar 31 (after Mavericks-Bucks ends)
    end_time = datetime(2026, 3, 31, 3, 30, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"Error in check loop: {e}")
        time.sleep(75)


if __name__ == "__main__":
    main()
