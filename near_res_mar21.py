#!/usr/bin/env python3
"""
Near-resolution monitor for March 21, 2026 (Saturday).
No EPL/Bundesliga/SerieA/LaLiga — Championship + Eredivisie + MLS + Brazilian + Argentine + Mexican.
NBA/NCAAB markers to be added at runtime when markets appear.

28 games, 56 tokens. Both sides per game for dedup.
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
    # === Championship 12:30 UTC kick (end ~14:15) ===
    {"name": "Blackburn", "token_id": "58286119060054841992133849587124330118128288965155670770276611014015231158011",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Blackburn Rovers FC vs. Middlesbrough FC"},
    {"name": "Middlesbrough", "token_id": "62997692227367345100702262202062679008956999233513638972362078254527536442176",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Blackburn Rovers FC vs. Middlesbrough FC"},

    {"name": "Derby", "token_id": "92803500333515603450565694022329549227574169789724694620293888801103052240816",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Derby County FC vs. Birmingham City FC"},
    {"name": "Birmingham", "token_id": "30754355831668994974984910679931629190286441805596005879511819058481581849558",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Derby County FC vs. Birmingham City FC"},

    {"name": "Ipswich", "token_id": "29500416994204168559069023013043598023053303544217658080103750726425386526013",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Ipswich Town FC vs. Millwall FC"},
    {"name": "Millwall", "token_id": "66748706195420220399369969365265982761241663674618660148208751801760703746240",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Ipswich Town FC vs. Millwall FC"},

    # === Championship 15:00 UTC kick (end ~16:45) ===
    {"name": "Southampton", "token_id": "65178894330919310365073106427412455013596730506716293836735361485698450458105",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Southampton FC vs. Oxford United FC"},
    {"name": "Oxford", "token_id": "103196497790544016515038784545488011079359401216028960865082894756578183636686",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Southampton FC vs. Oxford United FC"},

    {"name": "QPR", "token_id": "26929507770780211262879190875214762703000868128622468858966718864530468485332",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Queens Park Rangers FC vs. Portsmouth FC"},
    {"name": "Portsmouth", "token_id": "113842492103910996012460745332447341551921031005424699683257550702371079259344",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Queens Park Rangers FC vs. Portsmouth FC"},

    {"name": "Hull", "token_id": "10741032538018387472847041455968279965218608611918361556429762039818813392403",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Hull City AFC vs. Sheffield Wednesday FC"},
    {"name": "Sheff Wed", "token_id": "5086129068064472346177675035570589633947217400268881185027340395075626423832",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Hull City AFC vs. Sheffield Wednesday FC"},

    {"name": "Sheff Utd", "token_id": "90985725425538906356686449639884110845588802226955149321899593249920055178016",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Sheffield United FC vs. Wrexham AFC"},
    {"name": "Wrexham", "token_id": "100246775964783915906034784149341877962013374102097580621241333902864557228505",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Sheffield United FC vs. Wrexham AFC"},

    {"name": "Bristol City", "token_id": "15169109731082940803009586920724768785046686520269085131101835434406111729524",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Bristol City FC vs. West Bromwich Albion FC"},
    {"name": "West Brom", "token_id": "28970903253641857176782660835713301997472838312105269878180276818717376387871",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Bristol City FC vs. West Bromwich Albion FC"},

    {"name": "Watford", "token_id": "24515756022509674582582841207986483485621064215453147536821126833886093367953",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Watford FC vs. Leicester City FC"},
    {"name": "Leicester", "token_id": "47215129396890698087255016997302513709700359225357721131136391824702374365885",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Watford FC vs. Leicester City FC"},

    # === Championship 17:15 UTC kick (end ~19:00) ===
    {"name": "Swansea", "token_id": "62918285703449599808387430691679025798690319598448820273160951351620139535013",
     "end_date": "2026-03-21T19:00:00Z", "pre_game_price": 0.0,
     "question": "Swansea City AFC vs. Coventry City FC"},
    {"name": "Coventry", "token_id": "3666321707655527901176920222620681833825174525106133522392853169091186744469",
     "end_date": "2026-03-21T19:00:00Z", "pre_game_price": 0.0,
     "question": "Swansea City AFC vs. Coventry City FC"},

    # === Eredivisie ===
    {"name": "Sittard", "token_id": "60972992950006054833769016665492048665268507742174761022357948013274860153547",
     "end_date": "2026-03-21T15:30:00Z", "pre_game_price": 0.0,
     "question": "Fortuna Sittard vs. FC Twente '65"},
    {"name": "Twente", "token_id": "79511512182367790027337390425757854932299615967644281521013226069830842002969",
     "end_date": "2026-03-21T15:30:00Z", "pre_game_price": 0.0,
     "question": "Fortuna Sittard vs. FC Twente '65"},

    {"name": "Sparta", "token_id": "8600879289367044535780685026835910801584614242924747861051540205813933905028",
     "end_date": "2026-03-21T19:30:00Z", "pre_game_price": 0.0,
     "question": "Sparta Rotterdam vs. FC Volendam"},
    {"name": "Volendam", "token_id": "27460245624868053475909393973762645806468136009673865108036742159634806244838",
     "end_date": "2026-03-21T19:30:00Z", "pre_game_price": 0.0,
     "question": "Sparta Rotterdam vs. FC Volendam"},

    {"name": "Zwolle", "token_id": "11755391901387873965774126544410431722291828960187366620144168967528291156380",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "PEC Zwolle vs. NAC Breda"},
    {"name": "NAC Breda", "token_id": "20559309565133093067089362593087050149288806955022488970616732568219238944900",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "PEC Zwolle vs. NAC Breda"},

    # === Norwegian ===
    {"name": "Viking", "token_id": "81077217360707061912834157572439505549005379572697639089036662604552523578567",
     "end_date": "2026-03-21T18:45:00Z", "pre_game_price": 0.0,
     "question": "Viking FK vs. Molde FK"},
    {"name": "Molde", "token_id": "16612449150001706500580582603543631439558031898928915821460542625838107311737",
     "end_date": "2026-03-21T18:45:00Z", "pre_game_price": 0.0,
     "question": "Viking FK vs. Molde FK"},

    # === MLS ===
    {"name": "Philly", "token_id": "87656221388718925136494386423745853980069339826595129015239240301618672547458",
     "end_date": "2026-03-21T22:15:00Z", "pre_game_price": 0.0,
     "question": "Philadelphia Union vs. Chicago Fire FC"},
    {"name": "Chicago Fire", "token_id": "48104067043411971942864523012137903238054975550652731310129927585235697523649",
     "end_date": "2026-03-21T22:15:00Z", "pre_game_price": 0.0,
     "question": "Philadelphia Union vs. Chicago Fire FC"},

    {"name": "Nashville", "token_id": "3189205825920828983385414073269589410430622896943943927235049152780353500176",
     "end_date": "2026-03-21T23:00:00Z", "pre_game_price": 0.0,
     "question": "Nashville SC vs. Orlando City SC"},
    {"name": "Orlando", "token_id": "87713749055371533545114923716679835539309868833493156204004393615157899478421",
     "end_date": "2026-03-21T23:00:00Z", "pre_game_price": 0.0,
     "question": "Nashville SC vs. Orlando City SC"},

    {"name": "Charlotte", "token_id": "109827372966505041746970780078959577970505630128170764221569561136868496172081",
     "end_date": "2026-03-22T01:15:00Z", "pre_game_price": 0.0,
     "question": "Charlotte FC vs. New York Red Bulls"},
    {"name": "NY Red Bulls", "token_id": "37771651062551373842007421821278934058934356583757067314761392193573709367666",
     "end_date": "2026-03-22T01:15:00Z", "pre_game_price": 0.0,
     "question": "Charlotte FC vs. New York Red Bulls"},

    {"name": "Atlanta", "token_id": "111206507902677101464883682267981095560045184430932066247716980162727930422144",
     "end_date": "2026-03-22T01:15:00Z", "pre_game_price": 0.0,
     "question": "Atlanta United FC vs. D.C. United SC"},
    {"name": "DC United", "token_id": "11341170807951785856320602147750462896232368200822348993308089998762117564434",
     "end_date": "2026-03-22T01:15:00Z", "pre_game_price": 0.0,
     "question": "Atlanta United FC vs. D.C. United SC"},

    {"name": "KC", "token_id": "47038650667238107424644378000695112252051299291010705097211828311797797165597",
     "end_date": "2026-03-22T02:15:00Z", "pre_game_price": 0.0,
     "question": "Sporting Kansas City vs. Colorado Rapids SC"},
    {"name": "Colorado", "token_id": "52782895681187163720741678685720605574833324147790759372789858211642426126936",
     "end_date": "2026-03-22T02:15:00Z", "pre_game_price": 0.0,
     "question": "Sporting Kansas City vs. Colorado Rapids SC"},

    {"name": "Austin", "token_id": "50893326188302574221093230194600239597011034528724844133112977890573832692875",
     "end_date": "2026-03-22T02:15:00Z", "pre_game_price": 0.0,
     "question": "Austin FC vs. Los Angeles FC"},
    {"name": "LAFC", "token_id": "25699177590749077160285364962378461134885892468301455444855527896252714033724",
     "end_date": "2026-03-22T02:15:00Z", "pre_game_price": 0.0,
     "question": "Austin FC vs. Los Angeles FC"},

    # === Brazilian ===
    {"name": "Bragantino", "token_id": "110324675636812427392562045234063597234021718778329060874274244835450134236888",
     "end_date": "2026-03-21T20:45:00Z", "pre_game_price": 0.0,
     "question": "Red Bull Bragantino vs. Botafogo FR"},
    {"name": "Botafogo", "token_id": "20563535765714994239697919093697186778240935201471485343482544287249020905084",
     "end_date": "2026-03-21T20:45:00Z", "pre_game_price": 0.0,
     "question": "Red Bull Bragantino vs. Botafogo FR"},

    {"name": "Fluminense", "token_id": "101033455551036624331342233783874232122243714688411345015626005254714076289994",
     "end_date": "2026-03-21T23:15:00Z", "pre_game_price": 0.0,
     "question": "Fluminense FC vs. CA Mineiro"},
    {"name": "Mineiro", "token_id": "58499301473061595505800061177194815269647189160751335468297053111287024238718",
     "end_date": "2026-03-21T23:15:00Z", "pre_game_price": 0.0,
     "question": "Fluminense FC vs. CA Mineiro"},

    {"name": "Sao Paulo", "token_id": "108553820529920949149996006016504664223522530612410179434553317351204633679908",
     "end_date": "2026-03-22T01:45:00Z", "pre_game_price": 0.0,
     "question": "São Paulo FC vs. SE Palmeiras"},
    {"name": "Palmeiras", "token_id": "103695430548004340576268157103284507270117731079430260155851960821125343497646",
     "end_date": "2026-03-22T01:45:00Z", "pre_game_price": 0.0,
     "question": "São Paulo FC vs. SE Palmeiras"},

    # === Argentine ===
    {"name": "Velez", "token_id": "100127430619871230871353041392554319150284982547284300708748197309779280523895",
     "end_date": "2026-03-21T20:15:00Z", "pre_game_price": 0.0,
     "question": "CA Vélez Sarsfield vs. CA Lanús"},
    {"name": "Lanus", "token_id": "28443017326865364834388727770937107920739662727784009622455435357024115719056",
     "end_date": "2026-03-21T20:15:00Z", "pre_game_price": 0.0,
     "question": "CA Vélez Sarsfield vs. CA Lanús"},

    {"name": "Newells", "token_id": "34256164551890343423552970471088482869423246741831221578376180247506399215518",
     "end_date": "2026-03-21T22:30:00Z", "pre_game_price": 0.0,
     "question": "CA Newell's Old Boys vs. CA Gimnasia y Esgrima de Mendoza"},
    {"name": "Gimnasia", "token_id": "19306346338977567131376738746612230535245852966919848219758765085286796807238",
     "end_date": "2026-03-21T22:30:00Z", "pre_game_price": 0.0,
     "question": "CA Newell's Old Boys vs. CA Gimnasia y Esgrima de Mendoza"},

    # === Mexican Liga MX ===
    {"name": "Atlas", "token_id": "41460639260539264317807559918861534007928030787348253656839049483371937144649",
     "end_date": "2026-03-22T00:45:00Z", "pre_game_price": 0.0,
     "question": "Atlas FC vs. Querétaro FC"},
    {"name": "Queretaro", "token_id": "80144363979698448628456151505757147326968579602628340481585691529102264547667",
     "end_date": "2026-03-22T00:45:00Z", "pre_game_price": 0.0,
     "question": "Atlas FC vs. Querétaro FC"},

    {"name": "Monterrey", "token_id": "71698827877585934977507121325004483661986071663634615963858417131291371409077",
     "end_date": "2026-03-22T02:45:00Z", "pre_game_price": 0.0,
     "question": "CF Monterrey vs. CD Guadalajara"},
    {"name": "Guadalajara", "token_id": "39965367193640057669154950096993469601727304165576881380928177994259029677378",
     "end_date": "2026-03-22T02:45:00Z", "pre_game_price": 0.0,
     "question": "CF Monterrey vs. CD Guadalajara"},

    {"name": "Pumas", "token_id": "93160476014169164976771336462240304927429325619721115062126476558794020736606",
     "end_date": "2026-03-22T04:45:00Z", "pre_game_price": 0.0,
     "question": "Pumas de la UNAM vs. CF América"},
    {"name": "America", "token_id": "93040541861168839382185194571552962501271158313283518255121403416270590784237",
     "end_date": "2026-03-22T04:45:00Z", "pre_game_price": 0.0,
     "question": "Pumas de la UNAM vs. CF América"},
]

# === Params — championship/lower-tier leagues have higher draw risk ===
MIN_NEAR_RES_PRICE = 0.86     # Tighter for lower-tier leagues
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.22          # Higher threshold for draw-prone leagues
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 18           # Tighter time window
MAX_SPEND_PER_TRADE = 15.0     # Conservative — championship has higher draw risk
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.25          # Conservative sizing for lower-tier
BOUGHT = set()                 # Dedup: prevent buying same token or same-game opponent


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
                        "market_id": f"near-res-mar21-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar21 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR21 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
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
    print(f"=== Near-Res Monitor: March 21 (Championship + Eredivisie + MLS + South America) ===")
    print(f"=== Started at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    print(f"=== {len(ALL_GAMES)} tokens ({len(ALL_GAMES)//2} games) ===")
    print(f"Params: MIN_PRICE={MIN_NEAR_RES_PRICE}, JUMP={MIN_PRICE_JUMP}, "
          f"SPREAD={MAX_SPREAD}, MAX_MINS={MAX_MINS_TO_END}")
    print(f"Sizing: MAX_SPEND=${MAX_SPEND_PER_TRADE}, PCT={PCT_OF_BALANCE}, "
          f"MIN_SPEND=${MIN_SPEND}")

    client = get_client()

    print("\nCapturing pre-game prices...")
    snapshot_pre_game_prices(client, ALL_GAMES)

    for i in range(1080):  # 18 hours
        check_and_buy(client, ALL_GAMES)
        time.sleep(60)
