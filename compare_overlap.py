#!/usr/bin/env python3
"""Compare win rate on deals that exist in BOTH live and paper logs.

Apples-to-apples comparison: same candle, same side, both bots took the trade.
This factors out trade selection differences and exposes pure execution edge.
"""

import json
import requests
from collections import defaultdict

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"
PAPER_LOG = "logs/btc_15m_mm_paper.jsonl"
GAMMA = "https://gamma-api.polymarket.com"


def load(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_resolution_cache = {}

def resolve_candle(slug):
    """Return 'UP' / 'DN' / None for a candle slug."""
    if slug in _resolution_cache:
        return _resolution_cache[slug]
    try:
        r = requests.get(f"{GAMMA}/events/slug/{slug}", timeout=10)
        if r.status_code != 200:
            return None
        mkt = r.json().get("markets", [None])[0]
        if not mkt or not mkt.get("closed"):
            return None
        outcomes = json.loads(mkt.get("outcomes", "[]"))
        prices = json.loads(mkt.get("outcomePrices", "[]"))
        if len(outcomes) < 2 or len(prices) < 2:
            return None
        up_idx = next((i for i, o in enumerate(outcomes) if o.lower() == "up"), 0)
        result = "UP" if float(prices[up_idx]) > 0.5 else "DN"
        _resolution_cache[slug] = result
        return result
    except Exception:
        return None


def main():
    paper_trades = load(PAPER_LOG)
    live_trades = load(LIVE_LOG)

    # Build slug -> list of (side, price) for buys
    paper_by_slug = defaultdict(list)
    for t in paper_trades:
        if t.get("action") == "BUY":
            paper_by_slug[t["slug"]].append((t["side"], t["price"]))

    live_by_slug = defaultdict(list)
    for t in live_trades:
        if t.get("action") == "BUY":
            live_by_slug[t["slug"]].append((t["side"], t["price"]))

    # Overlap = candles where BOTH bots had at least one BUY
    common_slugs = sorted(set(paper_by_slug.keys()) & set(live_by_slug.keys()))
    print(f"Paper candles with buys: {len(paper_by_slug)}")
    print(f"Live  candles with buys: {len(live_by_slug)}")
    print(f"Common candles: {len(common_slugs)}")
    print()

    if not common_slugs:
        print("No overlapping candles.")
        return

    # Aggregate per bot across common candles
    paper_wins = 0; paper_losses = 0
    live_wins = 0; live_losses = 0
    paper_pnl = 0.0; live_pnl = 0.0
    paper_n_deals = 0; live_n_deals = 0
    paper_total_cost = 0.0; live_total_cost = 0.0
    unresolved = 0
    SIZE = 5  # historical fills before size bump

    # Same-side comparison subset
    same_side_count = 0
    same_side_paper_cheaper = 0
    same_side_live_cheaper = 0
    same_side_equal = 0
    same_side_total_diff = 0.0  # paper - live (positive = live cheaper)

    for slug in common_slugs:
        winner = resolve_candle(slug)
        if winner is None:
            unresolved += 1
            continue

        # Paper deals on this candle
        for side, px in paper_by_slug[slug]:
            paper_n_deals += 1
            paper_total_cost += px
            if winner == side:
                paper_pnl += (1.0 - px) * SIZE
                paper_wins += 1
            else:
                paper_pnl += -px * SIZE
                paper_losses += 1

        # Live deals on this candle
        for side, px in live_by_slug[slug]:
            live_n_deals += 1
            live_total_cost += px
            if winner == side:
                live_pnl += (1.0 - px) * SIZE
                live_wins += 1
            else:
                live_pnl += -px * SIZE
                live_losses += 1

        # Same-side execution comparison
        paper_sides = {s: p for s, p in paper_by_slug[slug]}
        live_sides = {s: p for s, p in live_by_slug[slug]}
        for side in ("UP", "DN"):
            if side in paper_sides and side in live_sides:
                same_side_count += 1
                diff = paper_sides[side] - live_sides[side]
                same_side_total_diff += diff
                if diff > 0:
                    same_side_live_cheaper += 1
                elif diff < 0:
                    same_side_paper_cheaper += 1
                else:
                    same_side_equal += 1

    n = paper_wins + paper_losses + live_wins + live_losses
    if n == 0:
        print("No resolved overlaps.")
        return

    pn = paper_wins + paper_losses
    ln = live_wins + live_losses

    print(f"{'='*65}")
    print(f"COMMON CANDLES RESOLVED: {len(common_slugs) - unresolved}  (unresolved: {unresolved})")
    print(f"{'='*65}")
    print()
    print(f"{'metric':<32s} {'PAPER':>14s} {'LIVE':>14s}")
    print("-" * 62)
    print(f"{'Deals taken':<32s} {pn:>14d} {ln:>14d}")
    print(f"{'Wins':<32s} {paper_wins:>14d} {live_wins:>14d}")
    print(f"{'Losses':<32s} {paper_losses:>14d} {live_losses:>14d}")
    print(f"{'Win rate':<32s} {paper_wins/pn*100:>13.2f}% {live_wins/ln*100:>13.2f}%")
    print(f"{'Avg buy price':<32s} "
          f"{'$%.4f' % (paper_total_cost/pn):>14s} "
          f"{'$%.4f' % (live_total_cost/ln):>14s}")
    print(f"{'Total PnL (5 sh/deal)':<32s} "
          f"{'$%+.2f' % paper_pnl:>14s} "
          f"{'$%+.2f' % live_pnl:>14s}")
    print(f"{'PnL per deal':<32s} "
          f"{'$%+.4f' % (paper_pnl/pn):>14s} "
          f"{'$%+.4f' % (live_pnl/ln):>14s}")
    print(f"{'Edge per share':<32s} "
          f"{'$%+.4f' % (paper_wins/pn - paper_total_cost/pn):>14s} "
          f"{'$%+.4f' % (live_wins/ln - live_total_cost/ln):>14s}")

    print()
    print(f"{'='*65}")
    print(f"SAME-SIDE EXECUTION COMPARISON")
    print(f"{'='*65}")
    print(f"Cases where both bots bought the same side on the same candle: {same_side_count}")
    if same_side_count:
        print(f"  Live cheaper:  {same_side_live_cheaper}")
        print(f"  Same price:    {same_side_equal}")
        print(f"  Paper cheaper: {same_side_paper_cheaper}")
        print(f"  Avg saving by live: ${same_side_total_diff/same_side_count:.4f}/share")
        print(f"                    = ${same_side_total_diff/same_side_count*5:.4f}/deal (5 sh)")


if __name__ == "__main__":
    main()
