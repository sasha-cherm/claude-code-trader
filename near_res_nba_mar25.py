#!/usr/bin/env python3
"""
Near-resolution monitor for March 25, 2026 — 12 NBA games.

Tipoffs 23:00-02:30 UTC → near-res windows 01:00-05:00 UTC Mar 26.
Launch at ~21:00 UTC to snapshot pre-game prices.

Validated params from March 22: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
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

ALL_GAMES = [
    # === NBA (12 games) ===
    # Tipoff 23:00 UTC Mar 25
    {"name": "Hawks", "token_id": "93005267235468997456934002388550021937018425537589605094014799710941741251069",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Pistons"},
    {"name": "Pistons", "token_id": "64177640059835852124241116498674937098540535726885083860163167335916700824150",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Pistons"},

    {"name": "Lakers", "token_id": "7612910576717793402991019799791772135256321521836599291298863333468643619461",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pacers"},
    {"name": "Pacers", "token_id": "114197304671868049202803403374363020064588068595117140773342483626582980094264",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pacers"},

    {"name": "Bulls", "token_id": "3162096944025599388343368267014382438955741801678961041209954555797739052890",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. 76ers"},
    {"name": "76ers", "token_id": "7458268339281501131092772693402177646688351956726977690754205017540705015311",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. 76ers"},

    # Tipoff 23:30 UTC Mar 25
    {"name": "Thunder", "token_id": "107873275012767872940089881195560536670209084976663788557868940051552278053349",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Celtics"},
    {"name": "Celtics", "token_id": "12160776981609763533501553797509574492383854838127183751971345302533107597107",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Celtics"},

    {"name": "Heat", "token_id": "3432670311544361562896003314110816516903559805884757448626772409947882253911",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},
    {"name": "Cavaliers", "token_id": "44725893014753223728715041388114476759343056601141677443767816816525366969933",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},

    # Tipoff 00:00 UTC Mar 26
    {"name": "Spurs", "token_id": "111585476520182526013310515691624101392915263061638864508466984623921201341648",
     "end_date": "2026-03-26T02:30:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Grizzlies"},
    {"name": "Grizzlies", "token_id": "75988829743818195059319292222936271583394612963468654999222933263264360226903",
     "end_date": "2026-03-26T02:30:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Grizzlies"},

    # Tipoff 01:00 UTC Mar 26
    {"name": "Wizards", "token_id": "62221675027285730323772047312176523219159899833963007822052605755843635311576",
     "end_date": "2026-03-26T03:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Jazz"},
    {"name": "Jazz", "token_id": "107202767399186069294944974241034452406798583186929225424182362073950877567232",
     "end_date": "2026-03-26T03:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Jazz"},

    # Tipoff 01:30 UTC Mar 26
    {"name": "Rockets", "token_id": "92478388793162701688228117655170187221557905686840754078187669782700067722048",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Timberwolves"},
    {"name": "Timberwolves", "token_id": "111191110166685402703345809072251891917258815235664098103848966919430435408957",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Timberwolves"},

    # Tipoff 02:00 UTC Mar 26
    {"name": "Mavericks", "token_id": "20922232650376756003161875689296660358662743194658994892319178428143934706670",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Nuggets"},
    {"name": "Nuggets", "token_id": "43403740338966946480122866016569684130438243069023216173919933608376541967800",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Nuggets"},

    {"name": "Nets", "token_id": "59988304926157291085741980783244124412733571922037236061861524240909694002156",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Warriors"},
    {"name": "Warriors", "token_id": "62676735322842398057034281587593087884927362055299349529547920334852418648339",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Warriors"},

    {"name": "Bucks", "token_id": "11320517947120382867354691332790182818908690626593202939648958728911767443152",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Trail Blazers"},
    {"name": "Trail Blazers", "token_id": "10116089711001117841135224750826069324066461435046964233291014901378997900491",
     "end_date": "2026-03-26T04:30:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Trail Blazers"},

    # Tipoff 02:30 UTC Mar 26
    {"name": "Raptors", "token_id": "104750558455342899598943060530064380790815094510981313121419519554249163923974",
     "end_date": "2026-03-26T05:00:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Clippers"},
    {"name": "Clippers", "token_id": "12333070480341614122618762158154035726831021854006502312831723071427076934870",
     "end_date": "2026-03-26T05:00:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Clippers"},
]

# === Params (validated Mar 22: 8/8 wins) ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 20.0
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.28
BOUGHT = set()  # Dedup: prevent buying same token or same-game opponent


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

            # Time-based filter
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
                mins_str = f" mins={mins_left:.0f}" if end_str else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f}{mins_str} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-nba-mar25-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.08, 0.99),
                        "edge": jump,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_left / 1440,
                        "opened_at": str(now),
                        "research_note": f"NBA Mar25 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"NBA MAR25 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']}: {err}")


check_and_buy.count = 0


def main():
    print(f"=== NBA Mar 25 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    # Snapshot pre-game prices
    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor loop — run until 06:00 UTC Mar 26
    end_time = datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
