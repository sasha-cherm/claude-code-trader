#!/usr/bin/env python3
"""
Soccer near-resolution monitor for March 19, 2026.
UEL + UECL Round of 16 second legs.

KEY AGGREGATES:
  AEK Larnaca vs Crystal Palace — 0-0 agg (17:45 UTC) ***TOP***
  Mainz vs Sigma Olomouc — 0-0 agg (17:45 UTC) ***TOP***
  Lyon vs Celta Vigo — 1-1 agg (17:45 UTC) ***TOP***
  Freiburg vs Genk — Genk lead 1-0 (17:45 UTC UEL)
  Midtjylland vs Nottingham Forest — Midtjylland lead 1-0 (17:45 UTC UEL)
  Sparta Praha vs AZ — AZ lead 2-1 (20:00 UTC)
  Raków vs Fiorentina — Fiorentina lead 2-1 (17:45 UTC)

Near-res windows: 17:45 kickoffs → 19:00-19:30 UTC, 20:00 kickoffs → 21:15-21:45 UTC
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
    # === 17:45 UTC Kickoffs (UECL) — near-res 19:00-19:30 UTC ===

    # AEK Larnaca vs Crystal Palace — AGG 0-0 ***TOP TARGET***
    {"name": "AEK Larnaca", "token_id": "113592167476112368377017567416536793397202318586644634522629615361927630230588",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will AEK Lárnakas win on 2026-03-19?"},
    {"name": "Crystal Palace", "token_id": "34478539241263835627716465625468103086042104068749881228511182842076581156184",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will Crystal Palace FC win on 2026-03-19?"},

    # Mainz vs Sigma Olomouc — AGG 0-0 ***TOP TARGET***
    {"name": "Mainz", "token_id": "69868544997512824044899123215660369925432048451579314120492168106306620825988",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will 1. FSV Mainz 05 win on 2026-03-19?"},
    {"name": "Sigma Olomouc", "token_id": "69758248607959633563184507277655271437157141598290208908645133551682657660986",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will SK Sigma Olomouc win on 2026-03-19?"},

    # Raków vs Fiorentina — AGG: Fiorentina lead 2-1
    {"name": "Rakow", "token_id": "102467901766651762647759573778846595736292552464284317814576569223866135699208",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will RKS Raków Częstochowa win on 2026-03-19?"},
    {"name": "Fiorentina", "token_id": "85257638182063031746984096738970682192757388223474617391514620886673455897270",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will ACF Fiorentina win on 2026-03-19?"},

    # === UEL 17:45 UTC Kickoffs — near-res 19:00-19:30 UTC ===

    # Freiburg vs Genk — AGG: Genk lead 1-0
    {"name": "Freiburg", "token_id": "31546125618447629392456763920667712957460313159582282143982873674114205010802",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will SC Freiburg win on 2026-03-19?"},
    {"name": "Genk", "token_id": "50952005678815583020950425809435852261976700869378288897106995885118304322395",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will KRC Genk win on 2026-03-19?"},

    # Midtjylland vs Nottingham Forest — AGG: Midtjylland lead 1-0
    {"name": "Midtjylland", "token_id": "47382633911097324690852856526737287671649541085913855159696395204536496865583",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will FC Midtjylland win on 2026-03-19?"},
    {"name": "Nott. Forest", "token_id": "11381745081746637908130783364467955863250369078721878469131698218997759271578",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "question": "Will Nottingham Forest FC win on 2026-03-19?"},

    # Lyon vs Celta Vigo — AGG 1-1 ***TOP TARGET*** (17:45 UTC kickoff!)
    {"name": "Lyon", "token_id": "16736607457308526637193898830256233071814673439646651083024928473642839224863",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will Olympique Lyonnais win on 2026-03-19?"},
    {"name": "Celta Vigo", "token_id": "62505429809364797963518971310518916509956092021742080639017340569942721490348",
     "end_date": "2026-03-19T19:30:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will RC Celta de Vigo win on 2026-03-19?"},

    # === 20:00 UTC Kickoffs — near-res 21:15-21:45 UTC ===

    # Roma vs Bologna — AGG tied ***TOP TARGET***
    {"name": "Roma", "token_id": "62201878766395679219609333607682818399554278525517620289291635280180784905777",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will AS Roma win on 2026-03-19?"},
    {"name": "Bologna", "token_id": "106619179671509077118313857008651187416821684235679509171170439420838436591827",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "level_agg": True, "question": "Will Bologna FC 1909 win on 2026-03-19?"},

    # Aston Villa vs Lille — AGG: Villa lead 1-0
    {"name": "Aston Villa", "token_id": "62033066181846619602217677397394431047823124200859036296834340893601132584539",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will Aston Villa FC win on 2026-03-19?"},
    {"name": "Lille", "token_id": "94428360559874939242944998940635747485895796179106438605354645643890388961768",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will Lille OSC win on 2026-03-19?"},

    # Sparta Praha vs AZ — AGG: AZ lead 2-1
    {"name": "Sparta Praha", "token_id": "45982255690619183697346722448259831858197509742730700252878372941959297252320",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will AC Sparta Praha win on 2026-03-19?"},
    {"name": "AZ", "token_id": "108423484933427952412566969307967095836553190215409673707553462810070050957499",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will AZ win on 2026-03-19?"},

    # Shakhtar vs Lech Poznan — AGG: Shakhtar lead 3-1
    {"name": "Shakhtar", "token_id": "86003295122105902358180916068167327039874572306169471252276491919780492230380",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will FK Shakhtar Donetsk win on 2026-03-19?"},
    {"name": "Lech Poznan", "token_id": "76067999946122985694354050321178024314155865411819856121664480853044666632263",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will KKS Lech Poznań win on 2026-03-19?"},

    # Strasbourg vs Rijeka — AGG: Strasbourg lead 2-1
    {"name": "Strasbourg", "token_id": "20305626165098596503187846726867794311196171522279539621852683915156076439440",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will RC Strasbourg Alsace win on 2026-03-19?"},
    {"name": "Rijeka", "token_id": "11351786307701812399802585090904300524591091995573958851807861188908837313754",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will HNK Rijeka win on 2026-03-19?"},

    # Rayo Vallecano vs Samsunspor — AGG: Rayo lead 3-1
    {"name": "Rayo Vallecano", "token_id": "89621114469900654363718805000859985501557629515605550141585470099339876063588",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will Rayo Vallecano de Madrid win on 2026-03-19?"},
    {"name": "Samsunspor", "token_id": "87857983873883107794643483589987578602325185053500445683412705289534955716321",
     "end_date": "2026-03-19T21:45:00Z", "pre_game_price": 0.0, "question": "Will Samsunspor win on 2026-03-19?"},
]

# Tiered params — level aggregate matches get bigger bets + slightly lower threshold
# Level agg: first goal at 80th min = 95%+ true prob, MMs price 0.82-0.92 → real edge
PARAMS_LEVEL_AGG = {
    "max_spend": 14.0,
    "min_price": 0.82,
    "max_price": 0.94,
    "min_jump": 0.20,
    "max_spread": 0.04,
    "max_mins": 15,
    "pct_balance": 0.32,
}
PARAMS_STANDARD = {
    "max_spend": 8.0,
    "min_price": 0.85,
    "max_price": 0.94,
    "min_jump": 0.22,
    "max_spread": 0.04,
    "max_mins": 15,
    "pct_balance": 0.20,
}
MIN_SPEND = 2.0
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
    balance = get_usdc_balance(client)
    now = datetime.now(timezone.utc)
    print(f"  Balance: ${balance:.2f}")

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

            # Calculate minutes to end
            end_dt = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins_left = (end_dt - now).total_seconds() / 60

            # Use tiered params based on level_agg flag
            p = PARAMS_LEVEL_AGG if w.get("level_agg") else PARAMS_STANDARD

            trigger = (
                buy_price >= p["min_price"] and
                buy_price <= p["max_price"] and
                jump >= p["min_jump"] and
                abs(spread) < p["max_spread"] and
                mins_left <= p["max_mins"] and
                mins_left > 0 and
                balance >= MIN_SPEND
            )

            tier_label = " [AGG]" if w.get("level_agg") else ""
            if abs(jump) > 0.05 or buy_price >= 0.80:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} mins_left={mins_left:.0f}{tier_label} {status}")

            if trigger:
                spend = min(p["max_spend"], balance * p["pct_balance"])
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
                        "market_id": f"near-res-soccer-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Soccer near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"SOCCER NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}, {mins_left:.0f} min left")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            print(f"  {w['name']:14s} ERROR: {e}")


def main():
    print(f"=== Soccer Near-Res Monitor: UECL + UEL March 19 ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"Params LEVEL_AGG: {PARAMS_LEVEL_AGG}")
    print(f"Params STANDARD: {PARAMS_STANDARD}")
    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    for i in range(480):  # 8 hours
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  ERROR in check: {e}")
        time.sleep(60)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
