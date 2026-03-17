#!/usr/bin/env python3
"""BTC near-resolution monitor.

Watches BTC daily threshold markets (e.g., "Will BTC be above $74K on March 17?")
and buys YES/NO when BTC price is clearly on one side of the strike close to resolution.

Strategy:
- Markets resolve at 16:00 UTC daily
- If BTC is >2% above a strike with <3h to resolution, buy YES
- If BTC is >2% below a strike with <3h to resolution, buy NO
- The further from the strike and closer to resolution, the higher the edge

Usage:
    python3 near_res_btc.py              # Run once (check and trade)
    python3 near_res_btc.py --monitor    # Poll every 5 min until 16:00 UTC
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from math import floor, exp, log, sqrt

import requests
from scipy.stats import norm  # for CDF

# Add project root
sys.path.insert(0, os.path.dirname(__file__))

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

# --- CONFIG ---
MAX_SPEND_PER_TRADE = 12.0    # Max USDC per BTC trade
MIN_SPEND = 3.0               # Skip if balance too low
MAX_BALANCE_PCT = 0.15         # Max 15% of balance per BTC trade
MIN_EDGE = 0.05                # 5% minimum edge
MAX_SPREAD = 0.05              # Tighter spread for BTC (liquid markets)
MAX_HOURS_TO_RES = 3.0         # Only trade within 3 hours of resolution
BTC_HOURLY_VOL = 0.011         # ~1.1% hourly volatility (realized)
POLL_INTERVAL_SEC = 300        # 5 minutes between checks
BOUGHT = set()                 # Track what we've bought this session


def get_btc_price() -> float:
    """Get current BTC price from CoinGecko."""
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bitcoin", "vs_currencies": "usd"},
        timeout=10,
    )
    return r.json()["bitcoin"]["usd"]


def calc_prob_above(current_price: float, strike: float, hours_left: float) -> float:
    """Calculate probability BTC stays above strike using geometric Brownian motion.

    Uses log-normal model with no drift (conservative).
    """
    if hours_left <= 0:
        return 1.0 if current_price > strike else 0.0
    if current_price <= 0 or strike <= 0:
        return 0.5

    sigma = BTC_HOURLY_VOL * sqrt(hours_left)
    # P(S_T > K) = Phi(d2) where d2 = (ln(S/K) - 0.5*σ²) / σ  (zero drift)
    d2 = (log(current_price / strike) - 0.5 * sigma**2) / sigma
    return norm.cdf(d2)


def find_btc_threshold_markets() -> list[dict]:
    """Find active BTC threshold markets resolving today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "ascending": "false",
        "limit": 200,
    }
    r = requests.get(url, params=params, timeout=15)
    markets = r.json()

    btc_markets = []
    for m in markets:
        q = m.get("question", "").lower()
        end = m.get("endDate", "")[:10]
        if end != today:
            continue
        if "bitcoin" not in q and "btc" not in q:
            continue
        if "above" not in q:
            continue  # Only threshold markets

        # Parse strike price from question like "above $74,000"
        import re
        match = re.search(r'\$(\d[\d,]*)', m.get("question", ""))
        if not match:
            continue
        strike = float(match.group(1).replace(",", ""))

        prices = json.loads(m.get("outcomePrices", "[]") or "[]")
        tokens = json.loads(m.get("clobTokenIds", "[]") or "[]")
        if len(prices) < 2 or len(tokens) < 2:
            continue

        yes_price = float(prices[0])
        no_price = float(prices[1])

        btc_markets.append({
            "question": m["question"],
            "strike": strike,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_token": tokens[0],
            "no_token": tokens[1],
            "end_date": m.get("endDate", ""),
            "volume": float(m.get("volume24hr", 0) or 0),
            "best_bid": m.get("bestBid"),
            "best_ask": m.get("bestAsk"),
        })

    return sorted(btc_markets, key=lambda x: x["strike"])


def evaluate_and_trade(client, markets: list[dict], btc_price: float):
    """Evaluate all BTC threshold markets and trade where we find edge."""
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = get_usdc_balance(client)

    print(f"\n[{now.strftime('%H:%M')} UTC] BTC: ${btc_price:,.0f} | Balance: ${balance:.2f}")

    for m in markets:
        # Parse resolution time
        end_str = m["end_date"]
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        hours_left = (end_dt - now).total_seconds() / 3600
        if hours_left < 0.1:
            continue

        strike = m["strike"]
        true_prob = calc_prob_above(btc_price, strike, hours_left)
        yes_price = m["yes_price"]
        no_price = m["no_price"]

        # Check YES side (BTC above strike)
        yes_edge = true_prob - yes_price
        no_edge = (1 - true_prob) - no_price

        side = None
        edge = 0
        token_id = None
        price = 0

        if yes_edge >= MIN_EDGE and yes_price < 0.95 and yes_price > 0.05:
            side = "YES"
            edge = yes_edge
            token_id = m["yes_token"]
            price = yes_price
        elif no_edge >= MIN_EDGE and no_price < 0.95 and no_price > 0.05:
            side = "NO"
            edge = no_edge
            token_id = m["no_token"]
            price = no_price

        status = f"  ${strike:,.0f}: P(above)={true_prob:.1%} vs YES={yes_price:.3f} | edge_Y={yes_edge:+.1%} edge_N={no_edge:+.1%}"
        if side:
            status += f" → {side} ✓"
        print(status)

        if not side or token_id in BOUGHT:
            continue

        if hours_left > MAX_HOURS_TO_RES:
            print(f"    Not yet: {hours_left:.1f}h > {MAX_HOURS_TO_RES}h window")
            continue

        # Check spread
        try:
            raw_book = client.get_order_book(token_id)
            book = orderbook_to_dict(raw_book)
            asks = book.get("asks", [])
            bids = book.get("bids", [])
            if asks and bids:
                spread = float(asks[0]["price"]) - float(bids[0]["price"])
                if spread > MAX_SPREAD:
                    print(f"    Skip: spread {spread:.3f} > {MAX_SPREAD}")
                    continue
        except Exception as e:
            print(f"    Skip: orderbook error: {e}")
            continue

        # Size the trade
        spend = min(MAX_SPEND_PER_TRADE, balance * MAX_BALANCE_PCT)
        if spend < MIN_SPEND:
            print(f"    Skip: insufficient balance (${balance:.2f})")
            continue

        # Place the trade
        print(f"    → BUY {side} @ {price:.3f}, ${spend:.2f}, edge={edge:.1%}, {hours_left:.1f}h left")
        resp = place_market_buy(client, token_id, spend)
        if resp:
            BOUGHT.add(token_id)
            # Get actual shares
            time.sleep(2)
            shares = get_actual_shares(client, token_id)

            pos = {
                "token_id": token_id,
                "market_id": f"btc-near-res-{int(strike/1000)}k",
                "question": m["question"],
                "side": side,
                "entry_price": price,
                "fair_price": true_prob if side == "YES" else 1 - true_prob,
                "edge": round(edge, 4),
                "size_usdc": spend,
                "shares": shares if shares > 0 else spend / price,
                "end_date": m["end_date"],
                "days_left_at_entry": hours_left / 24,
                "opened_at": str(now),
                "research_note": f"BTC ${btc_price:,.0f}, strike ${strike:,.0f}, {hours_left:.1f}h to res. P(above)={true_prob:.1%}, PM={yes_price:.3f}",
            }
            state["positions"].append(pos)
            save_state(state)
            balance = get_usdc_balance(client)

            send(
                f"🟡 BTC NEAR-RES: {side} '{m['question'][:50]}'\n"
                f"  ${spend:.2f} @ {price:.3f} ({shares:.2f} shares)\n"
                f"  BTC=${btc_price:,.0f}, P(above)={true_prob:.1%}, edge={edge:.1%}\n"
                f"  {hours_left:.1f}h to resolution"
            )
            print(f"    ✓ Bought! Shares: {shares:.2f}")
        else:
            print(f"    ✗ Order failed")


def main():
    parser = argparse.ArgumentParser(description="BTC near-resolution monitor")
    parser.add_argument("--monitor", action="store_true", help="Poll until resolution")
    args = parser.parse_args()

    client = get_client()
    print("BTC Near-Resolution Monitor")
    print("=" * 50)

    if args.monitor:
        print(f"Monitoring mode: checking every {POLL_INTERVAL_SEC}s until 16:00 UTC")
        while True:
            now = datetime.now(timezone.utc)
            # Stop after resolution time (16:05 UTC buffer)
            if now.hour >= 16 and now.minute >= 5:
                print("Past resolution time. Exiting.")
                break

            try:
                btc_price = get_btc_price()
                markets = find_btc_threshold_markets()
                if markets:
                    evaluate_and_trade(client, markets, btc_price)
                else:
                    print(f"[{now.strftime('%H:%M')}] No BTC threshold markets found for today")
            except Exception as e:
                print(f"[ERROR] {e}")

            time.sleep(POLL_INTERVAL_SEC)
    else:
        btc_price = get_btc_price()
        markets = find_btc_threshold_markets()
        print(f"\nFound {len(markets)} BTC threshold markets for today")
        if markets:
            evaluate_and_trade(client, markets, btc_price)
        else:
            print("No markets found")


if __name__ == "__main__":
    main()
