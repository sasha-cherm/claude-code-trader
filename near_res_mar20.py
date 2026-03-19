#!/usr/bin/env python3
"""
Near-resolution monitor for March 20, 2026.
NCAAB March Madness First Round Day 2 + NBA (6 games each).
Run from ~15:00 UTC, covers games through ~04:00 UTC March 21.

NOTE: Only 6 NCAAB Day 2 games found so far (all heavy favorites).
      More competitive matchups (8v9, 5v12 seeds) may appear later.
      CHECK AND ADD THEM at start of each session.

NCAAB games: heavily favored (0.90+), near-res less useful.
NBA games: competitive spreads, near-res more likely to trigger.
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
    # === European Soccer (kick ~18:00-20:00 UTC, near-res 19:30-21:45 UTC) ===
    # EPL: Bournemouth vs Man Utd (~19:45 UTC kick, end ~21:30)
    {"name": "Bournemouth", "token_id": "58206139529666709446170935349036911353681231083630030802859175769000049741130",
     "end_date": "2026-03-20T21:30:00Z", "pre_game_price": 0.0,
     "question": "Will AFC Bournemouth win on 2026-03-20?"},
    {"name": "Man Utd", "token_id": "46176690668105177227089990838594026351799238651232950832331852562296667074978",
     "end_date": "2026-03-20T21:30:00Z", "pre_game_price": 0.0,
     "question": "Will Manchester United FC win on 2026-03-20?"},

    # Bundesliga: RB Leipzig vs Hoffenheim (~19:30 UTC kick, end ~21:15)
    {"name": "RB Leipzig", "token_id": "32895632201664188245288154483911199625853539934459873851289829054190671084773",
     "end_date": "2026-03-20T21:15:00Z", "pre_game_price": 0.0,
     "question": "Will RB Leipzig win on 2026-03-20?"},
    {"name": "Hoffenheim", "token_id": "112391265105143936548597587321153102625341503055376389596547174746805265303733",
     "end_date": "2026-03-20T21:15:00Z", "pre_game_price": 0.0,
     "question": "Will TSG 1899 Hoffenheim win on 2026-03-20?"},

    # La Liga: Villarreal vs Real Sociedad (~20:00 UTC kick, end ~21:45)
    {"name": "Villarreal", "token_id": "70982478020778059146612454729531361547261983548245621271789519764999368221359",
     "end_date": "2026-03-20T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will Villarreal CF win on 2026-03-20?"},
    {"name": "Real Sociedad", "token_id": "90005007301333960641377759520624699810241338278923377664602689504034364924466",
     "end_date": "2026-03-20T21:45:00Z", "pre_game_price": 0.0,
     "question": "Will Real Sociedad de Fútbol win on 2026-03-20?"},

    # Championship: Preston vs Stoke (~19:45 UTC kick, end ~21:30)
    {"name": "Preston", "token_id": "4817264963112251949679335223608148192980804912981074933141316625457847209281",
     "end_date": "2026-03-20T21:30:00Z", "pre_game_price": 0.0,
     "question": "Will Preston North End FC win on 2026-03-20?"},
    {"name": "Stoke", "token_id": "74374910360545252279257673241263004860566726971638308023708302194781805890889",
     "end_date": "2026-03-20T21:30:00Z", "pre_game_price": 0.0,
     "question": "Will Stoke City FC win on 2026-03-20?"},

    # Eredivisie: Heracles vs Excelsior (~18:45 UTC kick, end ~20:30)
    {"name": "Heracles", "token_id": "48965609258704997328504077166253479112306793263435956358552569232919548547236",
     "end_date": "2026-03-20T20:30:00Z", "pre_game_price": 0.0,
     "question": "Will Heracles Almelo win on 2026-03-20?"},
    {"name": "Excelsior", "token_id": "109395311816687132888386554928560257046360128470340751497504252545097895188289",
     "end_date": "2026-03-20T20:30:00Z", "pre_game_price": 0.0,
     "question": "Will SBV Excelsior win on 2026-03-20?"},

    # === NCAAB March Madness First Round Day 2 ===
    # These are mostly blowout matchups — near-res less likely
    # End times generous: tipoff + 2.5h

    # Wright State vs Virginia (Virginia heavy fav 0.93)
    {"name": "Wright State", "token_id": "14228842199791161545109993213205762244864508348204445269335981533440328077735",
     "end_date": "2026-03-20T18:30:00Z", "pre_game_price": 0.0,
     "question": "Wright State Raiders vs. Virginia Cavaliers"},
    {"name": "Virginia", "token_id": "81904137712942224530925718360218200018428287086310004986895274303589259848112",
     "end_date": "2026-03-20T18:30:00Z", "pre_game_price": 0.0,
     "question": "Wright State Raiders vs. Virginia Cavaliers"},

    # Tennessee State vs Iowa State (Iowa State heavy fav 0.97)
    {"name": "Tennessee St", "token_id": "106379933779189809997557022850346241785693092980229872748435283820869564326293",
     "end_date": "2026-03-20T18:30:00Z", "pre_game_price": 0.0,
     "question": "Tennessee State Tigers vs. Iowa State Cyclones"},
    {"name": "Iowa State", "token_id": "15361374646856139721451799607802854417212524597994881086242204503144690018491",
     "end_date": "2026-03-20T18:30:00Z", "pre_game_price": 0.0,
     "question": "Tennessee State Tigers vs. Iowa State Cyclones"},

    # LIU vs Arizona (Arizona heavy fav 0.98)
    {"name": "LIU", "token_id": "4913730361920920558781272693126281406435302316350570006478823349891310491549",
     "end_date": "2026-03-20T21:00:00Z", "pre_game_price": 0.0,
     "question": "LIU Sharks vs. Arizona Wildcats"},
    {"name": "Arizona", "token_id": "9409490930224923614822487614966291700996606300666789458000739662899013820681",
     "end_date": "2026-03-20T21:00:00Z", "pre_game_price": 0.0,
     "question": "LIU Sharks vs. Arizona Wildcats"},

    # Queens NC vs Purdue (Purdue heavy fav 0.97)
    {"name": "Queens NC", "token_id": "108608431028516805322910059035854453364954187404710588904556256395227379154690",
     "end_date": "2026-03-20T21:00:00Z", "pre_game_price": 0.0,
     "question": "Queens (NC) Royals vs. Purdue Boilermakers"},
    {"name": "Purdue", "token_id": "94825023307695897341413564197216476268630722522032138668056667049777676974099",
     "end_date": "2026-03-20T21:00:00Z", "pre_game_price": 0.0,
     "question": "Queens (NC) Royals vs. Purdue Boilermakers"},

    # Cal Baptist vs Kansas (Kansas fav 0.90 — most competitive!)
    {"name": "Cal Baptist", "token_id": "55204324117415704168078913327623215628887924189767611245475223031027952461194",
     "end_date": "2026-03-21T01:00:00Z", "pre_game_price": 0.0,
     "question": "California Baptist Lancers vs. Kansas Jayhawks"},
    {"name": "Kansas", "token_id": "86216391130601990922184673346889196651962583362510043343400869228681856704674",
     "end_date": "2026-03-21T01:00:00Z", "pre_game_price": 0.0,
     "question": "California Baptist Lancers vs. Kansas Jayhawks"},

    # Furman vs UConn (UConn fav 0.95)
    {"name": "Furman", "token_id": "115197014545790711455252704048542820163808143402660557569124115092108053667594",
     "end_date": "2026-03-21T01:00:00Z", "pre_game_price": 0.0,
     "question": "Furman Paladins vs. Connecticut Huskies"},
    {"name": "UConn", "token_id": "89108373864437510966053279018117953216832793306244932425971907442192231322683",
     "end_date": "2026-03-21T01:00:00Z", "pre_game_price": 0.0,
     "question": "Furman Paladins vs. Connecticut Huskies"},

    # === NBA March 20 (tipoffs ~23:00-01:00 UTC) ===
    # These are more competitive and better for near-res

    {"name": "Knicks", "token_id": "90013344906622884074919259875357815246922506157228429697636130329655770569480",
     "end_date": "2026-03-20T23:30:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs. Nets"},
    {"name": "Nets", "token_id": "19201563645879300050010438705019362911261217005907737525341626515108972783414",
     "end_date": "2026-03-20T23:30:00Z", "pre_game_price": 0.0,
     "question": "Knicks vs. Nets"},

    {"name": "Warriors", "token_id": "86693799037126067240158438250389017274371045614187364356341461502182630203746",
     "end_date": "2026-03-21T01:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Pistons"},
    {"name": "Pistons", "token_id": "17003939380315524877653810261277105538708212000227633990046601909027777919476",
     "end_date": "2026-03-21T01:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Pistons"},

    {"name": "Hawks", "token_id": "54606307018656942720550200753027815667372018473623036094729426326643631855412",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Rockets"},
    {"name": "Rockets", "token_id": "29095775107738931708237744707896643458102828851719153739200449139131473565877",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Hawks vs. Rockets"},

    {"name": "Celtics", "token_id": "109220329594675595533865588380628641759767756605703035950781787505246991246420",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs. Grizzlies"},
    {"name": "Grizzlies", "token_id": "23086011370818244915859279878855186411163661006697003581844192558343745929977",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Celtics vs. Grizzlies"},

    {"name": "Trail Blazers", "token_id": "109021283308187724445216748902158026838799197184254281870091204386586933195142",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Trail Blazers vs. Timberwolves"},
    {"name": "Timberwolves", "token_id": "7787734462401651208223766249470753954465355099790202730382983753119951542562",
     "end_date": "2026-03-21T02:30:00Z", "pre_game_price": 0.0,
     "question": "Trail Blazers vs. Timberwolves"},

    {"name": "Raptors", "token_id": "13415003150793384080443080790288579981533217646600261055571395734776572036737",
     "end_date": "2026-03-21T03:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Nuggets"},
    {"name": "Nuggets", "token_id": "16986457248591298946207575492830879465171446768208184642251174472824748173629",
     "end_date": "2026-03-21T03:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Nuggets"},
]

# Tightened params — 13W/0L streak, slightly more aggressive sizing
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.94
MIN_PRICE_JUMP = 0.20       # Big jump = decisive lead
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20         # Basketball: last 20 min buffer
MAX_SPEND_PER_TRADE = 15.0   # Increased from $9 — compound harder
MIN_SPEND = 1.0              # Lowered from $2 — trade even with small balance
PCT_OF_BALANCE = 0.28        # Increased from 0.22 — 13W/0L justifies it
BOUGHT = set()               # Dedup: prevent buying same token twice


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
                        "market_id": f"near-res-mar20-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar20 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR20 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
                         f"${spend:.2f} ({shares:.2f} sh)\n"
                         f"Jump: {jump:+.3f}, {mins_left:.0f} min left")
                else:
                    print(f"  BUY FAILED for {w['name']}")
        except Exception as e:
            err = str(e)[:80]
            if "404" not in err:
                print(f"  {w['name']:14s} ERROR: {err}")

check_and_buy.count = 1


if __name__ == "__main__":
    print(f"=== Near-Res Monitor: March 20 (NCAAB Day 2 + NBA) ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"=== {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games) ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Sizing: MAX_SPEND=${MAX_SPEND_PER_TRADE}, PCT={PCT_OF_BALANCE}, "
          f"MIN_SPEND=${MIN_SPEND}")

    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    for i in range(720):  # 12 hours
        check_and_buy(client, ALL_GAMES)
        time.sleep(60)
