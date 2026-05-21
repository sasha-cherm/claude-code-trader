#!/usr/bin/env python3
"""Verify paper trading win rate by streak."""

import json
from collections import defaultdict

LOG = "logs/btc_15m_mm_paper.jsonl"


def main():
    trades = []
    with open(LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))

    # Index buys by (slug, side) to capture streak
    buy_streak = {}  # (slug, side) -> streak
    buy_price = {}
    for t in trades:
        if t.get("action") == "BUY":
            key = (t["slug"], t["side"])
            buy_streak[key] = t.get("streak", "?")
            buy_price[key] = t.get("price")

    # Match resolves to streaks
    streak_stats = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0,
                                          "up_n": 0, "up_wins": 0,
                                          "dn_n": 0, "dn_wins": 0})

    for t in trades:
        if t.get("action") != "RESOLVE":
            continue
        key = (t["slug"], t["side"])
        streak = buy_streak.get(key, "?")
        s = streak_stats[streak]
        s["n"] += 1
        if t.get("won"):
            s["wins"] += 1
        s["pnl"] += t.get("pnl", 0)
        if t["side"] == "UP":
            s["up_n"] += 1
            if t.get("won"):
                s["up_wins"] += 1
        else:
            s["dn_n"] += 1
            if t.get("won"):
                s["dn_wins"] += 1

    print(f"{'='*70}")
    print(f"PAPER TRADING WIN RATE BY STREAK")
    print(f"{'='*70}")
    print(f"{'Streak':<10s} {'N':>5s} {'Wins':>6s} {'WR':>7s} "
          f"{'UP':>6s} {'UP-W':>5s} {'UP-WR':>7s} "
          f"{'DN':>6s} {'DN-W':>5s} {'DN-WR':>7s} {'PnL':>9s}")
    print("─" * 90)

    for streak in sorted(streak_stats, key=lambda s: streak_stats[s]["n"], reverse=True):
        s = streak_stats[streak]
        wr = s["wins"] / s["n"] * 100 if s["n"] else 0
        up_wr = s["up_wins"] / s["up_n"] * 100 if s["up_n"] else 0
        dn_wr = s["dn_wins"] / s["dn_n"] * 100 if s["dn_n"] else 0
        print(f"{streak:<10s} {s['n']:>5d} {s['wins']:>6d} {wr:>6.1f}% "
              f"{s['up_n']:>6d} {s['up_wins']:>5d} {up_wr:>6.1f}% "
              f"{s['dn_n']:>6d} {s['dn_wins']:>5d} {dn_wr:>6.1f}% "
              f"${s['pnl']:>+8.2f}")

    # Specific question: 2xDN streak
    print(f"\n{'='*70}")
    print(f"FOCUS: 2xDN STREAK")
    print(f"{'='*70}")
    print(f"Backtest table predicts: P(next=UP) = 57.5% after 2xDN")
    s = streak_stats.get("2xDN")
    if s:
        up_wr = s["up_wins"] / s["up_n"] * 100 if s["up_n"] else 0
        print(f"Paper trading observed:")
        print(f"  Total resolves on 2xDN: {s['n']}")
        print(f"  UP buys (betting next will be UP):  {s['up_n']:3d}, won {s['up_wins']:3d} ({up_wr:.1f}%)")
        dn_wr = s["dn_wins"] / s["dn_n"] * 100 if s["dn_n"] else 0
        print(f"  DN buys (betting next will be DN):  {s['dn_n']:3d}, won {s['dn_wins']:3d} ({dn_wr:.1f}%)")
        # The win rate of UP buys is the empirical P(next=UP)
        if s["up_n"]:
            se = (up_wr/100 * (1 - up_wr/100) / s["up_n"]) ** 0.5 * 100
            print(f"\nEmpirical P(next=UP|2xDN) = {up_wr:.1f}% ± {se:.1f}% (1σ)")
            print(f"Backtest claim: 57.5%  → diff: {up_wr - 57.5:+.1f}%")


if __name__ == "__main__":
    main()
