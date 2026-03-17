#!/usr/bin/env python3
"""
Near-resolution monitor for Champions League March 17, 2026.

Usage:
  python3 near_res_cl_mar17.py --early   # Sporting vs Bodo/Glimt (17:45 kickoff, near-res 19:00-19:30)
  python3 near_res_cl_mar17.py           # Man City vs RM + Chelsea vs PSG + Arsenal vs Leverkusen (20:00 kickoff, near-res 21:15-21:45)
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

# Sporting vs Bodo/Glimt — kickoff 17:45 UTC, ends ~19:30 UTC
# Bodo/Glimt are heavy CL favorites ($562K volume)
EARLY_WATCH = [
    {
        "name": "Bodo/Glimt",
        "token_id": "81667796278564038256544977005416838662066952707140667017233596748247119767708",
        "end_date": "2026-03-17T19:30:00Z",
        "pre_game_price": 0.0,  # Will be set at runtime
        "question": "Will FK Bodø/Glimt win on 2026-03-17?",
    },
    {
        "name": "Sporting CP",
        "token_id": "61140652966863130348027495935215031496891607070352817033325685455006704238006",
        "end_date": "2026-03-17T19:30:00Z",
        "pre_game_price": 0.0,
        "question": "Will Sporting CP win on 2026-03-17?",
    },
    {
        "name": "Sporting/BG Draw",
        "token_id": "72429265217288858991511814047668837748469824491554767016144570850151659406562",
        "end_date": "2026-03-17T19:30:00Z",
        "pre_game_price": 0.0,
        "question": "Will Sporting CP vs. FK Bodø/Glimt end in a draw?",
    },
]

# Man City vs Real Madrid + Chelsea vs PSG + Arsenal vs Leverkusen — kickoff 20:00 UTC, ends ~21:45 UTC
CL_WATCH = [
    {
        "name": "Man City",
        "token_id": "93088875585442681803007077559405922313048382254935516642860307964213720037932",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Manchester City FC win on 2026-03-17?",
    },
    {
        "name": "Real Madrid",
        "token_id": "55723009503764906852137229221196982431481755148351124868578754295303789980602",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Real Madrid CF win on 2026-03-17?",
    },
    {
        "name": "Man City/RM Draw",
        "token_id": "95487646568849577210554203777265189565956273223905606855527886973693209233146",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Manchester City FC vs. Real Madrid CF end in a draw?",
    },
    {
        "name": "Chelsea",
        "token_id": "56817997803930189621621678482938928447956973865815474481042328008173861838753",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Chelsea FC win on 2026-03-17?",
    },
    {
        "name": "PSG",
        "token_id": "44111445313965949875646902229843929924317743459760140113673086381666707007527",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Paris Saint-Germain FC win on 2026-03-17?",
    },
    {
        "name": "Chelsea/PSG Draw",
        "token_id": "58718726174364621310521815907469929023493927093514361785699287934182852040113",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Chelsea FC vs. Paris Saint-Germain FC end in a draw?",
    },
    {
        "name": "Arsenal",
        "token_id": "108880650012405308230310790426893511945577423523009394904421019220163446158055",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Arsenal FC win on 2026-03-17?",
    },
    {
        "name": "Leverkusen",
        "token_id": "89752872295420908186397779588408998530110254457318197087057289333082954280496",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Bayer 04 Leverkusen win on 2026-03-17?",
    },
    {
        "name": "Arsenal/LEV Draw",
        "token_id": "980353891091935392163843458159224612118943371316549619660099315502689148058",
        "end_date": "2026-03-17T21:45:00Z",
        "pre_game_price": 0.0,
        "question": "Will Arsenal FC vs. Bayer 04 Leverkusen end in a draw?",
    },
]

MAX_SPEND_PER_TRADE = 15.0
MIN_SPEND = 3.0
MIN_PRICE_JUMP = 0.20
MIN_NEAR_RES_PRICE = 0.80   # Higher threshold — 0.62 was too low (Las Palmas loss)
MAX_NEAR_RES_PRICE = 0.93
MAX_SPREAD = 0.08            # Skip if buy-sell spread too wide (thin market)
MAX_MINS_TO_END = 25         # Only buy in last 25 mins (not 60)
BOUGHT = set()


def snapshot_pre_game_prices(client, watch_list):
    """Capture pre-game prices on first check."""
    for w in watch_list:
        if w["pre_game_price"] == 0.0:
            try:
                info = client.get_price(w["token_id"], "buy")
                w["pre_game_price"] = float(info.get("price", 0))
                print(f"  Pre-game {w['name']}: {w['pre_game_price']:.3f}")
            except Exception as e:
                print(f"  Pre-game {w['name']}: ERROR {e}")


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

            spread = price - sell_price
            status = "***BUY SIGNAL***" if (
                price >= MIN_NEAR_RES_PRICE and
                price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                mins_to_end < MAX_MINS_TO_END and
                spread < MAX_SPREAD
            ) else ""

            print(f"  {watch['name']:18s} buy={price:.3f} sell={sell_price:.3f} "
                  f"spread={spread:.3f} jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")
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
            "market_id": f"near-res-cl-{name.lower().replace(' ', '-')}",
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
            "research_note": f"CL Near-resolution: {name} price jumped {market['jump']:+.3f} from pre-game {market['pre_game_price']:.3f}",
        }
        state["positions"].append(pos)
        save_state(state)

        BOUGHT.add(tid)
        send(f"CL NEAR-RES BUY: {name} YES @ {price:.3f}\n  ${spend:.2f} ({shares:.2f} shares)\n  Jump: {market['jump']:+.3f}, {market['mins_to_end']:.0f} min to market end")
        print(f"  Success: {shares:.2f} shares")
        return True
    else:
        print(f"  BUY FAILED for {name}")
        return False


def main():
    if "--early" in sys.argv:
        watch = EARLY_WATCH
        label = "CL: Sporting vs Bodo/Glimt"
    else:
        watch = CL_WATCH
        label = "CL: Man City/RM + Chelsea/PSG + Arsenal/Leverkusen"

    print(f"=== CL Near-Resolution Monitor ({label}) Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    # Snapshot pre-game prices
    print("Capturing pre-game prices...")
    snapshot_pre_game_prices(client, watch)

    max_iterations = 180  # 3 hours
    for i in range(max_iterations):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")

        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        results = check_prices(client, watch)

        for r in results:
            spread = r["current_buy"] - r["current_sell"]
            if (r["jump"] >= MIN_PRICE_JUMP and
                r["current_buy"] >= MIN_NEAR_RES_PRICE and
                r["current_buy"] <= MAX_NEAR_RES_PRICE and
                r["mins_to_end"] < MAX_MINS_TO_END and
                spread < MAX_SPREAD and
                r["token_id"] not in BOUGHT and
                balance >= MIN_SPEND):

                try_buy(client, r, balance)
                balance = get_usdc_balance(client)

        active = [r for r in results if r["mins_to_end"] > -30]
        if not active:
            print("\nAll monitored markets ended. Stopping.")
            break

        time.sleep(60)

    print(f"\n=== CL Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
