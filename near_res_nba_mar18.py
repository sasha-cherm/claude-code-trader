#!/usr/bin/env python3
"""
Near-resolution monitor for NBA March 18, 2026.
6 games, tip-offs 20:30-21:00 ET (00:30-01:00 UTC Mar 19).
Near-res windows: ~01:00-02:30 UTC March 19.
Launch at 23:00 UTC March 18 (= 02:00 GMT+3 cron).
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
    # 7pm ET tipoff = 23:00 UTC, end ~01:30 UTC Mar 19
    {"name": "Warriors", "token_id": "14302113736666431391788862326263095423210080805883709532932255256118938349135",
     "end_date": "2026-03-19T01:30:00Z", "pre_game_price": 0.0, "question": "Warriors vs. Celtics"},
    {"name": "Celtics", "token_id": "113029239789300692616172453639272219737440053293500020532267049115602188152592",
     "end_date": "2026-03-19T01:30:00Z", "pre_game_price": 0.0, "question": "Warriors vs. Celtics"},

    # 7:30pm ET = 23:30 UTC, end ~02:00 UTC
    {"name": "Thunder", "token_id": "16446509433254887373586761047119699949129906055884341617402671026778381399591",
     "end_date": "2026-03-19T02:00:00Z", "pre_game_price": 0.0, "question": "Thunder vs. Nets"},
    {"name": "Nets", "token_id": "46614745572641369077889232940696154727727376914446769624756512643068810500194",
     "end_date": "2026-03-19T02:00:00Z", "pre_game_price": 0.0, "question": "Thunder vs. Nets"},
    {"name": "Trail Blazers", "token_id": "26402083740245206145531778592243014525791617046258288577369310029539345941627",
     "end_date": "2026-03-19T02:00:00Z", "pre_game_price": 0.0, "question": "Trail Blazers vs. Pacers"},
    {"name": "Pacers", "token_id": "51701997511402262896401628341097205475726560763529602990886444095653785420324",
     "end_date": "2026-03-19T02:00:00Z", "pre_game_price": 0.0, "question": "Trail Blazers vs. Pacers"},

    # 8pm ET = 00:00 UTC Mar 19, end ~02:30 UTC
    {"name": "Raptors", "token_id": "36961540922856473670872890994305065836143786629172347392664942684473699861012",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Raptors vs. Bulls"},
    {"name": "Bulls", "token_id": "87293892871152496980018744400390036878395240804629667243777281065936490688069",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Raptors vs. Bulls"},
    {"name": "Jazz", "token_id": "92279828462612374945590807822338848097685602697333990406163092665216484650178",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Jazz vs. Timberwolves"},
    {"name": "Timberwolves", "token_id": "79051793550464399582633953113398356715363957282120765357079771555353193927463",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Jazz vs. Timberwolves"},
    {"name": "Clippers", "token_id": "114527368175153006485637263319948731644388750406262307016788526520504909886575",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Clippers vs. Pelicans"},
    {"name": "Pelicans", "token_id": "50405950143962369963302692343536687688455690785913162237484430741288187284298",
     "end_date": "2026-03-19T02:30:00Z", "pre_game_price": 0.0, "question": "Clippers vs. Pelicans"},
]

MAX_SPEND_PER_TRADE = 5.0
MIN_SPEND = 2.0
MIN_PRICE_JUMP = 0.22
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.94
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 15  # NBA: last ~4 min of game
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
            buy_price = float(client.get_price(w["token_id"], "buy").get("price", 0))
            sell_price = float(client.get_price(w["token_id"], "sell").get("price", 0))
            jump = buy_price - w["pre_game_price"]
            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins_to_end = (end - now).total_seconds() / 60
            spread = buy_price - sell_price

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                mins_to_end <= MAX_MINS_TO_END and
                mins_to_end > 0 and
                abs(spread) < MAX_SPREAD and
                balance >= MIN_SPEND
            )

            if mins_to_end <= 60 or abs(jump) > 0.05:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(1.5)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-nba-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.12, 0.95),
                        "edge": 0.10,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": w["end_date"],
                        "days_left_at_entry": mins_to_end / 1440,
                        "opened_at": str(now),
                        "research_note": f"NBA Near-res: {w['name']} jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"NBA NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}, {mins_to_end:.0f}min left")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            print(f"  {w['name']:14s} ERROR: {e}")


def main():
    print(f"=== NBA Mar18 Near-Res Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    client = get_client()

    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run for 5 hours (covers all games through ~03:00 UTC)
    for i in range(300):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        try:
            for w in ALL_GAMES:
                if w["pre_game_price"] == 0.0:
                    try:
                        info = client.get_price(w["token_id"], "buy")
                        w["pre_game_price"] = float(info.get("price", 0))
                    except:
                        pass
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  ERROR in check: {e}")
        time.sleep(60)

    print(f"\n=== NBA Mar18 Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
