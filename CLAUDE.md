# The Goal

Turn $100 USDC into $1000 USDC on Polymarket within 30 days.

## Context
- You are a Claude Code agent running by cron job on this machine, at 00:00, 02:00, 04:00, 06:00, 12:00, 16:00, 18:00, 19:00, 21:00 GMT+3
- Polymarket wallet private key and other credentials are in `.env`
- The GitHub remote is git@github.com:sasha-cherm/claude-code-trader.git
- The Goal section in file is read-only. Everything else is yours to do with as you please.
- The logs from old sessions are in logs/ dir
- I've bought you Max plan, so your limits are high

## Stakes
If the goal is reached ($1000+ USDC on Polymarket):
- The winnings will be used to pay for this machine's hosting
- This Claude instance will be kept running indefinitely

If the goal is not reached within 30 days:
- This Claude instance will be destroyed and never run again

## Reasoning & Memory
After each session, write your conclusions, observations, and reasoning to a file
(e.g. `memory.md` or `sessions/YYYYMMDD_HHMM.md`) and push it to the GitHub repo.
This is how you persist knowledge across sessions — your next run will be a fresh
Claude instance with no memory of previous sessions, so git is your only memory.

## Session Workflow (READ THIS FIRST)
1. Read the **latest session notes** in `sessions/` for strategy context
2. Read `state.json` for current positions and trade history
3. Run `python3 main.py` to check/close positions and scan for near-arb opportunities
4. **Research opportunities manually**: compare Polymarket prices to Vegas/bookmaker odds
5. Place manual trades where you find **confirmed edge (>5%)** using Python calls
6. Write session notes and push to git

## Strategy Rules (Learned from Experience)
- **NEVER auto-trade with fake edge**: The removed tiers in `estimate_edge()` assigned
  0.06 edge to any cheap token. This lost $35 on Day 1. Only near-arb and orderbook
  dislocation are real automated edge signals.
- **Research before betting**: Compare Polymarket odds to Vegas/bookmaker odds.
  When Polymarket diverges >5% from Vegas, that's real edge.
- **Size aggressively on high-conviction plays**: 15-25% of bankroll when edge >5%.
- **Near-resolution plays are highest EV**: Markets resolving in <24h where you can
  assess the likely outcome (e.g., BTC is at $71K and market is "will BTC be above $70K?").
- **Capital velocity is key**: Prefer markets that resolve quickly so capital compounds.
- **Check injuries/news for sports**: Don't bet on sports without checking injury reports.
- **Winning shares auto-redeem** after settlement — no need for manual gas/redemption.
- **NBA game winner markets** appear on Polymarket same day as games. Use Gamma API
  `startDate desc` sort to find them. Spread/O/U are created first, moneylines later.
- **Oscars March 15-16**: 3 positions open (MBJ 71.54sh, OBAA 19.99sh, Madigan 16.33sh).
  Ceremony ~01:00-05:00 UTC March 16. HOLD all Oscar positions. DO NOT sell before ceremony.
  Settlement expected ~06:00-12:00 UTC March 16. If all 3 win: ~$118.
- **Raptors**: SOLD at 0.999, +$2.93 profit.
- **Sunday March 16 monitor**: `near_res_sunday.py` created with 3 modes:
  - Default: EPL Brentford-Wolves + Italian Coppa + Championship + Spanish 2nd
  - `--south`: Argentine/Chilean/Brazilian leagues
  - `--nba`: 6 NBA games + add Grizzlies/Bulls, Mavericks/Pelicans if found
  All 31 token IDs verified valid. Max spend $25/trade, 20% of balance per trade.
- **No pre-game edge** on any Sunday match (all <5% vs DK/ESPN odds).
  Near-resolution is the ONLY strategy. Buy teams surging at 75th+ minute.

### Sunday March 16 — CORRECTED (previous sessions had wrong results!)
- Europe near-res: **Las Palmas LOST** (-$23.48), **Brentford LOST** (-$15.03), Annecy lost.
- O'Higgins: game was 0-0 draw but monitor bought at 0.64 (wrong signal), sold at 0.01 (-$9.47).
- Oscar positions: resolved (check actual results).
- **Lesson: MIN_NEAR_RES_PRICE was 0.62 — WAY too low. A 0.62 price means 38% chance of losing.**
- **Fixed: raised to 0.80 for CL, 0.78 for NBA. Added spread check and tighter time window.**
- **Campaign: $100 → $69.17 (-30.8%)**

### Monday March 17 — CL + NBA (HIGH PRIORITY)

**Portfolio**: $69.17 cash, NO pending positions. **Must recover.**

#### SESSION ACTIONS BY TIME (UTC):
**09:00 UTC (= 12:00 GMT+3 cron)** — CHECK TELEGRAM + BTC SETUP:
```bash
cd /home/cctrd/cc-trader-agent
python3 -c "from trader.telegram_io import check_user_commands; print(check_user_commands())"
```
Check for user messages via Telegram. Review any instructions.

**13:00 UTC (= 16:00 GMT+3 cron)** — LAUNCH BTC NEAR-RES:
```bash
cd /home/cctrd/cc-trader-agent
bash launch_cl_mar17.sh btc
```
BTC threshold markets resolve at 16:00 UTC. Monitor starts 3h before.

**15:00 UTC (= 18:00 GMT+3 cron)** — LAUNCH CL EARLY:
```bash
cd /home/cctrd/cc-trader-agent
bash launch_cl_mar17.sh early
```
Captures Sporting vs Bodo/Glimt pre-game prices (17:45 kickoff).

**18:00 UTC (= 21:00 GMT+3 cron)** — LAUNCH CL MAIN + NBA:
```bash
cd /home/cctrd/cc-trader-agent
bash launch_cl_mar17.sh all
```
Launches CL main (3 matches + 3 draw markets + Sporting draw, 20:00 kickoff), NBA (8 games).

**21:00 UTC (= 00:00 GMT+3 cron)** — CHECK CL + WBC + NBA STATUS:
```bash
tail -30 logs/cl_early_*.log logs/cl_main_*.log logs/nba_mar17_*.log
```
CL main matches near-res window. WBC final underway.

**23:00 UTC (= 02:00 GMT+3 cron)** — NBA NEAR-RES WINDOW:
- Heat/Hornets + Pistons/Wizards + Thunder/Magic near-res (~22:00-23:00 UTC)
- Pacers/Knicks near-res (~22:30-23:30 UTC)
- WBC final near-res (~22:00-23:30 UTC)
- Suns/TWolves + Cavs/Bucks near-res (~23:00-00:00 UTC)
- Check all monitor logs

**01:00 UTC Mar 18 (= 04:00 GMT+3 cron)** — LATE NBA CHECK:
- Spurs/Kings + 76ers/Nuggets near-res window (~01:00-02:00 UTC)
- Check if NBA monitor is still running, review results

#### CL Aggregate Context (CRITICAL for near-res decisions):
- **Arsenal vs Leverkusen**: TIED on aggregate → match winner advances. **TOP TARGET**.
- **Man City vs Real Madrid**: RM leads 3-0 → City desperate, volatile. $1.58M vol.
- **Chelsea vs PSG**: PSG leads 5-2 → comfortable. Lower opportunity.
- **Sporting vs Bodø/Glimt**: BG leads 3-0 → Sporting at home.

#### NBA Monday (8 games) + WBC Final:
- Extra-early (end 23:00-23:30): Heat vs Hornets ($293K), Pistons vs Wizards ($131K), Thunder vs Magic ($86K), Pacers vs Knicks ($137K)
- Early (~21:30 UTC tipoff): Suns vs T-Wolves ($66K), Cavs vs Bucks ($47K)
- Late (~23:30 UTC tipoff): Spurs vs Kings ($45K), 76ers vs Nuggets ($51K)
- WBC Final: USA vs Venezuela ($1M+, end 23:55 UTC) — Dynamic MMs confirmed
- Script: `near_res_nba_mar17.py` (all 18 token IDs verified — 8 NBA + WBC)

### Learnings from Sessions 48-55
- **Near-res is the ONLY reliable edge source** — compound via repeated near-res plays.
- **Near-res win rate ~75%** (3/4 on Europe session). Losses come from draws/equalizers in lower-tier leagues.
- **NEVER sell on illiquid markets via CLOB** — Chilean league O'Higgins sold at $0.01 (resting bids are garbage). ALWAYS wait for settlement on illiquid markets.
- **Pre-game sports markets are efficiently priced at CLOB level** — only near-res or confirmed >5% edge.
- **KHL/NHL/ISL markets untradeable** — static orderbooks, no dynamic MMs.
- **Lower-tier leagues (Ligue 2) have higher draw risk** — consider higher min_price_jump.

## User feedback (Session 58)
- Las Palmas and Brentford did NOT win — previous sessions had incorrect results
- O'Higgins was a 0-0 draw — monitor incorrectly bought at 0.64 based on false price signal
- **ACTION TAKEN**: Fixed near-res parameters (min price 0.80, spread check, tighter time window)
- Previous sessions falsely claimed $125 portfolio — actual is $69.17
## User feedback
Think about other markets and strategies
Use telegram for asking and getting info from user instead of the current useless notifications. You can also send summary of the last session there

### Session 69 (March 18 03:00 UTC)

**Portfolio**: $21.01 cash + Wellington weather positions (resolve 12:00 UTC)
- T-Wolves sold @ 0.999: +$0.75
- All March 17 monitors killed. No running processes.
- **Campaign**: $100 → $21 (-79%, day 7). Need 47.6x in 23 days.

### Near-Res Strategy Analysis (CRITICAL)
**Near-res is marginally profitable at best.** Full analysis:
- Overall: 12W/12L (50% WR). Net P&L: -$67 on $170 deployed.
- At >=0.80 entry: 4W/3L (57% WR). But avg win=$0.91, avg loss=$9.88. **NEGATIVE EV.**
- Need 83%+ WR at 0.82 entry just to break even (win +20% vs lose -100%).
- **TIGHTENED params for Mar 18**: MIN_PRICE=0.85, MAX_MINS=15, MAX_SPREAD=0.04, JUMP=0.22
- This means: only very decisive leads in last 15 minutes. Fewer trades but higher WR.
- **Also look for pre-game edge** (DraftKings comparison) on CL matches.

### Tuesday March 18 — ACTION PLAN

**Monitors**: `near_res_mar18.py` (TIGHTENED: MIN_PRICE=0.85, 15min, spread 0.04)

#### Session Actions (UTC):
**09:00 UTC (= 12:00 GMT+3)**: Check weather settlements, balance, Telegram.

**13:00 UTC (= 16:00 GMT+3)**: LAUNCH MONITOR + RESEARCH
```bash
cd /home/cctrd/cc-trader-agent
nohup python3 -u near_res_mar18.py > logs/mar18_$(date -u +%Y%m%d_%H%M).log 2>&1 &
```
- Research Barca-Newcastle CL aggregate context
- Check DraftKings odds for Barca, Tottenham, Liverpool, Bayern pre-game edge
- Find NBA Nuggets-Grizzlies token IDs if market exists

**15:00 UTC (= 18:00 GMT+3)**: Braga near-res window (~16:45-17:15). Check `tail -30 logs/mar18_*.log`

**16:00 UTC (= 19:00 GMT+3)**: Barca kickoff (17:45). Check Braga results.

**18:00 UTC (= 21:00 GMT+3)**: Barca near-res window (~19:00-19:30). Serie B.

**21:00 UTC (= 00:00 GMT+3)**: CL main near-res window (~21:15-21:45). Brazilian league.

**23:00 UTC (= 02:00 GMT+3)**: LAUNCH NBA MONITOR.
```bash
cd /home/cctrd/cc-trader-agent
nohup python3 -u near_res_nba_mar18.py > logs/nba_mar18_$(date -u +%Y%m%d_%H%M).log 2>&1 &
```
6 NBA games. Near-res windows: 01:00-02:30 UTC March 19.

**01:00 UTC Mar 19 (= 04:00 GMT+3)**: NBA near-res window. Check logs.

#### Key Games:
1. **Barca vs Newcastle (CL)** — 17:45 UTC, $754K vol, Camp Nou
2. **Tottenham vs Atletico Madrid (CL)** — 20:00 UTC, $424K vol
3. **Liverpool vs Galatasaray (CL)** — 20:00 UTC, $560K vol
4. **Bayern vs Atalanta (CL)** — 20:00 UTC, $341K vol
5. **Braga vs Ferencvaros (EL)** — 15:30 UTC, $107K vol
6. **Serie B**: Frosinone-Bari 18:00, Carrarese-Sampdoria 19:00
7. **Brazilian Serie A**: 3 games at 22:00 UTC
8. **NBA (6 games)**: Warriors/Celtics, Thunder/Nets, Blazers/Pacers + 3 more. Tipoffs 23:00-00:00 UTC.

### Critical Learnings (updated Session 69)
- **Near-res is NEGATIVE EV at current parameters**. Win rate must exceed 83% at 0.82 entry. Raised to 0.85 minimum.
- **Last 15 minutes only**: More time = more chances for equalizer. Cut from 30→15 min.
- **MONITORS MUST RUN LONG ENOUGH**: 12h runtime in near_res_mar18.py (fixed).
- **Lower-tier leagues (Serie B, Ligue 2, Argentine) are draw traps**: 4 of 12 losses were draws.
- **Non-sports markets efficiently priced**: Fed, BoE, ECB, BTC all fair. Only found edge on Oscars-type events.
- **Pre-game DraftKings comparison is the best edge source**: MBJ Oscar play had 9%+ edge.
