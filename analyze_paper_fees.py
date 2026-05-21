#!/usr/bin/env python3
"""Recalculate paper trading results with Polymarket taker fees applied."""

import json
from collections import defaultdict

LOG = "logs/btc_15m_mm_paper.jsonl"
FEE_RATE = 0.072  # Crypto category taker fee rate


def taker_fee(price, size):
    """Polymarket taker fee: C * feeRate * p * (1-p)"""
    return size * FEE_RATE * price * (1.0 - price)


def main():
    trades = []
    with open(LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))

    buys = [t for t in trades if t["action"] == "BUY"]
    resolves = [t for t in trades if t["action"] == "RESOLVE"]
    no_fills = [t for t in trades if t["action"] == "NO_FILL"]

    # Replay balance with fees
    balance = 100.0
    positions = {}  # slug+side -> {price, size, fee}
    total_fees = 0.0
    resolved_pnl = 0.0
    wins = 0
    losses = 0

    daily = defaultdict(lambda: {"pnl": 0.0, "fees": 0.0, "trades": 0, "wins": 0})

    for t in trades:
        if t["action"] == "BUY":
            px = t["price"]
            size = t["size"]
            fee = taker_fee(px, size)
            cost = px * size + fee
            balance -= cost
            total_fees += fee
            key = f"{t['slug']}_{t['side']}"
            positions[key] = {"price": px, "size": size, "fee": fee,
                              "slug": t["slug"], "side": t["side"]}

        elif t["action"] == "RESOLVE":
            key = f"{t['slug']}_{t['side']}"
            pos = positions.pop(key, None)
            if not pos:
                # Use data from resolve entry itself
                px = t["price"]
                size = t["size"]
                fee = taker_fee(px, size)
            else:
                px = pos["price"]
                size = pos["size"]
                fee = pos["fee"]

            won = t.get("won", False)
            if won:
                balance += size  # $1/share payout
                pnl = (1.0 - px) * size - fee
                wins += 1
            else:
                pnl = -px * size - fee
                losses += 1

            resolved_pnl += pnl
            day = t["timestamp"][:10]
            daily[day]["pnl"] += pnl
            daily[day]["fees"] += fee
            daily[day]["trades"] += 1
            if won:
                daily[day]["wins"] += 1

    # Original PnL (no fees)
    orig_pnl = sum(r.get("pnl", 0) for r in resolves)
    orig_balance = 100.0 + orig_pnl

    print(f"{'='*60}")
    print(f"PAPER RESULTS: NO FEES vs WITH TAKER FEES")
    print(f"{'='*60}")
    print(f"")
    print(f"Fee formula: shares × {FEE_RATE} × price × (1 - price)")
    print(f"Fee at $0.50: ${taker_fee(0.50, 5):.3f} per 5-share trade")
    print(f"Fee at $0.46: ${taker_fee(0.46, 5):.3f} per 5-share trade")
    print(f"Fee at $0.48: ${taker_fee(0.48, 5):.3f} per 5-share trade")
    print(f"")
    print(f"  {'':>20s}  {'No Fees':>10s}  {'With Fees':>10s}  {'Diff':>10s}")
    print(f"  {'─'*20}  {'─'*10}  {'─'*10}  {'─'*10}")
    print(f"  {'Total PnL':>20s}  ${orig_pnl:>9.2f}  ${resolved_pnl:>9.2f}  ${resolved_pnl - orig_pnl:>9.2f}")
    print(f"  {'Total fees paid':>20s}  ${'0.00':>9s}  ${total_fees:>9.2f}")
    print(f"  {'Final balance':>20s}  ${orig_balance:>9.2f}  ${balance:>9.2f}")
    print(f"  {'Win rate':>20s}  {wins}/{wins+losses} = {wins/(wins+losses)*100:.1f}%")
    print(f"  {'Avg fee per trade':>20s}  ${'0.00':>9s}  ${total_fees/len(buys):>9.3f}")

    # Open positions cost
    open_cost = sum(p["price"] * p["size"] + p["fee"] for p in positions.values())
    print(f"  {'Open pos cost':>20s}  ${open_cost:>9.2f} ({len(positions)} positions)")
    print(f"  {'Total equity':>20s}  ${orig_balance:>9.2f}  ${balance + open_cost:>9.2f}")

    print(f"\n{'='*60}")
    print(f"DAILY BREAKDOWN (with fees)")
    print(f"{'='*60}")
    for day in sorted(daily):
        d = daily[day]
        wr = d["wins"]/d["trades"]*100 if d["trades"] else 0
        print(f"  {day}: {d['trades']:3d} trades, {d['wins']:3d} wins ({wr:5.1f}%), "
              f"PnL=${d['pnl']:+7.2f}, fees=${d['fees']:.2f}")

    # Break-even analysis
    print(f"\n{'='*60}")
    print(f"BREAK-EVEN ANALYSIS")
    print(f"{'='*60}")
    avg_buy_px = sum(b["price"] for b in buys) / len(buys)
    avg_fee = taker_fee(avg_buy_px, 5)
    print(f"Avg buy price: ${avg_buy_px:.3f}")
    print(f"Avg fee per trade: ${avg_fee:.3f}")
    print(f"Fee as % of cost: {avg_fee/(avg_buy_px*5)*100:.2f}%")
    print(f"")
    print(f"To break even on a single-leg trade at ${avg_buy_px:.2f}:")
    print(f"  Win payout:  ${5*(1-avg_buy_px) - avg_fee:.3f}")
    print(f"  Loss cost:   ${5*avg_buy_px + avg_fee:.3f}")
    print(f"  Break-even win rate needed: {(avg_buy_px*5 + avg_fee) / (5 + 2*avg_fee) * 100:.1f}%")
    print(f"  Actual win rate: {wins/(wins+losses)*100:.1f}%")


if __name__ == "__main__":
    main()
