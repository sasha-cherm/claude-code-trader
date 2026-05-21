#!/usr/bin/env python3
"""Compare paper vs live PnL with edge analysis."""

import json
import requests
from collections import defaultdict

LIVE_LOG = "logs/btc_15m_mm_live.jsonl"
PAPER_LOG = "logs/btc_15m_mm_paper.jsonl"
GAMMA = "https://gamma-api.polymarket.com"


def load(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out


# ─── Resolve a candle's outcome via Gamma API ────────────────────────────────
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
            _resolution_cache[slug] = None
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


def analyze_paper():
    """Paper bot has explicit RESOLVE entries — easy."""
    trades = load(PAPER_LOG)
    buys = [t for t in trades if t.get("action") == "BUY"]
    resolves = [t for t in trades if t.get("action") == "RESOLVE"]

    wins = [r for r in resolves if r.get("won")]
    losses = [r for r in resolves if not r.get("won")]
    total_pnl = sum(r.get("pnl", 0) for r in resolves)

    avg_buy_price = sum(b["price"] for b in buys) / len(buys) if buys else 0
    win_rate = len(wins) / len(resolves) if resolves else 0
    edge_per_share = win_rate - avg_buy_price
    edge_per_deal = edge_per_share * 5

    return {
        "label": "PAPER",
        "n_buys": len(buys),
        "n_resolved": len(resolves),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_buy_price": avg_buy_price,
        "total_pnl": total_pnl,
        "realized_pnl_per_deal": total_pnl / len(resolves) if resolves else 0,
        "edge_per_share": edge_per_share,
        "edge_per_deal": edge_per_deal,
    }


def analyze_live():
    """Live bot needs Gamma API resolution for each unique candle slug."""
    trades = load(LIVE_LOG)
    buys = [t for t in trades if t.get("action") == "BUY"]

    if not buys:
        return None

    print(f"Resolving {len(set(b['slug'] for b in buys))} unique live candles...")
    pnls = []
    wins = 0
    losses = 0
    unresolved = 0

    for b in buys:
        slug = b["slug"]
        side = b["side"]
        price = b["price"]
        size = b["size"]
        winner = resolve_candle(slug)
        if winner is None:
            unresolved += 1
            continue
        if winner == side:
            pnl = (1.0 - price) * size  # win: receive $1/share, paid `price`/share
            wins += 1
        else:
            pnl = -price * size           # loss: lose entire stake
            losses += 1
        pnls.append(pnl)

    total_pnl = sum(pnls)
    n_resolved = wins + losses
    avg_buy_price = sum(b["price"] for b in buys) / len(buys)
    win_rate = wins / n_resolved if n_resolved else 0
    edge_per_share = win_rate - avg_buy_price
    edge_per_deal = edge_per_share * 5

    return {
        "label": "LIVE",
        "n_buys": len(buys),
        "n_resolved": n_resolved,
        "n_unresolved": unresolved,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_buy_price": avg_buy_price,
        "total_pnl": total_pnl,
        "realized_pnl_per_deal": total_pnl / n_resolved if n_resolved else 0,
        "edge_per_share": edge_per_share,
        "edge_per_deal": edge_per_deal,
    }


def fmt_row(label, value, fmt="{:.4f}"):
    return f"  {label:<28s} {fmt.format(value)}"


def print_stats(s):
    print(f"\n{'='*60}")
    print(f"  {s['label']}")
    print(f"{'='*60}")
    print(fmt_row("BUY entries:", s["n_buys"], "{:d}"))
    print(fmt_row("Resolved:", s["n_resolved"], "{:d}"))
    if "n_unresolved" in s:
        print(fmt_row("Unresolved:", s["n_unresolved"], "{:d}"))
    print(fmt_row("Wins:", s["wins"], "{:d}"))
    print(fmt_row("Losses:", s["losses"], "{:d}"))
    print(fmt_row("Win rate:", s["win_rate"] * 100, "{:.2f}%"))
    print(fmt_row("Avg buy price:", s["avg_buy_price"], "${:.4f}"))
    print(fmt_row("Total PnL (realized):", s["total_pnl"], "${:+.2f}"))
    print(fmt_row("PnL per deal:", s["realized_pnl_per_deal"], "${:+.4f}"))
    print(fmt_row("Edge per share:", s["edge_per_share"], "${:+.4f}"))
    print(fmt_row("Edge per deal (5sh):", s["edge_per_deal"], "${:+.4f}"))


def main():
    paper = analyze_paper()
    live = analyze_live()

    print_stats(paper)
    if live:
        print_stats(live)

    if live:
        print()
        print("=" * 60)
        print("  PAPER vs LIVE")
        print("=" * 60)
        print(f"  {'metric':<28s} {'PAPER':>12s} {'LIVE':>12s}")
        print(f"  {'-'*52}")
        print(f"  {'BUY entries':<28s} {paper['n_buys']:>12d} {live['n_buys']:>12d}")
        print(f"  {'Resolved':<28s} {paper['n_resolved']:>12d} {live['n_resolved']:>12d}")
        print(f"  {'Win rate':<28s} {paper['win_rate']*100:>11.2f}% {live['win_rate']*100:>11.2f}%")
        p_avg = "$%.4f" % paper["avg_buy_price"]
        l_avg = "$%.4f" % live["avg_buy_price"]
        print(f"  {'Avg buy price':<28s} {p_avg:>12s} {l_avg:>12s}")
        p_pnl = "$%+.2f" % paper["total_pnl"]
        l_pnl = "$%+.2f" % live["total_pnl"]
        print(f"  {'Total realized PnL':<28s} {p_pnl:>12s} {l_pnl:>12s}")
        p_pd = "$%+.4f" % paper["realized_pnl_per_deal"]
        l_pd = "$%+.4f" % live["realized_pnl_per_deal"]
        print(f"  {'PnL per deal':<28s} {p_pd:>12s} {l_pd:>12s}")
        p_es = "$%+.4f" % paper["edge_per_share"]
        l_es = "$%+.4f" % live["edge_per_share"]
        print(f"  {'Edge per share':<28s} {p_es:>12s} {l_es:>12s}")
        p_ed = "$%+.4f" % paper["edge_per_deal"]
        l_ed = "$%+.4f" % live["edge_per_deal"]
        print(f"  {'Edge per deal':<28s} {p_ed:>12s} {l_ed:>12s}")


if __name__ == "__main__":
    main()
