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
    # March 14: Premier League 17:30 kickoffs (near-res ~19:00-19:15)
    {
        "name": "Chelsea",
        "token_id": "86033427677252416086751450370475670590824726105322635674860437641344282902660",
        "end_date": "2026-03-14T17:30:00Z",
        "pre_game_price": 0.525,
        "question": "Will Chelsea FC win on 2026-03-14?",
    },
    {
        "name": "Newcastle",
        "token_id": "79051789373886457546553944638473613045587191226843744294349583359740412740625",
        "end_date": "2026-03-14T17:30:00Z",
        "pre_game_price": 0.245,
        "question": "Will Newcastle United FC win on 2026-03-14?",
    },
    {
        "name": "Arsenal",
        "token_id": "38994064194073482228229509993277184534677234863592159586324882995065445332711",
        "end_date": "2026-03-14T17:30:00Z",
        "pre_game_price": 0.695,
        "question": "Will Arsenal FC win on 2026-03-14?",
    },
    {
        "name": "Everton",
        "token_id": "43604923306352456348302507504058451331490120371228577268768753674967093388529",
        "end_date": "2026-03-14T17:30:00Z",
        "pre_game_price": 0.105,
        "question": "Will Everton FC win on 2026-03-14?",
    },
    # Galatasaray & Napoli — 17:00 kickoff (near-res ~18:45)
    {
        "name": "Galatasaray",
        "token_id": "25515057910772055243331874116691924170920013614841644354223486326070351821619",
        "end_date": "2026-03-14T17:00:00Z",
        "pre_game_price": 0.635,
        "question": "Will Galatasaray SK win on 2026-03-14?",
    },
    {
        "name": "Napoli",
        "token_id": "23908744235029436668032187407696757858496393436364928402129538177797433532204",
        "end_date": "2026-03-14T17:00:00Z",
        "pre_game_price": 0.695,
        "question": "Will SSC Napoli win on 2026-03-14?",
    },
    # Valencia & Hamburger SV — 17:30 kickoff
    {
        "name": "Valencia",
        "token_id": "8750194317516268516817718126091365606027657031311578952835586854765548022671",
        "end_date": "2026-03-14T17:30:00Z",
        "pre_game_price": 0.365,
        "question": "Will Valencia CF win on 2026-03-14?",
    },
    # PSV — 17:45 kickoff
    {
        "name": "PSV",
        "token_id": "49533029700384006654091626079285563941775000157257605826954360379768422248009",
        "end_date": "2026-03-14T17:45:00Z",
        "pre_game_price": 0.665,
        "question": "Will PSV win on 2026-03-14?",
    },
]

# European evening matches (kickoff 19:45-20:30 UTC, near-res ~21:00-21:45)
EUROPE_WATCH = [
    {
        "name": "Man City",
        "token_id": "110162709167587205216232528451528728935099976071721615825821885124373392450388",
        "end_date": "2026-03-14T20:00:00Z",
        "pre_game_price": 0.585,
        "question": "Will Manchester City FC win on 2026-03-14?",
    },
    {
        "name": "West Ham",
        "token_id": "92825265075799673067651598133667095451197237682299985513689996841118596412360",
        "end_date": "2026-03-14T20:00:00Z",
        "pre_game_price": 0.195,
        "question": "Will West Ham United FC win on 2026-03-14?",
    },
    {
        "name": "Juventus",
        "token_id": "32897316543933165251725391380019961733982806506523098784268030110806251195504",
        "end_date": "2026-03-14T19:45:00Z",
        "pre_game_price": 0.635,
        "question": "Will Juventus FC win on 2026-03-14?",
    },
    {
        "name": "Ajax",
        "token_id": "13413759278643140865491808498379429762143370712073655986480539147479476284507",
        "end_date": "2026-03-14T20:00:00Z",
        "pre_game_price": 0.555,
        "question": "Will AFC Ajax win on 2026-03-14?",
    },
    {
        "name": "Monaco",
        "token_id": "4525178718973714005518178755756920621448711993962533058118612855091762018393",
        "end_date": "2026-03-14T20:05:00Z",
        "pre_game_price": 0.595,
        "question": "Will AS Monaco FC win on 2026-03-14?",
    },
    {
        "name": "Benfica",
        "token_id": "96678350184449364313383924060096992021831586517408123639485157413196462513033",
        "end_date": "2026-03-14T20:30:00Z",
        "pre_game_price": 0.755,
        "question": "Will Sport Lisboa e Benfica win on 2026-03-14?",
    },
    {
        "name": "Hertha",
        "token_id": "101350916652676475722763375668894677984591801526137475256169695767270592994694",
        "end_date": "2026-03-14T19:30:00Z",
        "pre_game_price": 0.435,
        "question": "Will Hertha BSC win on 2026-03-14?",
    },
]

# NBA games March 14-15 — near-res candidates
NBA_WATCH = [
    # Hornets vs Spurs — tip-off 19:30 UTC, competitive (CHA 35.5%)
    {
        "name": "Hornets",
        "token_id": "110869774625647847297483294625719024865442757690993620922476091681122575065947",
        "end_date": "2026-03-14T19:30:00Z",
        "pre_game_price": 0.355,
        "question": "Hornets vs. Spurs",
    },
    {
        "name": "Spurs",
        "token_id": "89413703435662076766671780767668367664284824115908819707674538237103927401639",
        "end_date": "2026-03-14T19:30:00Z",
        "pre_game_price": 0.645,
        "question": "Hornets vs. Spurs",
    },
    # Bucks vs Hawks — tip-off 19:00 UTC
    {
        "name": "Bucks",
        "token_id": "78265320434438407236904713809661535853467556329693049148689383877376486577277",
        "end_date": "2026-03-14T19:00:00Z",
        "pre_game_price": 0.225,
        "question": "Bucks vs. Hawks",
    },
    {
        "name": "Hawks",
        "token_id": "63122922322829694953022986094683228506728480541563434685829692181976875224010",
        "end_date": "2026-03-14T19:00:00Z",
        "pre_game_price": 0.775,
        "question": "Bucks vs. Hawks",
    },
    # Magic vs Heat — tip-off 00:00 UTC Mar 15
    {
        "name": "Magic",
        "token_id": "66615266624359354060400093448369771789228282833780928627869485822387307717041",
        "end_date": "2026-03-15T00:00:00Z",
        "pre_game_price": 0.395,
        "question": "Magic vs. Heat",
    },
    {
        "name": "Heat",
        "token_id": "34869283377703440323383941894688217713531070205322598936747028741052007807950",
        "end_date": "2026-03-15T00:00:00Z",
        "pre_game_price": 0.605,
        "question": "Magic vs. Heat",
    },
    # Nuggets vs Lakers — our position! tip-off 00:30 UTC Mar 15
    {
        "name": "Lakers",
        "token_id": "3620877471053864248474512777478096197717658103010744835632826689683333592523",
        "end_date": "2026-03-15T00:30:00Z",
        "pre_game_price": 0.415,
        "question": "Nuggets vs. Lakers",
    },
    {
        "name": "Nuggets",
        "token_id": "53527326655632348904951814527652963993760607637916381884216680176529652766595",
        "end_date": "2026-03-15T00:30:00Z",
        "pre_game_price": 0.585,
        "question": "Nuggets vs. Lakers",
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
    global WATCH_LIST
    # Choose watch list based on command-line arg
    if "--nba" in sys.argv:
        watch = NBA_WATCH
        label = "NBA/NHL"
    elif "--europe" in sys.argv:
        watch = EUROPE_WATCH
        label = "EUROPE"
    else:
        watch = WATCH_LIST
        label = "SAUDI/TURKISH"

    # Override the global WATCH_LIST for this run
    WATCH_LIST = watch

    print(f"=== Near-Resolution Monitor ({label}) Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}")

    # Resolve missing token IDs
    print("\nResolving token IDs...")
    find_token_ids(client)

    # Monitor loop — run for up to 2.5 hours
    max_iterations = 150  # 150 * 60s = 2.5 hours
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
