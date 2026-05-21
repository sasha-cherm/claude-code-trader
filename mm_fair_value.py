"""
Fair value engine for BTC 15-min candle prediction.

Uses two statistically-proven signals from 12-month Binance backtest:
  1. Streak mean reversion (primary) — strongest single signal
  2. Binance RSI zone (secondary) — confirmation/modifier

Also detects if the current (in-progress) candle is effectively resolved
(one side at 95%+ with <5 min remaining), extending the streak for
the next candle's fair value.
"""

import json
import math
import time

import requests

from mm_config import _get_gamma, utcnow, TICK


# ─── Streak Fair Value Table ────────────────────────────────────────────────
# Source: 12-month Binance backtest ~35,040 candles (btc_candle_predictor.py --streaks)
# Key: (streak_count, streak_color) → P(next candle is UP/GREEN)
# Only streaks with 900+ samples included. Streaks 5+ lack sufficient evidence
# and fall back to 0.50 via the dict default.

STREAK_PROB_UP = {
    (1, "UP"):  0.489,   # 9,131 samples → 48.9%
    (2, "UP"):  0.484,   # 4,469 samples → 48.4%
    (3, "UP"):  0.455,   # 2,163 samples → 45.5%
    (4, "UP"):  0.458,   #   985 samples → 45.8%
    (1, "DN"):  0.508,   # 9,132 samples → 50.8%
    (2, "DN"):  0.530,   # 4,496 samples → 53.0%
    (3, "DN"):  0.537,   # 2,111 samples → 53.7%
    (4, "DN"):  0.545,   #   978 samples → 54.5%
}


# ─── RSI Adjustment ────────────────────────────────────────────────────────
# Source: 12-month Binance backtest ~35,040 candles (btc_candle_predictor.py --rsi)
# Zones with <900 samples (>80 RSI, n=884) are set to 0.00 — insufficient evidence.

RSI_ADJUSTMENTS = [
    # (rsi_lower, rsi_upper, adjustment_to_prob_up)
    (0,  20, +0.023),   #    953 samples → 52.3%  oversold
    (20, 30, +0.033),   #  2,637 samples → 53.3%  oversold
    (30, 40, +0.033),   #  5,570 samples → 53.3%  mildly oversold
    (40, 60,  0.000),   # 16,238 samples → 50.0%  neutral
    (60, 70, -0.025),   #  5,980 samples → 47.5%  mildly overbought
    (70, 80, -0.039),   #  2,764 samples → 46.1%  overbought
    (80, 100,  0.000),  #    884 samples — below 900 threshold, no adjustment
]


def _rsi_adjustment(rsi):
    """Return probability adjustment for UP based on RSI zone."""
    if rsi is None:
        return 0.0
    for lo, hi, adj in RSI_ADJUSTMENTS:
        if lo <= rsi < hi:
            return adj
    return 0.0


# ─── Binance RSI ────────────────────────────────────────────────────────────

def fetch_binance_rsi(symbol="BTCUSDT", interval="15m", period=14, limit=50):
    """Fetch BTC 15-min candles from Binance and compute RSI(period)."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        closes = [float(d[4]) for d in data]

        if len(closes) < period + 1:
            return None

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]

        # Wilder smoothed averages
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)
    except Exception as e:
        print(f"[FV] Binance RSI error: {e}")
        return None


# ─── Current Candle Color Detection ─────────────────────────────────────────

def get_current_candle_color(client):
    """Check if the currently-running candle is effectively resolved.

    Returns "UP" or "DN" if one side has bid ≥ 0.95 and < 5 min remain.
    Returns None otherwise.
    """
    from mm_clob import get_book

    now_ts = int(utcnow().timestamp())
    current_start = (now_ts // 900) * 900
    current_end = current_start + 900
    time_left = current_end - now_ts

    if time_left > 300:
        return None  # more than 5 min left

    slug = f"btc-updown-15m-{current_start}"
    try:
        r = _get_gamma(f"/events/slug/{slug}")
        if r.status_code != 200:
            return None
        mkt = r.json().get("markets", [None])[0]
        if not mkt:
            return None

        tokens = json.loads(mkt.get("clobTokenIds", "[]"))
        outcomes = json.loads(mkt.get("outcomes", "[]"))
        if len(tokens) < 2 or len(outcomes) < 2:
            return None

        up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)
        dn_idx = 1 - up_idx

        # Check UP token price
        up_book = get_book(client, tokens[up_idx])
        if up_book and up_book.get("bids"):
            up_bid = float(up_book["bids"][0]["price"])
            if up_bid >= 0.95:
                print(f"[FV] Current candle effectively UP (bid={up_bid:.2f}, {time_left}s left)")
                return "UP"

        # Check DN token price
        dn_book = get_book(client, tokens[dn_idx])
        if dn_book and dn_book.get("bids"):
            dn_bid = float(dn_book["bids"][0]["price"])
            if dn_bid >= 0.95:
                print(f"[FV] Current candle effectively DN (bid={dn_bid:.2f}, {time_left}s left)")
                return "DN"

    except Exception as e:
        print(f"[FV] Current candle check error: {e}")

    return None


# ─── Fair Value Computation ─────────────────────────────────────────────────

def compute_fair_value(streak_count, streak_color, rsi=None):
    """Compute fair probability of next candle being UP.

    Returns (fair_up, fair_dn) where fair_up + fair_dn = 1.0.

    Args:
        streak_count: number of consecutive same-color candles (1+)
        streak_color: "UP" or "DN" (or None for no streak)
        rsi: Binance RSI(14) on 15-min timeframe, or None
    """
    if streak_count == 0 or streak_color is None or streak_color == "NONE":
        base = 0.50
    else:
        key = (streak_count, streak_color)
        base = STREAK_PROB_UP.get(key, 0.50)

    adj = _rsi_adjustment(rsi)
    fair_up = max(0.25, min(0.75, base + adj))
    fair_dn = round(1.0 - fair_up, 4)
    fair_up = round(fair_up, 4)

    return fair_up, fair_dn


def get_current_candle_up_prob(client):
    """Get market probability of current in-progress candle being UP.

    Uses the UP token's mid-price as the probability estimate.
    Returns float 0.0-1.0, or None if no data.
    """
    from mm_clob import get_book

    now_ts = int(utcnow().timestamp())
    current_start = (now_ts // 900) * 900
    slug = f"btc-updown-15m-{current_start}"

    try:
        r = _get_gamma(f"/events/slug/{slug}")
        if r.status_code != 200:
            return None
        mkt = r.json().get("markets", [None])[0]
        if not mkt:
            return None

        tokens = json.loads(mkt.get("clobTokenIds", "[]"))
        outcomes = json.loads(mkt.get("outcomes", "[]"))
        if len(tokens) < 2 or len(outcomes) < 2:
            return None

        up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)

        up_book = get_book(client, tokens[up_idx])
        if up_book:
            bids = up_book.get("bids", [])
            asks = up_book.get("asks", [])
            if bids and asks:
                return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            elif bids:
                return float(bids[0]["price"])
            elif asks:
                return float(asks[0]["price"])
    except Exception as e:
        print(f"[FV] Current candle prob error: {e}")

    return None


def compute_fair_value_weighted(base_streak_count, base_streak_color, current_up_prob, rsi=None):
    """Compute fair value weighted by current candle's uncertain outcome.

    Instead of binary streak detection, uses the market probability of the
    current in-progress candle to weight between streak-continues and
    streak-breaks scenarios.

    Args:
        base_streak_count: streak from resolved candles only (no current candle)
        base_streak_color: "UP", "DN", or "NONE"
        current_up_prob: market P(current candle = UP), 0.0-1.0, or None
        rsi: Binance RSI(14)

    Returns (fair_up, fair_dn)
    """
    if current_up_prob is None:
        return compute_fair_value(base_streak_count, base_streak_color, rsi)

    # Scenario A: current candle resolves UP
    if base_streak_color == "UP" and base_streak_count > 0:
        streak_a, color_a = base_streak_count + 1, "UP"
    else:
        streak_a, color_a = 1, "UP"

    # Scenario B: current candle resolves DN
    if base_streak_color == "DN" and base_streak_count > 0:
        streak_b, color_b = base_streak_count + 1, "DN"
    else:
        streak_b, color_b = 1, "DN"

    fair_up_a, _ = compute_fair_value(streak_a, color_a, rsi)
    fair_up_b, _ = compute_fair_value(streak_b, color_b, rsi)

    fair_up = round(current_up_prob * fair_up_a + (1.0 - current_up_prob) * fair_up_b, 4)
    fair_dn = round(1.0 - fair_up, 4)

    return fair_up, fair_dn
