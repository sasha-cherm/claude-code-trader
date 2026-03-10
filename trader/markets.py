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
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            end = datetime.strptime(end_date_str[:19], fmt[:len(fmt)])
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

        # === Tier 1: Near-arbitrage ===
        total = yes_price + no_price
        is_near_arb = total < 0.97

        # === Tier 2: High-payout low-price play ===
        min_price = min(yes_price, no_price)
        is_high_payout = min_price <= 0.28 and (volume > 1000 or liquidity > 800)

        if not is_near_arb and not is_high_payout:
            return None

        # Composite score
        # Higher = better opportunity
        arb_score = max(0.0, (0.97 - total) * 10) if is_near_arb else 0.0

        # Near-resolution bonus (within 7 days)
        resolution_bonus = 0.0
        if days_left is not None and 0 < days_left <= 7:
            resolution_bonus = 0.3 * (1.0 - days_left / 7)
        elif days_left is not None and 0 < days_left <= 14:
            resolution_bonus = 0.15 * (1.0 - days_left / 14)

        # Volume/liquidity score
        volume_score = min(volume / 20000.0, 1.0)
        liquidity_score = min(liquidity / 5000.0, 1.0)

        # High-payout score: lower price = higher potential return
        payout_score = 0.0
        if is_high_payout:
            # Prefer tokens priced 0.05-0.20 with decent volume
            if 0.05 <= min_price <= 0.20 and volume > 2000:
                payout_score = (0.20 - min_price) / 0.15 * 0.5

        composite_score = (
            arb_score * 0.40
            + resolution_bonus * 0.20
            + volume_score * 0.20
            + liquidity_score * 0.10
            + payout_score * 0.10
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
