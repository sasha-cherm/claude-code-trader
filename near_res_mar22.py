#!/usr/bin/env python3
"""
Near-resolution monitor for March 22, 2026 (Sunday).
KEY GAMES: Barcelona-Rayo (13:00), Arsenal-ManCity EFL Cup (16:30),
Athletic-Betis (17:30), Real Madrid-Atletico (20:00).
Plus: Feyenoord-Ajax, Norwegian, MLS, Brazilian, NBA (TBD).

IMPROVEMENT: Volatility check — if price crashed >20% in last 30 min
then recovered, raise threshold to 0.92+ (Leverkusen lesson from Mar 21).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

ALL_GAMES = [
    # === La Liga (TOP PRIORITY) ===
    # Barcelona vs Rayo Vallecano — 13:00 UTC kick (end ~14:45)
    {"name": "Barcelona", "token_id": "85472148416685863897240595134407738946454201641175811952882644022281429468328",
     "end_date": "2026-03-22T14:45:00Z", "pre_game_price": 0.0,
     "question": "FC Barcelona vs. Rayo Vallecano"},
    {"name": "Rayo", "token_id": "93585995644300324868000001908944277773901392851830851295009588507982769661477",
     "end_date": "2026-03-22T14:45:00Z", "pre_game_price": 0.0,
     "question": "FC Barcelona vs. Rayo Vallecano"},

    # Athletic Club vs Real Betis — 17:30 UTC kick (end ~19:15)
    {"name": "Athletic", "token_id": "94398821367677125291370679735467238406366234871312400934706651111495758240741",
     "end_date": "2026-03-22T19:15:00Z", "pre_game_price": 0.0,
     "question": "Athletic Club vs. Real Betis"},
    {"name": "Betis", "token_id": "77696817795581000009814126192926667567712375906575902666566932539590205049779",
     "end_date": "2026-03-22T19:15:00Z", "pre_game_price": 0.0,
     "question": "Athletic Club vs. Real Betis"},

    # Real Madrid vs Atletico Madrid — 20:00 UTC kick (end ~21:45)
    {"name": "Real Madrid", "token_id": "77530118520273064256136296921086343314452380218097735574854503040708128459605",
     "end_date": "2026-03-22T21:45:00Z", "pre_game_price": 0.0,
     "question": "Real Madrid vs. Atletico Madrid"},
    {"name": "Atletico", "token_id": "102162584058861782341459640970430737445725951182648724328461902446679800837770",
     "end_date": "2026-03-22T21:45:00Z", "pre_game_price": 0.0,
     "question": "Real Madrid vs. Atletico Madrid"},

    # === EFL Cup Final (SPECIAL: extra time + pens if drawn) ===
    # Arsenal vs Man City — 16:30 UTC kick (end ~18:15 if decided in 90 min, ~19:00+ if ET)
    # NOTE: Near-res ONLY if one team is clearly ahead (2+ goal lead or 1-0 at 88+ min)
    # Because cup final has ET, a 1-0 at 85th min is NOT reliable (they can equalize and go to ET)
    {"name": "Arsenal", "token_id": "71377433182851205680841246761509083153295115718889472943162377235871441027308",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Arsenal vs. Man City EFL Cup Final"},
    {"name": "Man City", "token_id": "78062639436308554153121574747053830957843296905095649047131706952288975438353",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "Arsenal vs. Man City EFL Cup Final"},

    # === Eredivisie ===
    # Feyenoord vs Ajax — 11:30 UTC kick (end ~13:15)
    {"name": "Feyenoord", "token_id": "107138920092843326013920041030851304675233726290666958584829931581847139156260",
     "end_date": "2026-03-22T13:15:00Z", "pre_game_price": 0.0,
     "question": "Feyenoord vs. Ajax"},
    {"name": "Ajax", "token_id": "113878443896319768505828444114200061985645337509069751914878476170936685700805",
     "end_date": "2026-03-22T13:15:00Z", "pre_game_price": 0.0,
     "question": "Feyenoord vs. Ajax"},

    # NEC vs Heerenveen — 09:30 UTC kick (end ~11:15)
    {"name": "NEC", "token_id": "",  # TBD — fill at launch
     "end_date": "2026-03-22T11:15:00Z", "pre_game_price": 0.0,
     "question": "NEC vs. Heerenveen"},

    # FC Utrecht vs Go Ahead Eagles — 12:00 UTC kick (end ~13:45)
    {"name": "FC Utrecht", "token_id": "",  # TBD
     "end_date": "2026-03-22T13:30:00Z", "pre_game_price": 0.0,
     "question": "FC Utrecht vs. Go Ahead Eagles"},

    # === Norwegian Eliteserien ===
    {"name": "Rosenborg", "token_id": "",  # TBD
     "end_date": "2026-03-22T13:30:00Z", "pre_game_price": 0.0,
     "question": "Rosenborg vs. Valerenga"},
    {"name": "Brann", "token_id": "24257519475765476947422542456129679722444314875554218826254303302875112626576",
     "end_date": "2026-03-22T16:00:00Z", "pre_game_price": 0.0,
     "question": "Brann vs. Tromso"},

    # === MLS ===
    # NYC vs Inter Miami — 15:15 UTC kick? (end ~17:00)
    {"name": "NYC FC", "token_id": "68869490511577960003350706703310476741285279468310643986371320036933615755081",
     "end_date": "2026-03-22T17:00:00Z", "pre_game_price": 0.0,
     "question": "NYC FC vs. Inter Miami"},
    {"name": "Inter Miami", "token_id": "73204938083418938806615746405399493884866532564363395933300309800529440427768",
     "end_date": "2026-03-22T17:00:00Z", "pre_game_price": 0.0,
     "question": "NYC FC vs. Inter Miami"},
    # Minnesota vs Seattle (end ~18:30)
    {"name": "Minnesota", "token_id": "18738492077676321335039327752730911155600758030968563387089451575279629357708",
     "end_date": "2026-03-22T18:30:00Z", "pre_game_price": 0.0,
     "question": "Minnesota vs. Seattle"},
    {"name": "Seattle", "token_id": "104520603605055176802109450457733439933652950792869488282513174081380724335382",
     "end_date": "2026-03-22T18:30:00Z", "pre_game_price": 0.0,
     "question": "Minnesota vs. Seattle"},
    # Portland vs LA Galaxy (end ~20:45)
    {"name": "Portland", "token_id": "43338332383007140456638013105621169752894982792704461739161084294740953994002",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "Portland vs. LA Galaxy"},
    {"name": "LA Galaxy", "token_id": "56668386096051280878465472889139462509897461898196318038620764266446064162307",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "Portland vs. LA Galaxy"},

    # === Brazilian ===
    {"name": "Cruzeiro", "token_id": "51015101202179869094225166143933292809809932744657866620438265505737077140478",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Cruzeiro vs. Santos"},
    {"name": "Santos", "token_id": "110533786134096045987603784985927123927459789915309680975646183780072724770570",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Cruzeiro vs. Santos"},
    {"name": "Bahia", "token_id": "105609826804147553661880450661764537247927930508985275135977951873324129920817",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Remo vs. Bahia"},
    {"name": "Remo", "token_id": "55626937656248052743126816151487234623443982907348158844535520198675006966760",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Remo vs. Bahia"},

    # === NBA (added day-of when markets appear) ===
    # Placeholder — next session fills these
]

# --- Parameters ---
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 18.0
PCT_OF_BALANCE = 0.28
MIN_SPEND = 1.0

# Volatility tracking (Leverkusen lesson)
PRICE_HISTORY = defaultdict(list)  # token_id -> [(timestamp, price)]
VOLATILITY_THRESHOLD = 0.20       # If price dropped >20% then recovered, raise min
VOLATILE_MIN_PRICE = 0.92         # Higher threshold for volatile matches

BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    for w in watch_list:
        if not w["token_id"] or w["pre_game_price"] != 0.0:
            continue
        try:
            info = client.get_price(w["token_id"], "buy")
            p = float(info.get("price", 0))
            if p > 0.01:
                w["pre_game_price"] = p
                print(f"  Pre-game {w['name']}: {p:.3f}")
        except Exception as e:
            print(f"  Pre-game {w['name']}: ERROR {e}")


def is_volatile(token_id, current_price):
    """Check if this token had a big price drop and recovery (Leverkusen pattern)."""
    history = PRICE_HISTORY.get(token_id, [])
    if len(history) < 5:
        return False
    # Check if price dropped >20% from max in last 30 min then recovered
    recent = [(t, p) for t, p in history if (datetime.now(timezone.utc) - t).total_seconds() < 1800]
    if len(recent) < 3:
        return False
    max_price = max(p for _, p in recent)
    min_price = min(p for _, p in recent)
    if max_price > 0.01 and (max_price - min_price) / max_price > VOLATILITY_THRESHOLD:
        # Price had a big swing — this match is volatile
        if current_price > min_price + (max_price - min_price) * 0.5:
            return True
    return False


def check_and_buy(client, watch_list):
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)
    check_and_buy.count = getattr(check_and_buy, 'count', 0) + 1
    print(f"\n--- Check #{check_and_buy.count} at {now.strftime('%H:%M:%S')} UTC ---")
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

            # Track price history for volatility check
            PRICE_HISTORY[w["token_id"]].append((now, buy_price))
            # Keep only last 60 entries
            if len(PRICE_HISTORY[w["token_id"]]) > 60:
                PRICE_HISTORY[w["token_id"]] = PRICE_HISTORY[w["token_id"]][-60:]

            jump = buy_price - w["pre_game_price"]
            spread = buy_price - sell_price

            end_str = w.get("end_date", "")
            if end_str:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                mins_left = (end_dt - now).total_seconds() / 60
            else:
                mins_left = 999

            # Volatility-aware minimum price
            volatile = is_volatile(w["token_id"], buy_price)
            min_price = VOLATILE_MIN_PRICE if volatile else MIN_NEAR_RES_PRICE

            trigger = (
                buy_price >= min_price and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                abs(spread) < MAX_SPREAD and
                mins_left <= MAX_MINS_TO_END and
                mins_left > 0 and
                balance >= MIN_SPEND
            )

            if abs(jump) > 0.05 or buy_price >= 0.85:
                vol_flag = " [VOLATILE]" if volatile else ""
                status = "***BUY***" if trigger else ""
                mins_str = f" mins={mins_left:.0f}" if end_str else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f}{mins_str}{vol_flag} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                vol_note = " (VOLATILE match, raised threshold)" if volatile else ""
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f}{vol_note} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-mar22-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar22 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.{vol_note}",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR22 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left{vol_note}")

        except Exception as e:
            if "404" not in str(e) and "500" not in str(e):
                print(f"  {w['name']:14s} ERROR: {e}")


def main():
    client = get_client()
    watch_list = [g for g in ALL_GAMES if g["token_id"]]

    print(f"=== Near-Res Monitor: March 22 ===")
    print(f"Tracking {len(watch_list)} tokens across {len(watch_list)//2} games")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, VOLATILE_MIN={VOLATILE_MIN_PRICE}, "
          f"JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Sizing: MAX_SPEND=${MAX_SPEND_PER_TRADE}, PCT={PCT_OF_BALANCE}, MIN_SPEND=${MIN_SPEND}")

    snapshot_pre_game_prices(client, watch_list)

    while True:
        try:
            check_and_buy(client, watch_list)
        except Exception as e:
            print(f"  CYCLE ERROR: {e}")
        time.sleep(90)


if __name__ == "__main__":
    main()
