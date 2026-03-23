#!/usr/bin/env python3
"""
Near-resolution monitor for March 26, 2026 — World Cup European Qualifiers.
8 WCQ semifinal matches + 2 friendlies (Brazil-France, Colombia-Croatia).

Kickoff schedule (UTC):
  17:00  Turkey vs Romania
  19:45  Denmark vs N.Macedonia, Ukraine vs Sweden, Poland vs Albania,
         Italy vs N.Ireland, Wales vs Bosnia, Czechia vs Ireland, Slovakia vs Kosovo
  20:00  Brazil vs France (friendly)
  23:30  Colombia vs Croatia (friendly)

Near-res windows:
  18:25-18:45  Turkey-Romania
  21:10-21:35  7 WCQ + Brazil-France
  01:00-01:15  Colombia-Croatia

NOTE: end_date in entries = estimated game end (kickoff + 1:50), NOT Gamma kickoff time.
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
    # === TURKEY vs ROMANIA (17:00 UTC kickoff) ===
    {"name": "Türkiye", "token_id": "22018366048679221312689532353132141774118368618367535314505237811618661972779",
     "end_date": "2026-03-26T18:50:00Z", "pre_game_price": 0.0,
     "question": "Will Türkiye win on 2026-03-26?"},
    {"name": "Romania", "token_id": "112841215548972398611357923888853394218118688455951191579296347809654429568932",
     "end_date": "2026-03-26T18:50:00Z", "pre_game_price": 0.0,
     "question": "Will Romania win on 2026-03-26?"},

    # === DENMARK vs NORTH MACEDONIA (19:45 UTC kickoff) ===
    {"name": "Denmark", "token_id": "60359916902742682612811897544650888470638554127994153972571059108626286184241",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Denmark win on 2026-03-26?"},
    {"name": "North Macedonia", "token_id": "49145734146103688552738301242696470794530826061954905356986171041067056277211",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will North Macedonia win on 2026-03-26?"},

    # === UKRAINE vs SWEDEN (19:45 UTC kickoff) ===
    {"name": "Ukraine", "token_id": "51648038919441832529767363491921234172552410621403267516309722559126850802839",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Ukraine win on 2026-03-26?"},
    {"name": "Sweden", "token_id": "91235421853549505515313154705985380922640511088664179396630749866887540062735",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Sweden win on 2026-03-26?"},

    # === POLAND vs ALBANIA (19:45 UTC kickoff) ===
    {"name": "Poland", "token_id": "92350971869097216188980840054804294078808667119845664642645117979344941426493",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Poland win on 2026-03-26?"},
    {"name": "Albania", "token_id": "21370087395289801498845097052682634535911452421455768891296390588065769889508",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Albania win on 2026-03-26?"},

    # === ITALY vs NORTHERN IRELAND (19:45 UTC kickoff) ===
    {"name": "Italy", "token_id": "105764838635404823518886560080395040173288676199569528025006252582264669638501",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Italy win on 2026-03-26?"},
    {"name": "Northern Ireland", "token_id": "86865219119205591935046652686750535286163296689324951188204675998940511533059",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Northern Ireland win on 2026-03-26?"},

    # === WALES vs BOSNIA (19:45 UTC kickoff) ===
    {"name": "Wales", "token_id": "38760949771854125427344891367777438346074995373259956605705707351231748622719",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Wales win on 2026-03-26?"},
    {"name": "Bosnia", "token_id": "6164834498480963192821301915693516689313399156949918681842273458894100734604",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Bosnia and Herzegovina win on 2026-03-26?"},

    # === CZECHIA vs REPUBLIC OF IRELAND (19:45 UTC kickoff) ===
    {"name": "Czechia", "token_id": "61292659578181055317206462427958034339347491683383916001306068674350366048035",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Czechia win on 2026-03-26?"},
    {"name": "Ireland", "token_id": "88445244396746222292585832805917431793669619605684458646566525986127500541066",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Republic of Ireland win on 2026-03-26?"},

    # === SLOVAKIA vs KOSOVO (19:45 UTC kickoff) ===
    {"name": "Slovakia", "token_id": "60603129014209495902707159565432220297300635654774091902224685404406941533459",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Slovakia win on 2026-03-26?"},
    {"name": "Kosovo", "token_id": "104036489249777635343653471029324236801463443770741059544435504560233091847745",
     "end_date": "2026-03-26T21:35:00Z", "pre_game_price": 0.0,
     "question": "Will Kosovo win on 2026-03-26?"},

    # === BRAZIL vs FRANCE (20:00 UTC kickoff, friendly) ===
    {"name": "Brazil", "token_id": "32956184720124463143248771917745518153762307040959896122703544754439210490550",
     "end_date": "2026-03-26T21:50:00Z", "pre_game_price": 0.0,
     "question": "Will Brazil win on 2026-03-26?"},
    {"name": "France", "token_id": "38298499234039796229938627084804138568691180585799099121025016397786519172841",
     "end_date": "2026-03-26T21:50:00Z", "pre_game_price": 0.0,
     "question": "Will France win on 2026-03-26?"},

    # === COLOMBIA vs CROATIA (23:30 UTC kickoff, friendly) ===
    {"name": "Colombia", "token_id": "33109009791798382791678550068937797578076238604746177356644515500652524284803",
     "end_date": "2026-03-27T01:20:00Z", "pre_game_price": 0.0,
     "question": "Will Colombia win on 2026-03-26?"},
    {"name": "Croatia", "token_id": "5594925124432097740818088576442258374054869833427729304267329125109725550475",
     "end_date": "2026-03-27T01:20:00Z", "pre_game_price": 0.0,
     "question": "Will Croatia win on 2026-03-26?"},
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
BOUGHT = set()  # Dedup: prevent buying same token or same-game opponent


def snapshot_pre_game_prices(client, watch_list):
    """Capture pre-game prices so we can measure jumps."""
    for g in watch_list:
        try:
            p = client.get_price(g["token_id"], "buy")
            g["pre_game_price"] = float(p.get("price", 0))
        except Exception:
            g["pre_game_price"] = 0.0
    return watch_list


def check_near_res(client, watch_list, balance):
    """Check for near-resolution signals and buy if criteria met."""
    now = datetime.now(timezone.utc)
    active = []
    for g in watch_list:
        end = datetime.fromisoformat(g["end_date"].replace("Z", "+00:00"))
        mins_to_end = (end - now).total_seconds() / 60
        if mins_to_end < -30 or mins_to_end > 120:
            continue  # Skip finished or too-far-away games
        active.append((g, mins_to_end))

    if not active:
        return balance

    for g, mins_to_end in active:
        tid = g["token_id"]
        name = g["name"]
        question = g.get("question", "")

        if tid in BOUGHT:
            continue

        try:
            buy_resp = client.get_price(tid, "buy")
            sell_resp = client.get_price(tid, "sell")
            buy_price = float(buy_resp.get("price", 0))
            sell_price = float(sell_resp.get("price", 0))
        except Exception:
            continue

        spread = buy_price - sell_price
        jump = buy_price - g["pre_game_price"] if g["pre_game_price"] > 0 else 0

        # Print status
        print(f"  {name:20s} buy={buy_price:.3f} sell={sell_price:.3f} "
              f"spread={spread:.3f} jump={jump:+.3f} mins={mins_to_end:.0f} ")

        # Check near-res criteria
        if (MIN_NEAR_RES_PRICE <= sell_price <= MAX_NEAR_RES_PRICE
                and jump >= MIN_PRICE_JUMP
                and abs(spread) <= MAX_SPREAD
                and 0 < mins_to_end <= MAX_MINS_TO_END):

            # Block opponent in same match
            match_q = question
            for other in watch_list:
                if other["token_id"] != tid and other.get("question", "").replace(name, "") != match_q:
                    # Same event check: match by end_date
                    if other["end_date"] == g["end_date"] and other["question"] != question:
                        pass  # Different question = different match
                    elif other["end_date"] == g["end_date"]:
                        if other["token_id"] not in BOUGHT:
                            BOUGHT.add(other["token_id"])

            spend = min(MAX_SPEND_PER_TRADE, balance * PCT_OF_BALANCE)
            if spend < MIN_SPEND:
                print(f"  *** SKIP {name}: balance too low (${balance:.2f})")
                continue

            print(f"\n  *** NEAR-RES BUY: {name} @ {sell_price:.3f} "
                  f"(jump={jump:+.3f}, mins={mins_to_end:.0f}, spend=${spend:.2f})")

            try:
                result = place_market_buy(client, tid, spend)
                print(f"  *** Result: {result}")
                BOUGHT.add(tid)

                # Record in state
                import time as _t
                _t.sleep(2)
                shares = get_actual_shares(client, tid)
                state = load_state()
                state["positions"].append({
                    "token_id": tid,
                    "market_id": f"wcq-mar26-{name.lower().replace(' ', '-')}",
                    "question": question,
                    "side": "YES",
                    "entry_price": sell_price,
                    "fair_price": sell_price + 0.05,
                    "edge": jump,
                    "size_usdc": spend,
                    "shares": shares,
                    "end_date": g["end_date"],
                    "days_left_at_entry": mins_to_end / 1440,
                    "opened_at": str(now),
                    "research_note": f"WCQ near-res: {name} @ {sell_price:.3f}, jump +{jump:.3f}"
                })
                save_state(state)

                balance = get_usdc_balance(client)
                send(f"🟢 BOUGHT {name} near-res @ {sell_price:.3f} | ${spend:.2f} | jump +{jump:.3f}")
            except Exception as ex:
                print(f"  *** BUY FAILED: {ex}")

    return balance


def main():
    print(f"=== WCQ March 26 Near-Res Monitor ===")
    print(f"Started at {datetime.now(timezone.utc).isoformat()}")
    print(f"Watching {len(ALL_GAMES)} tokens across 10 matches\n")

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"Balance: ${balance:.2f}\n")

    # Snapshot pre-game prices
    print("Snapshotting pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)
    for g in ALL_GAMES:
        print(f"  {g['name']:20s} pre-game={g['pre_game_price']:.3f}")
    print()

    check_num = 0
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Stop after all games done (latest end: Colombia-Croatia at 01:20 Mar 27)
            latest_end = datetime(2026, 3, 27, 1, 30, tzinfo=timezone.utc)
            if now > latest_end:
                print(f"\nAll games finished. Stopping.")
                break

            check_num += 1
            print(f"\n--- Check #{check_num} at {now.strftime('%H:%M:%S')} UTC ---")
            balance = get_usdc_balance(client)
            print(f"  Balance: ${balance:.2f}")
            balance = check_near_res(client, ALL_GAMES, balance)

        except Exception as ex:
            print(f"  ERROR: {ex}")

        time.sleep(60)  # Check every 60 seconds

    # Final summary
    print(f"\n=== Session Complete ===")
    balance = get_usdc_balance(client)
    print(f"Final balance: ${balance:.2f}")
    print(f"Tokens bought: {len(BOUGHT)}")
    send(f"📊 WCQ Mar 26 monitor done. Balance: ${balance:.2f}, trades: {len(BOUGHT)}")


if __name__ == "__main__":
    main()
