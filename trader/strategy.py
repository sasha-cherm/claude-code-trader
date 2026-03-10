"""
Trading strategy: Kelly-based position sizing with edge detection.

Strategy overview:
- Scan top Polymarket markets by volume/liquidity
- Use current order book to find markets where we believe we have edge
- Size positions using fractional Kelly criterion (1/4 Kelly for safety)
- Track open positions in state.json
- Take profit at 70%+ gain, cut loss at 50% loss
"""
import json
import os
from datetime import datetime
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs

from trader.config import (
    MAX_POSITION_USDC,
    MIN_EDGE,
    MAX_OPEN_POSITIONS,
    TARGET_BALANCE_USDC,
)
from trader.markets import find_opportunities
from trader.notify import send

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"positions": [], "trades": [], "sessions": 0}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def kelly_fraction(p_win: float, odds: float, fraction: float = 0.25) -> float:
    """
    Fractional Kelly criterion.
    p_win: our estimated probability of winning
    odds: decimal odds (payout per unit bet, e.g. 2.0 for even money)
    fraction: Kelly fraction (0.25 = quarter Kelly)
    """
    b = odds - 1.0
    q = 1.0 - p_win
    kelly = (b * p_win - q) / b
    return max(0.0, kelly * fraction)


def estimate_edge(opportunity: dict, orderbook: Optional[dict]) -> tuple[float, str, float]:
    """
    Estimate edge for a market opportunity.
    Returns (edge, side, fair_price).

    Simple model: use order book mid vs last trade price to find temporary dislocations.
    If no orderbook available, use price momentum heuristic.
    """
    yes_price = opportunity["yes_price"]
    no_price = opportunity["no_price"]

    # Basic heuristic: if YES + NO < 1.0 (negative spread), take the cheaper side
    total = yes_price + no_price
    if total < 0.97:
        # Arbitrage-ish opportunity: buy whichever is cheaper relative to fair value
        fair_yes = 1.0 - no_price
        if yes_price < fair_yes:
            edge = fair_yes - yes_price
            return edge, "YES", fair_yes
        else:
            fair_no = 1.0 - yes_price
            edge = fair_no - no_price
            return edge, "NO", fair_no

    # Order book spread play: buy near mid
    if orderbook:
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        if bids and asks:
            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            # Edge = half the spread if we're a price taker at mid
            if spread > 0.02:
                # Buy YES if mid suggests YES is cheap vs our model
                if yes_price < mid - 0.02:
                    return spread / 2, "YES", mid
                elif no_price < (1.0 - mid) - 0.02:
                    return spread / 2, "NO", 1.0 - mid

    return 0.0, "YES", yes_price


def place_market_order(client: ClobClient, token_id: str, amount_usdc: float) -> Optional[dict]:
    """Place a market buy order for a given token (FOK = fill-or-kill)."""
    try:
        from py_clob_client.order_builder.constants import BUY
        args = MarketOrderArgs(
            token_id=token_id,
            amount=amount_usdc,
            side=BUY,
        )
        signed = client.create_market_order(args)
        resp = client.post_order(signed)
        return resp
    except Exception as e:
        print(f"[ORDER] Failed to place order: {e}")
        return None


def check_and_close_positions(client: ClobClient, state: dict, balance: float) -> float:
    """Check open positions and close if TP/SL hit. Returns updated balance estimate."""
    positions = state.get("positions", [])
    closed = []
    still_open = []

    for pos in positions:
        try:
            token_id = pos["token_id"]
            entry_price = pos["entry_price"]
            size = pos["size_usdc"]
            side = pos.get("side", "YES")

            # Get current price from orderbook
            book = client.get_order_book(token_id)
            if book and book.get("bids"):
                current_price = float(book["bids"][0]["price"])
            else:
                still_open.append(pos)
                continue

            pnl_pct = (current_price - entry_price) / entry_price

            # Take profit at +70% or stop loss at -50%
            if pnl_pct >= 0.70:
                send(f"TP hit: {pos['question'][:50]} | {side} | entry={entry_price:.3f} current={current_price:.3f} | +{pnl_pct*100:.1f}%")
                # TODO: place sell order
                closed.append({**pos, "exit_price": current_price, "pnl_pct": pnl_pct, "closed_at": str(datetime.utcnow())})
            elif pnl_pct <= -0.50:
                send(f"SL hit: {pos['question'][:50]} | {side} | entry={entry_price:.3f} current={current_price:.3f} | {pnl_pct*100:.1f}%")
                closed.append({**pos, "exit_price": current_price, "pnl_pct": pnl_pct, "closed_at": str(datetime.utcnow())})
            else:
                still_open.append(pos)
        except Exception as e:
            print(f"[POSITIONS] Error checking position: {e}")
            still_open.append(pos)

    state["positions"] = still_open
    state["trades"].extend(closed)
    return balance


def run_session(client: ClobClient, balance: float) -> None:
    """Main trading session logic."""
    state = load_state()
    state["sessions"] = state.get("sessions", 0) + 1
    session_num = state["sessions"]

    send(f"Session #{session_num} | Balance: ${balance:.2f} USDC | Open positions: {len(state['positions'])}")

    if balance < 5.0:
        send("Balance too low to trade. Waiting.")
        save_state(state)
        return

    # Check/close existing positions
    balance = check_and_close_positions(client, state, balance)

    open_count = len(state["positions"])
    if open_count >= MAX_OPEN_POSITIONS:
        send(f"Max positions ({MAX_OPEN_POSITIONS}) reached. Holding.")
        save_state(state)
        return

    # Find new opportunities
    opps = find_opportunities(top_n=20)
    if not opps:
        send("No opportunities found this session.")
        save_state(state)
        return

    # Avoid re-entering existing positions
    existing_token_ids = {p["token_id"] for p in state["positions"]}

    trades_placed = 0
    for opp in opps:
        if open_count + trades_placed >= MAX_OPEN_POSITIONS:
            break

        yes_id = opp.get("yes_token_id")
        no_id = opp.get("no_token_id")

        if yes_id in existing_token_ids or no_id in existing_token_ids:
            continue

        # Get orderbook for edge estimation
        try:
            book = client.get_order_book(yes_id) if yes_id else None
        except Exception:
            book = None

        edge, side, fair_price = estimate_edge(opp, book)

        if edge < MIN_EDGE:
            continue

        token_id = yes_id if side == "YES" else no_id
        entry_price = opp["yes_price"] if side == "YES" else opp["no_price"]

        # Kelly sizing
        odds = 1.0 / entry_price  # approximate decimal odds
        k = kelly_fraction(fair_price, odds)
        size = min(k * balance, MAX_POSITION_USDC)
        size = max(1.0, round(size, 2))  # min $1

        if size > balance * 0.25:
            size = round(balance * 0.25, 2)  # max 25% of balance per trade

        # Place order
        result = place_market_order(client, token_id, size)
        if result:
            pos = {
                "token_id": token_id,
                "market_id": opp["market_id"],
                "question": opp["question"],
                "side": side,
                "entry_price": entry_price,
                "fair_price": fair_price,
                "edge": edge,
                "size_usdc": size,
                "opened_at": str(datetime.utcnow()),
            }
            state["positions"].append(pos)
            trades_placed += 1
            send(
                f"TRADE: {opp['question'][:60]}\n"
                f"  {side} @ {entry_price:.3f} | fair={fair_price:.3f} | edge={edge:.3f}\n"
                f"  Size: ${size:.2f} | Vol24h: ${opp['volume_24h']:.0f}"
            )
        else:
            print(f"[SESSION] Order failed for {opp['question'][:50]}")

    if trades_placed == 0:
        send("No trades placed this session (edge threshold not met).")

    save_state(state)
    print(f"[SESSION] Done. Trades placed: {trades_placed}. Open positions: {len(state['positions'])}")
