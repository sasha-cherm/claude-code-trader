"""
Market discovery and opportunity scoring.
Fetches active markets from Gamma API and scores them for edge.

Strategy for 10x goal:
- Find markets with low-priced tokens (0.04-0.25) — high payout if correct
- Prioritize markets ending within 14 days (near-resolution clarity)
- Strong volume/liquidity filters to avoid illiquid traps
- Look for near-arb situations (YES+NO < 0.97)
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests
from trader.config import GAMMA_HOST, MIN_LIQUIDITY_USDC, MIN_EDGE


def _parse_json_field(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return []
    return []


def get_active_markets(limit: int = 300) -> list[dict]:
    """Fetch active binary markets from Gamma API, sorted by 24h volume."""
    try:
        resp = requests.get(
            f"{GAMMA_HOST}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": limit,
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("markets", [])
    except Exception as e:
        print(f"[MARKETS] Error fetching markets: {e}")
        return []


def days_until_end(end_date_str: str) -> Optional[float]:
    """Parse end date and return days remaining. None if can't parse."""
    if not end_date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            s = end_date_str.rstrip("Z")
            if fmt.endswith("Z"):
                s = end_date_str
            end = datetime.strptime(s, fmt)
            end = end.replace(tzinfo=timezone.utc)
            delta = (end - datetime.now(timezone.utc)).total_seconds() / 86400
            return delta
        except Exception:
            continue
    return None


def score_market(market: dict) -> Optional[dict]:
    """
    Score a market for trading opportunity.
    Returns opportunity dict if worth trading, else None.

    Two tiers:
    1. Near-arb: YES+NO < 0.97 (strong edge regardless of price)
    2. High-payout: low-priced token (0.04-0.28) with strong volume — for 10x goal
    """
    try:
        if not market.get("acceptingOrders", False):
            return None
        if market.get("closed", True) or not market.get("active", False):
            return None

        # Skip social media count/post markets — no informational edge
        question_lower = market.get("question", "").lower()
        if any(kw in question_lower for kw in ["tweets", "tweet", "posts from", "post "]) and \
           any(kw in question_lower for kw in ["will elon", "will andrew", "will donald"]):
            return None

        # Skip sports game winner markets for automated trading — market prices these
        # efficiently and we have no edge without manual research (injuries, matchups).
        # Only near-arb and spread/total markets pass through.
        # Sports bets should be placed manually after research.
        # Detect sports winner markets by pattern:
        # 1. "Team vs. Team" without Spread/O/U keywords = game winner
        # 2. "Will X win on YYYY-MM-DD?" = match winner
        has_vs = "vs." in question_lower or "vs " in question_lower
        is_spread_ou = "spread" in question_lower or "o/u" in question_lower
        has_win_on_date = " win on 2" in question_lower  # "win on 2026-..."
        is_sports_winner = (has_vs and not is_spread_ou) or has_win_on_date
        # Allow sports markets through ONLY for near-arb detection (YES+NO < 0.97)
        # Competitive/high-payout sports markets should NOT be auto-traded

        token_ids = _parse_json_field(market.get("clobTokenIds", []))
        outcome_prices = _parse_json_field(market.get("outcomePrices", []))
        outcomes = _parse_json_field(market.get("outcomes", []))

        if len(token_ids) < 2 or len(outcome_prices) < 2:
            return None

        yes_idx = 0
        no_idx = 1
        if outcomes:
            for i, o in enumerate(outcomes):
                if str(o).upper() == "NO":
                    no_idx = i
                elif str(o).upper() == "YES":
                    yes_idx = i

        yes_price = float(outcome_prices[yes_idx] or 0)
        no_price = float(outcome_prices[no_idx] or 0)

        if yes_price <= 0 or no_price <= 0:
            return None

        # Hard limits: don't touch if both prices are near extremes
        # (e.g., 0.99 YES means market essentially resolved)
        if yes_price > 0.97 or no_price > 0.97:
            return None
        # Too cheap = too risky (likely about to resolve NO)
        if yes_price < 0.03 and no_price < 0.03:
            return None

        volume = float(market.get("volume24hr", 0) or market.get("volumeNum", 0) or 0)
        liquidity = float(market.get("liquidityNum", 0) or market.get("liquidity", 0) or 0)

        # Minimum liquidity/volume filter
        if liquidity < MIN_LIQUIDITY_USDC and volume < MIN_LIQUIDITY_USDC:
            return None

        best_bid = float(market.get("bestBid", yes_price) or yes_price)
        best_ask = float(market.get("bestAsk", yes_price) or yes_price)
        book_spread = best_ask - best_bid if best_ask > best_bid else 0

        # Skip extremely wide spreads (stale book)
        if book_spread > 0.20:
            return None

        end_date = market.get("endDate", "")
        days_left = days_until_end(end_date)

        # Skip markets past their end date (likely already resolved)
        if days_left is not None and days_left < -0.02:
            return None

        # === Tier 1: Near-arbitrage ===
        total = yes_price + no_price
        is_near_arb = total < 0.97

        # === Tier 2: High-payout low-price play ===
        min_price = min(yes_price, no_price)
        max_price = max(yes_price, no_price)
        # Only flag as high-payout if the opposing side lacks overwhelming conviction (<85%)
        # SKIP sports winner markets — prices are efficient, no edge without research
        # REQUIRE resolution within 7 days — capital velocity is key for 10x goal
        is_high_payout = (min_price <= 0.30 and min_price >= 0.08 and max_price < 0.85
                         and (volume > 5000 or liquidity > 2000)
                         and not is_sports_winner
                         and days_left is not None and days_left <= 7)

        # === Tier 3: Competitive market play ===
        # Markets where both sides are 30-70% — more likely to be mispriced
        # Spread/total markets are OK, but skip sports winner markets
        is_competitive = (0.30 <= yes_price <= 0.70 and 0.30 <= no_price <= 0.70
                         and (volume > 5000 or liquidity > 3000)
                         and days_left is not None and days_left <= 2
                         and not is_sports_winner)

        if not is_near_arb and not is_high_payout and not is_competitive:
            return None

        # Composite score — heavily weight near-resolution + volume for the 10x goal
        arb_score = max(0.0, (0.97 - total) * 10) if is_near_arb else 0.0

        # Near-resolution bonus: strongly prefer markets resolving within 24 hours
        # Capital recycling is key to compounding — same-day resolution means we can
        # reinvest winnings immediately rather than having capital locked up
        resolution_bonus = 0.0
        if days_left is not None and 0 < days_left <= 0.5:
            resolution_bonus = 0.7  # resolving in <12 hours: highest priority
        elif days_left is not None and 0 < days_left <= 1:
            resolution_bonus = 0.55  # same-day
        elif days_left is not None and 0 < days_left <= 3:
            resolution_bonus = 0.35 * (1.0 - days_left / 3)
        elif days_left is not None and 0 < days_left <= 7:
            resolution_bonus = 0.15 * (1.0 - days_left / 7)

        # Volume/liquidity score — prefer liquid markets for reliable fills
        volume_score = min(volume / 20000.0, 1.0)
        liquidity_score = min(liquidity / 5000.0, 1.0)

        # High-payout score: lower price = higher potential return
        # Sweet spot: 0.08-0.20 (5x-12.5x payout if correct)
        payout_score = 0.0
        if is_high_payout:
            if 0.04 <= min_price <= 0.12:
                payout_score = 0.6  # huge upside (8x-25x)
            elif 0.12 < min_price <= 0.20:
                payout_score = 0.4  # strong upside (5x-8x)
            elif 0.20 < min_price <= 0.28:
                payout_score = 0.2  # moderate upside (3.5x-5x)

        # Competitive market bonus: closer to 50/50 with near resolution
        competitive_score = 0.0
        if is_competitive:
            # Markets near 50/50 with fast resolution = high capital velocity
            balance_ratio = 1.0 - abs(yes_price - 0.5) * 2  # 1.0 at 50/50, 0.0 at extremes
            competitive_score = balance_ratio * 0.4

        composite_score = (
            arb_score * 0.15
            + resolution_bonus * 0.35
            + volume_score * 0.15
            + liquidity_score * 0.05
            + payout_score * 0.15
            + competitive_score * 0.15
        )

        return {
            "market_id": market.get("id"),
            "condition_id": market.get("conditionId"),
            "question": market.get("question", ""),
            "yes_token_id": token_ids[yes_idx],
            "no_token_id": token_ids[no_idx],
            "yes_price": yes_price,
            "no_price": no_price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "book_spread": book_spread,
            "volume_24h": volume,
            "liquidity": liquidity,
            "end_date": end_date,
            "days_left": days_left,
            "is_near_arb": is_near_arb,
            "is_high_payout": is_high_payout,
            "is_competitive": is_competitive,
            "score": composite_score,
        }
    except Exception as e:
        print(f"[SCORE] Error scoring market: {e}")
        return None


def find_opportunities(top_n: int = 20) -> list[dict]:
    """Return top N scored market opportunities."""
    markets = get_active_markets()
    scored = [s for m in markets if (s := score_market(m)) is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    print(f"[MARKETS] Found {len(scored)} opportunities from {len(markets)} markets")
    for o in scored[:5]:
        print(f"  [{o['score']:.3f}] {o['question'][:70]} | yes={o['yes_price']:.3f} no={o['no_price']:.3f} | arb={o['is_near_arb']} vol=${o['volume_24h']:.0f}")
    return scored[:top_n]
