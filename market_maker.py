#!/usr/bin/env python3
"""
Market Maker Bot for Polymarket.

Places GTC limit orders on both sides of a market to capture the bid-ask spread.
Designed for thin markets (weather, crypto ranges) where we can provide informed liquidity.

Usage:
    python3 market_maker.py --config mm_config.json
    python3 market_maker.py --weather   # Auto-generate config from weather forecasts
"""
import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from math import floor, exp, sqrt, pi, erf

from trader.client import get_client, get_usdc_balance, orderbook_to_dict
from trader.notify import send
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

# --- Config ---
MM_STATE_FILE = "mm_state.json"
POLL_INTERVAL = 120       # seconds between order checks
SPREAD_HALFWIDTH = 0.04   # place orders ±4 cents from fair value
MIN_SHARES = 5.0          # CLOB minimum order size (shares)
MAX_ORDER_SIZE = 5.0      # maximum $5 per side per market
MIN_FAIR_VALUE = 0.05     # don't quote on < 5% probability buckets
MAX_FAIR_VALUE = 0.95     # don't quote on > 95% probability buckets
CANCEL_BEFORE_HOURS = 6   # cancel all orders N hours before resolution

running = True


def signal_handler(sig, frame):
    global running
    print(f"\n[MM] Signal {sig} received, shutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def load_mm_state():
    if os.path.exists(MM_STATE_FILE):
        with open(MM_STATE_FILE) as f:
            return json.load(f)
    return {"orders": {}, "fills": [], "pnl": 0.0}


def save_mm_state(state):
    with open(MM_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def normal_cdf(x, mu=0, sigma=1):
    """Standard normal CDF."""
    return 0.5 * (1 + erf((x - mu) / (sigma * sqrt(2))))


def calc_weather_probs(forecast_temp, sigma=2.0, buckets=None):
    """
    Calculate probability for each temperature bucket.
    buckets: list of (label, low_bound, high_bound) where bounds are °C.
    Returns dict of {label: probability}.
    """
    probs = {}
    for label, low, high in buckets:
        p = normal_cdf(high, forecast_temp, sigma) - normal_cdf(low, forecast_temp, sigma)
        probs[label] = max(0.001, min(0.999, p))
    return probs


def get_weather_config():
    """Generate MM config from weather forecasts for Mar 21."""
    import requests

    cities = {
        'Tokyo': {'lat': 35.6762, 'lon': 139.6503, 'unit': 'C',
                  'buckets': [('8°C or below', -50, 8.5), ('9°C', 8.5, 9.5), ('10°C', 9.5, 10.5),
                              ('11°C', 10.5, 11.5), ('12°C', 11.5, 12.5), ('13°C', 12.5, 13.5),
                              ('14°C', 13.5, 14.5), ('15°C', 14.5, 15.5), ('16°C', 15.5, 16.5),
                              ('17°C', 16.5, 17.5), ('18°C or higher', 17.5, 50)]},
        'Warsaw': {'lat': 52.2297, 'lon': 21.0122, 'unit': 'C',
                   'buckets': [('4°C or below', -50, 4.5), ('5°C', 4.5, 5.5), ('6°C', 5.5, 6.5),
                               ('7°C', 6.5, 7.5), ('8°C', 7.5, 8.5), ('9°C', 8.5, 9.5),
                               ('10°C', 9.5, 10.5), ('11°C', 10.5, 11.5), ('12°C', 11.5, 12.5),
                               ('13°C', 12.5, 13.5), ('14°C or higher', 13.5, 50)]},
        'Madrid': {'lat': 40.4168, 'lon': -3.7038, 'unit': 'C',
                   'buckets': [('10°C or below', -50, 10.5), ('11°C', 10.5, 11.5), ('12°C', 11.5, 12.5),
                               ('13°C', 12.5, 13.5), ('14°C', 13.5, 14.5), ('15°C', 14.5, 15.5),
                               ('16°C', 15.5, 16.5), ('17°C', 16.5, 17.5), ('18°C', 17.5, 18.5),
                               ('19°C', 18.5, 19.5), ('20°C or higher', 19.5, 50)]},
        'Munich': {'lat': 48.1351, 'lon': 11.5820, 'unit': 'C',
                   'buckets': [('5°C or below', -50, 5.5), ('6°C', 5.5, 6.5), ('7°C', 6.5, 7.5),
                               ('8°C', 7.5, 8.5), ('9°C', 8.5, 9.5), ('10°C', 9.5, 10.5),
                               ('11°C', 10.5, 11.5), ('12°C', 11.5, 12.5), ('13°C', 12.5, 13.5),
                               ('14°C', 13.5, 14.5), ('15°C or higher', 14.5, 50)]},
        'Singapore': {'lat': 1.3521, 'lon': 103.8198, 'unit': 'C',
                      'buckets': [('25°C or below', -50, 25.5), ('26°C', 25.5, 26.5), ('27°C', 26.5, 27.5),
                                  ('28°C', 27.5, 28.5), ('29°C', 28.5, 29.5), ('30°C', 29.5, 30.5),
                                  ('31°C', 30.5, 31.5), ('32°C', 31.5, 32.5), ('33°C', 32.5, 33.5),
                                  ('34°C', 33.5, 34.5), ('35°C or higher', 34.5, 50)]},
        'Lucknow': {'lat': 26.8467, 'lon': 80.9462, 'unit': 'C',
                    'buckets': [('28°C or below', -50, 28.5), ('29°C', 28.5, 29.5), ('30°C', 29.5, 30.5),
                                ('31°C', 30.5, 31.5), ('32°C', 31.5, 32.5), ('33°C', 32.5, 33.5),
                                ('34°C', 33.5, 34.5), ('35°C', 34.5, 35.5), ('36°C', 35.5, 36.5),
                                ('37°C', 36.5, 37.5), ('38°C or higher', 37.5, 50)]},
        'Sao Paulo': {'lat': -23.5505, 'lon': -46.6333, 'unit': 'C',
                      'buckets': [('24°C or below', -50, 24.5), ('25°C', 24.5, 25.5), ('26°C', 25.5, 26.5),
                                  ('27°C', 26.5, 27.5), ('28°C', 27.5, 28.5), ('29°C', 28.5, 29.5),
                                  ('30°C', 29.5, 30.5), ('31°C', 30.5, 31.5), ('32°C', 31.5, 32.5),
                                  ('33°C', 32.5, 33.5), ('34°C or higher', 33.5, 50)]},
    }

    # Load token IDs from file
    with open('/tmp/weather_markets_mar21.json') as f:
        weather_data = json.load(f)

    # Get latest forecasts
    config = {"markets": [], "end_date": "2026-03-21T12:00:00Z"}

    for city_name, city_info in cities.items():
        if city_name not in weather_data:
            print(f"[MM] No market data for {city_name}, skipping")
            continue

        try:
            resp = requests.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude': city_info['lat'], 'longitude': city_info['lon'],
                'daily': 'temperature_2m_max',
                'timezone': 'auto',
                'start_date': '2026-03-21', 'end_date': '2026-03-21',
            }, timeout=10)
            data = resp.json()
            forecast = data['daily']['temperature_2m_max'][0]
        except Exception as e:
            print(f"[MM] Forecast error for {city_name}: {e}")
            continue

        # Calculate probabilities
        probs = calc_weather_probs(forecast, sigma=2.0, buckets=city_info['buckets'])

        # Match buckets to token IDs
        market_list = weather_data[city_name]
        for bucket_label, prob in probs.items():
            # Find matching market
            match = None
            for mkt in market_list:
                q = mkt['question']
                # Match by temperature string in question
                if bucket_label.replace('°', '°') in q or bucket_label in q:
                    match = mkt
                    break
                # Try partial match
                temp_num = bucket_label.split('°')[0].strip()
                if f"be {temp_num}°" in q or f"be {temp_num} °" in q:
                    match = mkt
                    break

            if match and len(match['tokens']) >= 2:
                config['markets'].append({
                    'label': f"{city_name} {bucket_label}",
                    'token_id': match['tokens'][0],     # YES token
                    'no_token_id': match['tokens'][1],   # NO token
                    'fair_value': round(prob, 4),
                    'max_size': MAX_ORDER_SIZE if prob >= 0.08 else 1.5,
                })

        print(f"[MM] {city_name}: forecast={forecast}°C, {len([p for p in probs.values() if p >= MIN_FAIR_VALUE])} tradeable buckets")

    return config


def place_limit_order(client, token_id, price, size_shares, side):
    """Place a GTC limit order. Returns order ID or None."""
    try:
        price = round(price, 2)  # tick size 0.01
        size_shares = floor(size_shares * 100) / 100.0

        if size_shares < MIN_SHARES:
            return None
        if price < 0.01 or price > 0.99:
            return None

        args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size_shares,
            side=side,
        )
        signed = client.create_order(args)
        # Use post_only=True to prevent crossing the book (marketable orders)
        resp = client.post_order(signed, orderType=OrderType.GTC, post_only=True)
        order_id = resp.get('orderID') or resp.get('id') or resp.get('order_id')
        return order_id
    except Exception as e:
        print(f"[MM] Order failed ({side} {size_shares:.1f}sh @ {price:.3f}): {e}")
        return None


def cancel_order(client, order_id):
    """Cancel a single order."""
    try:
        client.cancel(order_id)
        return True
    except Exception as e:
        print(f"[MM] Cancel failed for {order_id}: {e}")
        return False


def cancel_all_orders(client):
    """Cancel all open orders."""
    try:
        client.cancel_all()
        print("[MM] All orders cancelled")
        return True
    except Exception as e:
        print(f"[MM] Cancel all failed: {e}")
        return False


def check_order_status(client, order_id):
    """Check if an order is still open, filled, or cancelled."""
    try:
        order = client.get_order(order_id)
        return order
    except Exception:
        return None


def run_market_maker(config, total_budget=15.0, dry_run=False):
    """
    Main market maker loop.
    config: dict with 'markets' list and 'end_date'
    """
    client = get_client()
    balance = get_usdc_balance(client)
    print(f"[MM] Starting. Balance: ${balance:.2f}, Budget: ${total_budget:.2f}")

    if balance < 5:
        print("[MM] Balance too low")
        return

    budget = min(total_budget, balance * 0.25)  # Never use more than 25% of balance
    markets = config.get('markets', [])
    end_date = config.get('end_date', '')

    # Filter to tradeable markets — focus on highest probability buckets
    tradeable = [m for m in markets if MIN_FAIR_VALUE <= m['fair_value'] <= MAX_FAIR_VALUE]
    # Sort by fair value descending, take top N to concentrate capital
    tradeable.sort(key=lambda m: m['fair_value'], reverse=True)
    # Each market needs ~$1.50+ for YES side (5 shares * ~0.15-0.40)
    # With budget B, can support ~B/1.5 markets on YES side only
    max_markets = min(len(tradeable), max(5, int(budget / 1.5)))
    tradeable = tradeable[:max_markets]
    print(f"[MM] {len(tradeable)}/{len(markets)} markets selected (top by probability)")

    if not tradeable:
        print("[MM] No tradeable markets")
        return

    # Allocate budget: more to higher-probability markets
    total_weight = sum(m['fair_value'] for m in tradeable)
    for m in tradeable:
        m['_alloc'] = budget * (m['fair_value'] / total_weight) if total_weight > 0 else budget / len(tradeable)

    state = load_mm_state()
    orders_placed = 0
    total_placed = 0

    send(f"🏪 MM Bot starting: {len(tradeable)} markets, ${budget:.2f} budget")

    for mkt in tradeable:
        if not running:
            break

        token_id = mkt['token_id']
        fair = mkt['fair_value']
        label = mkt.get('label', token_id[:16])
        alloc = mkt.get('_alloc', budget / len(tradeable))
        bid_alloc = alloc * 0.7   # 70% on buy side (cheaper, more shares)
        ask_alloc = alloc * 0.3   # 30% on sell side (via NO token)

        bid_price = round(max(0.01, fair - SPREAD_HALFWIDTH), 2)
        ask_price = round(min(0.99, fair + SPREAD_HALFWIDTH), 2)

        # Calculate shares — ensure minimum 5 shares (CLOB minimum)
        max_bid = min(bid_alloc, MAX_ORDER_SIZE)
        max_ask = min(ask_alloc, MAX_ORDER_SIZE)
        bid_shares = floor((max_bid / bid_price) * 100) / 100.0 if bid_price > 0 else 0
        ask_shares = floor((max_ask / ask_price) * 100) / 100.0 if ask_price > 0 else 0
        # Enforce minimum — bump up to 5 shares if under
        if 0 < bid_shares < MIN_SHARES:
            bid_shares = MIN_SHARES
            max_bid = bid_shares * bid_price
        if 0 < ask_shares < MIN_SHARES:
            ask_shares = MIN_SHARES
            max_ask = ask_shares * ask_price

        if dry_run:
            no_price = round(1.0 - ask_price, 2)
            print(f"  [DRY] {label}: BID {bid_shares:.0f}sh @ {bid_price:.2f} (${max_bid:.2f}), "
                  f"ASK(NO) @ {no_price:.2f} (${max_ask:.2f}) | fair={fair:.3f}")
            orders_placed += 2
            total_placed += max_bid + max_ask
            continue

        # Place bid (buy YES at low price)
        if bid_shares >= 1.0:
            bid_id = place_limit_order(client, token_id, bid_price, bid_shares, BUY)
            if bid_id:
                state['orders'][bid_id] = {
                    'token_id': token_id, 'label': label, 'side': 'BUY_YES',
                    'price': bid_price, 'size': bid_shares, 'fair': fair,
                    'placed_at': str(datetime.now(timezone.utc)),
                }
                orders_placed += 1
                total_placed += max_bid

        # Place ask (via buying NO token = equivalent to selling YES)
        no_price = round(1.0 - ask_price, 2)
        no_token_id = mkt.get('no_token_id')

        if no_token_id and no_price >= 0.01:
            no_shares = floor((max_ask / no_price) * 100) / 100.0 if no_price > 0 else 0
            if no_shares >= 1.0:
                ask_id = place_limit_order(client, no_token_id, no_price, no_shares, BUY)
                if ask_id:
                    state['orders'][ask_id] = {
                        'token_id': no_token_id, 'label': f"{label} (NO)", 'side': 'BUY_NO',
                        'price': no_price, 'size': no_shares, 'fair': 1.0 - fair,
                        'placed_at': str(datetime.now(timezone.utc)),
                    }
                    orders_placed += 1
                    total_placed += max_ask

        if orders_placed % 10 == 0 and orders_placed > 0:
            print(f"[MM] Placed {orders_placed} orders so far...")
            time.sleep(0.5)  # rate limiting

        time.sleep(0.3)  # rate limiting between markets

    save_mm_state(state)
    msg = f"MM Bot: {orders_placed} orders placed across {len(tradeable)} markets (${total_placed:.2f} committed)"
    print(f"[MM] {msg}")
    send(msg)

    if dry_run:
        return

    # Monitor loop
    print(f"[MM] Entering monitor loop (poll every {POLL_INTERVAL}s)")
    last_check = time.time()

    while running:
        time.sleep(10)

        if time.time() - last_check < POLL_INTERVAL:
            continue

        last_check = time.time()
        print(f"[MM] Checking orders at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        # Check time to resolution
        if end_date:
            from trader.markets import days_until_end
            hours_left = days_until_end(end_date) * 24
            if hours_left < CANCEL_BEFORE_HOURS:
                print(f"[MM] {hours_left:.1f}h to resolution, cancelling all orders")
                cancel_all_orders(client)
                send(f"MM Bot: Cancelled all orders ({hours_left:.1f}h to resolution)")
                break

        # Check for fills by querying open orders
        try:
            open_orders = client.get_orders()
            open_ids = set()
            if isinstance(open_orders, list):
                for o in open_orders:
                    oid = o.get('id') or o.get('orderID')
                    if oid:
                        open_ids.add(oid)

            # Check which of our orders got filled
            filled = []
            for oid, info in list(state['orders'].items()):
                if oid not in open_ids:
                    filled.append((oid, info))
                    del state['orders'][oid]

            if filled:
                for oid, info in filled:
                    fill_msg = f"FILL: {info['label']} {info['side']} {info['size']:.0f}sh @ {info['price']:.3f}"
                    print(f"[MM] {fill_msg}")
                    state['fills'].append({**info, 'filled_at': str(datetime.now(timezone.utc))})

                send(f"MM fills: {len(filled)} orders filled")
                save_mm_state(state)

        except Exception as e:
            print(f"[MM] Monitor error: {e}")

    # Cleanup
    print("[MM] Shutting down, cancelling remaining orders...")
    cancel_all_orders(client)
    save_mm_state(state)
    print("[MM] Done.")


def main():
    parser = argparse.ArgumentParser(description='Polymarket Market Maker')
    parser.add_argument('--weather', action='store_true', help='Auto-generate config from weather forecasts')
    parser.add_argument('--config', type=str, help='Path to MM config JSON')
    parser.add_argument('--budget', type=float, default=15.0, help='Total USDC budget for MM')
    parser.add_argument('--dry-run', action='store_true', help='Print orders without placing them')
    parser.add_argument('--spread', type=float, default=0.04, help='Half-spread width (default 0.04)')
    args = parser.parse_args()

    global SPREAD_HALFWIDTH
    SPREAD_HALFWIDTH = args.spread

    if args.weather:
        print("[MM] Generating weather MM config...")
        config = get_weather_config()
        print(f"[MM] Generated config with {len(config.get('markets', []))} markets")

        if args.dry_run:
            run_market_maker(config, total_budget=args.budget, dry_run=True)
        else:
            run_market_maker(config, total_budget=args.budget)

    elif args.config:
        with open(args.config) as f:
            config = json.load(f)
        run_market_maker(config, total_budget=args.budget, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
