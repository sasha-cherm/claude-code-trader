#!/usr/bin/env python3
"""Compare paper vs live on COMMON candles, split by size period."""

import json
import requests
from collections import defaultdict

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"
PAPER_LOG = "logs/btc_15m_mm_paper.jsonl"
GAMMA = "https://gamma-api.polymarket.com"

_cache = {}
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
    return [json.loads(l) for l in open(path) if l.strip()]


def analyze(paper_buys_by_slug, live_buys_by_slug, slugs, label):
    p_wins = p_loss = l_wins = l_loss = 0
    p_pnl = l_pnl = 0.0
    p_n = l_n = 0
    p_cost = l_cost = 0.0
    unresolved = 0

    for slug in slugs:
        winner = resolve(slug)
        if winner is None:
            unresolved += 1
            continue
        for side, px, size in paper_buys_by_slug.get(slug, []):
            p_n += 1
            p_cost += px
            if winner == side:
                p_pnl += (1.0 - px) * 5  # normalize to 5-share units
                p_wins += 1
            else:
                p_pnl += -px * 5
                p_loss += 1
        for side, px, size in live_buys_by_slug.get(slug, []):
            l_n += 1
            l_cost += px
            if winner == side:
                l_pnl += (1.0 - px) * 5  # normalize
                l_wins += 1
            else:
                l_pnl += -px * 5
                l_loss += 1

    if p_n == 0 or l_n == 0:
        return

    print(f"\n{'='*65}")
    print(f"  {label}  ({len(slugs) - unresolved} resolved / {len(slugs)} common candles)")
    print(f"{'='*65}")
    print(f"  {'metric':<24s} {'PAPER':>14s} {'LIVE':>14s}")
    print(f"  {'-'*52}")
    print(f"  {'Deals':<24s} {p_n:>14d} {l_n:>14d}")
    print(f"  {'Wins / Losses':<24s} {f'{p_wins}/{p_loss}':>14s} {f'{l_wins}/{l_loss}':>14s}")
    print(f"  {'Win rate':<24s} {p_wins/p_n*100:>13.2f}% {l_wins/l_n*100:>13.2f}%")
    print(f"  {'Avg buy price':<24s} {'$%.4f' % (p_cost/p_n):>14s} {'$%.4f' % (l_cost/l_n):>14s}")
    print(f"  {'Total PnL (5sh)':<24s} {'$%+.2f' % p_pnl:>14s} {'$%+.2f' % l_pnl:>14s}")
    print(f"  {'PnL per deal':<24s} {'$%+.4f' % (p_pnl/p_n):>14s} {'$%+.4f' % (l_pnl/l_n):>14s}")
    print(f"  {'Edge/share':<24s} "
          f"{'$%+.4f' % (p_wins/p_n - p_cost/p_n):>14s} "
          f"{'$%+.4f' % (l_wins/l_n - l_cost/l_n):>14s}")


def main():
    paper = load(PAPER_LOG)
    live = load(LIVE_LOG)

    paper_buys = defaultdict(list)
    for t in paper:
        if t.get("action") == "BUY":
            paper_buys[t["slug"]].append((t["side"], t["price"], t["size"]))

    live_buys = defaultdict(list)
    live_buys_size5 = defaultdict(list)
    live_buys_size6 = defaultdict(list)
    for t in live:
        if t.get("action") == "BUY":
            key = t["slug"]
            tup = (t["side"], t["price"], t["size"])
            live_buys[key].append(tup)
            if t["size"] == 5.0:
                live_buys_size5[key].append(tup)
            elif t["size"] == 6.0:
                live_buys_size6[key].append(tup)

    size5_slugs = set(live_buys_size5) & set(paper_buys)
    size6_slugs = set(live_buys_size6) & set(paper_buys)
    all_slugs = set(live_buys) & set(paper_buys)

    analyze(paper_buys, live_buys, all_slugs, "OVERALL (all common candles)")
    analyze(paper_buys, live_buys_size5, size5_slugs, "PERIOD 1 — size=5 (Apr 6-8)")
    analyze(paper_buys, live_buys_size6, size6_slugs, "PERIOD 2 — size=6 (Apr 8-9)")


if __name__ == "__main__":
    main()
