#!/usr/bin/env python3
"""
Near-resolution monitor for March 27, 2026 — FIFA Friendlies.

Matches (kickoff → end = kickoff+1:45):
- Russia vs Nicaragua: 16:30 → 18:15 UTC
- South Africa vs Panama: 17:00 → 18:45 UTC
- Austria vs Ghana: 17:00 → 18:45 UTC
- Montenegro vs Andorra: 17:00 → 18:45 UTC
- Greece vs Paraguay: 19:00 → 20:45 UTC
- Algeria vs Guatemala: 19:30 → 21:15 UTC
- England vs Uruguay: 19:45 → 21:30 UTC  ← BIG GAME
- Switzerland vs Germany: 19:45 → 21:30 UTC  ← BIG GAME, CLOSE
- Netherlands vs Norway: 19:45 → 21:30 UTC  ← BIG GAME
- Morocco vs Ecuador: 20:15 → 22:00 UTC  ← CLOSE GAME
- Haiti vs Tunisia: 00:00 → 01:45 UTC Mar 28  ← LATE

Draw markets added: GRE-PAR, ENG-URU, SUI-GER, NED-NOR, MOR-ECU (YES only).
If game tied at 80th+ min, draw YES jumps to 0.85+ → near-res buy signal.

Near-res windows: 17:55-18:45, 20:25-20:45, 21:00-22:00, 01:25-01:45 UTC.
Launch at ~13:00-15:00 UTC Mar 27.

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
    # === Russia vs Nicaragua (16:30 kickoff, end ~18:15 UTC) ===
    {"name": "Russia", "token_id": "92905974649974343437597849036718016295923556320322096012055362637600019168273",
     "end_date": "2026-03-27T18:15:00Z", "pre_game_price": 0.0,
     "question": "Russia vs. Nicaragua"},
    {"name": "Nicaragua", "token_id": "50940999913874599626471198790804065059021264641424023181142543879870912991748",
     "end_date": "2026-03-27T18:15:00Z", "pre_game_price": 0.0,
     "question": "Russia vs. Nicaragua"},

    # === South Africa vs Panama (17:00 kickoff, end ~18:45 UTC) ===
    {"name": "South Africa", "token_id": "9537848244865344465140449484470727412916560825092683286964853981616581091719",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "South Africa vs. Panama"},
    {"name": "Panama", "token_id": "59120556931166453997584733513484674305265657038509941772192328417043041973486",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "South Africa vs. Panama"},

    # === Austria vs Ghana (17:00 kickoff, end ~18:45 UTC) ===
    {"name": "Austria", "token_id": "45791910036777921853790610249580414491272574467834031579525603423405610142172",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "Austria vs. Ghana"},
    {"name": "Ghana", "token_id": "27149912891770422686751939853826582194058868172234211440109220069969223497301",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "Austria vs. Ghana"},

    # === Montenegro vs Andorra (17:00 kickoff, end ~18:45 UTC) ===
    {"name": "Montenegro", "token_id": "45555381421899737772952524829866349446190810254984880374096590780879610375708",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "Montenegro vs. Andorra"},
    {"name": "Andorra", "token_id": "39617462614876505153558757856090611209038217330874572771289485154030194750355",
     "end_date": "2026-03-27T18:45:00Z", "pre_game_price": 0.0,
     "question": "Montenegro vs. Andorra"},

    # === Greece vs Paraguay (19:00 kickoff, end ~20:45 UTC) ===
    {"name": "Greece", "token_id": "49122073540490785227784875805804881232874903040346158315482132817743987401698",
     "end_date": "2026-03-27T20:45:00Z", "pre_game_price": 0.0,
     "question": "Greece vs. Paraguay"},
    {"name": "Paraguay", "token_id": "38136333483830556473008411760166046756447263930990964284159295977098474376465",
     "end_date": "2026-03-27T20:45:00Z", "pre_game_price": 0.0,
     "question": "Greece vs. Paraguay"},

    # === Algeria vs Guatemala (19:30 kickoff, end ~21:15 UTC) ===
    {"name": "Algeria", "token_id": "57309542917521379800592134646765587881079216677202370003631647191030063385118",
     "end_date": "2026-03-27T21:15:00Z", "pre_game_price": 0.0,
     "question": "Algeria vs. Guatemala"},
    {"name": "Guatemala", "token_id": "75658836156818293228472770836735507087043674638576319512030016369318395510378",
     "end_date": "2026-03-27T21:15:00Z", "pre_game_price": 0.0,
     "question": "Algeria vs. Guatemala"},

    # === England vs Uruguay (19:45 kickoff, end ~21:30 UTC) — BIG GAME ===
    {"name": "England", "token_id": "62027978202128437004226799586845029753774803743824843480497409382240963614049",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "England vs. Uruguay"},
    {"name": "Uruguay", "token_id": "22600053953224215295708806209918333730479155224889613955309211381348292476195",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "England vs. Uruguay"},

    # === Switzerland vs Germany (19:45 kickoff, end ~21:30 UTC) — CLOSE GAME ===
    {"name": "Switzerland", "token_id": "9285847577518774066577522599321001903414887074256176990370158818902397150193",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Switzerland vs. Germany"},
    {"name": "Germany", "token_id": "103936675958365847504729583765433169097902785521073769405453047518495324799852",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Switzerland vs. Germany"},

    # === Netherlands vs Norway (19:45 kickoff, end ~21:30 UTC) ===
    {"name": "Netherlands", "token_id": "6662931739968395106647433937346568296609228021621026345970130532190231925050",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Netherlands vs. Norway"},
    {"name": "Norway", "token_id": "64197174722290951861361476133197632169929868110190792937631697777538844979282",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Netherlands vs. Norway"},

    # === Morocco vs Ecuador (20:15 kickoff, end ~22:00 UTC) — CLOSE GAME ===
    {"name": "Morocco", "token_id": "77435356206019003396084887852594763447085899764135953900908751228568395934280",
     "end_date": "2026-03-27T22:00:00Z", "pre_game_price": 0.0,
     "question": "Morocco vs. Ecuador"},
    {"name": "Ecuador", "token_id": "93418328761949017438328962178087801082141784093529847351286268419154518497060",
     "end_date": "2026-03-27T22:00:00Z", "pre_game_price": 0.0,
     "question": "Morocco vs. Ecuador"},

    # === Haiti vs Tunisia (00:00 kickoff Mar 28, end ~01:45 UTC) ===
    {"name": "Haiti", "token_id": "44003866209272527774489724834462438776091288318474307703140799346845264386717",
     "end_date": "2026-03-28T01:45:00Z", "pre_game_price": 0.0,
     "question": "Haiti vs. Tunisia"},
    {"name": "Tunisia", "token_id": "23511830895608046506815830191266833883248965695593004600706650689648936762941",
     "end_date": "2026-03-28T01:45:00Z", "pre_game_price": 0.0,
     "question": "Haiti vs. Tunisia"},

    # === DRAW MARKETS (YES only — triggers when game tied at 80th+ minute) ===
    # If game is 0-0 or tied late, draw YES jumps to 0.85+ → near-res buy signal

    # Greece-Paraguay draw (kickoff 19:00, end ~20:45 UTC) — 29.5% pre-game
    {"name": "GRE-PAR Draw YES", "token_id": "84731395200470886643248891935838237741475713652743068875925169567395351142979",
     "end_date": "2026-03-27T20:45:00Z", "pre_game_price": 0.0,
     "question": "Greece vs. Paraguay draw"},

    # England-Uruguay draw (kickoff 19:45, end ~21:30 UTC) — 22.5% pre-game
    {"name": "ENG-URU Draw YES", "token_id": "111552417545911698827661214654623573151317290018294447868462539966891867094245",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "England vs. Uruguay draw"},

    # Switzerland-Germany draw (kickoff 19:45, end ~21:30 UTC) — 26.5% pre-game
    {"name": "SUI-GER Draw YES", "token_id": "66719983600850239396655516420152317427653109211084997582628627364823929743130",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Switzerland vs. Germany draw"},

    # Netherlands-Norway draw (kickoff 19:45, end ~21:30 UTC) — 23.5% pre-game
    {"name": "NED-NOR Draw YES", "token_id": "14788755366359767274691811621738048867771369511884589224327519595997163406054",
     "end_date": "2026-03-27T21:30:00Z", "pre_game_price": 0.0,
     "question": "Netherlands vs. Norway draw"},

    # Morocco-Ecuador draw (kickoff 20:15, end ~22:00 UTC) — 33.5% pre-game, CLOSEST
    {"name": "MOR-ECU Draw YES", "token_id": "46034780032529612926045946307343366431092406436093394190316253751073041707395",
     "end_date": "2026-03-27T22:00:00Z", "pre_game_price": 0.0,
     "question": "Morocco vs. Ecuador draw"},
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
                        "market_id": f"near-res-soccer-mar27-{w['name'].lower().replace(' ', '-')}",
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
    print("=== FIFA Friendlies Mar 27 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run until 02:00 UTC Mar 28 (after Haiti-Tunisia ends)
    end_time = datetime(2026, 3, 28, 2, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(75)

    final_bal = get_usdc_balance(client)
    print(f"\n=== Monitor ended. Final balance: ${final_bal:.2f} ===")
    send(f"Soccer Mar 27 monitor ended. Balance: ${final_bal:.2f}")


if __name__ == "__main__":
    main()
