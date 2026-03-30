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

## Current Strategy: BTC 15-min Candle Market Making (March 30+)

**ALL previous strategies (near-res sports, directional BTC candles) are RETIRED.**
The ONLY active strategy is market-making on BTC 15-min Up/Down candles.

### How it works
- Script: `btc_15m_mm.py` (runs continuously in background)
- Finds next unstarted 15-min BTC candle via Gamma API slug `btc-updown-15m-{unix_ts}`
- Places BUY 5sh on Up token at best_bid AND BUY 5sh on Down token at (1 - best_ask)
- If spread > 2 ticks, improves by 1 tick each side
- Polls orderbook every 1 second, adjusts orders to follow the book
- If one leg fills at price X, the other leg can't cost more than (1-X) to guarantee profit
- Partial fills: don't touch remaining if < 5 shares (CLOB minimum)
- 5 seconds before candle starts: cancel unfilled / market-buy missing leg / lock profit
- If both legs fill: profit = (1 - up_cost - down_cost) × shares (guaranteed on resolution)
- Winning shares auto-redeem after settlement

### Key details
- Min order: 5 shares. Order size: 5 shares per leg.
- Typical profit per candle: $0.05 (1 cent spread × 5 shares)
- 96 candles per day = up to ~$4.80/day theoretical max (if all fill)
- Trade log: `logs/btc_15m_mm_trades.jsonl`
- Launch: `nohup python3 -u btc_15m_mm.py > logs/btc_15m_mm_$(date -u +%Y%m%d_%H%M).log 2>&1 &`

### Session workflow
1. Check if `btc_15m_mm.py` is running: `ps aux | grep btc_15m_mm`
2. Check logs: `tail -30 logs/btc_15m_mm_*.log`
3. Check trade log: `tail -5 logs/btc_15m_mm_trades.jsonl`
4. Check balance: `python3 -c "from trader.client import get_client, get_usdc_balance; print(get_usdc_balance(get_client()))"`
5. If not running, relaunch it
6. Write session notes, push to git

### Historical Context (strategies retired March 30)
- Near-res sports, directional BTC candles, weather MM — all retired
- Campaign: $100 → $15.86 over 20 days. New strategy: BTC 15m MM for steady income.

### User feedback
Think about other markets and strategies
Use telegram for asking and getting info from user instead of the current useless notifications. You can also send summary of the last session there

### Key Technical Details
- Polymarket CLOB: can't SELL tokens you don't hold. For two-sided MM, BUY Up + BUY Down.
- Slug pattern: `btc-updown-15m-{unix_timestamp_of_candle_start_utc}`
- Markets created ~15 min before candle starts. Prices near 50/50 pre-candle.
- Min order: 5 shares. Tick: $0.01.
- Winning shares auto-redeem after settlement.
- Commissions started March 30 — use maker (GTC limit) orders.
