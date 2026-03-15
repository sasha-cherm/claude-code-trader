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

# March 15 EPL 15:00 UTC kickoffs → match ends ~16:50 UTC
# Run with default (no flag) at 16:00 cron
WATCH_LIST = [
    {
        "name": "Man United",
        "token_id": "49199458578674299280518325446666793632087135647583739482099632115201280158865",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.575,
        "question": "Will Manchester United FC win on 2026-03-15?",
    },
    {
        "name": "Aston Villa",
        "token_id": "33963961321781294066793384128140382622650266529966795638041684912285934887597",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.195,
        "question": "Will Aston Villa FC win on 2026-03-15?",
    },
    {
        "name": "Crystal Palace",
        "token_id": "53860536354451728164758573120509120640842800890402836959946656108912850633383",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.385,
        "question": "Will Crystal Palace FC win on 2026-03-15?",
    },
    {
        "name": "Leeds",
        "token_id": "74649244239744218165949496953496152268678754269160115006529600518430963099320",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.315,
        "question": "Will Leeds United FC win on 2026-03-15?",
    },
    {
        "name": "Nott. Forest",
        "token_id": "53826182091114174886828435963756500685188864753078374559198340086078124917899",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.415,
        "question": "Will Nottingham Forest FC win on 2026-03-15?",
    },
    {
        "name": "Fulham",
        "token_id": "36339850254157377830381845388945943780350502305284825112673686524258047733362",
        "end_date": "2026-03-15T16:50:00Z",
        "pre_game_price": 0.305,
        "question": "Will Fulham FC win on 2026-03-15?",
    },
    {
        "name": "Strasbourg",
        "token_id": "33683147281890171043354345209533950730743388118823392184419735139166976980514",
        "end_date": "2026-03-15T15:50:00Z",
        "pre_game_price": 0.545,
        "question": "Will RC Strasbourg Alsace win on 2026-03-15?",
    },
    # Bundesliga 14:30 UTC kickoff → match ends ~16:20 UTC
    {
        "name": "Werder Bremen",
        "token_id": "59908085706169149298453256852695977985858599445080047197005731044601778414174",
        "end_date": "2026-03-15T16:20:00Z",
        "pre_game_price": 0.465,
        "question": "Will SV Werder Bremen win on 2026-03-15?",
    },
    {
        "name": "Mainz",
        "token_id": "70463659833118434932121900409446017687175970320223208483199932175066511150301",
        "end_date": "2026-03-15T16:20:00Z",
        "pre_game_price": 0.265,
        "question": "Will 1. FSV Mainz 05 win on 2026-03-15?",
    },
    # Serie A 14:00 UTC kickoff → ends ~15:50 UTC
    {
        "name": "Sassuolo",
        "token_id": "115336295632317988478953398287616370959381354532555835292629662046588766635083",
        "end_date": "2026-03-15T15:50:00Z",
        "pre_game_price": 0.375,
        "question": "Will US Sassuolo Calcio win on 2026-03-15?",
    },
    {
        "name": "Cagliari",
        "token_id": "72164875894651384249674561268820986982882695061857894273393683320969555944005",
        "end_date": "2026-03-15T15:50:00Z",
        "pre_game_price": 0.305,
        "question": "Will Cagliari Calcio win on 2026-03-15?",
    },
]

# Liverpool/Spurs + Ligue 1 + Bundesliga + Serie A evening matches
# Run with --europe flag at 18:00/19:00 cron
EUROPE_WATCH = [
    # Liverpool vs Spurs — 17:30 UTC kickoff → ends ~19:20 UTC
    {
        "name": "Liverpool",
        "token_id": "66167282560194887008564299553098597284350396523168513310347866677310039164905",
        "end_date": "2026-03-15T19:20:00Z",
        "pre_game_price": 0.765,
        "question": "Will Liverpool FC win on 2026-03-15?",
    },
    {
        "name": "Tottenham",
        "token_id": "99455241418187642495529445550648546128939146170410824511522791868477388956789",
        "end_date": "2026-03-15T19:20:00Z",
        "pre_game_price": 0.095,
        "question": "Will Tottenham Hotspur FC win on 2026-03-15?",
    },
    # Le Havre vs Lyon — 16:15 UTC kickoff → ends ~18:05 UTC
    {
        "name": "Le Havre",
        "token_id": "67231234491374583022361755057300515639797444042235243164448624186123473489808",
        "end_date": "2026-03-15T18:05:00Z",
        "pre_game_price": 0.255,
        "question": "Will Le Havre AC win on 2026-03-15?",
    },
    {
        "name": "Lyon",
        "token_id": "37377370994752037702847381904203367294295290402867927334113282320460400884629",
        "end_date": "2026-03-15T18:05:00Z",
        "pre_game_price": 0.475,
        "question": "Will Olympique Lyonnais win on 2026-03-15?",
    },
    # Union Berlin — 16:30 UTC kickoff → ends ~18:20 UTC
    {
        "name": "Union Berlin",
        "token_id": "56641814751167200171673046320920175033674354018860266749757763925800910183753",
        "end_date": "2026-03-15T18:20:00Z",
        "pre_game_price": 0.265,
        "question": "Will 1. FC Union Berlin win on 2026-03-15?",
    },
    # Como vs Roma — 17:00 UTC kickoff → ends ~18:50 UTC
    {
        "name": "Como",
        "token_id": "8227112772631693094739639478407668571632728228508949382980000001004338215415",
        "end_date": "2026-03-15T18:50:00Z",
        "pre_game_price": 0.475,
        "question": "Will Como 1907 win on 2026-03-15?",
    },
    # Stuttgart vs Leipzig — 18:30 UTC kickoff → ends ~20:20 UTC
    {
        "name": "Stuttgart",
        "token_id": "61585818258249406325894193591416461445716385424660795859631828408464193337286",
        "end_date": "2026-03-15T20:20:00Z",
        "pre_game_price": 0.395,
        "question": "Will VfB Stuttgart win on 2026-03-15?",
    },
    # Lazio vs Milan — 19:45 UTC kickoff → ends ~21:35 UTC
    {
        "name": "Lazio",
        "token_id": "88160567144921577214376437708658544588172738066048712396946761530657189890408",
        "end_date": "2026-03-15T21:35:00Z",
        "pre_game_price": 0.205,
        "question": "Will SS Lazio win on 2026-03-15?",
    },
    {
        "name": "AC Milan",
        "token_id": "19554927725489076481012307663534400676387785907590892236210445650327988814876",
        "end_date": "2026-03-15T21:35:00Z",
        "pre_game_price": 0.515,
        "question": "Will AC Milan win on 2026-03-15?",
    },
    # Rennes — 19:45 UTC kickoff → ends ~21:35 UTC
    {
        "name": "Rennes",
        "token_id": "33482302459280139891814666653449787984492151798705735558171128921420326780168",
        "end_date": "2026-03-15T21:35:00Z",
        "pre_game_price": 0.435,
        "question": "Will Stade Rennais FC 1901 win on 2026-03-15?",
    },
    # Real Sociedad — 20:00 UTC kickoff → ends ~21:50 UTC
    {
        "name": "Real Sociedad",
        "token_id": "25698934227857913953850853984486665090105797463757652225453371733717629887259",
        "end_date": "2026-03-15T21:50:00Z",
        "pre_game_price": 0.505,
        "question": "Will Real Sociedad de Fútbol win on 2026-03-15?",
    },
]

# NBA games March 15 — end_date is tip-off time, games end ~2.5h later
# 19:00 cron: MIN vs OKC near end (~19:30 UTC)
# 21:00 cron: DET vs TOR, DAL vs CLE near end (~22:00 UTC)
# 00:00 cron: POR vs PHI near end (~00:30 UTC)
# 02:00 cron: GSW vs NYK near end (~02:30 UTC), UTA vs SAC in progress
NBA_WATCH = [
    {
        "name": "Timberwolves",
        "token_id": "72810586197585785194598917405425586022922993698884057036860456597458350862208",
        "end_date": "2026-03-15T19:30:00Z",  # game ends ~19:30 UTC
        "pre_game_price": 0.225,
        "question": "Timberwolves vs. Thunder",
    },
    {
        "name": "Thunder",
        "token_id": "77924895823984704357291646568595586506671111239972966308352581216927852107129",
        "end_date": "2026-03-15T19:30:00Z",
        "pre_game_price": 0.775,
        "question": "Timberwolves vs. Thunder",
    },
    {
        "name": "Pistons",
        "token_id": "70457986130149362920170503631165857912603883842969975511878425625770842075688",
        "end_date": "2026-03-15T22:00:00Z",
        "pre_game_price": 0.605,
        "question": "Pistons vs. Raptors",
    },
    {
        "name": "Raptors",
        "token_id": "67049270054048456266663906825097999756591436738469079719416498827447415270685",
        "end_date": "2026-03-15T22:00:00Z",
        "pre_game_price": 0.395,
        "question": "Pistons vs. Raptors",
    },
    {
        "name": "Cavaliers",
        "token_id": "110305381223890885784301123756740765727714315684391656978762837578545088708094",
        "end_date": "2026-03-15T22:00:00Z",
        "pre_game_price": 0.915,
        "question": "Mavericks vs. Cavaliers",
    },
    {
        "name": "Trail Blazers",
        "token_id": "104807386405203753627029272733434517075421396226707309390912932054047431986054",
        "end_date": "2026-03-16T00:30:00Z",
        "pre_game_price": 0.745,
        "question": "Trail Blazers vs. 76ers",
    },
    {
        "name": "Knicks",
        "token_id": "94128496026797918984844864568223307829485952150454162992788300657069085242634",
        "end_date": "2026-03-16T02:30:00Z",
        "pre_game_price": 0.875,
        "question": "Warriors vs. Knicks",
    },
    {
        "name": "Bucks",
        "token_id": "32551155368524168873951622774578938504266557172625716658873470005302238348663",
        "end_date": "2026-03-15T22:00:00Z",
        "pre_game_price": 0.725,
        "question": "Pacers vs. Bucks",
    },
    {
        "name": "Jazz",
        "token_id": "29938514184970414348155694778671980817991099472183324339505529775105034074937",
        "end_date": "2026-03-16T04:30:00Z",
        "pre_game_price": 0.445,
        "question": "Jazz vs. Kings",
    },
    {
        "name": "Kings",
        "token_id": "103652504291292774936796488328924952807631851838476414345461142609770264573246",
        "end_date": "2026-03-16T04:30:00Z",
        "pre_game_price": 0.555,
        "question": "Jazz vs. Kings",
    },
]

MAX_SPEND_PER_TRADE = 5.0
MIN_SPEND = 2.0
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

    # Size: spend up to MAX_SPEND_PER_TRADE, capped at 80% of balance
    # Near-res plays resolve in minutes, so we can deploy most of our cash
    spend = min(MAX_SPEND_PER_TRADE, balance * 0.80)
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
        label = "EPL/BUNDESLIGA/SERIE-A"

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
