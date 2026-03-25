#!/usr/bin/env python3
"""Quick near-res monitor for Nuggets vs Suns (March 24, tipoff 03:00 UTC March 25)."""
import os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from trader.client import get_client, get_usdc_balance
from trader.strategy import place_market_buy, get_actual_shares, load_state, save_state
from trader.notify import send

GAMES = [
    {"name": "Nuggets", "token_id": "23233394988453138676453756568931964683203148302915027263468721213424953033444",
     "end_date": "2026-03-25T05:30:00Z", "pre_game_price": 0.68,
     "question": "Nuggets vs. Suns"},
    {"name": "Suns", "token_id": "96641301590558848799981015724831293565424869668527634336704268465596562110754",
     "end_date": "2026-03-25T05:30:00Z", "pre_game_price": 0.31,
     "question": "Nuggets vs. Suns"},
]

MIN_PRICE = 0.85
MAX_PRICE = 0.96
MIN_JUMP = 0.20
MAX_SPREAD = 0.04
MAX_MINS = 20
MAX_SPEND = 8.0
MIN_SPEND = 1.0
PCT = 0.28
BOUGHT = set()
count = 0

client = get_client()
print(f"=== Nuggets vs Suns Near-Res ===")
print(f"Balance: ${get_usdc_balance(client):.2f}")
print(f"Started {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")

end_time = datetime(2026, 3, 25, 5, 35, tzinfo=timezone.utc)
while datetime.now(timezone.utc) < end_time:
    now = datetime.now(timezone.utc)
    balance = get_usdc_balance(client)
    print(f"\n--- #{count} {now.strftime('%H:%M:%S')} bal=${balance:.2f} ---")
    count += 1

    for w in GAMES:
        if w["token_id"] in BOUGHT:
            continue
        try:
            bp = float(client.get_price(w["token_id"], "buy").get("price", 0))
            sp = float(client.get_price(w["token_id"], "sell").get("price", 0))
            jump = bp - w["pre_game_price"]
            spread = bp - sp
            end_dt = datetime.fromisoformat(w["end_date"].replace("Z", "+00:00"))
            mins = (end_dt - now).total_seconds() / 60

            trigger = (bp >= MIN_PRICE and bp <= MAX_PRICE and jump >= MIN_JUMP and
                      abs(spread) < MAX_SPREAD and mins <= MAX_MINS and mins > 0 and balance >= MIN_SPEND)

            if abs(jump) > 0.05 or bp >= 0.80:
                tag = "***BUY***" if trigger else ""
                print(f"  {w['name']:8s} buy={bp:.3f} sell={sp:.3f} jump={jump:+.3f} mins={mins:.0f} {tag}")

            if trigger:
                spend = min(MAX_SPEND, balance * PCT)
                if spend < MIN_SPEND:
                    continue
                print(f"  *** BUYING {w['name']} @ {bp:.3f} for ${spend:.2f} ***")
                result = place_market_buy(client, w["token_id"], spend)
                if result:
                    time.sleep(2)
                    shares = get_actual_shares(client, w["token_id"])
                    state = load_state()
                    state["positions"].append({
                        "token_id": w["token_id"], "market_id": f"near-res-denphx-{w['name'].lower()}",
                        "question": w["question"], "side": "YES", "entry_price": bp,
                        "fair_price": min(bp + 0.08, 0.99), "edge": jump,
                        "size_usdc": spend, "shares": shares if shares > 0 else spend / bp,
                        "end_date": w["end_date"], "days_left_at_entry": mins / 1440,
                        "opened_at": str(now),
                        "research_note": f"DEN-PHX near-res: {w['name']} jumped {jump:+.3f}, {mins:.0f} min left.",
                    })
                    save_state(state)
                    BOUGHT.add(w["token_id"])
                    for o in GAMES:
                        if o["question"] == w["question"] and o["token_id"] != w["token_id"]:
                            BOUGHT.add(o["token_id"])
                    send(f"DEN-PHX BUY: {w['name']} @ {bp:.3f}, ${spend:.2f}, {mins:.0f}m left")
        except Exception as e:
            if "404" not in str(e):
                print(f"  {w['name']}: {str(e)[:60]}")
    time.sleep(70)

print(f"\n=== Done {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ===")
