#!/usr/bin/env python3
"""
Near-resolution monitor: watches soccer match prices on Polymarket.
When a team's win price jumps significantly (indicating they scored/are winning),
and the match is near its end, buy YES on the leader.

Logic:
- Poll market prices every 60 seconds
- If a win market price > 0.62 AND < 0.85 (sweet spot: leading but not yet priced in)
- AND the match end_date is within 45 minutes (80th minute territory)
- Buy up to $10-12 of the leader
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

# Markets to monitor: (search_term, end_date_utc, pre_game_fav_price)
WATCH_LIST = [
    # Saudi League (kickoff ~15:30, ends ~17:15, PM end 18:00)
    {
        "name": "Al Qadisiyah",
        "token_id": "105836362869408823324177118215126371998519795443641115541764244066501605428150",
        "end_date": "2026-03-13T18:00:00Z",
        "pre_game_price": 0.405,
        "question": "Will Al Qadisiyah Saudi Club win on 2026-03-13?",
    },
    {
        "name": "Al Ahli",
        "token_id": "75185641502519272705063822919555187238482510854841025352351433084740549515570",
        "end_date": "2026-03-13T18:00:00Z",
        "pre_game_price": 0.305,
        "question": "Will Al Ahli Saudi Club win on 2026-03-13?",
    },
    {
        "name": "Al Ittihad",
        "token_id": None,  # Need to find
        "end_date": "2026-03-13T18:00:00Z",
        "pre_game_price": 0.615,
        "question": "Will Al Ittihad win on 2026-03-13?",
    },
    # Fenerbahce (kickoff ~17:00 Turkish time, PM end 17:00 UTC? -- check)
    {
        "name": "Fenerbahçe",
        "token_id": "46709670121582610004912857317063745965467029251368454355229888096157919924763",
        "end_date": "2026-03-13T17:00:00Z",
        "pre_game_price": 0.675,
        "question": "Will Fenerbahçe SK win on 2026-03-13?",
    },
    # PEC Zwolle vs Groningen (kickoff ~17:00, PM end 19:00)
    {
        "name": "PEC Zwolle",
        "token_id": None,  # Need to find
        "end_date": "2026-03-13T19:00:00Z",
        "pre_game_price": 0.355,
        "question": "Will PEC Zwolle win on 2026-03-13?",
    },
    {
        "name": "FC Groningen",
        "token_id": None,  # Need to find
        "end_date": "2026-03-13T19:00:00Z",
        "pre_game_price": 0.375,
        "question": "Will FC Groningen win on 2026-03-13?",
    },
]

MAX_SPEND_PER_TRADE = 12.0
MIN_SPEND = 5.0
MIN_PRICE_JUMP = 0.15  # Price must have jumped 15%+ from pre-game
MIN_NEAR_RES_PRICE = 0.62  # Minimum price to trigger buy (team clearly leading)
MAX_NEAR_RES_PRICE = 0.85  # Don't buy above this (not enough upside)
BOUGHT = set()  # Track what we've already bought


def find_token_ids(client):
    """Resolve missing token IDs from Gamma API."""
    import requests
    for watch in WATCH_LIST:
        if watch["token_id"] is None:
            try:
                resp = requests.get("https://gamma-api.polymarket.com/markets", params={
                    "active": "true",
                    "closed": "false",
                    "_limit": "5",
                    "search": watch["name"] + " win 2026-03-13",
                })
                markets = resp.json()
                for m in markets:
                    q = m.get("question", "")
                    if watch["name"].lower() in q.lower() and "win" in q.lower():
                        tids = json.loads(m.get("clobTokenIds", "[]"))
                        if tids:
                            watch["token_id"] = tids[0]  # YES token
                            watch["question"] = q
                            print(f"  Found {watch['name']}: {tids[0][:20]}...")
                            break
            except Exception as e:
                print(f"  Failed to find {watch['name']}: {e}")


def check_prices(client):
    """Check current prices for all watched markets."""
    results = []
    for watch in WATCH_LIST:
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

            print(f"  {watch['name']:15s} buy={price:.3f} sell={sell_price:.3f} "
                  f"jump={jump:+.3f} mins_left={mins_to_end:.0f} {status}")
        except Exception as e:
            print(f"  {watch['name']:15s} ERROR: {e}")

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

        # Update state
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
    print(f"=== Near-Resolution Monitor Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    # Resolve missing token IDs
    print("\nResolving token IDs...")
    find_token_ids(client)

    # Monitor loop — run for up to 2 hours
    max_iterations = 120  # 120 * 60s = 2 hours
    for i in range(max_iterations):
        now = datetime.now(timezone.utc)
        print(f"\n--- Check #{i+1} at {now.strftime('%H:%M:%S UTC')} ---")

        balance = get_usdc_balance(client)
        print(f"  Balance: ${balance:.2f}")

        results = check_prices(client)

        for r in results:
            # Buy signal conditions:
            # 1. Price jumped significantly from pre-game
            # 2. Price is in sweet spot (0.62-0.85)
            # 3. Match is near end (< 60 min to PM end_date, meaning 80th+ min)
            # 4. We haven't already bought this
            if (r["jump"] >= MIN_PRICE_JUMP and
                r["current_buy"] >= MIN_NEAR_RES_PRICE and
                r["current_buy"] <= MAX_NEAR_RES_PRICE and
                r["mins_to_end"] < 60 and
                r["token_id"] not in BOUGHT and
                balance >= MIN_SPEND):

                try_buy(client, r, balance)
                balance = get_usdc_balance(client)

        # Check if all markets have ended
        active = [r for r in results if r["mins_to_end"] > -30]
        if not active:
            print("\nAll monitored markets ended. Stopping.")
            break

        time.sleep(60)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")


if __name__ == "__main__":
    main()
