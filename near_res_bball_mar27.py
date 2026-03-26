#!/usr/bin/env python3
"""
Near-resolution monitor for March 27, 2026 — 10 NBA + 2 NCAAB Sweet 16.

NCAAB Sweet 16 (tipoff ~23:35 UTC Mar 27 / 7:35PM ET):
- Alabama vs Michigan (18/81) — $137K vol

NBA Early (tipoff ~23:00-23:30 UTC Mar 27):
- Clippers vs Pacers (78/21) — $33K vol
- Hawks vs Celtics (27/73) — $24K vol
- Heat vs Cavaliers (37/63) — $38K vol ← CLOSEST

NBA Mid (tipoff ~00:00-01:00 UTC Mar 28):
- Rockets vs Grizzlies (88/12) — $10K vol
- Bulls vs Thunder (7.5/92.5) — $90K vol
- Pelicans vs Raptors (28/71) — $4.5K vol

NCAAB Sweet 16 (tipoff ~01:45 UTC Mar 28 / 9:45PM ET):
- Michigan State vs UConn (47/53) — $422K vol ← COIN FLIP, BEST TARGET

NBA Late (tipoff ~02:00-02:30 UTC Mar 28):
- Jazz vs Nuggets (7.5/92.5) — $7K vol
- Wizards vs Warriors (15/85) — $14K vol
- Mavericks vs Trail Blazers (22/77) — $33K vol
- Nets vs Lakers (6.5/93.5) — $19K vol

Near-res windows:
- 01:00-02:00 UTC Mar 28 (NBA early + Alabama-Michigan)
- 02:30-03:00 UTC (NBA mid)
- 03:30-04:00 UTC (MSU-UConn)
- 04:30-05:00 UTC (NBA late)

Launch at ~21:00-23:00 UTC Mar 27.

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
    # === Alabama vs Michigan — NCAAB Sweet 16 (tipoff ~23:35 UTC, end ~01:35 UTC Mar 28) ===
    {"name": "Alabama", "token_id": "31058028660405173173651315689025730539994483848792849474560279252203011850319",
     "end_date": "2026-03-28T01:35:00Z", "pre_game_price": 0.0,
     "question": "Alabama vs. Michigan"},
    {"name": "Michigan", "token_id": "84031203592002917334262470868576093775510312558710425317269896203693659940128",
     "end_date": "2026-03-28T01:35:00Z", "pre_game_price": 0.0,
     "question": "Alabama vs. Michigan"},

    # === Clippers vs Pacers (tipoff ~23:00 UTC, end ~01:30 UTC Mar 28) ===
    {"name": "Clippers", "token_id": "66623376009737658478526904468037148785237831025311445804738042694106366298048",
     "end_date": "2026-03-28T01:30:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs. Pacers"},
    {"name": "Pacers", "token_id": "90527368220056094499787958638375970410413722308601684454359395969617817547528",
     "end_date": "2026-03-28T01:30:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs. Pacers"},

    # === Hawks vs Celtics (tipoff ~23:30 UTC, end ~02:00 UTC Mar 28) ===
    {"name": "Hawks", "token_id": "43163282684901309138667654714362435628489629394534958193813776385065852352937",
     "end_date": "2026-03-28T02:00:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Celtics"},
    {"name": "Celtics", "token_id": "51181805474352400402227334744198550578352608385394549394718349763159334940317",
     "end_date": "2026-03-28T02:00:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Celtics"},

    # === Heat vs Cavaliers (tipoff ~23:30 UTC, end ~02:00 UTC Mar 28) — CLOSE ===
    {"name": "Heat", "token_id": "77559241074239791146483316774205587811353199775671108863986222014613556277366",
     "end_date": "2026-03-28T02:00:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},
    {"name": "Cavaliers", "token_id": "110583828665134319756217985538045278198982902791171614366178394831028294472397",
     "end_date": "2026-03-28T02:00:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},

    # === Rockets vs Grizzlies (tipoff ~00:00 UTC Mar 28, end ~02:30 UTC) ===
    {"name": "Rockets", "token_id": "106121111293631873456338358008770105983486719820128302114836404194205814787775",
     "end_date": "2026-03-28T02:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Grizzlies"},
    {"name": "Grizzlies", "token_id": "111163036344978533605666908122966404680345770715162375533869257626249126809951",
     "end_date": "2026-03-28T02:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Grizzlies"},

    # === Bulls vs Thunder (tipoff ~00:00 UTC Mar 28, end ~02:30 UTC) ===
    {"name": "Bulls", "token_id": "18857230268452066537363078992091971286351084487881561453941610368968619016743",
     "end_date": "2026-03-28T02:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. Thunder"},
    {"name": "Thunder", "token_id": "12140363270813721013935821508234774830862117498614233251879688391015459761132",
     "end_date": "2026-03-28T02:30:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. Thunder"},

    # === Pelicans vs Raptors (tipoff ~00:30 UTC Mar 28, end ~03:00 UTC) ===
    {"name": "Pelicans", "token_id": "99238619516689954966660518388377418115649586258782777184568961525592312572576",
     "end_date": "2026-03-28T03:00:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Raptors"},
    {"name": "Raptors", "token_id": "96680837172156204078520012519048926631851907270080528666720928195353466709528",
     "end_date": "2026-03-28T03:00:00Z", "pre_game_price": 0.0,
     "question": "Pelicans vs. Raptors"},

    # === Michigan State vs UConn — NCAAB Sweet 16 (tipoff ~01:45 UTC Mar 28, end ~03:45 UTC) ===
    # COIN FLIP — best near-res target
    {"name": "Michigan St", "token_id": "23071365530007840499595140099244953388320355039725407838409210788227385062169",
     "end_date": "2026-03-28T03:45:00Z", "pre_game_price": 0.0,
     "question": "Michigan State vs. UConn"},
    {"name": "UConn", "token_id": "908726398549149977786555873192888390832262725037682630056119381505182857140",
     "end_date": "2026-03-28T03:45:00Z", "pre_game_price": 0.0,
     "question": "Michigan State vs. UConn"},

    # === Jazz vs Nuggets (tipoff ~01:00 UTC Mar 28, end ~03:30 UTC) ===
    {"name": "Jazz", "token_id": "57556874640503396890402262204962103443449154609571310621682268434995035540002",
     "end_date": "2026-03-28T03:30:00Z", "pre_game_price": 0.0,
     "question": "Jazz vs. Nuggets"},
    {"name": "Nuggets", "token_id": "108980002028227041087000240279859781506974969655696509469254643058542901391582",
     "end_date": "2026-03-28T03:30:00Z", "pre_game_price": 0.0,
     "question": "Jazz vs. Nuggets"},

    # === Wizards vs Warriors (tipoff ~02:00 UTC Mar 28, end ~04:30 UTC) ===
    {"name": "Wizards", "token_id": "37782331886451001281355376561517840459401092874305203124685971144847835244106",
     "end_date": "2026-03-28T04:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Warriors"},
    {"name": "Warriors", "token_id": "49797003103003486440893863921013334308949611912350988285734183004413855401131",
     "end_date": "2026-03-28T04:30:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Warriors"},

    # === Mavericks vs Trail Blazers (tipoff ~02:00 UTC Mar 28, end ~04:30 UTC) ===
    {"name": "Mavericks", "token_id": "18592363220936550153275639716955697958040865498165269821145504161600639358805",
     "end_date": "2026-03-28T04:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Trail Blazers"},
    {"name": "Trail Blazers", "token_id": "92404739907495418278445005339932522383975444996131860155094056057861300789685",
     "end_date": "2026-03-28T04:30:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Trail Blazers"},

    # === Nets vs Lakers (tipoff ~02:30 UTC Mar 28, end ~05:00 UTC) ===
    {"name": "Nets", "token_id": "105372800452037398580285112900013569640706347305176961291761271865199492553933",
     "end_date": "2026-03-28T05:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Lakers"},
    {"name": "Lakers", "token_id": "53814578390846706799335334420276388082271504502099011987284093586299619386518",
     "end_date": "2026-03-28T05:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Lakers"},
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
                        "market_id": f"near-res-bball-mar27-{w['name'].lower().replace(' ', '-')}",
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
    print("=== NBA+NCAAB Mar 27 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 05:30 UTC Mar 28 (after last game ends)
    end_time = datetime(2026, 3, 28, 5, 30, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(75)

    final_bal = get_usdc_balance(client)
    print(f"\n=== Monitor ended. Final balance: ${final_bal:.2f} ===")
    send(f"NBA+NCAAB Mar 27 monitor ended. Balance: ${final_bal:.2f}")


if __name__ == "__main__":
    main()
