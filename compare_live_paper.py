#!/usr/bin/env python3
"""Compare live vs paper trading on overlapping candles."""

import json
from collections import defaultdict
from datetime import datetime

LIVE = "logs/btc_15m_mm_live.jsonl"
PAPER = "logs/btc_15m_mm_paper.jsonl"


def load(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def find_window(live):
    """Find time window covered by live log."""
    ts = [l["timestamp"] for l in live if "timestamp" in l]
    return min(ts), max(ts)


def main():
    live = load(LIVE)
    paper = load(PAPER)

    if not live:
        print("No live entries yet")
        return

    live_start, live_end = find_window(live)
    print(f"Live log window: {live_start} → {live_end}")
    print(f"Live entries: {len(live)}, Paper entries: {len(paper)}")
    print()

    # Build per-candle dicts
    def build_candle_map(entries):
        """slug -> {up: leg_info, dn: leg_info}"""
        out = defaultdict(lambda: {"UP": {}, "DN": {}, "candle": None,
                                     "streak": None, "rsi": None, "fair_up": None})
        for e in entries:
            slug = e.get("slug")
            if not slug:
                continue
            side = e.get("side")
            action = e.get("action")
            if "candle" in e:
                out[slug]["candle"] = e["candle"]
            if "streak" in e:
                out[slug]["streak"] = e["streak"]
            if "rsi" in e:
                out[slug]["rsi"] = e["rsi"]
            if "fair_up" in e:
                out[slug]["fair_up"] = e["fair_up"]
            if side in ("UP", "DN"):
                leg = out[slug][side]
                if action == "PLACE":
                    leg["placed"] = True
                    leg["place_px"] = e.get("price")
                    leg["target"] = e.get("target", e.get("price"))
                    leg["best_ask"] = e.get("best_ask")
                if action == "BUY":
                    leg["filled"] = True
                    leg["fill_px"] = e.get("price")
                    if "target" in e:
                        leg["target"] = e["target"]
                if action == "CANCEL":
                    leg["cancelled"] = True
                if action == "RESULT":
                    leg["status"] = e.get("status")
                    if "place_px" in e:
                        leg["place_px"] = e["place_px"]
                if action == "RESOLVE":
                    leg["resolved"] = True
                    leg["won"] = e.get("won")
                    leg["pnl"] = e.get("pnl")
                    leg["result"] = e.get("result")
        return out

    live_map = build_candle_map(live)
    paper_map = build_candle_map(paper)

    # Find candles that appear in live (within live window)
    live_slugs = set(live_map.keys())
    common_slugs = sorted(live_slugs & set(paper_map.keys()))
    live_only = live_slugs - set(paper_map.keys())
    paper_only = set(paper_map.keys()) - live_slugs

    print(f"Candles in live: {len(live_slugs)}")
    print(f"Candles in both: {len(common_slugs)}")
    print(f"Live-only (paper missed): {len(live_only)}")
    print()

    # Per-candle comparison table
    print(f"{'='*110}")
    print(f"PER-CANDLE COMPARISON (live window only)")
    print(f"{'='*110}")
    header = f"{'slug suffix':<14s} {'streak':<6s} {'fair':<5s} | {'PAPER UP':<14s} {'PAPER DN':<14s} | {'LIVE UP':<14s} {'LIVE DN':<14s}"
    print(header)
    print("─" * 110)

    def fmt_leg(leg):
        if not leg:
            return "—"
        if leg.get("filled"):
            px = leg.get("fill_px")
            return f"FILL@{px:.2f}" if px is not None else "FILL"
        if leg.get("placed"):
            px = leg.get("place_px")
            return f"open@{px:.2f}" if px is not None else "open"
        if leg.get("status") == "NEVER_PLACED":
            return "skipped"
        return "—"

    paper_fills_up = 0; paper_fills_dn = 0
    live_fills_up = 0; live_fills_dn = 0
    paper_placed_up = 0; paper_placed_dn = 0
    live_placed_up = 0; live_placed_dn = 0

    for slug in common_slugs:
        ts = slug.replace("btc-updown-15m-", "")
        l = live_map[slug]
        p = paper_map[slug]
        streak = l.get("streak") or p.get("streak") or "?"
        fair = l.get("fair_up") or p.get("fair_up")
        fair_s = f"{fair:.2f}" if fair else "?"

        p_up = fmt_leg(p["UP"]); p_dn = fmt_leg(p["DN"])
        l_up = fmt_leg(l["UP"]); l_dn = fmt_leg(l["DN"])

        if p["UP"].get("filled"): paper_fills_up += 1
        if p["DN"].get("filled"): paper_fills_dn += 1
        if l["UP"].get("filled"): live_fills_up += 1
        if l["DN"].get("filled"): live_fills_dn += 1
        if p["UP"].get("placed") or p["UP"].get("filled"): paper_placed_up += 1
        if p["DN"].get("placed") or p["DN"].get("filled"): paper_placed_dn += 1
        if l["UP"].get("placed") or l["UP"].get("filled"): live_placed_up += 1
        if l["DN"].get("placed") or l["DN"].get("filled"): live_placed_dn += 1

        print(f"{ts:<14s} {streak:<6s} {fair_s:<5s} | {p_up:<14s} {p_dn:<14s} | {l_up:<14s} {l_dn:<14s}")

    n = len(common_slugs)
    print()
    print(f"{'='*70}")
    print(f"AGGREGATE OVER {n} OVERLAPPING CANDLES")
    print(f"{'='*70}")
    print(f"{'':<20s} {'PAPER':>15s} {'LIVE':>15s}")
    print(f"{'─'*55}")
    print(f"{'UP placed':<20s} {paper_placed_up:>15d} {live_placed_up:>15d}")
    print(f"{'UP filled':<20s} {paper_fills_up:>15d} {live_fills_up:>15d}")
    if paper_placed_up:
        print(f"{'UP fill rate':<20s} {paper_fills_up/paper_placed_up*100:>14.1f}%", end="")
    else:
        print(f"{'UP fill rate':<20s} {'—':>15s}", end="")
    if live_placed_up:
        print(f" {live_fills_up/live_placed_up*100:>14.1f}%")
    else:
        print(f" {'—':>15s}")
    print()
    print(f"{'DN placed':<20s} {paper_placed_dn:>15d} {live_placed_dn:>15d}")
    print(f"{'DN filled':<20s} {paper_fills_dn:>15d} {live_fills_dn:>15d}")
    if paper_placed_dn:
        print(f"{'DN fill rate':<20s} {paper_fills_dn/paper_placed_dn*100:>14.1f}%", end="")
    else:
        print(f"{'DN fill rate':<20s} {'—':>15s}", end="")
    if live_placed_dn:
        print(f" {live_fills_dn/live_placed_dn*100:>14.1f}%")
    else:
        print(f" {'—':>15s}")

    paper_total_fills = paper_fills_up + paper_fills_dn
    live_total_fills = live_fills_up + live_fills_dn
    print()
    print(f"{'TOTAL fills':<20s} {paper_total_fills:>15d} {live_total_fills:>15d}")
    print(f"{'  per candle':<20s} {paper_total_fills/n if n else 0:>15.2f} {live_total_fills/n if n else 0:>15.2f}")

    # USDC balance
    print()
    print(f"{'='*70}")
    print(f"BALANCES")
    print(f"{'='*70}")
    try:
        with open("mm_paper_state.json") as f:
            ps = json.load(f)
        print(f"Paper balance: ${ps['balance']:.2f}  + {len(ps['positions'])} open positions")
    except Exception:
        pass

    try:
        from trader.client import get_client, get_usdc_balance
        c = get_client()
        live_bal = get_usdc_balance(c)
        print(f"Live USDC:     ${live_bal:.2f}")
    except Exception as e:
        print(f"Live balance err: {e}")


if __name__ == "__main__":
    main()
