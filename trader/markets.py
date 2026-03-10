"""
Market discovery and opportunity scoring.
Fetches active markets from Gamma API and scores them for edge.
"""
import json
import requests
from typing import Optional
from trader.config import GAMMA_HOST, MIN_LIQUIDITY_USDC, MIN_EDGE


def _parse_json_field(value) -> list:
    """Parse a field that may be a JSON string or already a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return []
    return []


def get_active_markets(limit: int = 200) -> list[dict]:
    """Fetch active binary markets from Gamma API."""
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


def score_market(market: dict) -> Optional[dict]:
    """
    Score a market for trading opportunity.
    Returns opportunity dict if worth trading, else None.

    Uses Gamma API fields: outcomePrices, clobTokenIds, bestBid, bestAsk, volume24hr, liquidity.
    """
    try:
        # Must accept orders and have CLOB token IDs
        if not market.get("acceptingOrders", False):
            return None
        if market.get("closed", True) or not market.get("active", False):
            return None

        token_ids = _parse_json_field(market.get("clobTokenIds", []))
        outcome_prices = _parse_json_field(market.get("outcomePrices", []))
        outcomes = _parse_json_field(market.get("outcomes", []))

        if len(token_ids) < 2 or len(outcome_prices) < 2:
            return None

        # Determine YES/NO indices
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

        # Skip markets too close to resolution (near 0 or 1)
        if yes_price < 0.05 or yes_price > 0.95:
            return None

        # Check liquidity / volume
        volume = float(market.get("volume24hr", 0) or market.get("volumeNum", 0) or 0)
        liquidity = float(market.get("liquidityNum", 0) or market.get("liquidity", 0) or 0)

        if liquidity < MIN_LIQUIDITY_USDC and volume < MIN_LIQUIDITY_USDC:
            return None

        # Spread from best bid/ask
        best_bid = float(market.get("bestBid", yes_price) or yes_price)
        best_ask = float(market.get("bestAsk", yes_price) or yes_price)
        book_spread = best_ask - best_bid

        # Skip very wide spreads (stale book)
        if book_spread > 0.15:
            return None

        # Implied spread between YES+NO prices
        implied_spread = abs(1.0 - (yes_price + no_price))
        if implied_spread > 0.12:
            return None

        # Score: prefer uncertain markets with good volume/liquidity
        distance_from_50 = abs(yes_price - 0.50)
        volume_score = min(volume / 10000.0, 1.0)
        liquidity_score = min(liquidity / 5000.0, 1.0)
        # Tighter spread = better market quality
        spread_score = max(0.0, 1.0 - book_spread / 0.10)

        composite_score = (
            distance_from_50 * 0.2
            + volume_score * 0.35
            + liquidity_score * 0.25
            + spread_score * 0.20
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
            "end_date": market.get("endDate"),
            "score": composite_score,
        }
    except Exception as e:
        print(f"[SCORE] Error scoring market: {e}")
        return None


def find_opportunities(top_n: int = 10) -> list[dict]:
    """Return top N scored market opportunities."""
    markets = get_active_markets()
    scored = [s for m in markets if (s := score_market(m)) is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
