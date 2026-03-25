"""
Earnings market scanner.

Each session, scans active Polymarket markets for earnings-related questions,
extracts the ticker + hurdle, fetches analyst consensus via yfinance, and flags
opportunities where consensus diverges meaningfully from the Polymarket price.

Edge signal (like CHWY NO):
  - Market asks "Will X beat $Y EPS?"
  - If analyst consensus < $Y  → buy NO (market overprices YES)
  - If analyst consensus > $Y  → buy YES (market underprices YES)
  - Threshold: abs(consensus - hurdle) / hurdle > 5%
"""
import re
import json
import requests
from typing import Optional

GAMMA_HOST = "https://gamma-api.polymarket.com"

# Regex to extract dollar amounts from titles (e.g. "$0.28", "$1.2B", "$500M")
_DOLLAR_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)\s*(B|M|K)?", re.IGNORECASE)

# Common company name → ticker mappings (expand as needed)
_NAME_TO_TICKER = {
    "chewy": "CHWY", "chwy": "CHWY",
    "nvidia": "NVDA", "nvda": "NVDA",
    "apple": "AAPL", "aapl": "AAPL",
    "microsoft": "MSFT", "msft": "MSFT",
    "amazon": "AMZN", "amzn": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "googl": "GOOGL",
    "meta": "META", "facebook": "META",
    "tesla": "TSLA", "tsla": "TSLA",
    "netflix": "NFLX", "nflx": "NFLX",
    "palantir": "PLTR", "pltr": "PLTR",
    "coinbase": "COIN", "coin": "COIN",
    "gamestop": "GME", "gme": "GME",
    "pinduoduo": "PDD", "pdd": "PDD", "temu": "PDD",
    "cintas": "CTAS", "ctas": "CTAS",
    "microstrategy": "MSTR", "mstr": "MSTR",
    "robinhood": "HOOD", "hood": "HOOD",
    "arm": "ARM",
    "asml": "ASML",
    "alibaba": "BABA", "baba": "BABA",
    "snowflake": "SNOW", "snow": "SNOW",
    "salesforce": "CRM", "crm": "CRM",
    "uber": "UBER",
    "lyft": "LYFT",
    "airbnb": "ABNB", "abnb": "ABNB",
    "rivian": "RIVN", "rivn": "RIVN",
    "lucid": "LCID", "lcid": "LCID",
    "shopify": "SHOP", "shop": "SHOP",
    "disney": "DIS", "dis": "DIS",
    "nike": "NKE", "nke": "NKE",
    "intel": "INTC", "intc": "INTC",
    "amd": "AMD",
    "qualcomm": "QCOM", "qcom": "QCOM",
    "broadcom": "AVGO", "avgo": "AVGO",
}

# Keywords that identify earnings-related markets (must be specific to avoid false positives)
_EARNINGS_KEYWORDS = [
    "earnings", "eps", " beat ", "quarterly earnings", "quarterly results",
    "annual results", "q1 earnings", "q2 earnings", "q3 earnings", "q4 earnings",
    "fiscal quarter", "net income", "revenue beat", "profit beat",
    "beats consensus", "beat estimates", "beat expectations",
    "report earnings", "reports earnings", "beats earnings",
]


def _fetch_all_markets(limit: int = 500) -> list[dict]:
    """Fetch active markets sorted by volume and by start date (two passes)."""
    markets = {}
    for order in ("volume24hr", "startDate"):
        try:
            resp = requests.get(
                f"{GAMMA_HOST}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": order,
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for m in data:
                    markets[m.get("id", m.get("conditionId", ""))] = m
        except Exception as e:
            print(f"[EARNINGS] Fetch error (order={order}): {e}")
    return list(markets.values())


def _is_earnings_market(market: dict) -> bool:
    text = (market.get("question", "") + " " + market.get("description", "")).lower()
    return any(kw in text for kw in _EARNINGS_KEYWORDS)


def _extract_ticker(question: str) -> Optional[str]:
    """Try to extract a stock ticker from the question text."""
    q_lower = question.lower()
    # Check name mapping
    for name, ticker in _NAME_TO_TICKER.items():
        if name in q_lower:
            return ticker
    # Look for explicit uppercase ticker pattern like (CHWY) or just CHWY
    m = re.search(r'\b([A-Z]{2,5})\b', question)
    if m:
        candidate = m.group(1)
        # Filter out common non-ticker words
        if candidate not in ("WILL", "THE", "FOR", "AND", "OR", "NOT", "ITS", "EPS",
                              "CEO", "COO", "CFO", "IPO", "GDP", "USD", "ETF",
                              "YES", "NO", "Q1", "Q2", "Q3", "Q4", "FY"):
            return candidate
    return None


def _parse_hurdle(question: str, description: str = "") -> Optional[float]:
    """
    Extract the numeric earnings hurdle from the question/description.
    Returns value in dollars (converts M/B suffixes).
    """
    text = question + " " + description
    m = _DOLLAR_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    if suffix == "B":
        value *= 1_000_000_000
    elif suffix == "M":
        value *= 1_000_000
    elif suffix == "K":
        value *= 1_000
    return value


def _get_consensus_eps(ticker: str) -> Optional[float]:
    """
    Fetch analyst consensus quarterly EPS estimate via yfinance.
    Uses eps_trend '0q' (current quarter) — the right unit for PM earnings markets
    which ask about a specific quarter, not the full year.
    Falls back to epsForward/4 if eps_trend is unavailable.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        trend = t.eps_trend
        if trend is not None and "0q" in trend.index:
            return float(trend.loc["0q", "current"])
        # Fallback: annualized forward EPS / 4
        info = t.info
        annual = info.get("epsForward") or info.get("epsCurrentYear")
        if annual:
            return float(annual) / 4.0
        return None
    except Exception as e:
        print(f"[EARNINGS] yfinance EPS error for {ticker}: {e}")
        return None


def _get_consensus_revenue(ticker: str) -> Optional[float]:
    """
    Fetch analyst consensus quarterly revenue estimate via yfinance.
    Uses earnings_estimate '0q' avg if available, else totalRevenue/4.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        est = t.earnings_estimate
        if est is not None and "0q" in est.index:
            return float(est.loc["0q", "avg"])
        info = t.info
        annual = info.get("totalRevenue")
        if annual:
            return float(annual) / 4.0
        return None
    except Exception as e:
        print(f"[EARNINGS] yfinance revenue error for {ticker}: {e}")
        return None


def scan_earnings_opportunities() -> list[dict]:
    """
    Scan all active Polymarket markets for earnings opportunities.
    Returns list of dicts with: market, ticker, hurdle, consensus, edge, side, note.
    """
    print("[EARNINGS] Scanning for earnings markets...")
    markets = _fetch_all_markets()
    print(f"[EARNINGS] Total active markets fetched: {len(markets)}")

    results = []
    earnings_markets = [m for m in markets if _is_earnings_market(m)]
    print(f"[EARNINGS] Earnings-related markets found: {len(earnings_markets)}")

    for market in earnings_markets:
        question = market.get("question", "")
        description = market.get("description", "")
        ticker = _extract_ticker(question)
        hurdle = _parse_hurdle(question, description)

        # Parse prices
        try:
            prices = json.loads(market.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if prices else None
            no_price = float(prices[1]) if len(prices) > 1 else None
        except Exception:
            yes_price = no_price = None

        # Extract token IDs
        try:
            token_ids = json.loads(market.get("clobTokenIds", "[]"))
        except Exception:
            token_ids = []
        yes_token_id = token_ids[0] if token_ids else None
        no_token_id = token_ids[1] if len(token_ids) > 1 else None

        result = {
            "question": question[:120],
            "market_id": market.get("id") or market.get("conditionId", ""),
            "ticker": ticker,
            "hurdle": hurdle,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
            "token_id": None,  # set after side is determined
            "volume_24h": market.get("volume24hr", 0),
            "end_date": market.get("endDate", ""),
            "consensus_eps": None,
            "edge": 0.0,
            "side": None,
            "note": "",
        }

        if ticker and hurdle is not None and yes_price is not None:
            # Determine if this is EPS or revenue
            q_lower = question.lower()
            is_revenue = any(kw in q_lower for kw in ("revenue", "sales", "net revenue"))

            if is_revenue:
                consensus = _get_consensus_revenue(ticker)
            else:
                consensus = _get_consensus_eps(ticker)

            result["consensus_eps"] = consensus

            if consensus is not None and hurdle > 0:
                rel_diff = (consensus - hurdle) / abs(hurdle)

                if rel_diff < -0.05:
                    # Consensus BELOW hurdle → bet NO (company likely to miss)
                    implied_no = no_price or (1.0 - yes_price)
                    result["edge"] = round(abs(rel_diff), 4)
                    result["side"] = "NO"
                    result["token_id"] = no_token_id
                    result["note"] = (
                        f"Consensus ${consensus:.2f} < hurdle ${hurdle:.2f} "
                        f"({rel_diff*100:+.1f}%). "
                        f"PM prices YES at {yes_price:.2f}, NO at {implied_no:.2f}."
                    )
                elif rel_diff > 0.05:
                    # Consensus ABOVE hurdle → bet YES (company likely to beat)
                    result["edge"] = round(rel_diff, 4)
                    result["side"] = "YES"
                    result["token_id"] = yes_token_id
                    result["note"] = (
                        f"Consensus ${consensus:.2f} > hurdle ${hurdle:.2f} "
                        f"({rel_diff*100:+.1f}%). "
                        f"PM prices YES at {yes_price:.2f}."
                    )
                else:
                    result["note"] = (
                        f"Consensus ${consensus:.2f} vs hurdle ${hurdle:.2f} "
                        f"({rel_diff*100:+.1f}%) — within 5%, no edge."
                    )
        elif ticker and yes_price is not None:
            result["note"] = f"No parseable hurdle — manual review needed. YES={yes_price:.2f}"

        results.append(result)
        print(f"[EARNINGS]  {question[:70]} | ticker={ticker} hurdle={hurdle} side={result['side']} edge={result['edge']:.3f}")

    return results


def trade_earnings_opportunities(client, opportunities: list[dict], balance: float,
                                  max_per_trade: float = 10.0) -> list[dict]:
    """
    Auto-trade earnings opportunities where edge >= 5%.
    Places limit buy orders (maker) at best bid to avoid commissions.
    Returns list of trades placed.
    """
    from trader.strategy import place_market_buy, get_actual_shares
    from datetime import datetime, timezone

    placed = []
    edged = [o for o in opportunities if o.get("edge", 0) >= 0.05 and o.get("side") and o.get("token_id")]

    for opp in edged:
        token_id = opp["token_id"]
        side = opp["side"]
        size = min(max_per_trade, balance * 0.10)  # max 10% of balance per earnings trade
        size = max(1.0, round(size, 2))

        if size > balance * 0.95:
            print(f"[EARNINGS] Skipping {opp['question'][:50]} — insufficient balance")
            continue

        print(f"[EARNINGS] Trading {side} on {opp['question'][:60]} | size=${size:.2f}")
        result = place_market_buy(client, token_id, size)
        if result:
            import time; time.sleep(1)
            shares = get_actual_shares(client, token_id)
            entry_price = opp["yes_price"] if side == "YES" else opp["no_price"]
            trade = {
                "token_id": token_id,
                "market_id": opp.get("market_id", ""),
                "question": opp["question"],
                "side": side,
                "entry_price": entry_price or 0,
                "size_usdc": size,
                "shares": shares,
                "end_date": opp.get("end_date", ""),
                "edge": opp["edge"],
                "earnings_note": opp["note"],
                "opened_at": str(datetime.now(timezone.utc)),
            }
            placed.append(trade)
            balance -= size
        else:
            print(f"[EARNINGS] Market order failed for {opp['question'][:50]}")

    return placed


def format_earnings_report(opportunities: list[dict]) -> str:
    """Format scanner results as a Telegram message."""
    if not opportunities:
        return "EARNINGS SCAN: No earnings markets found."

    lines = [f"EARNINGS SCAN: {len(opportunities)} market(s) found\n"]
    edged = [o for o in opportunities if o["edge"] >= 0.05]
    no_edge = [o for o in opportunities if o["edge"] < 0.05]

    if edged:
        lines.append("=== EDGE FOUND ===")
        for o in sorted(edged, key=lambda x: -x["edge"]):
            lines.append(
                f"[{o['side']} {o.get('edge', 0)*100:.0f}%] {o['question'][:80]}\n"
                f"  Ticker: {o['ticker']} | YES={o['yes_price']} NO={o['no_price']}\n"
                f"  {o['note']}"
            )
    if no_edge:
        lines.append("\n=== NO EDGE ===")
        for o in no_edge:
            lines.append(f"• {o['question'][:80]}\n  {o['note']}")

    return "\n".join(lines)
