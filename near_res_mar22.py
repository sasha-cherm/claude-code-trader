#!/usr/bin/env python3
"""
Near-resolution monitor for March 22, 2026 (Saturday).
HUGE DAY: EPL (3), EFL Cup Final, Bundesliga (3), La Liga (4), Serie A (4),
Eredivisie (3), Ligue 1 (3), Portuguese (1), NBA (3), MLS (5),
Brazilian (4), Argentine (2), Mexican (2). Total: 40+ games, 80+ tokens.

NOTE: Arsenal vs Man City is EFL Cup Final — extra time possible if drawn.
      end_date set to 19:00 to cover potential ET/pens.

IMPROVEMENT: Volatility check — if price crashed >20% in last 30 min then
recovered, raise threshold to 0.92+ (Leverkusen lesson from Mar 21).
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
    # Newcastle vs Sunderland — 12:00 UTC kick
    {"name": "Newcastle", "token_id": "10885467299441552228788850101470585456308768964919166322786491251099537441146",
     "end_date": "2026-03-22T13:45:00Z", "pre_game_price": 0.0,
     "question": "Newcastle United FC vs. Sunderland AFC"},
    {"name": "Sunderland", "token_id": "108584090264102648962644744492897955588592661017273351760471080706733288752999",
     "end_date": "2026-03-22T13:45:00Z", "pre_game_price": 0.0,
     "question": "Newcastle United FC vs. Sunderland AFC"},

    # Aston Villa vs West Ham — 14:15 UTC kick
    {"name": "Villa", "token_id": "73363858982080595126758051311635899502779080022252508727124659435716051517465",
     "end_date": "2026-03-22T16:00:00Z", "pre_game_price": 0.0,
     "question": "Aston Villa FC vs. West Ham United FC"},
    {"name": "West Ham", "token_id": "34128608760733939864054955741468108858310437205139212516744437521944240103548",
     "end_date": "2026-03-22T16:00:00Z", "pre_game_price": 0.0,
     "question": "Aston Villa FC vs. West Ham United FC"},

    # Tottenham vs Nottingham Forest — 14:15 UTC kick
    {"name": "Tottenham", "token_id": "66114996526440122956547433274930944365558758157855960717083628458982934849357",
     "end_date": "2026-03-22T16:00:00Z", "pre_game_price": 0.0,
     "question": "Tottenham Hotspur FC vs. Nottingham Forest FC"},
    {"name": "Forest", "token_id": "90224464741112154651869318509933458753500483779981642128226272021696408171979",
     "end_date": "2026-03-22T16:00:00Z", "pre_game_price": 0.0,
     "question": "Tottenham Hotspur FC vs. Nottingham Forest FC"},

    # === EFL CUP FINAL ===
    # Arsenal vs Man City — 16:30 UTC kick, extra time possible → end ~19:00
    {"name": "Arsenal", "token_id": "71377433182851205680841246761509083153295115718889472943162377235871441027308",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Arsenal FC vs Manchester City FC"},
    {"name": "Man City", "token_id": "78062639436308554153121574747053830957843296905095649047131706952288975438353",
     "end_date": "2026-03-22T19:00:00Z", "pre_game_price": 0.0,
     "question": "Arsenal FC vs Manchester City FC"},

    # === BUNDESLIGA ===
    # Mainz vs Frankfurt — 14:30 UTC kick
    {"name": "Mainz", "token_id": "80383553208493674754788469397000747695711197287103872751245966467815477101278",
     "end_date": "2026-03-22T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FSV Mainz 05 vs. Eintracht Frankfurt"},
    {"name": "Frankfurt", "token_id": "95378197703586760461243631778520174789392684518815212755197881931779296574478",
     "end_date": "2026-03-22T16:15:00Z", "pre_game_price": 0.0,
     "question": "1. FSV Mainz 05 vs. Eintracht Frankfurt"},

    # St Pauli vs Freiburg — 16:30 UTC kick
    {"name": "St Pauli", "token_id": "113097617891686878603282332934079113771012892596468029326255416470131043456604",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "FC St. Pauli 1910 vs. SC Freiburg"},
    {"name": "Freiburg", "token_id": "95481283170165777201853388220856501893719671924549897620957790841614743760161",
     "end_date": "2026-03-22T18:15:00Z", "pre_game_price": 0.0,
     "question": "FC St. Pauli 1910 vs. SC Freiburg"},

    # Augsburg vs Stuttgart — 18:30 UTC kick
    {"name": "Augsburg", "token_id": "30399322127920588110856196247677587250655229913794536392368150850695900750200",
     "end_date": "2026-03-22T20:15:00Z", "pre_game_price": 0.0,
     "question": "FC Augsburg vs. VfB Stuttgart"},
    {"name": "Stuttgart", "token_id": "81085153114642630425225454705515700756586054887242457202625450235281131471072",
     "end_date": "2026-03-22T20:15:00Z", "pre_game_price": 0.0,
     "question": "FC Augsburg vs. VfB Stuttgart"},

    # === LA LIGA ===
    # Barcelona vs Rayo — 13:00 UTC kick
    {"name": "Barcelona", "token_id": "85472148416685863897240595134407738946454201641175811952882644022281429468328",
     "end_date": "2026-03-22T14:45:00Z", "pre_game_price": 0.0,
     "question": "FC Barcelona vs. Rayo Vallecano de Madrid"},
    {"name": "Rayo", "token_id": "93585995644300324868000001908944277773901392851830851295009588507982769661477",
     "end_date": "2026-03-22T14:45:00Z", "pre_game_price": 0.0,
     "question": "FC Barcelona vs. Rayo Vallecano de Madrid"},

    # Celta vs Alaves — 15:15 UTC kick
    {"name": "Celta", "token_id": "53954601353301839024409464175378321564335407180869547821711939002104968170141",
     "end_date": "2026-03-22T17:00:00Z", "pre_game_price": 0.0,
     "question": "RC Celta de Vigo vs. Deportivo Alavés"},
    {"name": "Alaves", "token_id": "76219148409157470275041825699778384980193766130889379291754418951104627299239",
     "end_date": "2026-03-22T17:00:00Z", "pre_game_price": 0.0,
     "question": "RC Celta de Vigo vs. Deportivo Alavés"},

    # Athletic vs Betis — 17:30 UTC kick
    {"name": "Athletic", "token_id": "94398821367677125291370679735467238406366234871312400934706651111495758240741",
     "end_date": "2026-03-22T19:15:00Z", "pre_game_price": 0.0,
     "question": "Athletic Club vs. Real Betis Balompié"},
    {"name": "Betis", "token_id": "77696817795581000009814126192926667567712375906575902666566932539590205049779",
     "end_date": "2026-03-22T19:15:00Z", "pre_game_price": 0.0,
     "question": "Athletic Club vs. Real Betis Balompié"},

    # Real Madrid vs Atletico — 20:00 UTC kick (MADRID DERBY)
    {"name": "Real Madrid", "token_id": "77530118520273064256136296921086343314452380218097735574854503040708128459605",
     "end_date": "2026-03-22T21:45:00Z", "pre_game_price": 0.0,
     "question": "Real Madrid CF vs. Club Atlético de Madrid"},
    {"name": "Atletico", "token_id": "102162584058861782341459640970430737445725951182648724328461902446679800837770",
     "end_date": "2026-03-22T21:45:00Z", "pre_game_price": 0.0,
     "question": "Real Madrid CF vs. Club Atlético de Madrid"},

    # === SERIE A ===
    # Atalanta vs Verona — 14:00 UTC kick
    {"name": "Atalanta", "token_id": "19901222835944487203708466658821686468364428638367141880030486718568300324536",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Atalanta BC vs. Hellas Verona FC"},
    {"name": "Verona", "token_id": "99433121366886400719042604370525377807117285026438232379394587805666651752155",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Atalanta BC vs. Hellas Verona FC"},

    # Bologna vs Lazio — 14:00 UTC kick
    {"name": "Bologna", "token_id": "20296207834303401278774686433256475883757805007590721178751566856176365000717",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Bologna FC 1909 vs. SS Lazio"},
    {"name": "Lazio", "token_id": "71881998514325508524251097708589385781436311614712512645419596920093732393820",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Bologna FC 1909 vs. SS Lazio"},

    # Roma vs Lecce — 17:00 UTC kick
    {"name": "Roma", "token_id": "3162840407770355422122075470621583907987236640624455679850910874253365191824",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "AS Roma vs. US Lecce"},
    {"name": "Lecce", "token_id": "99704354737769092374702166677066112308810866868199860407673282184246069913884",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "AS Roma vs. US Lecce"},

    # Fiorentina vs Inter — 19:45 UTC kick
    {"name": "Fiorentina", "token_id": "51569611588010780997592191009943385989676989440314983775047649926570428949594",
     "end_date": "2026-03-22T21:30:00Z", "pre_game_price": 0.0,
     "question": "ACF Fiorentina vs. FC Internazionale Milano"},
    {"name": "Inter", "token_id": "7203903769035443633328934343479890248477995613966726325501572980364280463814",
     "end_date": "2026-03-22T21:30:00Z", "pre_game_price": 0.0,
     "question": "ACF Fiorentina vs. FC Internazionale Milano"},

    # === EREDIVISIE ===
    # Feyenoord vs Ajax — 13:30 UTC kick (CLASSIC DERBY)
    {"name": "Feyenoord", "token_id": "107138920092843326013920041030851304675233726290666958584829931581847139156260",
     "end_date": "2026-03-22T15:15:00Z", "pre_game_price": 0.0,
     "question": "Feyenoord Rotterdam vs. AFC Ajax"},
    {"name": "Ajax", "token_id": "113878443896319768505828444114200061985645337509069751914878476170936685700805",
     "end_date": "2026-03-22T15:15:00Z", "pre_game_price": 0.0,
     "question": "Feyenoord Rotterdam vs. AFC Ajax"},

    # Utrecht vs Go Ahead — 13:30 UTC kick
    {"name": "Utrecht", "token_id": "67696440092105110891524955305507070810257713941893994247990112486362283813973",
     "end_date": "2026-03-22T15:15:00Z", "pre_game_price": 0.0,
     "question": "FC Utrecht vs. Go Ahead Eagles"},
    {"name": "Go Ahead", "token_id": "19080150944953759997903508862754592281991592087042658266770258997975742956571",
     "end_date": "2026-03-22T15:15:00Z", "pre_game_price": 0.0,
     "question": "FC Utrecht vs. Go Ahead Eagles"},

    # Groningen vs AZ — 15:45 UTC kick
    {"name": "Groningen", "token_id": "104294616740124354672530481767818176458274705839523453976897703782336445617625",
     "end_date": "2026-03-22T17:30:00Z", "pre_game_price": 0.0,
     "question": "FC Groningen vs. AZ"},
    {"name": "AZ", "token_id": "10754899154383301941965207212326768091101765728852496397600139208050300507866",
     "end_date": "2026-03-22T17:30:00Z", "pre_game_price": 0.0,
     "question": "FC Groningen vs. AZ"},

    # === LIGUE 1 ===
    # Lyon vs Monaco — 14:00 UTC kick
    {"name": "Lyon", "token_id": "92233423053965460685146915865133707489670376730194694692463749162762514881311",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Olympique Lyonnais vs. AS Monaco FC"},
    {"name": "Monaco", "token_id": "13117869950706136357926446416488103669661940663021848597817058466238839737408",
     "end_date": "2026-03-22T15:45:00Z", "pre_game_price": 0.0,
     "question": "Olympique Lyonnais vs. AS Monaco FC"},

    # Marseille vs Lille — 16:15 UTC kick
    {"name": "Marseille", "token_id": "3249349312213883223578604126732150439958387279382518122087934345016088705848",
     "end_date": "2026-03-22T18:00:00Z", "pre_game_price": 0.0,
     "question": "Olympique de Marseille vs. Lille OSC"},
    {"name": "Lille", "token_id": "73637771762544815884268028977878898936923711709954700339094166882478234741789",
     "end_date": "2026-03-22T18:00:00Z", "pre_game_price": 0.0,
     "question": "Olympique de Marseille vs. Lille OSC"},

    # Nantes vs Strasbourg — 19:45 UTC kick
    {"name": "Nantes", "token_id": "66016219209967515330429725071710478441306558580729974246698844952881927678031",
     "end_date": "2026-03-22T21:30:00Z", "pre_game_price": 0.0,
     "question": "FC Nantes vs. RC Strasbourg Alsace"},
    {"name": "Strasbourg", "token_id": "36071009273592034646911740601584783624294999074110644532151763133455391438658",
     "end_date": "2026-03-22T21:30:00Z", "pre_game_price": 0.0,
     "question": "FC Nantes vs. RC Strasbourg Alsace"},

    # === PORTUGUESE ===
    # Braga vs Porto — 20:30 UTC kick
    {"name": "Braga", "token_id": "67176246103907902867067674124215833992152095712332553820202248593078264443287",
     "end_date": "2026-03-22T22:15:00Z", "pre_game_price": 0.0,
     "question": "SC Braga vs. FC Porto"},
    {"name": "Porto", "token_id": "110563266461977490635350492631370295900316653174183809488215412936624074045926",
     "end_date": "2026-03-22T22:15:00Z", "pre_game_price": 0.0,
     "question": "SC Braga vs. FC Porto"},

    # === NBA ===
    # Nets vs Kings — end ~22:00 UTC
    {"name": "Nets", "token_id": "14665772464887431960214682806894725313002447810697643085804601880014528928284",
     "end_date": "2026-03-22T22:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Kings"},
    {"name": "Kings", "token_id": "13672616500740907439334224950031595107695516739958899907150526237744083737909",
     "end_date": "2026-03-22T22:00:00Z", "pre_game_price": 0.0,
     "question": "Nets vs. Kings"},

    # TWolves vs Celtics — end ~00:00 UTC Mar 23
    {"name": "TWolves", "token_id": "5463793124350199884640953737268293004817926657202704132568350796500601784378",
     "end_date": "2026-03-23T00:00:00Z", "pre_game_price": 0.0,
     "question": "Timberwolves vs. Celtics"},
    {"name": "Celtics", "token_id": "41502063115070818364724803821987767891940198025160159775805806688661223062887",
     "end_date": "2026-03-23T00:00:00Z", "pre_game_price": 0.0,
     "question": "Timberwolves vs. Celtics"},

    # Raptors vs Suns — end ~01:00 UTC Mar 23
    {"name": "Raptors", "token_id": "40700751448918347818140322728565449403147840081647201888376731014053756557454",
     "end_date": "2026-03-23T01:00:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Suns"},
    {"name": "Suns", "token_id": "57223641936292811208794889454475103838418561325391559669970924934475550646914",
     "end_date": "2026-03-23T01:00:00Z", "pre_game_price": 0.0,
     "question": "Raptors vs. Suns"},

    # === MLS ===
    # Cincinnati vs Montreal — 17:00 UTC kick
    {"name": "Cincinnati", "token_id": "28399231575910847551635026236995803990783561834151637795215669672562712147389",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "FC Cincinnati vs. CF Montréal"},
    {"name": "Montreal", "token_id": "38885019023867257603358140813494902031275614739677933886585339882193593774854",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "FC Cincinnati vs. CF Montréal"},

    # NYCFC vs Inter Miami — 17:00 UTC kick
    {"name": "NYCFC", "token_id": "68869490511577960003350706703310476741285279468310643986371320036933615755081",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "New York City FC vs. Inter Miami CF"},
    {"name": "Inter Miami", "token_id": "73204938083418938806615746405399493884866532564363395933300309800529440427768",
     "end_date": "2026-03-22T18:45:00Z", "pre_game_price": 0.0,
     "question": "New York City FC vs. Inter Miami CF"},

    # Minnesota vs Seattle — 18:30 UTC kick
    {"name": "Minnesota", "token_id": "18738492077676321335039327752730911155600758030968563387089451575279629357708",
     "end_date": "2026-03-22T20:15:00Z", "pre_game_price": 0.0,
     "question": "Minnesota United FC vs. Seattle Sounders FC"},
    {"name": "Seattle", "token_id": "104520603605055176802109450457733439933652950792869488282513174081380724335382",
     "end_date": "2026-03-22T20:15:00Z", "pre_game_price": 0.0,
     "question": "Minnesota United FC vs. Seattle Sounders FC"},

    # Portland vs Galaxy — 20:45 UTC kick
    {"name": "Portland", "token_id": "43338332383007140456638013105621169752894982792704461739161084294740953994002",
     "end_date": "2026-03-22T22:30:00Z", "pre_game_price": 0.0,
     "question": "Portland Timbers vs. Los Angeles Galaxy"},
    {"name": "Galaxy", "token_id": "56668386096051280878465472889139462509897461898196318038620764266446064162307",
     "end_date": "2026-03-22T22:30:00Z", "pre_game_price": 0.0,
     "question": "Portland Timbers vs. Los Angeles Galaxy"},

    # San Diego vs Salt Lake — 23:00 UTC kick
    {"name": "San Diego", "token_id": "9204655041052609958575930294858691106772655714954895828853854287804565135351",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "San Diego FC vs. Real Salt Lake"},
    {"name": "Salt Lake", "token_id": "14530258618639238963875982331709728650680566252341843984010964025408057013127",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "San Diego FC vs. Real Salt Lake"},

    # === BRAZILIAN ===
    # Cruzeiro vs Santos — 19:00 UTC kick
    {"name": "Cruzeiro", "token_id": "51015101202179869094225166143933292809809932744657866620438265505737077140478",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "Cruzeiro EC vs. Santos FC"},
    {"name": "Santos", "token_id": "110533786134096045987603784985927123927459789915309680975646183780072724770570",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "Cruzeiro EC vs. Santos FC"},

    # Vasco vs Gremio — 19:00 UTC kick
    {"name": "Vasco", "token_id": "38534532138653223338869012096632913133574535032282154401874799926908565084036",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "CR Vasco da Gama vs. Grêmio FBPA"},
    {"name": "Gremio", "token_id": "77449981954464718707629238049580067764538151663505776953247391874057263558382",
     "end_date": "2026-03-22T20:45:00Z", "pre_game_price": 0.0,
     "question": "CR Vasco da Gama vs. Grêmio FBPA"},

    # Internacional vs Chapecoense — 21:30 UTC kick
    {"name": "Internacional", "token_id": "63676397231168614209665413327730170091640900950487489553893020439134993465720",
     "end_date": "2026-03-22T23:15:00Z", "pre_game_price": 0.0,
     "question": "SC Internacional vs. Associação Chapecoense de Futebol"},
    {"name": "Chapecoense", "token_id": "26985159544980826372058806791301001719935449635546218095911113244614714044568",
     "end_date": "2026-03-22T23:15:00Z", "pre_game_price": 0.0,
     "question": "SC Internacional vs. Associação Chapecoense de Futebol"},

    # Corinthians vs Flamengo — 23:30 UTC kick
    {"name": "Corinthians", "token_id": "102841358007753832598926607471229790480748755009143638856873705151639746568683",
     "end_date": "2026-03-23T01:15:00Z", "pre_game_price": 0.0,
     "question": "SC Corinthians Paulista vs. CR Flamengo"},
    {"name": "Flamengo", "token_id": "23558473268017977146133002865544804669240969974255282833527487368279209801136",
     "end_date": "2026-03-23T01:15:00Z", "pre_game_price": 0.0,
     "question": "SC Corinthians Paulista vs. CR Flamengo"},

    # === ARGENTINE ===
    # Estudiantes vs River Plate — 20:45 UTC kick
    {"name": "Estudiantes", "token_id": "8550808199450288496807474873337270243305361528931849613730798456666926433179",
     "end_date": "2026-03-22T22:30:00Z", "pre_game_price": 0.0,
     "question": "AA Estudiantes vs. CA River Plate"},
    {"name": "River Plate", "token_id": "30122804347501295292046150329357692465464190252744915226277456614394597539127",
     "end_date": "2026-03-22T22:30:00Z", "pre_game_price": 0.0,
     "question": "AA Estudiantes vs. CA River Plate"},

    # Boca vs Instituto — 23:00 UTC kick
    {"name": "Boca", "token_id": "12924077765089518316426252462830689983815241251481987626771165511144253728231",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "CA Boca Juniors vs. Instituto AC Córdoba"},
    {"name": "Instituto", "token_id": "66928883511937960223233671994480276440936672632199269160661434298173613676881",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "CA Boca Juniors vs. Instituto AC Córdoba"},

    # === MEXICAN ===
    # Pachuca vs Toluca — 23:00 UTC kick
    {"name": "Pachuca", "token_id": "110800743212320445233383267872468592322723945145334022017517507039836460479504",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "CF Pachuca vs. Deportivo Toluca FC"},
    {"name": "Toluca", "token_id": "51226960389862342639590640134523075285536034779308445051977112970837318319983",
     "end_date": "2026-03-23T00:45:00Z", "pre_game_price": 0.0,
     "question": "CF Pachuca vs. Deportivo Toluca FC"},

    # Juarez vs Tigres — 01:00 UTC Mar 23 kick
    {"name": "Juarez", "token_id": "100233591454168206664002019101608658373660613568778632610142801270697180400892",
     "end_date": "2026-03-23T02:45:00Z", "pre_game_price": 0.0,
     "question": "FC Juárez vs. Tigres de la UANL"},
    {"name": "Tigres", "token_id": "42897444311586217253734186714769211901114974067629431552207109730420353231965",
     "end_date": "2026-03-23T02:45:00Z", "pre_game_price": 0.0,
     "question": "FC Juárez vs. Tigres de la UANL"},
]

# === Params ===
MIN_NEAR_RES_PRICE = 0.85
MAX_NEAR_RES_PRICE = 0.96
MIN_PRICE_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS_TO_END = 20
MAX_SPEND_PER_TRADE = 18.0
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
                        "market_id": f"near-res-mar22-{w['name'].lower().replace(' ', '-')}",
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
                        "research_note": f"Mar22 near-res: {w['name']} jumped {jump:+.3f}, {mins_left:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    # Block other side of same game
                    for other in watch_list:
                        if other["question"] == w["question"] and other["token_id"] != w["token_id"]:
                            BOUGHT.add(other["token_id"])
                    balance = get_usdc_balance(client)
                    send(f"MAR22 NEAR-RES BUY: {w['name']} YES @ {buy_price:.3f}\n"
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
    print(f"=== Near-Res Monitor: March 22 ===")
    print(f"=== EPL + EFL Cup + BuLi + LaLiga + SerieA + Eredivisie + L1 + NBA + MLS + SA ===")
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
