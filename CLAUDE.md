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

### Sunday March 16 (COMPLETED/IN PROGRESS)
- ~~Oscar ceremony + settlement. All 3 won. Balance $117.41. DONE.~~
- ~~13:00 UTC: KHL/ISL — no signals (illiquid/static). DONE.~~
- ~~15:00 UTC: Confirmed no pre-game edge on NBA/CL at CLOB execution prices. DONE.~~
- **`--mid` monitor RUNNING** (PID 265546) — Danish + Argentine near-res
- **Europe + South monitors AUTO-START at 18:00 UTC** (scheduler PID 265920)
- **NBA monitor AUTO-STARTS at 01:00 UTC Mar 17** (scheduler PID 265938)
- **21:00 UTC**: Check results from all monitors.

### Monday March 17 — CL NEAR-RES (HIGH PRIORITY)
- **CL script READY**: `near_res_cl_mar17.py` created with all token IDs
  - `--early`: Sporting vs Bodø/Glimt (17:45 UTC kickoff, near-res 19:00-19:30)
  - default: Man City vs RM + Chelsea vs PSG + Arsenal vs Leverkusen (20:00 kickoff, near-res 21:15-21:45)
- **CL Aggregate Context** (critical for near-res):
  - Arsenal vs Leverkusen: **TIED on aggregate** → match winner likely advances. Most decisive tie.
  - Man City vs Real Madrid: RM leads 3-0 → City needs 4+ goals. Desperate attacking play = volatile prices. $820K volume.
  - Chelsea vs PSG: PSG leads 5-2 → comfortable. Lower near-res opportunity.
  - Sporting vs Bodø/Glimt: BG leads 3-0 → Sporting at home fighting back.
- **18:00 UTC Mar 17**: START `python3 -u near_res_cl_mar17.py --early > logs/cl_early.log 2>&1 &`
- **21:00 UTC Mar 17**: START `python3 -u near_res_cl_mar17.py > logs/cl_main.log 2>&1 &`
- Also check for NBA Monday games and other soccer opportunities.

### Learnings from Sessions 48-49
- **Pre-game sports markets are efficiently priced at CLOB level** — Gamma display shows fake edge, CLOB execution matches Vegas within 1-2%. Only trade near-res or confirmed >5% edge at CLOB.
- **KHL/NHL/ISL markets are untradeable** — static orderbooks, no dynamic MMs. Skip.
- **Near-res is the ONLY reliable edge source** — compound via repeated near-res plays.

