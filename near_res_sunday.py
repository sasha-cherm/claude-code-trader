#!/usr/bin/env python3
"""
Near-resolution monitor for Sunday March 16, 2026.
Key matches: EPL (Brentford-Wolves), Italian Coppa, South American leagues, NBA.

Usage:
  python3 near_res_sunday.py           # EPL/Europe 18:00 kickoffs (run at 19:00 cron)
  python3 near_res_sunday.py --south   # South American matches (run at 21:00 cron)
  python3 near_res_sunday.py --nba     # NBA games (run at 00:00/02:00 cron)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

# EPL/Europe 18:00 UTC kickoffs → ends ~19:50 UTC
# Run at 19:00 cron
EUROPE_WATCH = [
    {
        "name": "Brentford",
        "token_id": "47494701246623683904467099439211712078496707997982781452643608690648347494691",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.615,
        "question": "Will Brentford FC win on 2026-03-16?",
    },
    {
        "name": "Wolves",
        "token_id": "98107912998624786361577465233693172875466676473751002010266720534494299124333",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.165,
        "question": "Will Wolverhampton Wanderers FC win on 2026-03-16?",
    },
    {
        "name": "Fiorentina",
        "token_id": "43983711992682466425811740625239734206601633218569106954677431072543095443529",
        "end_date": "2026-03-16T19:35:00Z",
        "pre_game_price": 0.495,
        "question": "Will ACF Fiorentina win on 2026-03-16?",
    },
    {
        "name": "Cremonese",
        "token_id": "88758540586548013257655823628323495448742483005238291704425202430956623302069",
        "end_date": "2026-03-16T19:35:00Z",
        "pre_game_price": 0.245,
        "question": "Will US Cremonese win on 2026-03-16?",
    },
    {
        "name": "Rayo Vallecano",
        "token_id": "23561011456839630483320447422611805590525573311608314249136826402719853192782",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.565,
        "question": "Will Rayo Vallecano win on 2026-03-16?",
    },
    {
        "name": "Levante",
        "token_id": "90347551560998319459646346345246341704554454009264927560302680546197984074340",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.185,
        "question": "Will Levante UD win on 2026-03-16?",
    },
    {
        "name": "Portsmouth",
        "token_id": "79113958372401132960623887825921476327895108551989880716565658866851105146926",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.435,
        "question": "Will Portsmouth FC win on 2026-03-16?",
    },
    {
        "name": "Derby",
        "token_id": "77630630823935491730059268360060621037610896686110028761231141117748139682620",
        "end_date": "2026-03-16T19:50:00Z",
        "pre_game_price": 0.265,
        "question": "Will Derby County FC win on 2026-03-16?",
    },
]

# South American matches — kickoffs 19:00-23:15 UTC
# Run at 21:00 cron
SOUTH_WATCH = [
    {
        "name": "Union La Calera",
        "token_id": "94138453717501536312396825434338777298642977051488669600090841371771666075486",
        "end_date": "2026-03-16T20:50:00Z",
        "pre_game_price": 0.35,
        "question": "Will CD Union La Calera win on 2026-03-16?",
    },
    {
        "name": "O'Higgins",
        "token_id": "40912250292393906879991095230111090654175781756283114646873359278730469319965",
        "end_date": "2026-03-16T20:50:00Z",
        "pre_game_price": 0.345,
        "question": "Will O'Higgins FC win on 2026-03-16?",
    },
    {
        "name": "San Lorenzo",
        "token_id": "74050595533791162209410774082575246805836917194681466581558416756459286653551",
        "end_date": "2026-03-16T21:20:00Z",
        "pre_game_price": 0.425,
        "question": "Will CA San Lorenzo win on 2026-03-16?",
    },
    {
        "name": "Defensa y Justicia",
        "token_id": "115662459717938769394474917600788573269931675726269611112305465186973799016988",
        "end_date": "2026-03-16T21:20:00Z",
        "pre_game_price": 0.23,
        "question": "Will CSyD Defensa y Justicia win on 2026-03-16?",
    },
    {
        "name": "Gremio",
        "token_id": "22606161942836590259152868618326795372083549629697214690607452275569710541288",
        "end_date": "2026-03-16T22:50:00Z",
        "pre_game_price": 0.365,
        "question": "Will Gremio FBPA win on 2026-03-16?",
    },
    {
        "name": "Chapecoense",
        "token_id": "57285580455056571850152187101106275867589588913402316395781341686703871808451",
        "end_date": "2026-03-16T22:50:00Z",
        "pre_game_price": 0.335,
        "question": "Will Associacao Chapecoense win on 2026-03-16?",
    },
    {
        "name": "Racing Club",
        "token_id": "54543999227343540292052660942402162498556050093466701054998310074338149087037",
        "end_date": "2026-03-16T22:50:00Z",
        "pre_game_price": 0.685,
        "question": "Will Racing Club win on 2026-03-16?",
    },
    {
        "name": "Colo-Colo",
        "token_id": "88050960151573875482696292441215974313877536321316272925853953588022906339676",
        "end_date": "2026-03-16T23:20:00Z",
        "pre_game_price": 0.60,
        "question": "Will CSD Colo-Colo win on 2026-03-16?",
    },
    {
        "name": "Huachipato",
        "token_id": "45316465784857150947881595431932533767212696231019286474761583382369495716526",
        "end_date": "2026-03-16T23:20:00Z",
        "pre_game_price": 0.165,
        "question": "Will CD Huachipato win on 2026-03-16?",
    },
    {
        "name": "Instituto",
        "token_id": "108825396125612175573015452479729067210165850729042423862689726219625647850241",
        "end_date": "2026-03-17T01:05:00Z",
        "pre_game_price": 0.355,
        "question": "Will Instituto AC Cordoba win on 2026-03-16?",
    },
    {
        "name": "Independiente",
        "token_id": "88626157957975398327866824855763393177140506559427647018206781729912402975531",
        "end_date": "2026-03-17T01:05:00Z",
        "pre_game_price": 0.335,
        "question": "Will CA Independiente win on 2026-03-16?",
    },
]

# NBA games March 16 — tipoffs 23:00-02:00 UTC
# Run at 00:00 and 02:00 cron
NBA_WATCH = [
    {
        "name": "Magic",
        "token_id": "17903029841550754588158468564197784782221223501312289634518249177723567254003",
        "end_date": "2026-03-17T01:30:00Z",
        "pre_game_price": 0.445,
        "question": "Magic vs. Hawks",
    },
    {
        "name": "Hawks",
        "token_id": "68866164332470038810779719704128219836588448080079601845460184172839399597967",
        "end_date": "2026-03-17T01:30:00Z",
        "pre_game_price": 0.555,
        "question": "Magic vs. Hawks",
    },
    {
        "name": "Warriors",
        "token_id": "36454094111890707929864203818577880501802704342353295641320148081388826910972",
        "end_date": "2026-03-17T01:30:00Z",
        "pre_game_price": 0.675,
        "question": "Warriors vs. Wizards",
    },
    {
        "name": "Wizards",
        "token_id": "11711925051585049856226523814899913743340477553716361325225774576108948904532",
        "end_date": "2026-03-17T01:30:00Z",
        "pre_game_price": 0.325,
        "question": "Warriors vs. Wizards",
    },
    {
        "name": "Suns",
        "token_id": "3816518481671871062577988250327091694215573060566533078632537202325188211390",
        "end_date": "2026-03-17T02:00:00Z",
        "pre_game_price": 0.225,
        "question": "Suns vs. Celtics",
    },
    {
        "name": "Celtics",
        "token_id": "51955614961347467687453869068976148651866097014609771873245014743438386350024",
        "end_date": "2026-03-17T02:00:00Z",
        "pre_game_price": 0.775,
        "question": "Suns vs. Celtics",
    },
    {
        "name": "Blazers",
        "token_id": "76810239256659738454108496355863002598719856235416794857507402205455866024593",
        "end_date": "2026-03-17T02:00:00Z",
        "pre_game_price": 0.805,
        "question": "Trail Blazers vs. Nets",
    },
    {
        "name": "Nets",
        "token_id": "38600232329200688987180768699520821242643228049856328861898321954490511578350",
        "end_date": "2026-03-17T02:00:00Z",
        "pre_game_price": 0.195,
        "question": "Trail Blazers vs. Nets",
    },
    {
        "name": "Lakers",
        "token_id": "52749416297637676815876521259710492921538580354991559301907142803634588041399",
        "end_date": "2026-03-17T04:00:00Z",
        "pre_game_price": 0.47,
        "question": "Lakers vs. Rockets",
    },
    {
        "name": "Rockets",
        "token_id": "41591584094162347097224382297209272584406202929488443469145039769359224793818",
        "end_date": "2026-03-17T04:00:00Z",
        "pre_game_price": 0.53,
        "question": "Lakers vs. Rockets",
    },
    {
        "name": "Spurs",
        "token_id": "107595808475121353954878414033697282185110804024578231628702476953787251712388",
        "end_date": "2026-03-17T04:30:00Z",
        "pre_game_price": 0.765,
        "question": "Spurs vs. Clippers",
    },
    {
        "name": "Clippers",
        "token_id": "70125856368455597409103054709052917217494863863068571440955061920140576770481",
        "end_date": "2026-03-17T04:30:00Z",
        "pre_game_price": 0.235,
        "question": "Spurs vs. Clippers",
    },
]

MAX_SPEND_PER_TRADE = 12.0  # Higher spend for post-Oscar bankroll
MIN_SPEND = 3.0
MIN_PRICE_JUMP = 0.15
MIN_NEAR_RES_PRICE = 0.62
MAX_NEAR_RES_PRICE = 0.85
BOUGHT = set()


def check_prices(client, watch_list):
    """Check current prices for all watched markets."""
    results = []
    for watch in watch_list:
        if not watch["token_id"]:
            continue
        try:
            price_info = client.get_price(watch["token_id"], "buy")
            price = float(price_info.get("price", 0))

            sell_info = client.get_price(watch["token_id"], "sell")
            sell_price = float(sell_info.get("price", 0))

            jump = price - watch["pre_game_price"]

            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(watch["end_date"].replace("Z", "+00:00"))
            mins_to_end = (end - now).total_seconds() / 60

            results.append({
                **watch,
                "current_buy": price,
                "current_sell": sell_price,
                "jump": jump,
                "mins_to_end": mins_to_end,
            })

            status = "***BUY SIGNAL***" if (
                price >= MIN_NEAR_RES_PRICE and
                price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                mins_to_end < 60
            ) else ""

            print(f"  {watch['name']:18s} buy={price:.3f} sell={sell_price:.3f} "
                  f"jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")
        except Exception as e:
            print(f"  {watch['name']:18s} ERROR: {e}")

    return results


def try_buy(client, market, balance):
    """Attempt to buy a near-resolution opportunity."""
    tid = market["token_id"]
    name = market["name"]
    price = market["current_buy"]

    if tid in BOUGHT:
        print(f"  Already bought {name}, skipping")
        return False

    # Size: spend up to MAX_SPEND_PER_TRADE, capped at 20% of balance
    spend = min(MAX_SPEND_PER_TRADE, balance * 0.20)
    if spend < MIN_SPEND:
        print(f"  Insufficient balance for {name} (need ${MIN_SPEND}, have ${balance:.2f})")
        return False

    print(f"\n  *** BUYING {name} YES @ {price:.3f} for ${spend:.2f} ***")
    result = place_market_buy(client, tid, spend)

    if result:
        time.sleep(1.5)
        shares = get_actual_shares(client, tid)

        state = load_state()
        pos = {
            "token_id": tid,
            "market_id": f"near-res-{name.lower().replace(' ', '-')}",
            "question": market["question"],
            "side": "YES",
            "entry_price": price,
            "fair_price": min(price + 0.15, 0.95),
            "edge": 0.10,
            "size_usdc": spend,
            "shares": shares if shares > 0 else spend / price,
            "end_date": market["end_date"],
            "days_left_at_entry": market["mins_to_end"] / 1440,
            "opened_at": str(datetime.now(timezone.utc)),
            "research_note": f"Near-resolution: {name} price jumped {market['jump']:+.3f} from pre-game {market['pre_game_price']:.3f}",
        }
        state["positions"].append(pos)
        save_state(state)

        BOUGHT.add(tid)
        send(f"NEAR-RES BUY: {name} YES @ {price:.3f}\n  ${spend:.2f} ({shares:.2f} shares)\n  Jump: {market['jump']:+.3f}, {market['mins_to_end']:.0f} min to market end")
        print(f"  Success: {shares:.2f} shares")
        return True
    else:
        print(f"  BUY FAILED for {name}")
        return False


def main():
    if "--nba" in sys.argv:
        watch = NBA_WATCH
        label = "NBA Sunday"
    elif "--south" in sys.argv:
        watch = SOUTH_WATCH
        label = "SOUTH AMERICA"
    else:
        watch = EUROPE_WATCH
        label = "EPL/EUROPE Sunday"

    print(f"=== Near-Resolution Monitor ({label}) Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    max_iterations = 150  # 2.5 hours
    for i in range(max_iterations):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")

        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        results = check_prices(client, watch)

        for r in results:
            if (r["jump"] >= MIN_PRICE_JUMP and
                r["current_buy"] >= MIN_NEAR_RES_PRICE and
                r["current_buy"] <= MAX_NEAR_RES_PRICE and
                r["mins_to_end"] < 60 and
                r["token_id"] not in BOUGHT and
                balance >= MIN_SPEND):

                try_buy(client, r, balance)
                balance = get_usdc_balance(client)

        active = [r for r in results if r["mins_to_end"] > -30]
        if not active:
            print("\nAll monitored markets ended. Stopping.")
            break

        time.sleep(60)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
