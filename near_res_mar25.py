#!/usr/bin/env python3
"""
Near-resolution monitor for March 25, 2026 — 12 NBA + 6 NCAAB games.

NBA Games (end times UTC):
- Hawks vs Pistons: end 23:00 (tipoff ~20:30)
- Lakers vs Pacers: end 23:00 (tipoff ~20:30)
- Bulls vs 76ers: end 23:00 (tipoff ~20:30)
- Thunder vs Celtics: end 23:30 (tipoff ~21:00)
- Heat vs Cavaliers: end 23:30 (tipoff ~21:00)
- Spurs vs Grizzlies: end 00:00 (tipoff ~21:30)
- Rockets vs Timberwolves: end 01:30 (tipoff ~23:00)
- Nets vs Warriors: end 02:00 (tipoff ~23:30)
- Bucks vs Trail Blazers: end 02:00 (tipoff ~23:30)

NCAAB Sweet 16 / NIT (end times UTC):
- Illinois State vs Dayton (NIT): end 23:00 Mar 25
- Illinois vs Houston: end 04:00 Mar 26
- Nebraska vs Iowa: end 04:00 Mar 26
- Arkansas vs Arizona: end 04:00 Mar 26

Soccer:
- UWCL Real Madrid Fem vs Barcelona: kickoff 17:45 UTC, near-res ~19:10-19:30
- UWCL Man Utd WFC vs Bayern Munich: kickoff 20:00 UTC, near-res ~21:25-21:45
- Argentine Riestra vs San Lorenzo: kickoff 22:00 UTC, near-res ~23:25-23:45

Near-res windows: 19:00-04:00 UTC.
Launch at ~16:00 UTC to catch UWCL pre-game + all NBA/NCAAB.

Validated params from March 22: MIN_PRICE=0.85, JUMP=0.20, SPREAD=0.04, MAX_MINS=20.
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
    # === NBA March 25 ===

    # Hawks vs Pistons — Pistons favored (0.61)
    {"name": "Hawks", "token_id": "93005267235468997456934002388550021937018425537589605094014799710941741251069",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Pistons"},
    {"name": "Pistons", "token_id": "64177640059835852124241116498674937098540535726885083860163167335916700824150",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Pistons"},

    # Lakers vs Pacers — Lakers heavy fav (0.87)
    {"name": "Lakers", "token_id": "7612910576717793402991019799791772135256321521836599291298863333468643619461",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pacers"},
    {"name": "Pacers", "token_id": "114197304671868049202803403374363020064588068595117140773342483626582980094264",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pacers"},

    # Bulls vs 76ers — 76ers favored (0.66)
    {"name": "Bulls", "token_id": "3162096944025599388343368267014382438955741801678961041209954555797739052890",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. 76ers"},
    {"name": "76ers", "token_id": "7458268339281501131092772693402177646688351956726977690754205017540705015311",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Bulls vs. 76ers"},

    # Thunder vs Celtics — Thunder favored (0.60)
    {"name": "Thunder", "token_id": "107873275012767872940089881195560536670209084976663788557868940051552278053349",
     "end_date": "2026-03-25T23:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Celtics"},
    {"name": "Celtics", "token_id": "12160776981609763533501553797509574492383854838127183751971345302533107597107",
     "end_date": "2026-03-25T23:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Celtics"},

    # Heat vs Cavaliers — Cavs favored (0.67)
    {"name": "Heat", "token_id": "3432670311544361562896003314110816516903559805884757448626772409947882253911",
     "end_date": "2026-03-25T23:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},
    {"name": "Cavaliers", "token_id": "44725893014753223728715041388114476759343056601141677443767816816525366969933",
     "end_date": "2026-03-25T23:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Cavaliers"},

    # Spurs vs Grizzlies — Spurs heavy fav (0.91)
    {"name": "Spurs", "token_id": "111585476520182526013310515691624101392915263061638864508466984623921201341648",
     "end_date": "2026-03-26T00:00:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Grizzlies"},
    {"name": "Grizzlies", "token_id": "75988829743818195059319292222936271583394612963468654999222933263264360226903",
     "end_date": "2026-03-26T00:00:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Grizzlies"},

    # Rockets vs Timberwolves — close (0.53/0.47)
    {"name": "Rockets", "token_id": "92478388793162701688228117655170187221557905686840754078187669782700067722048",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Timberwolves"},
    {"name": "Timberwolves", "token_id": "111191110166685402703345809072251891917258815235664098103848966919430435408957",
     "end_date": "2026-03-26T01:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Timberwolves"},

    # Nets vs Warriors — Warriors heavy fav (0.85)
    {"name": "Nets", "token_id": "59988304926157291085741980783244124412733571922037236061861524240909694002156",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Warriors"},
    {"name": "Warriors", "token_id": "62676735322842398057034281587593087884927362055299349529547920334852418648339",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Warriors"},

    # Bucks vs Trail Blazers — Blazers heavy fav (0.81)
    {"name": "Bucks", "token_id": "11320517947120382867354691332790182818908690626593202939648958728911767443152",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Trail Blazers"},
    {"name": "Trail Blazers", "token_id": "10116089711001117841135224750826069324066461435046964233291014901378997900491",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Trail Blazers"},

    # Wizards vs Jazz — Jazz favored (0.63)
    {"name": "Wizards", "token_id": "62221675027285730323772047312176523219159899833963007822052605755843635311576",
     "end_date": "2026-03-26T01:00:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Jazz"},
    {"name": "Jazz", "token_id": "107202767399186069294944974241034452406798583186929225424182362073950877567232",
     "end_date": "2026-03-26T01:00:00Z", "pre_game_price": 0.0,
     "question": "Wizards vs. Jazz"},

    # Raptors vs Clippers — Clippers favored (0.59)
    {"name": "Raptors", "token_id": "104750558455342899598943060530064380790815094510981313121419519554249163923974",
     "end_date": "2026-03-26T02:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Clippers"},
    {"name": "Clippers", "token_id": "12333070480341614122618762158154035726831021854006502312831723071427076934870",
     "end_date": "2026-03-26T02:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Clippers"},

    # Mavericks vs Nuggets — Nuggets heavy fav (0.87)
    {"name": "Mavericks", "token_id": "20922232650376756003161875689296660358662743194658994892319178428143934706670",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Nuggets"},
    {"name": "Nuggets", "token_id": "43403740338966946480122866016569684130438243069023216173919933608376541967800",
     "end_date": "2026-03-26T02:00:00Z", "pre_game_price": 0.0,
     "question": "Mavericks vs. Nuggets"},

    # === SOCCER (end_date = kickoff + 105min for actual game end) ===

    # UWCL: Real Madrid Fem vs Barcelona — Barca heavy fav (0.77)
    # Kickoff 17:45 UTC → game end ~19:30 UTC
    {"name": "RM Fem", "token_id": "11826143872088739580158177267190470326214851012779219815762540361195206739048",
     "end_date": "2026-03-25T19:30:00Z", "pre_game_price": 0.0,
     "question": "RM Fem vs. Barcelona UWCL"},
    {"name": "Barcelona W", "token_id": "80870004363502250258573422997567538727860553884846771803694940375847004123249",
     "end_date": "2026-03-25T19:30:00Z", "pre_game_price": 0.0,
     "question": "RM Fem vs. Barcelona UWCL"},

    # UWCL: Man Utd WFC vs Bayern Munich — Bayern slight fav (0.44)
    # Kickoff 20:00 UTC → game end ~21:45 UTC
    {"name": "ManU WFC", "token_id": "16524059063622991321604091220921123543004597224305591698343954530716638591526",
     "end_date": "2026-03-25T21:45:00Z", "pre_game_price": 0.0,
     "question": "ManU WFC vs. Bayern UWCL"},
    {"name": "Bayern W", "token_id": "71498419258395109939148043204088004008281266076447059857977621178164559260442",
     "end_date": "2026-03-25T21:45:00Z", "pre_game_price": 0.0,
     "question": "ManU WFC vs. Bayern UWCL"},

    # Argentine: Riestra vs San Lorenzo — Riestra home (0.37)
    # Kickoff 22:00 UTC → game end ~23:45 UTC
    {"name": "Riestra", "token_id": "74577689037205812729010880220398340494588324177290579151816333852160655856754",
     "end_date": "2026-03-25T23:45:00Z", "pre_game_price": 0.0,
     "question": "Riestra vs. San Lorenzo ARG"},
    {"name": "San Lorenzo", "token_id": "47735556377698811657802038595299214256400532238852114993223869054713788087113",
     "end_date": "2026-03-25T23:45:00Z", "pre_game_price": 0.0,
     "question": "Riestra vs. San Lorenzo ARG"},

    # === NCAAB NIT ===

    # Illinois State vs Dayton — Dayton fav (0.74)
    {"name": "Illinois State", "token_id": "20518741957876099846246882430456399016792500691579831398424930686207668352882",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Illinois State vs. Dayton"},
    {"name": "Dayton", "token_id": "83942838033600614415033575511643085263133414949839943791047868453832617999588",
     "end_date": "2026-03-25T23:00:00Z", "pre_game_price": 0.0,
     "question": "Illinois State vs. Dayton"},

    # === NCAAB Sweet 16 ===

    # Illinois vs Houston — Houston fav (0.60)
    {"name": "Illinois", "token_id": "32808458875366467745777044160603661512817861173859925631005519080722962618453",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Illinois vs. Houston"},
    {"name": "Houston", "token_id": "59202108327135535421172568160321982683582378216670455227255549883175903089000",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Illinois vs. Houston"},

    # Nebraska vs Iowa — Nebraska slight fav (0.56)
    {"name": "Nebraska", "token_id": "6143758395191852229197516807548968371194839168426806816072019634277215860097",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Nebraska vs. Iowa"},
    {"name": "Iowa", "token_id": "8407769013236185519523211059555999620435865750175863777492373951715898856141",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Nebraska vs. Iowa"},

    # Arkansas vs Arizona — Arizona heavy fav (0.78)
    {"name": "Arkansas", "token_id": "41100365308798661859145040199494781670056892400248239396610536912652520057776",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Arkansas vs. Arizona"},
    {"name": "Arizona", "token_id": "82191725722679457478728557018601391881404208647693525967471584875912376235549",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Arkansas vs. Arizona"},

    # Texas vs Purdue — Purdue heavy fav (0.74)
    {"name": "Texas", "token_id": "39223504527462038575405867651841624516940270580793639574399176355422116610922",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Texas vs. Purdue"},
    {"name": "Purdue", "token_id": "107907338415976933532550388925205335990876677187021977689507641894936360729790",
     "end_date": "2026-03-26T04:00:00Z", "pre_game_price": 0.0,
     "question": "Texas vs. Purdue"},

    # Nevada vs Auburn — Auburn heavy fav (0.79)
    {"name": "Nevada", "token_id": "3324910729221891771074257286666647874024224847738670490039851287500651144183",
     "end_date": "2026-03-26T01:00:00Z", "pre_game_price": 0.0,
     "question": "Nevada vs. Auburn"},
    {"name": "Auburn", "token_id": "70779812690425708826291547979738675069018448910837681603934469865966357584534",
     "end_date": "2026-03-26T01:00:00Z", "pre_game_price": 0.0,
     "question": "Nevada vs. Auburn"},
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

            # Time-based filter
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
                mins_str = f" mins={mins_left:.0f}" if end_str else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f}{mins_str} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-mar25-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar25 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR25 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']}: {err}")


check_and_buy.count = 0


def main():
    print(f"=== NBA+NCAAB Mar 25 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Monitoring {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games)")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")

    client = get_client()
    print(f"Balance: ${get_usdc_balance(client):.2f}")

    # Snapshot pre-game prices
    print("\nSnapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Monitor loop — run until 05:00 UTC Mar 26
    end_time = datetime(2026, 3, 26, 5, 0, tzinfo=timezone.utc)
    while datetime.now(timezone.utc) < end_time:
        try:
            check_and_buy(client, ALL_GAMES)
        except Exception as e:
            print(f"  Loop error: {e}")
        time.sleep(70)

    print(f"\n=== Monitor finished at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")


if __name__ == "__main__":
    main()
