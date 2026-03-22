#!/usr/bin/env python3
"""
Near-resolution monitor for March 23, 2026 (Sunday).
No European top-flight football (international break).
Covers: NBA (10 games), CS2 BLAST Rotterdam (3 BO3),
Argentine (2), Colombian (4), Spanish 2nd (1).

NBA tipoffs: 23:00-02:30 UTC → near-res windows 01:00-05:00 UTC.
CS2 BLAST: 13:00-22:00 UTC → near-res throughout.
SA soccer: 19:00-03:15 UTC.
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
    # === NBA (10 games) — PRIMARY TARGETS ===
    # Tipoff 23:00 UTC, end ~01:30 UTC Mar 24
    {"name": "Lakers", "token_id": "36554252596750352536756041160933914502243849250270435904104107105252569326470",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pistons"},
    {"name": "Pistons", "token_id": "90898434341036885550167009542356127359697126382953020709355461557872368670502",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Pistons"},

    {"name": "Pacers", "token_id": "18017778254808081226448072657965279533575271810532649848768553949230133149757",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Pacers vs. Magic"},
    {"name": "Magic", "token_id": "50112749285745781665598696775836785951165008805595400507995011127893418357240",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Pacers vs. Magic"},

    {"name": "Thunder", "token_id": "1421592761821212311389600912962457612848636675876077694454441235092479677134",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. 76ers"},
    {"name": "76ers", "token_id": "13560143566849154621173780407296479105208565487765040574267024017435814580293",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. 76ers"},

    {"name": "Spurs", "token_id": "54040793702755773114825566903063607420011507184604466416432809138170957187145",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Heat"},
    {"name": "Heat", "token_id": "16449252860020742419157684558762238159994582638842050309886335182535976167658",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Spurs vs. Heat"},

    # Tipoff 23:30 UTC
    {"name": "Grizzlies", "token_id": "103325552653149933388345123480612218674588057252537745791847407554177123887300",
     "end_date": "2026-03-24T02:00:00Z", "pre_game_price": 0.0,
     "question": "Grizzlies vs. Hawks"},
    {"name": "Hawks", "token_id": "63385009162113992791902764519974524692441433935920553317266479074095500393368",
     "end_date": "2026-03-24T02:00:00Z", "pre_game_price": 0.0,
     "question": "Grizzlies vs. Hawks"},

    # Tipoff 00:00 UTC Mar 24
    {"name": "Rockets", "token_id": "105139898025358400147566406811842044349091149199068278109777501377907181467504",
     "end_date": "2026-03-24T02:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Bulls"},
    {"name": "Bulls", "token_id": "113185554942518318007005963115469624970662547367595734773283185931311433682669",
     "end_date": "2026-03-24T02:30:00Z", "pre_game_price": 0.0,
     "question": "Rockets vs. Bulls"},

    # Tipoff 01:00 UTC Mar 24
    {"name": "Raptors", "token_id": "24003798022284661815115465198045105173620180394150088216818014403950447317812",
     "end_date": "2026-03-24T03:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Jazz"},
    {"name": "Jazz", "token_id": "53647289072355457386285367337948263846078805023514571222248673749239034314351",
     "end_date": "2026-03-24T03:30:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Jazz"},

    # Tipoff 01:30 UTC Mar 24
    {"name": "Warriors", "token_id": "85025648185075194745490101116685758298140419237212875302040829779117018340421",
     "end_date": "2026-03-24T04:00:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Mavericks"},
    {"name": "Mavericks", "token_id": "85240010153575140654032351888432878078413873630806894767924524706591209936544",
     "end_date": "2026-03-24T04:00:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Mavericks"},

    # Tipoff 02:00 UTC Mar 24
    {"name": "Nets", "token_id": "112392421113526268327841704520005161761861502749757671768515508106883142135214",
     "end_date": "2026-03-24T04:30:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Trail Blazers"},
    {"name": "Trail Blazers", "token_id": "41281353374659336429442335882359408330666971646082141797983101057857090108671",
     "end_date": "2026-03-24T04:30:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Trail Blazers"},

    # Tipoff 02:30 UTC Mar 24
    {"name": "Bucks", "token_id": "100315563070377403107471838673743358414871520286654658851074346088530908424207",
     "end_date": "2026-03-24T05:00:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Clippers"},
    {"name": "Clippers", "token_id": "63909746413243929587927034115642087628158345101443794907264514578995822316301",
     "end_date": "2026-03-24T05:00:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Clippers"},

    # === CS2 BLAST Open Rotterdam (3 BO3) — SECONDARY ===
    # NAVI vs Aurora — starts ~13:00 UTC, end by ~17:00
    {"name": "NAVI", "token_id": "100582132586681337164375215801953981016574229675546374059256896904442833535303",
     "end_date": "2026-03-23T17:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Natus Vincere vs Aurora Gaming (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "Aurora", "token_id": "93077658376579992195653013396851999544691415054227896128738319042784733418282",
     "end_date": "2026-03-23T17:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Natus Vincere vs Aurora Gaming (BO3) - BLAST Open Rotterdam Group A"},

    # Falcons vs FURIA — starts ~15:30 UTC, end by ~19:30
    {"name": "Falcons", "token_id": "96152515631371174532926937362487917853962795752690359835130985596332646922176",
     "end_date": "2026-03-23T19:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Team Falcons vs FURIA (BO3) - BLAST Open Rotterdam Group A"},
    {"name": "FURIA", "token_id": "2116715792897421481852255923916932431938704579218893739317900084278762591545",
     "end_date": "2026-03-23T19:30:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: Team Falcons vs FURIA (BO3) - BLAST Open Rotterdam Group A"},

    # PARIVISION vs Vitality — starts ~18:00 UTC, end by ~22:00
    {"name": "PARIVISION", "token_id": "7014938091910369633169807904150657321623381419444222440101393386125116555217",
     "end_date": "2026-03-23T22:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: PARIVISION vs Vitality (BO3) - BLAST Open Rotterdam Group B"},
    {"name": "Vitality", "token_id": "10141557233740063570433717403369411773881426926727499858134434191781902173105",
     "end_date": "2026-03-23T22:00:00Z", "pre_game_price": 0.0,
     "question": "Counter-Strike: PARIVISION vs Vitality (BO3) - BLAST Open Rotterdam Group B"},

    # === ARGENTINE (2 games) ===
    # Estudiantes vs Central Cordoba — 20:00 UTC kick, end ~22:00
    {"name": "Estudiantes", "token_id": "51403185299506367907606481788667849354333208144961127882949060811146032576314",
     "end_date": "2026-03-23T22:00:00Z", "pre_game_price": 0.0,
     "question": "Will Estudiantes de La Plata win on 2026-03-23?"},
    {"name": "Central Cordoba", "token_id": "61220251651857371973763705046777519402639358798325553056275592779543656184862",
     "end_date": "2026-03-23T22:00:00Z", "pre_game_price": 0.0,
     "question": "Will CA Central Córdoba win on 2026-03-23?"},

    # Huracan vs Barracas Central — 22:15 UTC kick, end ~00:15 Mar 24
    {"name": "Huracan", "token_id": "18030369057516754742482344582929420914257245404683306029993036149342355296883",
     "end_date": "2026-03-24T00:15:00Z", "pre_game_price": 0.0,
     "question": "Will CA Huracán win on 2026-03-23?"},
    {"name": "Barracas", "token_id": "62790555644996246135729586616153891835946361265973671463703870783110031468492",
     "end_date": "2026-03-24T00:15:00Z", "pre_game_price": 0.0,
     "question": "Will CA Barracas Central win on 2026-03-23?"},

    # === COLOMBIAN (4 games) ===
    # Boyaca Chico vs Tolima — 17:00 UTC kick, end ~19:00
    {"name": "Tolima", "token_id": "98793672620282741077770631136899283554382246118248442199276862701268528153740",
     "end_date": "2026-03-23T19:00:00Z", "pre_game_price": 0.0,
     "question": "Will CD Tolima win on 2026-03-23?"},
    {"name": "Boyaca Chico", "token_id": "115097963429597223020521282985280875745641836632755050240794591049140912936583",
     "end_date": "2026-03-23T19:00:00Z", "pre_game_price": 0.0,
     "question": "Will Boyacá Chicó FC win on 2026-03-23?"},

    # Santa Fe vs Ind Medellin — 19:10 UTC kick, end ~21:10
    {"name": "Santa Fe", "token_id": "37025085440733720834568200885336785418340192812213379025622510246040497126114",
     "end_date": "2026-03-23T21:10:00Z", "pre_game_price": 0.0,
     "question": "Will Independiente Santa Fe win on 2026-03-23?"},
    {"name": "Ind Medellin", "token_id": "81322135088796349471354734772046470888133345667606746447645936324786775669226",
     "end_date": "2026-03-23T21:10:00Z", "pre_game_price": 0.0,
     "question": "Will Independiente Medellín win on 2026-03-23?"},

    # Jaguares vs Aguilas Doradas — 21:20 UTC kick, end ~23:20
    {"name": "Jaguares", "token_id": "8773506897055003838039498468150103969168167273765293025898663284597257573057",
     "end_date": "2026-03-23T23:20:00Z", "pre_game_price": 0.0,
     "question": "Will Jaguares de Córdoba FC win on 2026-03-23?"},
    {"name": "Aguilas", "token_id": "110899969008377345956258644944043021214306044823901005762268509775375145893232",
     "end_date": "2026-03-23T23:20:00Z", "pre_game_price": 0.0,
     "question": "Will Águilas Doradas Rionegro win on 2026-03-23?"},

    # Junior FC vs Bucaramanga — 23:30 UTC kick, end ~01:30 Mar 24
    {"name": "Junior FC", "token_id": "39477338986002316231105373290594225572950675050113017902753712666213779373805",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Will CDP Junior FC win on 2026-03-23?"},
    {"name": "Bucaramanga", "token_id": "96382499371976631216048940703794888073544619863149928082136063770217297601986",
     "end_date": "2026-03-24T01:30:00Z", "pre_game_price": 0.0,
     "question": "Will CA Bucaramanga win on 2026-03-23?"},

    # === SPANISH 2ND DIVISION ===
    # Castellon vs Leonesa — 17:30 UTC kick, end ~19:30
    {"name": "Castellon", "token_id": "41871872001670317897641252355347827008460650306311045032037006871954691295671",
     "end_date": "2026-03-23T19:30:00Z", "pre_game_price": 0.0,
     "question": "Will CD Castellón win on 2026-03-23?"},
    {"name": "Leonesa", "token_id": "109031625264428736552408890378058743209466154691129025849972222302298768287031",
     "end_date": "2026-03-23T19:30:00Z", "pre_game_price": 0.0,
     "question": "Will Cultural y Deportiva Leonesa win on 2026-03-23?"},
]

# === Params (same as validated Mar 22) ===
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
                        "market_id": f"near-res-mar23-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar23 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR23 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
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
    print(f"=== Near-Res Monitor: March 23 ===")
    print(f"=== NBA (10) + CS2 BLAST (3) + Argentine (2) + Colombian (4) + Sp2 (1) ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"=== {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games) ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Sizing: MAX_SPEND=${MAX_SPEND_PER_TRADE}, PCT={PCT_OF_BALANCE}, "
          f"MIN_SPEND=${MIN_SPEND}")

    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    # Run from now through 05:30 UTC Mar 24 (last NBA game ends ~05:00)
    for i in range(1200):  # 20 hours
        check_and_buy(client, ALL_GAMES)
        time.sleep(60)
