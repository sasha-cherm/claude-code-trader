#!/usr/bin/env python3
"""
Near-resolution monitor for March 21, 2026 (Saturday).
MASSIVE DAY: EPL (5), Bundesliga (3+1 BL2), La Liga (3), Championship (10),
Eredivisie (3), Norwegian (1), MLS (6), Brazilian (3), Argentine (2),
Mexican (3), NBA (10). Total: 50+ games, 100+ tokens.
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
    # === EPL (TOP PRIORITY — highest volume, best MMs) ===
    # Brighton vs Liverpool — 12:30 UTC kick (end ~14:15)
    {"name": "Brighton", "token_id": "100464054121002033210929966097122721185902091676775506635237858654025169363262",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Brighton & Hove Albion FC vs. Liverpool FC"},
    {"name": "Liverpool", "token_id": "35083807819338446925002466154655205330091854330432756866206371119620373615428",
     "end_date": "2026-03-21T14:15:00Z", "pre_game_price": 0.0,
     "question": "Brighton & Hove Albion FC vs. Liverpool FC"},

    # Man City vs Crystal Palace — 15:00 UTC kick (end ~16:45)
    {"name": "Man City", "token_id": "59926179825727217606167341176846116057970189763068493202217393131144123674309",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Manchester City FC vs. Crystal Palace FC"},
    {"name": "Crystal Palace", "token_id": "47798652524102667635886769882234495418506879283040748965001754646341968655128",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Manchester City FC vs. Crystal Palace FC"},

    # Fulham vs Burnley — 15:00 UTC kick (end ~16:45)
    {"name": "Fulham", "token_id": "100424505911492726143069668369640898890012859227903329249368753635028896002613",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Fulham FC vs. Burnley FC"},
    {"name": "Burnley", "token_id": "111387501328662145897103162600496351393235879641274336060199507793806731099077",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "Fulham FC vs. Burnley FC"},

    # Everton vs Chelsea — 17:30 UTC kick (end ~19:15)
    {"name": "Everton", "token_id": "16201391243045422507023801607586153372791417104258215636932788686821300331314",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "Everton FC vs. Chelsea FC"},
    {"name": "Chelsea", "token_id": "77019523621478946963865271857336353830849712350406503519645871793341730636267",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "Everton FC vs. Chelsea FC"},

    # Leeds vs Brentford — 20:00 UTC kick (end ~21:45)
    {"name": "Leeds", "token_id": "33550256521588566181818107761102086100116148175456742347678976997881043151893",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "Leeds United FC vs. Brentford FC"},
    {"name": "Brentford", "token_id": "25666419921296394159751233259946485552020074285656528843009715659948160932435",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "Leeds United FC vs. Brentford FC"},

    # === Bundesliga (14:30 UTC kick, end ~16:15) ===
    {"name": "Bayern", "token_id": "73608654579667762253217116531720070507518940654076511529510999262262027884268",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "FC Bayern München vs. 1. FC Union Berlin"},
    {"name": "Union Berlin", "token_id": "53091408207552281959372860321965041196316558699049937733771437981327670353864",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "FC Bayern München vs. 1. FC Union Berlin"},

    {"name": "Wolfsburg", "token_id": "49819722077709162050722942057375341115813548416036024717549689040608689645975",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "VfL Wolfsburg vs. SV Werder Bremen"},
    {"name": "Werder", "token_id": "77887570342911999493957585235617706142387479967121537823906236245364748124425",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "VfL Wolfsburg vs. SV Werder Bremen"},

    {"name": "Cologne", "token_id": "102299088679352054417736559867455924360388544782091043921390037034349668411627",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FC Köln vs. Borussia Mönchengladbach"},
    {"name": "Gladbach", "token_id": "48879164904929398817341221432144137544626011479377909046565667403976318180164",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FC Köln vs. Borussia Mönchengladbach"},

    {"name": "Heidenheim", "token_id": "81618470378539016004084304569271130489919761679979279838229928389812463145047",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FC Heidenheim 1846 vs. Bayer 04 Leverkusen"},
    {"name": "Leverkusen", "token_id": "60255938594662677927258374878138772075596471823932570540145040845653072385376",
     "end_date": "2026-03-21T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FC Heidenheim 1846 vs. Bayer 04 Leverkusen"},

    # Dortmund vs Hamburg (2. Bundesliga) — 17:30 UTC kick (end ~19:15)
    {"name": "Dortmund", "token_id": "69975983437630865740919355819359124143797871698581159840041946973598354888329",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "BV Borussia 09 Dortmund vs. Hamburger SV"},
    {"name": "Hamburg", "token_id": "114536474308445902340063082220979684912189800956998978843513496881483655598673",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "BV Borussia 09 Dortmund vs. Hamburger SV"},

    # === La Liga ===
    # Espanyol vs Getafe — 15:00 UTC kick (end ~16:45)
    {"name": "Espanyol", "token_id": "73701870899525630801278951663635231976004791734689446731960507846593991776271",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "RCD Espanyol de Barcelona vs. Getafe CF"},
    {"name": "Getafe", "token_id": "33222809016663559049188985006887368887946397491576107441078958500201998466014",
     "end_date": "2026-03-21T16:45:00Z", "pre_game_price": 0.0,
     "question": "RCD Espanyol de Barcelona vs. Getafe CF"},

    # Osasuna vs Girona — 17:30 UTC kick (end ~19:15)
    {"name": "Osasuna", "token_id": "258677385302688182461898417967106726834258313005766909541915428260925716921",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "CA Osasuna vs. Girona FC"},
    {"name": "Girona", "token_id": "77761244344818711819030470373492527977913587169152648708182888704278173793633",
     "end_date": "2026-03-21T19:15:00Z", "pre_game_price": 0.0,
     "question": "CA Osasuna vs. Girona FC"},

    # Sevilla vs Valencia — 20:00 UTC kick (end ~21:45)
    {"name": "Sevilla", "token_id": "89261921640419081793779673565275963528601998871096312990615893330972331046097",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "Sevilla FC vs. Valencia CF"},
    {"name": "Valencia", "token_id": "17685810212873216925695961769327560666758490814990506012223434116202381971711",
     "end_date": "2026-03-21T21:45:00Z", "pre_game_price": 0.0,
     "question": "Sevilla FC vs. Valencia CF"},

    # === NBA (10 games, tipoffs 21:00 UTC - 02:00 UTC) ===
    {"name": "Thunder", "token_id": "94844051458161093758408644748213964911062272689244334591279755394311450989118",
     "end_date": "2026-03-22T00:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Wizards"},
    {"name": "Wizards", "token_id": "68095691128077179100318731792628872850372804787496257265201482153936637006429",
     "end_date": "2026-03-22T00:30:00Z", "pre_game_price": 0.0,
     "question": "Thunder vs. Wizards"},
    {"name": "Grizzlies", "token_id": "112493961779042478006346891746610690983081151525885535705297709617620965327035",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Grizzlies vs. Hornets"},
    {"name": "Hornets", "token_id": "25081080501033233654312754818909248623567642297753593125268132775695454858235",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Grizzlies vs. Hornets"},
    {"name": "Lakers", "token_id": "66419344206339468073253308897091364505984570816153869860212591505290583609104",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Magic"},
    {"name": "Magic", "token_id": "59710325672987047484152804198498095977107600959651145229891529355298398088578",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Lakers vs. Magic"},
    {"name": "Cavaliers", "token_id": "115254320258539752708522193689293486816166369187979320184482189657307784963064",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Cavaliers vs. Pelicans"},
    {"name": "Pelicans", "token_id": "82016993096564541113171196398807867514046438129512700947240007036841990360444",
     "end_date": "2026-03-22T02:30:00Z", "pre_game_price": 0.0,
     "question": "Cavaliers vs. Pelicans"},
    {"name": "Warriors", "token_id": "73477341174479152259577917870650353681944211549294712547249725182626389515512",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Hawks"},
    {"name": "Hawks", "token_id": "47688476558965333598463501419452813288450981075962287030049367585373980290969",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Warriors vs. Hawks"},
    {"name": "Heat", "token_id": "66619962828726174779371387502442846499813128559203573763873012123716556972866",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Rockets"},
    {"name": "Rockets", "token_id": "44709731364797464574395633651617729372591090876651472137054184195967359549215",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Heat vs. Rockets"},
    {"name": "Pacers", "token_id": "70525269588579059962845302246989422128946174955986385912648420268953386711358",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Pacers vs. Spurs"},
    {"name": "Spurs", "token_id": "32877728229253329027329636082000638918329218780414503302794994633349393481502",
     "end_date": "2026-03-22T03:30:00Z", "pre_game_price": 0.0,
     "question": "Pacers vs. Spurs"},
    {"name": "Clippers", "token_id": "109494632565651733301020904932199813861932582132036302717250905296971266287588",
     "end_date": "2026-03-22T04:00:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs. Mavericks"},
    {"name": "Mavericks", "token_id": "107498027172937403056773925260063954037483348009099426755694609797390489418850",
     "end_date": "2026-03-22T04:00:00Z", "pre_game_price": 0.0,
     "question": "Clippers vs. Mavericks"},
    {"name": "76ers", "token_id": "92252343234129633768649797505793003493639180172408450196464214414346494971632",
     "end_date": "2026-03-22T05:00:00Z", "pre_game_price": 0.0,
     "question": "76ers vs. Jazz"},
    {"name": "Jazz", "token_id": "79365399650316026880040710776474208525322429296929910801469223466522919311892",
     "end_date": "2026-03-22T05:00:00Z", "pre_game_price": 0.0,
     "question": "76ers vs. Jazz"},
    {"name": "Bucks", "token_id": "89978578624481415270168164861148571396567375367208822145977787083394124020127",
     "end_date": "2026-03-22T05:30:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Suns"},
    {"name": "Suns", "token_id": "62621931224691683466453100876075260824584725786291390369738235958307849567075",
     "end_date": "2026-03-22T05:30:00Z", "pre_game_price": 0.0,
     "question": "Bucks vs. Suns"},

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

# === Params — EPL/BuLi/LaLiga are reliable; lower-tier needs caution ===
MIN_NEAR_RES_PRICE = 0.85     # Top-tier leagues can go slightly lower
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20          # Standard threshold
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20           # Standard time window
MAX_SPEND_PER_TRADE = 18.0     # Moderate — compound gains
MIN_SPEND = 1.0
PCT_OF_BALANCE = 0.28          # Moderate sizing
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
