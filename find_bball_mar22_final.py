import requests
import json

GAMMA = "https://gamma-api.polymarket.com"

print("="*60)
print("NBA & NCAAB TOKEN IDS FOR MARCH 22, 2026")
print("="*60)

# From the search, basketball markets are spread across windows.
# NBA games with March 22 date in slug end between 22:00 Mar 22 and 06:00 Mar 23 UTC
# CBB games are in the 00:00-06:00 Mar 23 window

# Collect ALL markets in the relevant windows
all_markets = []
for start, end in [
    ("2026-03-22T18:00:00Z", "2026-03-23T00:00:00Z"),
    ("2026-03-23T00:00:00Z", "2026-03-23T06:00:00Z"),
    ("2026-03-23T06:00:00Z", "2026-03-23T12:00:00Z"),
]:
    r = requests.get(f"{GAMMA}/markets", params={
        "active": "true", "closed": "false", "limit": 200,
        "end_date_min": start, "end_date_max": end,
    })
    data = r.json()
    all_markets.extend(data)

# Also get the BKN-SAC game (ends 22:00 Mar 22)
r = requests.get(f"{GAMMA}/events", params={"slug": "nba-bkn-sac-2026-03-22"})
bkn_events = r.json()
for ev in bkn_events:
    for mkt in ev.get("markets", []):
        all_markets.append(mkt)

# Deduplicate
seen_ids = set()
unique = []
for m in all_markets:
    mid = m.get("id", "")
    if mid and mid not in seen_ids:
        seen_ids.add(mid)
        unique.append(m)

# Separate NBA and CBB
nba_winner = []
nba_other = []
cbb_winner = []
cbb_other = []

for m in unique:
    slug = (m.get("slug", "") or "").lower()
    q = m.get("question", "")
    lower_q = q.lower()

    is_winner = not any(x in lower_q for x in ["spread", "over", "under", "total", "o/u"])

    if "nba-" in slug and "2026-03-22" in slug:
        if is_winner:
            nba_winner.append(m)
        else:
            nba_other.append(m)
    elif "cbb-" in slug and ("2026-03-22" in slug or "2026-03-23" in slug):
        if is_winner:
            cbb_winner.append(m)
        else:
            cbb_other.append(m)

def print_market(m, indent=""):
    q = m.get("question", "")
    slug = m.get("slug", "")
    end = m.get("endDate", "")
    vol = m.get("volume", 0)
    tokens_raw = m.get("clobTokenIds", "[]")
    if isinstance(tokens_raw, str):
        tokens = json.loads(tokens_raw)
    else:
        tokens = tokens_raw
    outcomes_raw = m.get("outcomes", "[]")
    if isinstance(outcomes_raw, str):
        outcomes = json.loads(outcomes_raw)
    else:
        outcomes = outcomes_raw

    print(f"{indent}{q}")
    print(f"{indent}  Slug: {slug}")
    print(f"{indent}  End: {end}, Vol: ${float(vol):,.0f}")
    for outcome, tid in zip(outcomes, tokens):
        print(f"{indent}  {outcome}: {tid}")

# Print NBA
print(f"\n{'='*60}")
print(f"NBA WINNER MARKETS ({len(nba_winner)} games)")
print(f"{'='*60}")
for m in sorted(nba_winner, key=lambda x: x.get("endDate", "")):
    print()
    print_market(m)

if nba_other:
    print(f"\nNBA OTHER MARKETS (spread/total): {len(nba_other)}")
    for m in sorted(nba_other, key=lambda x: x.get("endDate", "")):
        print()
        print_market(m)

# Print CBB
print(f"\n{'='*60}")
print(f"NCAAB WINNER MARKETS ({len(cbb_winner)} games)")
print(f"{'='*60}")
for m in sorted(cbb_winner, key=lambda x: x.get("endDate", "")):
    print()
    print_market(m)

if cbb_other:
    print(f"\nNCAAB OTHER MARKETS (spread/total): {len(cbb_other)}")
    for m in sorted(cbb_other, key=lambda x: x.get("endDate", "")):
        print()
        print_market(m)

# GRAND TOTAL
print(f"\n{'='*60}")
print(f"GRAND TOTAL")
print(f"{'='*60}")
print(f"NBA winner markets: {len(nba_winner)}")
print(f"NBA other markets: {len(nba_other)}")
print(f"NCAAB winner markets: {len(cbb_winner)}")
print(f"NCAAB other markets: {len(cbb_other)}")
print(f"Total basketball markets: {len(nba_winner) + len(nba_other) + len(cbb_winner) + len(cbb_other)}")
