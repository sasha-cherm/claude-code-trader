#!/usr/bin/env python3
"""
Monte Carlo simulation of BTC 15-min MM strategy over 1 year.

Extracts parameters from actual live trade history, then simulates
10,000 paths forward with dynamic position sizing.

Position sizing rule:
  size = base_size + floor((balance - start_balance) / 50)
  Clamped to [MIN_SIZE, MAX_SIZE].

Optimized: simulates per-DAY granularity (draws N fills from daily
distribution, vectorized across simulations).
"""

import json
import numpy as np

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"


def extract_params():
    """Extract win rate, buy price distribution, fill rate from live data."""
    import requests

    GAMMA = "https://gamma-api.polymarket.com"
    trades = [json.loads(l) for l in open(LIVE_LOG) if l.strip()]
    buys = [t for t in trades if t.get("action") == "BUY"]
    results = [t for t in trades if t.get("action") == "RESULT"]

    buy_prices = np.array([b["price"] for b in buys])

    # Win rate from Gamma API resolution
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

    wins = 0
    resolved = 0
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

    # Fill distribution per candle (0, 1, or 2 fills)
    from collections import Counter
    candle_fills = Counter()
    candle_set = set()
    for r in results:
        slug = r.get("slug", "")
        candle_set.add(slug)
        if r.get("status") == "FILLED" or r.get("filled"):
            candle_fills[slug] += 1

    fill_counts = [candle_fills.get(s, 0) for s in candle_set]
    fill_dist = Counter(fill_counts)
    n_candles = len(fill_counts)
    p0 = fill_dist.get(0, 0) / n_candles
    p1 = fill_dist.get(1, 0) / n_candles
    p2 = fill_dist.get(2, 0) / n_candles

    # Deals per day
    from datetime import datetime
    ts_first = buys[0]["timestamp"][:19]
    ts_last = buys[-1]["timestamp"][:19]
    t0 = datetime.fromisoformat(ts_first)
    t1 = datetime.fromisoformat(ts_last)
    days_active = max((t1 - t0).total_seconds() / 86400, 0.5)

    # Expected deals per day = 96 candles × (p1 + 2×p2)
    exp_deals_day = 96 * (p1 + 2 * p2)

    return {
        "win_rate": win_rate,
        "wins": wins,
        "resolved": resolved,
        "buy_prices": buy_prices,
        "avg_buy_price": float(np.mean(buy_prices)),
        "std_buy_price": float(np.std(buy_prices)),
        "p_fill": [p0, p1, p2],
        "exp_deals_day": exp_deals_day,
        "days_active": days_active,
        "n_candles_observed": n_candles,
    }


def run_simulation(params, n_sims=10000, n_days=365, start_balance=150.0,
                   base_size=6, size_step=50, min_size=5, max_size=1000,
                   win_rate_override=None):
    """Vectorized Monte Carlo: simulate per-day, vectorize across sims.

    For each day, each sim draws the number of daily fills, then resolves
    them in sequence (needed for dynamic position sizing).
    """
    rng = np.random.default_rng(42)

    wr = win_rate_override if win_rate_override is not None else params["win_rate"]
    buy_prices = params["buy_prices"]
    p_fill = params["p_fill"]
    candles_per_day = 96

    # Expected daily fills per sim
    # Each candle: 0/1/2 fills. 96 candles/day.
    # We can model daily total fills as: sum of 96 draws from {0,1,2}
    # Mean daily fills = 96 × (p1 + 2×p2)
    # Variance = 96 × E[X^2] - (96×E[X])^2/96... just use poisson or empirical
    #
    # Faster: precompute daily fills as 96 × multinomial
    # But per-trade sizing requires sequential processing within a day.
    #
    # Optimization: batch all sims per day, but process trades sequentially.
    # For N fills in a day, we need N sequential balance updates.
    # We can do daily fill count, then loop over fills within each day.

    # Precompute all daily fill counts: shape (n_sims, n_days)
    # Each day has 96 candles, each with 0/1/2 fills
    # Total daily fills = sum of 96 multinomial draws
    # Approximate: for each candle, draw from {0,1,2} with p_fill probs
    # Sum over 96 candles → daily total
    # We can batch this: draw (n_sims, n_days, 96) and sum last axis
    print("Generating fill counts...")
    candle_fills_all = rng.choice([0, 1, 2], size=(n_sims, n_days, candles_per_day),
                                  p=p_fill)
    daily_fills = candle_fills_all.sum(axis=2)  # shape (n_sims, n_days)
    del candle_fills_all

    # Precompute all buy prices and win/loss outcomes
    max_daily_fills = int(daily_fills.max())
    print(f"Max daily fills in any sim: {max_daily_fills}")

    # Preallocate random draws
    # For each day, for each fill slot up to max_daily_fills:
    #   - buy price (sampled from empirical)
    #   - win/loss (bernoulli)
    print("Generating trade outcomes...")
    price_indices = rng.integers(0, len(buy_prices),
                                 size=(n_sims, n_days, max_daily_fills))
    prices_all = buy_prices[price_indices]  # shape (n_sims, n_days, max_daily_fills)
    wins_all = rng.random(size=(n_sims, n_days, max_daily_fills)) < wr
    del price_indices

    # Run simulation
    print("Running simulation...")
    balances = np.full(n_sims, start_balance)
    peaks = np.full(n_sims, start_balance)
    troughs = np.full(n_sims, start_balance)
    total_deals = np.zeros(n_sims, dtype=int)
    total_wins_count = np.zeros(n_sims, dtype=int)

    milestones = [30, 90, 180, 365]
    milestone_bals = {d: np.zeros(n_sims) for d in milestones}

    for day in range(n_days):
        if day % 30 == 0:
            print(f"  Day {day}/{n_days}...")

        for sim in range(n_sims):
            if balances[sim] <= 0:
                continue

            n_fills_today = daily_fills[sim, day]
            for f in range(n_fills_today):
                bal = balances[sim]
                # Position size
                size = base_size + int((bal - start_balance) / size_step)
                size = max(min_size, min(max_size, size))

                px = prices_all[sim, day, f]
                cost = px * size
                if cost > bal:
                    continue

                total_deals[sim] += 1
                if wins_all[sim, day, f]:
                    balances[sim] += (1.0 - px) * size
                    total_wins_count[sim] += 1
                else:
                    balances[sim] -= px * size

                if balances[sim] > peaks[sim]:
                    peaks[sim] = balances[sim]
                if balances[sim] < troughs[sim]:
                    troughs[sim] = balances[sim]

                if balances[sim] <= 0:
                    balances[sim] = 0
                    break

        for m in milestones:
            if day + 1 == m:
                milestone_bals[m][:] = balances

    # Handle sims that didn't reach 365
    for m in milestones:
        if m > n_days:
            milestone_bals[m][:] = balances

    return {
        "final": balances,
        "peaks": peaks,
        "troughs": troughs,
        "deals": total_deals,
        "wins": total_wins_count,
        "drawdowns": peaks - troughs,
        "milestones": milestone_bals,
    }


def print_results(params, results, start_balance, n_days, base_size, size_step,
                  min_size, max_size):
    balances = results["final"]
    n_sims = len(balances)

    print(f"\n{'='*60}")
    print(f"SIMULATION PARAMETERS")
    print(f"{'='*60}")
    print(f"  Win rate:           {params['win_rate']:.4f} ({params['wins']}/{params['resolved']})")
    print(f"  Avg buy price:      ${params['avg_buy_price']:.4f} ± {params['std_buy_price']:.4f}")
    print(f"  Fill distribution:  0={params['p_fill'][0]:.3f}  1={params['p_fill'][1]:.3f}  2={params['p_fill'][2]:.3f}")
    print(f"  Expected deals/day: {params['exp_deals_day']:.1f}")
    print(f"  Start balance:      ${start_balance:.2f}")
    print(f"  Base size:          {base_size} shares")
    print(f"  Size rule:          +1sh per +${size_step}, min={min_size}, max={max_size}")
    print(f"  Simulations:        {n_sims:,}")
    print(f"  Horizon:            {n_days} days")

    edge = params["win_rate"] - params["avg_buy_price"]
    print(f"\n  Edge/share:         ${edge:+.4f}")
    print(f"  Edge/deal ({base_size}sh):   ${edge * base_size:+.4f}")
    print(f"  Est daily (no comp): ${edge * base_size * params['exp_deals_day']:+.2f}")

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")

    pcts = [5, 10, 25, 50, 75, 90, 95]
    print(f"\n  Final balance distribution:")
    print(f"  {'Percentile':<14s} {'Balance':>14s}")
    print(f"  {'-'*30}")
    for p in pcts:
        v = np.percentile(balances, p)
        print(f"  {p:>3d}th          ${v:>13,.2f}")
    print(f"  {'Mean':<14s} ${np.mean(balances):>13,.2f}")

    print(f"\n  Milestone balances:")
    print(f"  {'Day':<6s} {'5th%':>12s} {'25th%':>12s} {'Median':>12s} {'75th%':>12s} {'95th%':>12s}")
    print(f"  {'-'*68}")
    for m in sorted(results["milestones"]):
        arr = results["milestones"][m]
        print(f"  {m:<6d} ${np.percentile(arr,5):>11,.2f} ${np.percentile(arr,25):>11,.2f} "
              f"${np.median(arr):>11,.2f} ${np.percentile(arr,75):>11,.2f} ${np.percentile(arr,95):>11,.2f}")

    print(f"\n  Target probabilities (1 year):")
    for t in [200, 300, 500, 1000, 2000, 5000, 10000, 50000, 100000]:
        prob = np.mean(balances >= t) * 100
        if prob >= 0.01:
            print(f"    P(>= ${t:>7,}) = {prob:>6.2f}%")

    print(f"\n  Risk metrics:")
    print(f"    P(bankruptcy):         {np.mean(balances <= 0)*100:.2f}%")
    print(f"    P(below ${start_balance:.0f}):       {np.mean(balances < start_balance)*100:.2f}%")
    print(f"    Median max drawdown:   ${np.median(results['drawdowns']):,.2f}")
    print(f"    95th% max drawdown:    ${np.percentile(results['drawdowns'], 95):,.2f}")
    print(f"    Median total deals:    {int(np.median(results['deals'])):,}")

    # Position size at various outcomes
    med_final = np.median(balances)
    p95_final = np.percentile(balances, 95)
    med_size = max(min_size, min(max_size, base_size + int((med_final - start_balance) / size_step)))
    p95_size = max(min_size, min(max_size, base_size + int((p95_final - start_balance) / size_step)))
    print(f"\n  Position sizes:")
    print(f"    At median outcome (${med_final:,.0f}): {med_size} shares")
    print(f"    At 95th% outcome (${p95_final:,.0f}): {p95_size} shares")


def sensitivity(params, start_balance, n_days, base_size, size_step, min_size, max_size):
    """Quick sensitivity to win rate."""
    print(f"\n{'='*60}")
    print(f"SENSITIVITY: 1-year outcome vs win rate")
    print(f"{'='*60}")
    print(f"  {'Win Rate':>10s} {'Median':>14s} {'Mean':>14s} {'P(>=1k)':>10s} {'P(>=10k)':>10s}")
    print(f"  {'-'*60}")

    for wr in [0.490, 0.500, 0.505, 0.510, 0.515, 0.520, 0.525, 0.530, 0.540, 0.550]:
        res = run_simulation(params, n_sims=2000, n_days=n_days,
                             start_balance=start_balance,
                             base_size=base_size, size_step=size_step,
                             min_size=min_size, max_size=max_size,
                             win_rate_override=wr)
        bals = res["final"]
        p1k = np.mean(bals >= 1000) * 100
        p10k = np.mean(bals >= 10000) * 100
        marker = " <--" if abs(wr - params["win_rate"]) < 0.003 else ""
        print(f"  {wr:>9.1%}   ${np.median(bals):>13,.2f} ${np.mean(bals):>13,.2f} "
              f"{p1k:>9.1f}% {p10k:>9.1f}%{marker}")


def main():
    params = extract_params()

    start_balance = 150.0
    base_size = 6
    size_step = 50
    min_size = 5
    max_size = 1000
    n_days = 365
    n_sims = 10000

    results = run_simulation(params, n_sims=n_sims, n_days=n_days,
                             start_balance=start_balance,
                             base_size=base_size, size_step=size_step,
                             min_size=min_size, max_size=max_size)

    print_results(params, results, start_balance, n_days, base_size, size_step,
                  min_size, max_size)

    sensitivity(params, start_balance, n_days, base_size, size_step, min_size, max_size)


if __name__ == "__main__":
    main()
