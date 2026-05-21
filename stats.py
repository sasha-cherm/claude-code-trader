#!/usr/bin/env python3
"""Live & paper trading dashboard — run anytime for current stats."""

import json
import requests
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"
PAPER_LOG = "logs/btc_15m_mm_paper.jsonl"
PAPER_STATE = "mm_paper_state.json"
GAMMA = "https://gamma-api.polymarket.com"
RESOLVE_CACHE_FILE = "logs/resolve_cache.json"

_cache = {}
def _load_cache():
    global _cache
    try:
        _cache = json.load(open(RESOLVE_CACHE_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        _cache = {}

def _save_cache():
    with open(RESOLVE_CACHE_FILE, "w") as f:
        json.dump(_cache, f)

def resolve(slug):
    if slug in _cache:
        return _cache[slug]
    try:
        r = requests.get(f"{GAMMA}/events/slug/{slug}", timeout=10)
        if r.status_code != 200:
            return None
        mkt = r.json().get("markets", [None])[0]
        if not mkt or not mkt.get("closed"):
            return None
        outcomes = json.loads(mkt.get("outcomes", "[]"))
        prices = json.loads(mkt.get("outcomePrices", "[]"))
        up_idx = next((i for i, o in enumerate(outcomes) if o.lower() == "up"), 0)
        res = "UP" if float(prices[up_idx]) > 0.5 else "DN"
        _cache[slug] = res
        return res
    except Exception:
        return None


def load(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except FileNotFoundError:
        return []


def analyze_live(trades):
    """Resolve every live BUY against Gamma API to get true PnL."""
    buys = [t for t in trades if t.get("action") == "BUY"]
    results = [t for t in trades if t.get("action") == "RESULT"]

    if not buys:
        return None

    # Fill rate from RESULT entries
    candle_fills = defaultdict(int)
    candle_total = set()
    for r in results:
        slug = r.get("slug", "")
        candle_total.add(slug)
        if r.get("status") == "FILLED" or r.get("filled"):
            candle_fills[slug] += 1

    n_candles = len(candle_total)
    fill_counts = [candle_fills.get(s, 0) for s in candle_total]
    placed_unfilled = sum(1 for r in results if r.get("status") == "PLACED_UNFILLED")
    never_placed = sum(1 for r in results if r.get("status") == "NEVER_PLACED")
    filled_results = sum(1 for r in results if r.get("status") == "FILLED")

    # Resolve outcomes
    wins = losses = 0
    pnl_series = []  # running PnL after each resolved trade
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    total_cost = 0.0
    unresolved = 0

    # Group by slug for chronological processing
    buys_sorted = sorted(buys, key=lambda b: b["timestamp"])

    for b in buys_sorted:
        winner = resolve(b["slug"])
        if winner is None:
            unresolved += 1
            continue
        px = b["price"]
        sz = b["size"]
        total_cost += px * sz
        if winner == b["side"]:
            pnl = (1.0 - px) * sz
            wins += 1
        else:
            pnl = -px * sz
            losses += 1
        running_pnl += pnl
        pnl_series.append(running_pnl)

        # Track drawdown from peak PnL
        if running_pnl > peak_pnl:
            peak_pnl = running_pnl
        dd_abs = peak_pnl - running_pnl
        if dd_abs > max_dd_abs:
            max_dd_abs = dd_abs
        # % drawdown relative to (start_balance + peak_pnl)
        # Use deposit as base since we track PnL not absolute balance
        equity_at_peak = 150.0 + peak_pnl  # approximate start
        if equity_at_peak > 0:
            dd_pct = dd_abs / equity_at_peak * 100
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    n = wins + losses
    if n == 0:
        return None

    # Current drawdown
    curr_dd_abs = peak_pnl - running_pnl
    curr_equity = 150.0 + running_pnl
    peak_equity = 150.0 + peak_pnl
    curr_dd_pct = curr_dd_abs / peak_equity * 100 if peak_equity > 0 else 0

    # Time window
    ts_first = buys_sorted[0]["timestamp"][:19]
    ts_last = buys_sorted[-1]["timestamp"][:19]
    t0 = datetime.fromisoformat(ts_first)
    t1 = datetime.fromisoformat(ts_last)
    days = max((t1 - t0).total_seconds() / 86400, 0.01)

    avg_px = total_cost / sum(b["size"] for b in buys_sorted if resolve(b["slug"]))
    # simpler: just mean of prices
    avg_px = np.mean([b["price"] for b in buys_sorted])

    return {
        "label": "LIVE",
        "n_buys": len(buys),
        "n_resolved": n,
        "n_unresolved": unresolved,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n,
        "avg_buy_price": avg_px,
        "total_pnl": running_pnl,
        "peak_pnl": peak_pnl,
        "pnl_per_deal": running_pnl / n,
        "edge_per_share": wins / n - avg_px,
        "deals_per_day": n / days,
        "days": days,
        "n_candles": n_candles,
        "fill_rate_per_leg": filled_results / len(results) if results else 0,
        "placed_unfilled": placed_unfilled,
        "never_placed": never_placed,
        "curr_dd_abs": curr_dd_abs,
        "curr_dd_pct": curr_dd_pct,
        "max_dd_abs": max_dd_abs,
        "max_dd_pct": max_dd_pct,
        "peak_equity": peak_equity,
        "curr_equity": curr_equity,
    }


def analyze_paper(trades):
    """Paper has explicit RESOLVE entries."""
    buys = [t for t in trades if t.get("action") == "BUY"]
    resolves = [t for t in trades if t.get("action") == "RESOLVE"]
    no_fills = [t for t in trades if t.get("action") == "NO_FILL"]

    if not resolves:
        return None

    wins = losses = 0
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    start_bal = 100.0

    for r in resolves:
        pnl = r.get("pnl", 0)
        if r.get("won"):
            wins += 1
        else:
            losses += 1
        running_pnl += pnl
        if running_pnl > peak_pnl:
            peak_pnl = running_pnl
        dd_abs = peak_pnl - running_pnl
        if dd_abs > max_dd_abs:
            max_dd_abs = dd_abs
        equity_at_peak = start_bal + peak_pnl
        if equity_at_peak > 0:
            dd_pct = dd_abs / equity_at_peak * 100
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    n = wins + losses
    avg_px = np.mean([b["price"] for b in buys]) if buys else 0

    ts_first = buys[0]["timestamp"][:19] if buys else ""
    ts_last = buys[-1]["timestamp"][:19] if buys else ""
    if ts_first and ts_last:
        t0 = datetime.fromisoformat(ts_first)
        t1 = datetime.fromisoformat(ts_last)
        days = max((t1 - t0).total_seconds() / 86400, 0.01)
    else:
        days = 1

    curr_dd_abs = peak_pnl - running_pnl
    peak_equity = start_bal + peak_pnl
    curr_equity = start_bal + running_pnl
    curr_dd_pct = curr_dd_abs / peak_equity * 100 if peak_equity > 0 else 0

    # Paper state for open positions
    open_pos = 0
    paper_bal = curr_equity
    try:
        s = json.load(open(PAPER_STATE))
        paper_bal = s["balance"]
        open_pos = len(s["positions"])
    except Exception:
        pass

    return {
        "label": "PAPER",
        "n_buys": len(buys),
        "n_resolved": n,
        "n_unresolved": 0,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n if n else 0,
        "avg_buy_price": avg_px,
        "total_pnl": running_pnl,
        "peak_pnl": peak_pnl,
        "pnl_per_deal": running_pnl / n if n else 0,
        "edge_per_share": (wins / n - avg_px) if n else 0,
        "deals_per_day": n / days,
        "days": days,
        "n_candles": len(set(b["slug"] for b in buys)),
        "fill_rate_per_leg": n / (n + len(no_fills) * 2) if (n + len(no_fills)) else 0,
        "placed_unfilled": 0,
        "never_placed": 0,
        "curr_dd_abs": curr_dd_abs,
        "curr_dd_pct": curr_dd_pct,
        "max_dd_abs": max_dd_abs,
        "max_dd_pct": max_dd_pct,
        "peak_equity": peak_equity,
        "curr_equity": curr_equity,
        "open_positions": open_pos,
        "paper_balance": paper_bal,
    }


def print_stats(s):
    if not s:
        return
    label = s["label"]
    w = 14

    print(f"\n{'='*58}")
    print(f"  {label} TRADING STATS")
    print(f"{'='*58}")

    print(f"\n  --- Performance ---")
    print(f"  {'Resolved deals:':<28s} {s['n_resolved']:>{w},d}")
    print(f"  {'Unresolved:':<28s} {s.get('n_unresolved', 0):>{w},d}")
    print(f"  {'Wins / Losses:':<28s} {str(s['wins'])+' / '+str(s['losses']):>{w}s}")
    print(f"  {'Win rate:':<28s} {s['win_rate']*100:>{w-1}.2f}%")
    print(f"  {'Avg buy price:':<28s} {'$%.4f' % s['avg_buy_price']:>{w}s}")
    print(f"  {'Edge per share:':<28s} {'$%+.4f' % s['edge_per_share']:>{w}s}")

    print(f"\n  --- PnL ---")
    print(f"  {'Total PnL:':<28s} {'$%+.2f' % s['total_pnl']:>{w}s}")
    print(f"  {'Peak PnL:':<28s} {'$%+.2f' % s['peak_pnl']:>{w}s}")
    print(f"  {'PnL per deal:':<28s} {'$%+.4f' % s['pnl_per_deal']:>{w}s}")

    print(f"\n  --- Equity ---")
    print(f"  {'Peak equity:':<28s} {'$%.2f' % s['peak_equity']:>{w}s}")
    print(f"  {'Current equity:':<28s} {'$%.2f' % s['curr_equity']:>{w}s}")
    if label == "PAPER":
        print(f"  {'Paper balance:':<28s} {'$%.2f' % s.get('paper_balance', 0):>{w}s}")
        print(f"  {'Open positions:':<28s} {s.get('open_positions', 0):>{w}d}")

    print(f"\n  --- Drawdown ---")
    print(f"  {'Current DD from peak:':<28s} {'$%.2f' % s['curr_dd_abs']:>{w}s} "
          f"({s['curr_dd_pct']:.1f}%)")
    print(f"  {'Max DD from peak:':<28s} {'$%.2f' % s['max_dd_abs']:>{w}s} "
          f"({s['max_dd_pct']:.1f}%)")
    # Traffic light
    dd = s["curr_dd_pct"]
    if dd < 15:
        status = "OK"
    elif dd < 25:
        status = "WATCH"
    elif dd < 60:
        status = "WARNING — consider reducing size"
    else:
        status = "STOP BOT"
    print(f"  {'DD status:':<28s} {status}")

    print(f"\n  --- Activity ---")
    print(f"  {'Days active:':<28s} {s['days']:>{w}.1f}")
    print(f"  {'Deals per day:':<28s} {s['deals_per_day']:>{w}.1f}")
    print(f"  {'Total BUYs:':<28s} {s['n_buys']:>{w},d}")
    print(f"  {'Fill rate (per leg):':<28s} {s['fill_rate_per_leg']*100:>{w-1}.1f}%")
    if s.get("placed_unfilled"):
        print(f"  {'Placed but unfilled:':<28s} {s['placed_unfilled']:>{w},d}")
    if s.get("never_placed"):
        print(f"  {'Never placed:':<28s} {s['never_placed']:>{w},d}")


def print_comparison(paper, live):
    if not paper or not live:
        return

    print(f"\n{'='*58}")
    print(f"  SIDE-BY-SIDE COMPARISON")
    print(f"{'='*58}")
    rows = [
        ("Resolved deals", f"{paper['n_resolved']}", f"{live['n_resolved']}"),
        ("Win rate", f"{paper['win_rate']*100:.2f}%", f"{live['win_rate']*100:.2f}%"),
        ("Avg buy price", f"${paper['avg_buy_price']:.4f}", f"${live['avg_buy_price']:.4f}"),
        ("Edge/share", f"${paper['edge_per_share']:+.4f}", f"${live['edge_per_share']:+.4f}"),
        ("Total PnL", f"${paper['total_pnl']:+.2f}", f"${live['total_pnl']:+.2f}"),
        ("PnL/deal", f"${paper['pnl_per_deal']:+.4f}", f"${live['pnl_per_deal']:+.4f}"),
        ("Peak equity", f"${paper['peak_equity']:.2f}", f"${live['peak_equity']:.2f}"),
        ("Current equity", f"${paper['curr_equity']:.2f}", f"${live['curr_equity']:.2f}"),
        ("Current DD %", f"{paper['curr_dd_pct']:.1f}%", f"{live['curr_dd_pct']:.1f}%"),
        ("Max DD %", f"{paper['max_dd_pct']:.1f}%", f"{live['max_dd_pct']:.1f}%"),
        ("Deals/day", f"{paper['deals_per_day']:.1f}", f"{live['deals_per_day']:.1f}"),
        ("Fill rate/leg", f"{paper['fill_rate_per_leg']*100:.1f}%",
         f"{live['fill_rate_per_leg']*100:.1f}%"),
    ]
    print(f"\n  {'Metric':<22s} {'PAPER':>14s} {'LIVE':>14s}")
    print(f"  {'-'*52}")
    for label, p_val, l_val in rows:
        print(f"  {label:<22s} {p_val:>14s} {l_val:>14s}")


def main():
    _load_cache()
    print(f"  Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # Check bots running
    import subprocess
    try:
        out = subprocess.check_output(["pgrep", "-af", "btc_15m_mm"], text=True).strip()
        running = [l for l in out.splitlines() if "grep" not in l]
    except subprocess.CalledProcessError:
        running = []

    print(f"  Running bots: {len(running)}")
    for r in running:
        parts = r.split(None, 1)
        print(f"    PID {parts[0]}: {parts[1] if len(parts) > 1 else '?'}")

    # Check USDC
    try:
        from trader.client import get_client, get_usdc_balance
        c = get_client()
        usdc = get_usdc_balance(c)
        print(f"  USDC wallet: ${usdc:.2f}")
    except Exception:
        pass

    paper_trades = load(PAPER_LOG)
    live_trades = load(LIVE_LOG)

    paper = analyze_paper(paper_trades)
    live = analyze_live(live_trades)
    _save_cache()

    print_stats(paper)
    print_stats(live)
    print_comparison(paper, live)


if __name__ == "__main__":
    main()
