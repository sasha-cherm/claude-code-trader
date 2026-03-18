#!/usr/bin/env python3
"""
Basketball near-resolution monitor for March 19, 2026.
NCAAB March Madness First Round (16+ games) + NBA (8 games).
Run from ~15:00 UTC, covers games through ~04:00 UTC March 20.

NCAAB game waves (ET → UTC):
  Wave 1: 12:15 PM ET (16:15 UTC) → end ~18:30 UTC
  Wave 2: 2:45 PM ET (18:45 UTC) → end ~21:00 UTC
  Wave 3: 6:50 PM ET (22:50 UTC) → end ~01:00 UTC Mar 20
  Wave 4: 9:20 PM ET (01:20 UTC) → end ~03:30 UTC Mar 20
NBA: ~23:00 UTC onwards
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

# Focus on competitive games (pre-game 0.20-0.80) — most price movement
ALL_GAMES = [
    # === NCAAB March Madness First Round ===
    # Wave 1 (~16:15 UTC)
    {"name": "VCU Rams", "token_id": "84007361241758978489330197202827235700289078898880514910472901778979242019662",
     "pre_game_price": 0.0, "question": "VCU Rams vs. North Carolina Tar Heels"},
    {"name": "North Carolina", "token_id": "62722671790005482936206654382262146252373495629515527865660421386850609062191",
     "pre_game_price": 0.0, "question": "VCU Rams vs. North Carolina Tar Heels"},

    {"name": "TCU", "token_id": "58726589905511844388202427084789336286370979148438729614953611254856096987951",
     "pre_game_price": 0.0, "question": "TCU Horned Frogs vs. Ohio State Buckeyes"},
    {"name": "Ohio State", "token_id": "25041790120082913142830289704554002065922685936030849614487780676957407176862",
     "pre_game_price": 0.0, "question": "TCU Horned Frogs vs. Ohio State Buckeyes"},

    {"name": "Texas A&M", "token_id": "105762781628898089029582560551473093466427670167883803785334513336753998221944",
     "pre_game_price": 0.0, "question": "Texas A&M Aggies vs. Saint Mary's Gaels"},
    {"name": "Saint Mary's", "token_id": "53033511085124805981399975297553063209712114340038544865571483069211885971492",
     "pre_game_price": 0.0, "question": "Texas A&M Aggies vs. Saint Mary's Gaels"},

    {"name": "Santa Clara", "token_id": "72092088534102665491754907080448551373252988479960671082832260974085870498530",
     "pre_game_price": 0.0, "question": "Santa Clara Broncos vs. Kentucky Wildcats"},
    {"name": "Kentucky", "token_id": "96201733608502458627905480167652884986455618063746028131178484397498655375032",
     "pre_game_price": 0.0, "question": "Santa Clara Broncos vs. Kentucky Wildcats"},

    {"name": "Iowa", "token_id": "88019718517198041112185994197211713400925479368660214430030324078219596742767",
     "pre_game_price": 0.0, "question": "Iowa Hawkeyes vs. Clemson Tigers"},
    {"name": "Clemson", "token_id": "32146107534054651254521208750298898199286769571146548559273896548639204207770",
     "pre_game_price": 0.0, "question": "Iowa Hawkeyes vs. Clemson Tigers"},

    {"name": "Utah State", "token_id": "106391806073421269485399607017664717821740629965082479456785139555756131627776",
     "pre_game_price": 0.0, "question": "Utah State Aggies vs. Villanova Wildcats"},
    {"name": "Villanova", "token_id": "46384102915573339305724199265524140011695076949974814714682032938457082371118",
     "pre_game_price": 0.0, "question": "Utah State Aggies vs. Villanova Wildcats"},

    {"name": "Missouri", "token_id": "55334076214622044193667907059179236766755802174484771082968098756458488908571",
     "pre_game_price": 0.0, "question": "Missouri Tigers vs. Miami Hurricanes"},
    {"name": "Miami", "token_id": "20405373265263690273095397068448682914023530285766741619048773375756780963975",
     "pre_game_price": 0.0, "question": "Missouri Tigers vs. Miami Hurricanes"},

    {"name": "St. Louis", "token_id": "32383763199294923318526347312242993888949003428719061559136080445195605493642",
     "pre_game_price": 0.0, "question": "Saint Louis Billikens vs. Georgia Bulldogs"},
    {"name": "Georgia", "token_id": "54034530941382088240057378429034130481256150294287711254662539979606717652302",
     "pre_game_price": 0.0, "question": "Saint Louis Billikens vs. Georgia Bulldogs"},

    {"name": "S. Florida", "token_id": "79683168977793405368408014202910010834474183585397308403134237692342458505581",
     "pre_game_price": 0.0, "question": "South Florida Bulls vs. Louisville Cardinals"},
    {"name": "Louisville", "token_id": "68656678862547551986739165606156144618089179299986883035106515773477403186433",
     "pre_game_price": 0.0, "question": "South Florida Bulls vs. Louisville Cardinals"},

    {"name": "Akron", "token_id": "105015751806411093867366456953350999512252519399462229009921348002493556208921",
     "pre_game_price": 0.0, "question": "Akron Zips vs. Texas Tech Red Raiders"},
    {"name": "Texas Tech", "token_id": "79308286211285981481697518081271815960844799414039636458581868757032388361925",
     "pre_game_price": 0.0, "question": "Akron Zips vs. Texas Tech Red Raiders"},

    {"name": "Hofstra", "token_id": "29049461839578908236523492739355178159371369103001808454443054866483894885322",
     "pre_game_price": 0.0, "question": "Hofstra Pride vs. Alabama Crimson Tide"},
    {"name": "Alabama", "token_id": "76341225335584030858099123253090069370153706642291968639596138457391093565914",
     "pre_game_price": 0.0, "question": "Hofstra Pride vs. Alabama Crimson Tide"},

    {"name": "N. Iowa", "token_id": "55801363062437471428303088900148458552848867285220568959087703537314018520002",
     "pre_game_price": 0.0, "question": "Northern Iowa Panthers vs. St. John's Red Storm"},
    {"name": "St. John's", "token_id": "28882775410265555682378301862169900393141889664473253758091424010365598882358",
     "pre_game_price": 0.0, "question": "Northern Iowa Panthers vs. St. John's Red Storm"},

    # === NBA ===
    {"name": "Lakers", "token_id": "2664311162279059241862911770684565005151952311104325708669060839371754814097",
     "pre_game_price": 0.0, "question": "Lakers vs. Heat"},
    {"name": "Heat", "token_id": "110123870429261472646091235399700253214071590057720614618889482078075539548139",
     "pre_game_price": 0.0, "question": "Lakers vs. Heat"},

    {"name": "Clippers", "token_id": "60575497838766567479516370815152287536952631025514569038130964886289573065910",
     "pre_game_price": 0.0, "question": "Clippers vs. Pelicans"},
    {"name": "Pelicans", "token_id": "79832739104860263621760874642614994931987160492087207209715526221561854279540",
     "pre_game_price": 0.0, "question": "Clippers vs. Pelicans"},

    {"name": "Magic", "token_id": "796736141611226746258458380975877540661765256247564573932839229212462426299",
     "pre_game_price": 0.0, "question": "Magic vs. Hornets"},
    {"name": "Hornets", "token_id": "77739027788999909521244198087653826925663878907920170534312635645253556364467",
     "pre_game_price": 0.0, "question": "Magic vs. Hornets"},

    {"name": "76ers", "token_id": "9671037757766261865333683416344182222963863039079643250060623642002908652142",
     "pre_game_price": 0.0, "question": "76ers vs. Kings"},
    {"name": "Kings", "token_id": "83166862404022037546438708044398180964951650658256973749014813595679738532589",
     "pre_game_price": 0.0, "question": "76ers vs. Kings"},

    {"name": "Bucks", "token_id": "46568752051400142231839894437410103750972721143249544188593867825991769733835",
     "pre_game_price": 0.0, "question": "Bucks vs. Jazz"},
    {"name": "Jazz", "token_id": "73817802175806263509294714745469099323845088470847881404901729210013533741039",
     "pre_game_price": 0.0, "question": "Bucks vs. Jazz"},

    {"name": "Suns", "token_id": "11564349858406434865982242316140416931836549861036221723255014943670914914830",
     "pre_game_price": 0.0, "question": "Suns vs. Spurs"},
    {"name": "Spurs", "token_id": "68357839609088065969671307057548845364374774168248976411149138239614425711349",
     "pre_game_price": 0.0, "question": "Suns vs. Spurs"},

    {"name": "Cavaliers", "token_id": "14791690825989374177171930918237667200736228606778994948508422217087701196815",
     "pre_game_price": 0.0, "question": "Cavaliers vs. Bulls"},
    {"name": "Bulls", "token_id": "2053750301724228157370324704408926248138691501785348834429298312230383532126",
     "pre_game_price": 0.0, "question": "Cavaliers vs. Bulls"},
]

# Tightened params — need 85%+ WR to profit
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.94
MIN_PRICE_JUMP = 0.20       # Big jump = decisive lead
MAX_SPREAD = 0.04
MAX_SPEND_PER_TRADE = 5.0
MIN_SPEND = 2.0
PCT_OF_BALANCE = 0.15       # Slightly smaller — more games, more chances
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

            trigger = (
                buy_price >= MIN_NEAR_RES_PRICE and
                buy_price <= MAX_NEAR_RES_PRICE and
                jump >= MIN_PRICE_JUMP and
                abs(spread) < MAX_SPREAD and
                balance >= MIN_SPEND
            )

            if abs(jump) > 0.05 or buy_price >= 0.85:
                status = "***BUY***" if trigger else ""
                print(f"  {w['name']:14s} buy={buy_price:.3f} sell={sell_price:.3f} "
                      f"spread={spread:.3f} jump={jump:+.3f} {status}")

            if trigger:
                spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
                if spend < MIN_SPEND:
                    continue
                now = datetime.now(timezone.utc)
                print(f"\n  *** BUYING {w['name']} YES @ {buy_price:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(1.5)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"],
                        "market_id": f"near-res-bball-{w['name'].lower().replace(' ', '-')}",
                        "question": w["question"],
                        "side": "YES",
                        "entry_price": buy_price,
                        "fair_price": min(buy_price + 0.08, 0.99),
                        "edge": 0.08,
                        "size_usdc": spend,
                        "shares": shares if shares > 0 else spend / buy_price,
                        "end_date": "",
                        "days_left_at_entry": 0,
                        "opened_at": str(now),
                        "research_note": f"Basketball near-res: {w['name']} jumped {jump:+.3f} from pre-game {w['pre_game_price']:.3f}.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    send(f"BBALL NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n${spend:.2f} ({shares:.2f} sh)\nJump: {jump:+.3f}\n{w['question']}")
                    balance = get_usdc_balance(client)
                else:
                    print(f"  BUY FAILED for {w['name']}")
            time.sleep(0.5)  # Rate limit between API calls
        except Exception as e:
            print(f"  {w['name']:14s} ERROR: {e}")


def main():
    print(f"=== Basketball Near-Res Monitor: NCAAB March Madness + NBA ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"=== {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games) ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, SPREAD={MAX_SPREAD}")
    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run for 14 hours (covers 16:00 UTC to 06:00 UTC next day)
    for i in range(840):
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
