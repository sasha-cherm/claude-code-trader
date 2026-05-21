#!/usr/bin/env python3
"""
Monte Carlo drawdown analysis for BTC 15-min MM strategy.

Key questions:
1. What are the typical drawdowns for a WINNING strategy (true edge > 0)?
2. What drawdown level indicates the edge is GONE (strategy broken)?
3. What stop-loss threshold minimizes false stops while catching real failures?

Simulates two scenarios:
A. Strategy HAS edge (observed win rate ~51.15%)
B. Strategy has NO edge (win rate = avg buy price = ~47.5%, i.e. pure noise)

The optimal stop threshold is where:
- Very few winning sims trigger the stop (low false positive rate)
- Most losing sims trigger the stop (high true positive rate)
"""

import json
import numpy as np
from collections import defaultdict

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"


def extract_params():
    import requests
    GAMMA = "https://gamma-api.polymarket.com"
    trades = [json.loads(l) for l in open(LIVE_LOG) if l.strip()]
    buys = [t for t in trades if t.get("action") == "BUY"]
    results = [t for t in trades if t.get("action") == "RESULT"]

    buy_prices = np.array([b["price"] for b in buys])

    print("Resolving live trades...")
    cache_file = "logs/resolve_cache.json"
    try:
        cache = json.loads(open(cache_file).read())
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    def resolve(slug):
        if slug in cache:
            return cache[slug]
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
            cache[slug] = res
            return res
        except Exception:
            return None

    wins = resolved = 0
    for b in buys:
        winner = resolve(b["slug"])
        if winner is None:
            continue
        resolved += 1
        if winner == b["side"]:
            wins += 1

    win_rate = wins / resolved if resolved else 0.50
    with open(cache_file, "w") as f:
        json.dump(cache, f)

    from collections import Counter
    candle_fills = Counter()
    candle_set = set()
    for r in results:
        slug = r.get("slug", "")
        candle_set.add(slug)
        if r.get("status") == "FILLED" or r.get("filled"):
            candle_fills[slug] += 1
    fill_counts = [candle_fills.get(s, 0) for s in candle_set]
    fd = Counter(fill_counts)
    n = len(fill_counts)
    p_fill = [fd.get(0, 0)/n, fd.get(1, 0)/n, fd.get(2, 0)/n]

    return {
        "win_rate": win_rate,
        "wins": wins,
        "resolved": resolved,
        "buy_prices": buy_prices,
        "avg_buy_price": float(np.mean(buy_prices)),
        "p_fill": p_fill,
    }


def simulate_drawdowns(params, win_rate, n_sims=5000, n_days=90,
                       start_balance=150.0, base_size=6, size_step=50,
                       min_size=5, max_size=1000):
    """Simulate and track maximum percentage drawdown from peak."""
    rng = np.random.default_rng(42)
    buy_prices = params["buy_prices"]
    p_fill = params["p_fill"]
    candles_per_day = 96

    # Pre-generate all randomness
    candle_fills_all = rng.choice([0, 1, 2], size=(n_sims, n_days, candles_per_day), p=p_fill)
    daily_fills = candle_fills_all.sum(axis=2)
    del candle_fills_all
    max_daily = int(daily_fills.max())
    price_idx = rng.integers(0, len(buy_prices), size=(n_sims, n_days, max_daily))
    prices_all = buy_prices[price_idx]
    wins_all = rng.random(size=(n_sims, n_days, max_daily)) < win_rate
    del price_idx

    # Track per-sim: max % drawdown, all daily drawdown %s
    max_pct_drawdowns = np.zeros(n_sims)
    # Track drawdown at various deal counts (for early detection)
    # Record drawdown % after every N deals
    check_points = [25, 50, 100, 200, 500]
    dd_at_checkpoint = {cp: [] for cp in check_points}

    for sim in range(n_sims):
        bal = start_balance
        peak = start_balance
        max_dd_pct = 0.0
        deals = 0

        for day in range(n_days):
            nf = daily_fills[sim, day]
            for f in range(nf):
                size = base_size + int((bal - start_balance) / size_step)
                size = max(min_size, min(max_size, size))
                px = prices_all[sim, day, f]
                if px * size > bal:
                    continue

                deals += 1
                if wins_all[sim, day, f]:
                    bal += (1.0 - px) * size
                else:
                    bal -= px * size

                if bal > peak:
                    peak = bal
                dd_pct = (peak - bal) / peak * 100 if peak > 0 else 0
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

                for cp in check_points:
                    if deals == cp:
                        dd_at_checkpoint[cp].append(dd_pct)

                if bal <= 0:
                    max_dd_pct = 100.0
                    break
            if bal <= 0:
                break

        max_pct_drawdowns[sim] = max_dd_pct

    return max_pct_drawdowns, dd_at_checkpoint


def main():
    params = extract_params()
    wr = params["win_rate"]
    avg_px = params["avg_buy_price"]

    print(f"\nObserved win rate: {wr:.4f}")
    print(f"Avg buy price: ${avg_px:.4f}")
    print(f"Edge/share: ${wr - avg_px:+.4f}")

    # ── A. Drawdowns when strategy HAS edge (observed win rate) ──
    print(f"\n{'='*65}")
    print(f"SCENARIO A: Strategy HAS edge (WR={wr:.1%})")
    print(f"{'='*65}")
    print("Simulating 5000 paths over 90 days...")
    dd_edge, dd_cp_edge = simulate_drawdowns(params, win_rate=wr, n_sims=5000, n_days=90)

    pcts = [50, 75, 90, 95, 99]
    print(f"\n  Max drawdown % distribution (90 days):")
    print(f"  {'Percentile':<14s} {'Max DD%':>10s}")
    print(f"  {'-'*26}")
    for p in pcts:
        print(f"  {p:>3d}th          {np.percentile(dd_edge, p):>9.2f}%")
    print(f"  {'Mean':<14s} {np.mean(dd_edge):>9.2f}%")

    # ── B. Drawdowns when strategy has NO edge ──
    # No edge = win rate equals break-even (= avg buy price)
    no_edge_wr = avg_px
    print(f"\n{'='*65}")
    print(f"SCENARIO B: Strategy has NO edge (WR={no_edge_wr:.1%})")
    print(f"{'='*65}")
    print("Simulating 5000 paths over 90 days...")
    dd_noedge, dd_cp_noedge = simulate_drawdowns(params, win_rate=no_edge_wr,
                                                   n_sims=5000, n_days=90)

    print(f"\n  Max drawdown % distribution (90 days):")
    print(f"  {'Percentile':<14s} {'Max DD%':>10s}")
    print(f"  {'-'*26}")
    for p in pcts:
        print(f"  {p:>3d}th          {np.percentile(dd_noedge, p):>9.2f}%")
    print(f"  {'Mean':<14s} {np.mean(dd_noedge):>9.2f}%")

    # ── C. Drawdowns when strategy is NEGATIVE edge ──
    neg_wr = avg_px - 0.02  # 2% worse than breakeven
    print(f"\n{'='*65}")
    print(f"SCENARIO C: Strategy has NEGATIVE edge (WR={neg_wr:.1%})")
    print(f"{'='*65}")
    print("Simulating 5000 paths over 90 days...")
    dd_neg, dd_cp_neg = simulate_drawdowns(params, win_rate=neg_wr,
                                            n_sims=5000, n_days=90)

    print(f"\n  Max drawdown % distribution (90 days):")
    print(f"  {'Percentile':<14s} {'Max DD%':>10s}")
    print(f"  {'-'*26}")
    for p in pcts:
        print(f"  {p:>3d}th          {np.percentile(dd_neg, p):>9.2f}%")
    print(f"  {'Mean':<14s} {np.mean(dd_neg):>9.2f}%")

    # ── D. Stop threshold analysis ──
    print(f"\n{'='*65}")
    print(f"STOP-LOSS THRESHOLD ANALYSIS")
    print(f"{'='*65}")
    print(f"\nFor each drawdown threshold, what % of sims would trigger a stop?")
    print(f"  - False stop: edge EXISTS but stop triggered (bad — we lose a winning strategy)")
    print(f"  - True stop:  no edge but stop triggered (good — we exit a broken strategy)")
    print()
    print(f"  {'DD Threshold':>14s} {'Edge Stopped':>14s} {'NoEdge Stopped':>16s} {'NegEdge Stopped':>16s} {'Signal/Noise':>14s}")
    print(f"  {'-'*76}")

    best_threshold = 0
    best_ratio = 0

    for thresh in [5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70]:
        edge_stopped = np.mean(dd_edge >= thresh) * 100
        noedge_stopped = np.mean(dd_noedge >= thresh) * 100
        neg_stopped = np.mean(dd_neg >= thresh) * 100
        # Signal/noise ratio: noedge_stopped / max(edge_stopped, 0.1)
        ratio = noedge_stopped / max(edge_stopped, 0.1)
        if ratio > best_ratio and noedge_stopped > 50:
            best_ratio = ratio
            best_threshold = thresh
        print(f"  {thresh:>12d}%  {edge_stopped:>13.1f}% {noedge_stopped:>15.1f}% "
              f"{neg_stopped:>15.1f}% {ratio:>13.1f}x")

    print(f"\n  Best threshold (max signal/noise with >50% detection): {best_threshold}%")

    # ── E. Early detection: drawdown after N deals ──
    print(f"\n{'='*65}")
    print(f"EARLY DETECTION: Drawdown after N deals")
    print(f"{'='*65}")
    print(f"\nIf the bot is losing, how soon can we detect it?")
    print()
    for cp in [25, 50, 100, 200]:
        e_vals = np.array(dd_cp_edge.get(cp, [0]))
        n_vals = np.array(dd_cp_noedge.get(cp, [0]))
        neg_vals = np.array(dd_cp_neg.get(cp, [0]))
        if len(e_vals) < 10 or len(n_vals) < 10:
            continue
        print(f"  After {cp} deals:")
        print(f"    {'':>20s} {'Edge':>10s} {'NoEdge':>10s} {'NegEdge':>10s}")
        print(f"    {'Median DD%':<20s} {np.median(e_vals):>9.1f}% {np.median(n_vals):>9.1f}% {np.median(neg_vals):>9.1f}%")
        print(f"    {'90th% DD%':<20s} {np.percentile(e_vals, 90):>9.1f}% {np.percentile(n_vals, 90):>9.1f}% {np.percentile(neg_vals, 90):>9.1f}%")
        # What threshold at this checkpoint separates edge from no-edge?
        for t in [5, 10, 15, 20, 25]:
            e_stop = np.mean(e_vals >= t) * 100
            n_stop = np.mean(n_vals >= t) * 100
            neg_stop = np.mean(neg_vals >= t) * 100
            if n_stop > 30 and e_stop < 20:
                print(f"    → {t}% DD threshold: edge stops {e_stop:.1f}%, "
                      f"noedge stops {n_stop:.1f}%, neg stops {neg_stop:.1f}%")
        print()

    # ── F. Recommendation ──
    print(f"{'='*65}")
    print(f"RECOMMENDATION")
    print(f"{'='*65}")
    p95_edge = np.percentile(dd_edge, 95)
    p99_edge = np.percentile(dd_edge, 99)
    print(f"\n  A winning strategy (51.15% WR) can draw down:")
    print(f"    - up to {p95_edge:.1f}% in 95% of cases")
    print(f"    - up to {p99_edge:.1f}% in 99% of cases")
    print(f"\n  Suggested stop-loss rules:")
    print(f"    CONSERVATIVE: Stop at {int(p95_edge)+5}% drawdown from peak")
    print(f"      → catches ~5% of winning runs (false positive)")
    print(f"    MODERATE:     Stop at {int(p99_edge)+5}% drawdown from peak")
    print(f"      → catches ~1% of winning runs (false positive)")
    print(f"    AGGRESSIVE:   Stop at {best_threshold}% drawdown from peak")
    print(f"      → best signal/noise ratio ({best_ratio:.1f}x)")
    print(f"\n  Also monitor: if DD > 15% after just 50 deals, that's")
    print(f"  a strong early signal the edge may be gone.")


if __name__ == "__main__":
    main()
