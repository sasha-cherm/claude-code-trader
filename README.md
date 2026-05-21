# BTC 15-min Candle Market Maker — Live Bot

## Goal
Turn $100 USDC into $1000 USDC on Polymarket.  
Current balance: **$189.35** (as of 2026-05-14)

## Strategy
Maker-only limit BUY orders on both sides (UP + DN) of Polymarket BTC 15-min candle markets.  
Fair value is computed from two statistically-validated signals:
1. **Streak mean reversion** — after N same-color candles, what is P(next=UP)?
2. **RSI zone** — RSI(14) on Binance 15m data as a secondary modifier

Orders are placed below best ask (never crossing the spread). Unfilled orders are cancelled at candle start. Winning shares auto-redeem after settlement.

## Key Files

| File | Purpose |
|------|---------|
| `btc_15m_mm_live.py` | Main live trading bot (run continuously) |
| `mm_fair_value.py` | Fair value tables + computation logic — **edit this to update stats** |
| `mm_config.py` | Shared config: tick size, poll interval, order helpers |
| `mm_clob.py` | CLOB API wrappers: get_book, place_order, cancel, fill check |
| `mm_discovery.py` | Finds next unstarted candle slug via Gamma API |
| `mm_redeem.py` | Gas-free CTF redemption via Polymarket V2 relayer |
| `btc_candle_predictor.py` | Research script: fetches Binance data, runs streak/RSI analysis |
| `analyze_pnl.py` | Analyzes `logs/btc_15m_mm_live.jsonl` — PnL per streak group |
| `logs/btc_15m_mm_live.jsonl` | Trade log: every PLACE / BUY / CANCEL / RESULT action |

## Current Fair Value Statistics

Derived from **12-month Binance backtest (~35,040 candles, May 2025 – May 2026)**.  
Only entries with **900+ samples** are included. Streaks 5+ default to 50/50.

### Streak Table — P(next candle = UP/GREEN)

| Streak | Samples | P(UP) | Signal |
|--------|---------|-------|--------|
| 1x UP | 9,131 | **48.9%** | slight DN lean |
| 2x UP | 4,469 | **48.4%** | slight DN lean |
| 3x UP | 2,163 | **45.5%** | DN lean |
| 4x UP | 985 | **45.8%** | DN lean |
| 5x UP+ | <900 | 50.0% | no signal (insufficient data) |
| 1x DN | 9,132 | **50.8%** | slight UP lean |
| 2x DN | 4,496 | **53.0%** | UP lean |
| 3x DN | 2,111 | **53.7%** | UP lean |
| 4x DN | 978 | **54.5%** | UP lean |
| 5x DN+ | <900 | 50.0% | no signal (insufficient data) |

### RSI Adjustment — additive modifier on P(UP)

| RSI Zone | Samples | Actual P(UP) | Adjustment |
|----------|---------|-------------|------------|
| < 20 | 953 | 52.3% | **+0.023** |
| 20–30 | 2,637 | 53.3% | **+0.033** |
| 30–40 | 5,570 | 53.3% | **+0.033** |
| 40–60 | 16,238 | 50.0% | 0.000 |
| 60–70 | 5,980 | 47.5% | **−0.025** |
| 70–80 | 2,764 | 46.1% | **−0.039** |
| > 80 | 884 | 45.1% | 0.000 (below 900 threshold) |

## Live Trading Performance by Streak Group

Resolved from `logs/btc_15m_mm_live.jsonl` via Gamma API (as of 2026-05-14).  
2,713 BUYs across 2,396 unique candles. Total realized PnL: **+$68.72**

| Streak | BUYs | Win% | Avg Buy Px | Total PnL | Edge/share | Note |
|--------|------|------|-----------|-----------|------------|------|
| 1x UP | 728 | 48.5% | 0.478 | +$47.44 | +0.007 | workhorse |
| 1x DN | 745 | 48.2% | 0.481 | −$15.33 | ~flat | |
| 2x UP | 374 | 48.9% | 0.471 | +$0.68 | +0.018 | |
| 2x DN | 246 | 49.2% | 0.508 | **−$48.13** | −0.016 | was overbidding UP at 56.5¢ (old table: 57.5%) |
| 3x UP | 184 | 46.2% | 0.461 | −$12.94 | +0.001 | |
| 3x DN | 171 | 54.4% | 0.464 | **+$84.45** | +0.080 | strongest signal |
| 4x UP | 50 | 52.0% | 0.547 | −$1.89 | −0.027 | was overbidding DN (old table: 35.7%) |
| 4x DN | 91 | 47.8% | 0.458 | +$20.63 | +0.020 | |

*Stats updated 2026-05-14. The 2xDN and 4xUP losses were caused by stale fair values — fixed in this session.*

## How to Update the Statistics

### Step 1 — Re-run the backtest

```bash
python3 btc_candle_predictor.py --streaks --rsi
```

This fetches fresh Binance data and prints streak + RSI zone tables.  
To use a longer window (recommended: 12 months):

```bash
python3 - << 'EOF'
from btc_candle_predictor import fetch_extended_history, compute_features
df = fetch_extended_history(num_candles=35040)   # ~12 months of 15m candles
feat = compute_features(df)
# Then call analyze_streaks(feat) and analyze_rsi_zones(feat)
EOF
```

### Step 2 — Apply the 900-sample rule

Only update a streak/RSI entry if it has **≥ 900 samples** in the backtest.  
Entries below this threshold are too noisy — leave them at 50/50 (streaks) or 0.00 (RSI).

### Step 3 — Edit `mm_fair_value.py`

Update `STREAK_PROB_UP` dict and `RSI_ADJUSTMENTS` list with the new values.  
Also update the sample counts in the comments.

### Step 4 — Re-run live PnL analysis

```bash
python3 analyze_pnl.py
```

For streak-level breakdown (requires Gamma API calls, takes ~5 min):

```bash
python3 - << 'EOF'
# paste the inline analysis script from session notes
EOF
```

### Step 5 — Restart the bot

```bash
# The bot self-kills old instances on startup
nohup python3 -u btc_15m_mm_live.py > logs/btc_15m_mm_live_$(date -u +%Y%m%d_%H%M).log 2>&1 &
```

## Launch / Monitor

```bash
# Check if running
ps aux | grep btc_15m_mm_live | grep -v grep

# Watch live log
tail -f logs/$(ls -t logs/btc_15m_mm_live_*.log | head -1 | xargs basename)

# Check USDC balance
python3 -c "from trader.client import get_client, get_usdc_balance; print(get_usdc_balance(get_client()))"

# Check recent trades
tail -20 logs/btc_15m_mm_live.jsonl | python3 -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"
```
