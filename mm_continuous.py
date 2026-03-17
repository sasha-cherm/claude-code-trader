#!/usr/bin/env python3
"""
Continuous Market Maker for Polymarket Weather Markets.

Differs from market_maker.py:
- Continuously monitors and adjusts orders (not fire-and-forget)
- Dynamically discovers weather markets via Gamma API
- Verifies fills on-chain before counting them
- Re-quotes after fills
- Adjusts orders when market moves >2c from ideal

Usage:
    python3 mm_continuous.py                 # Default $10 budget, Mar 18 markets
    python3 mm_continuous.py --budget 15     # Custom budget
    python3 mm_continuous.py --dry-run       # Print without placing
"""
import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from math import floor, sqrt, erf

import requests

sys.path.insert(0, os.path.dirname(__file__))

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.strategy import get_actual_shares
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

# --- Config ---
POLL_INTERVAL = 60          # seconds between adjustment cycles
SPREAD_HALF = 0.03          # ±3 cents from fair value
REQUOTE_THRESHOLD = 0.02    # re-quote if order is >2c from ideal
MIN_SHARES = 5.0            # CLOB minimum
MAX_PER_MARKET = 4.0        # Max $4 per side per market
MIN_FAIR = 0.06             # Don't quote below 6% probability
MAX_FAIR = 0.94             # Don't quote above 94%
CANCEL_BEFORE_HOURS = 3     # Cancel orders 3h before resolution
SIGMA = 1.5                 # Temperature forecast std dev (°C)
STATE_FILE = "mm_continuous_state.json"

running = True


def signal_handler(sig, frame):
    global running
    print(f"\n[CMM] Signal {sig}, shutting down...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def normal_cdf(x, mu=0, sigma=1):
    return 0.5 * (1 + erf((x - mu) / (sigma * sqrt(2))))


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"orders": {}, "positions": {}, "fills": [], "pnl": 0.0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# --- Market Discovery ---

def discover_weather_markets(target_date: str) -> list[dict]:
    """Find weather markets for a specific date via Gamma API slug lookup.

    Slug format: highest-temperature-in-{city}-on-{month}-{day}-{year}-{temp}c
    Returns list of dicts with: question, token_yes, token_no, city, temp_bucket, end_date.
    """
    import re

    # City -> temperature range to scan
    CITIES = {
        "wellington": range(15, 25),
        "london": range(10, 22),
        "singapore": range(28, 37),
        "tokyo": range(10, 22),
        "seoul": range(5, 18),
        "shanghai": range(8, 20),
        "munich": range(3, 16),
        "warsaw": range(3, 16),
        "madrid": range(8, 22),
        "lucknow": range(26, 40),
        "sao-paulo": range(22, 36),
    }

    d = datetime.strptime(target_date, "%Y-%m-%d")
    month_name = d.strftime("%B").lower()
    day = d.day
    year = d.year
    date_part = f"{month_name}-{day}-{year}"

    url = "https://gamma-api.polymarket.com/markets"
    markets_out = []

    for city, temp_range in CITIES.items():
        for temp in temp_range:
            slug = f"highest-temperature-in-{city}-on-{date_part}-{temp}c"
            try:
                resp = requests.get(url, params={"slug": slug}, timeout=8)
                data = resp.json()
                if not data:
                    continue
                m = data[0] if isinstance(data, list) else data
                if m.get("closed"):
                    continue

                tokens = json.loads(m.get("clobTokenIds", "[]") or "[]")
                if len(tokens) < 2:
                    continue

                q = m.get("question", "")
                is_range = "or higher" in q or "or below" in q or "or above" in q

                markets_out.append({
                    "question": q,
                    "token_yes": tokens[0],
                    "token_no": tokens[1],
                    "city": city,
                    "bucket_temp": temp,
                    "is_range": is_range,
                    "end_date": m.get("endDate", ""),
                    "volume": float(m.get("volume24hr", 0) or 0),
                    "condition_id": m.get("conditionId", ""),
                })
            except Exception:
                continue

        time.sleep(0.1)  # Rate limiting between cities

    return markets_out


def get_forecast(city: str, target_date: str) -> float | None:
    """Get max temperature forecast from Open-Meteo."""
    coords = {
        "tokyo": (35.6762, 139.6503),
        "warsaw": (52.2297, 21.0122),
        "madrid": (40.4168, -3.7038),
        "munich": (48.1351, 11.582),
        "singapore": (1.3521, 103.8198),
        "lucknow": (26.8467, 80.9462),
        "sao-paulo": (-23.5505, -46.6333),
        "london": (51.5074, -0.1278),
        "wellington": (-41.2865, 174.7762),
        "shanghai": (31.2304, 121.4737),
        "seoul": (37.5665, 126.978),
        "miami": (25.7617, -80.1918),
        "chicago": (41.8781, -87.6298),
        "new-york": (40.7128, -74.006),
    }
    if city not in coords:
        return None

    lat, lon = coords[city]
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "daily": "temperature_2m_max",
            "timezone": "auto",
            "start_date": target_date, "end_date": target_date,
        }, timeout=10)
        data = resp.json()
        return data["daily"]["temperature_2m_max"][0]
    except Exception:
        return None


def calc_bucket_fair(forecast: float, bucket_temp: int | None, is_range: bool, question: str) -> float:
    """Calculate fair value for a temperature bucket."""
    if bucket_temp is None:
        return 0.5  # Can't price without temp

    if is_range:
        if "or higher" in question or "or above" in question:
            # P(T >= bucket_temp - 0.5)
            return 1 - normal_cdf(bucket_temp - 0.5, forecast, SIGMA)
        elif "or below" in question:
            # P(T <= bucket_temp + 0.5)
            return normal_cdf(bucket_temp + 0.5, forecast, SIGMA)

    # Exact bucket: P(bucket_temp - 0.5 <= T < bucket_temp + 0.5)
    p = normal_cdf(bucket_temp + 0.5, forecast, SIGMA) - normal_cdf(bucket_temp - 0.5, forecast, SIGMA)
    return max(0.005, min(0.995, p))


# --- Order Management ---

def place_gtc(client, token_id: str, price: float, shares: float, side) -> str | None:
    """Place GTC post-only order. Returns order ID or None."""
    price = round(price, 2)
    shares = floor(shares * 100) / 100.0

    if shares < MIN_SHARES or price < 0.01 or price > 0.99:
        return None

    try:
        args = OrderArgs(token_id=token_id, price=price, size=shares, side=side)
        signed = client.create_order(args)
        resp = client.post_order(signed, orderType=OrderType.GTC, post_only=True)
        return resp.get("orderID") or resp.get("id") or resp.get("order_id")
    except Exception as e:
        print(f"[CMM] Order fail ({side} {shares:.0f}sh @ {price:.2f}): {e}")
        return None


def cancel_order(client, order_id: str) -> bool:
    try:
        client.cancel(order_id)
        return True
    except Exception:
        return False


class ContinuousMM:
    def __init__(self, client, budget: float, target_dates: list[str], dry_run=False):
        self.client = client
        self.budget = budget
        self.target_dates = target_dates
        self.dry_run = dry_run
        self.state = load_state()
        self.markets = []       # discovered markets with fair values
        self.forecasts = {}     # city -> forecast temp
        self.cycle = 0

    def discover(self):
        """Find all weather markets for target dates and compute fair values."""
        all_markets = []
        for date in self.target_dates:
            mks = discover_weather_markets(date)
            all_markets.extend(mks)
        print(f"[CMM] Discovered {len(all_markets)} markets across {len(self.target_dates)} dates")

        # Get forecasts for each city
        cities_seen = set()
        for m in all_markets:
            city = m["city"]
            if city not in cities_seen:
                cities_seen.add(city)
                date = m["end_date"][:10]
                fc = get_forecast(city, date)
                if fc is not None:
                    self.forecasts[f"{city}_{date}"] = fc
                    print(f"[CMM] {city} ({date}): forecast {fc}°C")

        # Calculate fair values
        tradeable = []
        for m in all_markets:
            key = f"{m['city']}_{m['end_date'][:10]}"
            fc = self.forecasts.get(key)
            if fc is None:
                continue

            fair = calc_bucket_fair(fc, m["bucket_temp"], m["is_range"], m["question"])
            m["fair"] = round(fair, 4)

            if MIN_FAIR <= fair <= MAX_FAIR:
                tradeable.append(m)

        # Sort by volume (prefer liquid markets)
        tradeable.sort(key=lambda m: m["volume"], reverse=True)

        # Limit to top N markets by budget
        max_markets = max(3, int(self.budget / 2.0))
        self.markets = tradeable[:max_markets]
        print(f"[CMM] {len(self.markets)} tradeable markets selected")

        for m in self.markets:
            print(f"  {m['city']} {m.get('bucket_temp','')}°C: fair={m['fair']:.3f} vol=${m['volume']:.0f}")

    def get_ideal_prices(self, fair: float) -> tuple[float, float]:
        """Return (bid, ask) prices given fair value."""
        bid = round(max(0.01, fair - SPREAD_HALF), 2)
        ask = round(min(0.99, fair + SPREAD_HALF), 2)
        return bid, ask

    def manage_cycle(self):
        """One management cycle: check all orders, adjust as needed."""
        self.cycle += 1
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        balance = get_usdc_balance(self.client)

        # Check open orders from exchange
        try:
            open_orders = self.client.get_orders()
        except Exception as e:
            print(f"[CMM] get_orders error: {e}")
            return

        open_ids = {}
        if isinstance(open_orders, list):
            for o in open_orders:
                oid = o.get("id") or o.get("orderID")
                if oid:
                    open_ids[oid] = o

        # 1. Check for fills (orders disappeared)
        filled = []
        for oid in list(self.state["orders"].keys()):
            if oid not in open_ids:
                info = self.state["orders"][oid]
                # Verify fill on-chain
                tid = info["token_id"]
                shares = get_actual_shares(self.client, tid)
                if shares > 0:
                    print(f"[CMM] FILL VERIFIED: {info['label']} {info['side']} {info['size']:.0f}sh @ {info['price']:.2f} (on-chain: {shares:.2f}sh)")
                    self.state["positions"][tid] = {
                        "shares": shares,
                        "label": info["label"],
                        "entry_price": info["price"],
                        "filled_at": str(datetime.now(timezone.utc)),
                    }
                    self.state["fills"].append({**info, "verified_shares": shares, "filled_at": str(datetime.now(timezone.utc))})
                    filled.append(info)
                else:
                    print(f"[CMM] Order gone but 0 shares on-chain: {info['label']} (cancelled, not filled)")
                del self.state["orders"][oid]

        if filled:
            labels = ", ".join(f["label"] for f in filled)
            send(f"MM fill: {labels}")

        # 2. Check existing orders need re-quoting
        orders_adjusted = 0
        for oid, info in list(self.state["orders"].items()):
            if oid not in open_ids:
                continue  # Already handled above

            # Find the market for this order
            mkt = None
            for m in self.markets:
                if m["token_yes"] == info["token_id"] or m["token_no"] == info["token_id"]:
                    mkt = m
                    break

            if not mkt:
                continue

            fair = mkt["fair"]
            ideal_bid, ideal_ask = self.get_ideal_prices(fair)
            current_price = info["price"]

            if info["side"] == "BUY_YES":
                ideal = ideal_bid
            else:  # BUY_NO (= selling YES)
                ideal = round(1.0 - ideal_ask, 2)

            if abs(current_price - ideal) > REQUOTE_THRESHOLD:
                # Cancel and re-place
                if cancel_order(self.client, oid):
                    del self.state["orders"][oid]

                    new_shares = floor((MAX_PER_MARKET / ideal) * 100) / 100.0 if ideal > 0 else 0
                    new_oid = place_gtc(self.client, info["token_id"], ideal, max(MIN_SHARES, new_shares), BUY)
                    if new_oid:
                        self.state["orders"][new_oid] = {
                            "token_id": info["token_id"],
                            "label": info["label"],
                            "side": info["side"],
                            "price": ideal,
                            "size": max(MIN_SHARES, new_shares),
                            "fair": fair,
                            "placed_at": str(datetime.now(timezone.utc)),
                        }
                        orders_adjusted += 1
                        print(f"[CMM] Adjusted: {info['label']} {current_price:.2f} -> {ideal:.2f}")

        # 3. Place orders on markets with no quotes
        orders_placed = 0
        budget_used = sum(
            info["price"] * info["size"]
            for info in self.state["orders"].values()
        )
        budget_in_positions = sum(
            pos["entry_price"] * pos["shares"]
            for pos in self.state["positions"].values()
        )
        available = self.budget - budget_used - budget_in_positions

        for mkt in self.markets:
            if available < 1.0:
                break

            fair = mkt["fair"]
            bid_price, ask_price = self.get_ideal_prices(fair)
            yes_token = mkt["token_yes"]
            no_token = mkt["token_no"]
            label = f"{mkt['city']} {mkt.get('bucket_temp', '?')}°C"

            # Check if we already have orders on this market
            has_bid = any(
                info["token_id"] == yes_token and info["side"] == "BUY_YES"
                for info in self.state["orders"].values()
            )
            has_ask = any(
                info["token_id"] == no_token and info["side"] == "BUY_NO"
                for info in self.state["orders"].values()
            )

            if not has_bid and available >= bid_price * MIN_SHARES:
                spend = min(MAX_PER_MARKET, available * 0.5)
                shares = floor((spend / bid_price) * 100) / 100.0 if bid_price > 0 else 0
                shares = max(MIN_SHARES, shares)

                if self.dry_run:
                    print(f"  [DRY] BID {label}: {shares:.0f}sh @ {bid_price:.2f}")
                    orders_placed += 1
                else:
                    oid = place_gtc(self.client, yes_token, bid_price, shares, BUY)
                    if oid:
                        self.state["orders"][oid] = {
                            "token_id": yes_token, "label": label,
                            "side": "BUY_YES", "price": bid_price,
                            "size": shares, "fair": fair,
                            "placed_at": str(datetime.now(timezone.utc)),
                        }
                        available -= bid_price * shares
                        orders_placed += 1

            no_price = round(1.0 - ask_price, 2)
            if not has_ask and no_price >= 0.01 and available >= no_price * MIN_SHARES:
                spend = min(MAX_PER_MARKET, available * 0.5)
                shares = floor((spend / no_price) * 100) / 100.0 if no_price > 0 else 0
                shares = max(MIN_SHARES, shares)

                if self.dry_run:
                    print(f"  [DRY] ASK {label}: {shares:.0f}sh NO @ {no_price:.2f}")
                    orders_placed += 1
                else:
                    oid = place_gtc(self.client, no_token, no_price, shares, BUY)
                    if oid:
                        self.state["orders"][oid] = {
                            "token_id": no_token, "label": label,
                            "side": "BUY_NO", "price": no_price,
                            "size": shares, "fair": 1.0 - fair,
                            "placed_at": str(datetime.now(timezone.utc)),
                        }
                        available -= no_price * shares
                        orders_placed += 1

            time.sleep(0.3)

        # 4. Check time-to-resolution for any market nearing expiry
        for mkt in self.markets:
            try:
                end_dt = datetime.fromisoformat(mkt["end_date"].replace("Z", "+00:00"))
                hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_left < CANCEL_BEFORE_HOURS:
                    # Cancel orders on this market
                    for oid, info in list(self.state["orders"].items()):
                        if info["token_id"] in (mkt["token_yes"], mkt["token_no"]):
                            cancel_order(self.client, oid)
                            del self.state["orders"][oid]
                            print(f"[CMM] Cancelled {info['label']} ({hours_left:.1f}h to resolution)")
            except Exception:
                pass

        save_state(self.state)

        active = len(self.state["orders"])
        pos_count = len(self.state["positions"])
        if self.cycle % 5 == 1:  # Print summary every 5 cycles
            print(f"[CMM] {now_str} | cycle {self.cycle} | ${balance:.2f} | {active} orders | {pos_count} positions | +{orders_placed} new | ~{orders_adjusted} adjusted")

    def run(self):
        """Main loop."""
        print(f"[CMM] Continuous MM starting | budget=${self.budget:.0f} | dates={self.target_dates}")
        self.discover()

        if not self.markets:
            print("[CMM] No tradeable markets found")
            return

        # Initial order placement
        self.manage_cycle()

        if self.dry_run:
            print("[CMM] Dry run complete")
            return

        send(f"CMM started: {len(self.markets)} markets, ${self.budget:.0f} budget, {POLL_INTERVAL}s cycles")

        # Continuous loop
        while running:
            time.sleep(POLL_INTERVAL)
            if not running:
                break

            try:
                self.manage_cycle()
            except Exception as e:
                print(f"[CMM] Cycle error: {e}")
                import traceback
                traceback.print_exc()

            # Re-discover markets every 30 cycles (30 min)
            if self.cycle % 30 == 0:
                print("[CMM] Re-discovering markets...")
                self.discover()

        # Cleanup
        print("[CMM] Shutting down, cancelling orders...")
        for oid in list(self.state["orders"].keys()):
            cancel_order(self.client, oid)
            del self.state["orders"][oid]
        save_state(self.state)
        send("CMM stopped, all orders cancelled")
        print("[CMM] Done.")


def main():
    parser = argparse.ArgumentParser(description="Continuous Weather Market Maker")
    parser.add_argument("--budget", type=float, default=10.0, help="Total USDC budget")
    parser.add_argument("--dates", nargs="+", help="Target dates (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without placing")
    parser.add_argument("--spread", type=float, default=0.03, help="Half-spread (default 0.03)")
    args = parser.parse_args()

    global SPREAD_HALF
    SPREAD_HALF = args.spread

    if not args.dates:
        # Default: tomorrow and day after
        today = datetime.now(timezone.utc).date()
        args.dates = [
            (today + timedelta(days=1)).isoformat(),
            (today + timedelta(days=2)).isoformat(),
        ]

    client = get_client()
    balance = get_usdc_balance(client)
    print(f"[CMM] Balance: ${balance:.2f}")

    budget = min(args.budget, balance * 0.20)
    mm = ContinuousMM(client, budget, args.dates, dry_run=args.dry_run)
    mm.run()


if __name__ == "__main__":
    main()
