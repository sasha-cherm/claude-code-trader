#!/usr/bin/env python3
"""Analyze paper trading results from btc_15m_mm_paper.jsonl."""

import json
from collections import Counter, defaultdict
from datetime import datetime

LOG = "logs/btc_15m_mm_paper.jsonl"

def load_trades():
    trades = []
    with open(LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades

def main():
    trades = load_trades()
    print(f"Total log entries: {len(trades)}")

    # Separate by action
    actions = Counter(t["action"] for t in trades)
    print(f"\nActions: {dict(actions)}")

    buys = [t for t in trades if t["action"] == "BUY"]
    resolves = [t for t in trades if t["action"] == "RESOLVE"]
    no_fills = [t for t in trades if t["action"] == "NO_FILL"]

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total BUYs:      {len(buys)}")
    print(f"Total RESOLVEs:  {len(resolves)}")
    print(f"Total NO_FILLs:  {len(no_fills)}")

    # Buy analysis
    if buys:
        up_buys = [b for b in buys if b.get("side") == "UP"]
        dn_buys = [b for b in buys if b.get("side") == "DN"]
        print(f"\nBuys: {len(up_buys)} UP + {len(dn_buys)} DN")

        prices = [b["price"] for b in buys]
        print(f"Avg buy price: ${sum(prices)/len(prices):.3f}")
        print(f"Min buy price: ${min(prices):.3f}")
        print(f"Max buy price: ${max(prices):.3f}")

    # Both-legs analysis: find candles where we bought both UP and DN
    buy_by_slug = defaultdict(list)
    for b in buys:
        buy_by_slug[b["slug"]].append(b)

    both_legs = 0
    single_legs = 0
    guaranteed_profit = 0.0
    for slug, legs in buy_by_slug.items():
        sides = set(l["side"] for l in legs)
        if "UP" in sides and "DN" in sides:
            both_legs += 1
            up_px = next(l["price"] for l in legs if l["side"] == "UP")
            dn_px = next(l["price"] for l in legs if l["side"] == "DN")
            size = legs[0]["size"]
            profit = (1.0 - up_px - dn_px) * size
            guaranteed_profit += profit
        else:
            single_legs += 1

    print(f"\nCandles with both legs: {both_legs}")
    print(f"Candles with single leg: {single_legs}")
    if both_legs:
        print(f"Guaranteed profit from both-leg candles: ${guaranteed_profit:.2f}")
        print(f"Avg guaranteed profit per both-leg: ${guaranteed_profit/both_legs:.3f}")

    # Resolution analysis
    if resolves:
        wins = [r for r in resolves if r.get("won")]
        losses = [r for r in resolves if not r.get("won")]
        print(f"\n{'='*60}")
        print(f"RESOLUTIONS")
        print(f"{'='*60}")
        print(f"Wins:   {len(wins)}")
        print(f"Losses: {len(losses)}")
        print(f"Win rate: {len(wins)/len(resolves)*100:.1f}%")

        total_pnl = sum(r.get("pnl", 0) for r in resolves)
        win_pnl = sum(r.get("pnl", 0) for r in wins)
        loss_pnl = sum(r.get("pnl", 0) for r in losses)
        print(f"\nTotal PnL:  ${total_pnl:+.2f}")
        print(f"Win PnL:    ${win_pnl:+.2f}")
        print(f"Loss PnL:   ${loss_pnl:+.2f}")
        if wins:
            print(f"Avg win:    ${win_pnl/len(wins):+.3f}")
        if losses:
            print(f"Avg loss:   ${loss_pnl/len(losses):+.3f}")

        # PnL by side
        up_resolves = [r for r in resolves if r.get("side") == "UP"]
        dn_resolves = [r for r in resolves if r.get("side") == "DN"]
        up_pnl = sum(r.get("pnl", 0) for r in up_resolves)
        dn_pnl = sum(r.get("pnl", 0) for r in dn_resolves)
        up_wins = sum(1 for r in up_resolves if r.get("won"))
        dn_wins = sum(1 for r in dn_resolves if r.get("won"))
        print(f"\nUP: {len(up_resolves)} trades, {up_wins} wins, PnL=${up_pnl:+.2f}")
        print(f"DN: {len(dn_resolves)} trades, {dn_wins} wins, PnL=${dn_pnl:+.2f}")

    # Daily breakdown
    if resolves:
        print(f"\n{'='*60}")
        print(f"DAILY BREAKDOWN")
        print(f"{'='*60}")
        daily = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for r in resolves:
            ts = r.get("timestamp", "")[:10]
            daily[ts]["trades"] += 1
            if r.get("won"):
                daily[ts]["wins"] += 1
            daily[ts]["pnl"] += r.get("pnl", 0)

        for day in sorted(daily):
            d = daily[day]
            wr = d["wins"]/d["trades"]*100 if d["trades"] else 0
            print(f"  {day}: {d['trades']:3d} trades, {d['wins']:3d} wins ({wr:5.1f}%), PnL=${d['pnl']:+.2f}")

    # Streak analysis: wins/losses by streak
    if resolves:
        print(f"\n{'='*60}")
        print(f"PnL BY STREAK")
        print(f"{'='*60}")
        streak_stats = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
        for r in resolves:
            streak = r.get("streak", "0xNONE")
            # Match back to the buy to get streak
            streak_stats[streak]["n"] += 1
            if r.get("won"):
                streak_stats[streak]["wins"] += 1
            streak_stats[streak]["pnl"] += r.get("pnl", 0)

        for streak in sorted(streak_stats, key=lambda s: streak_stats[s]["n"], reverse=True):
            s = streak_stats[streak]
            wr = s["wins"]/s["n"]*100 if s["n"] else 0
            print(f"  {streak:>8s}: {s['n']:3d} trades, {s['wins']:3d} wins ({wr:5.1f}%), PnL=${s['pnl']:+.2f}")

    # Balance over time
    if buys or resolves:
        print(f"\n{'='*60}")
        print(f"BALANCE PROGRESSION")
        print(f"{'='*60}")
        all_with_bal = sorted(
            [t for t in trades if "balance" in t and "timestamp" in t],
            key=lambda t: t["timestamp"]
        )
        if all_with_bal:
            print(f"  Start:   ${100.00:.2f}")
            # Show first and last of each day
            by_day = defaultdict(list)
            for t in all_with_bal:
                by_day[t["timestamp"][:10]].append(t)
            for day in sorted(by_day):
                last = by_day[day][-1]
                print(f"  {day}: ${last['balance']:.2f}")

    # Fill rate
    total_candles = len(buy_by_slug) + len(no_fills)
    if total_candles:
        print(f"\n{'='*60}")
        print(f"FILL RATE")
        print(f"{'='*60}")
        print(f"Candles attempted: {total_candles}")
        print(f"At least one fill: {len(buy_by_slug)} ({len(buy_by_slug)/total_candles*100:.1f}%)")
        print(f"Both legs filled:  {both_legs} ({both_legs/total_candles*100:.1f}%)")
        print(f"No fill:           {len(no_fills)} ({len(no_fills)/total_candles*100:.1f}%)")

    # Current state
    print(f"\n{'='*60}")
    print(f"CURRENT STATE")
    print(f"{'='*60}")
    try:
        with open("mm_paper_state.json") as f:
            state = json.load(f)
        print(f"Balance: ${state['balance']:.2f}")
        print(f"Open positions: {len(state['positions'])}")
        for p in state["positions"]:
            print(f"  {p['slug']} {p['side']} @ {p['price']:.2f} ({p['size']} shares)")
        # Total equity = balance + sum of position costs (they'll resolve to $5 or $0)
        pos_cost = sum(p["price"] * p["size"] for p in state["positions"])
        print(f"Position cost: ${pos_cost:.2f}")
        print(f"Total equity (balance + position cost): ${state['balance'] + pos_cost:.2f}")
    except Exception as e:
        print(f"State error: {e}")


if __name__ == "__main__":
    main()
