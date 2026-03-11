"""
Trading strategy: Kelly-based position sizing with edge detection.

Strategy overview:
- Scan top Polymarket markets by volume/liquidity
- Look for low-priced tokens (0.05-0.30) with asymmetric upside for 10x goal
- Size positions using fractional Kelly criterion (1/4 Kelly for safety)
- Track open positions with share counts in state.json
- Take profit at +60% gain, cut loss at -55% loss
- Actually close positions via market SELL orders
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from trader.config import (
    MAX_POSITION_USDC,
    MIN_EDGE,
    MAX_OPEN_POSITIONS,
    TARGET_BALANCE_USDC,
)
from trader.client import orderbook_to_dict
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
    if b <= 0:
        return 0.0
    kelly = (b * p_win - q) / b
    return max(0.0, kelly * fraction)


def estimate_edge(opportunity: dict, orderbook: Optional[dict]) -> tuple[float, str, float]:
    """
    Estimate edge for a market opportunity.
    Returns (edge, side, estimated_fair_price).

    Priority:
    1. Near-arb: YES+NO < 0.97 — buy whichever side is underpriced
    2. Order book mid dislocation
    3. Near-resolution momentum (end_date within 5 days)
    """
    yes_price = opportunity["yes_price"]
    no_price = opportunity["no_price"]
    end_date = opportunity.get("end_date", "")

    # 1. Near-arbitrage: prices don't sum to 1
    total = yes_price + no_price
    if total < 0.97:
        fair_yes = 1.0 - no_price
        if yes_price < fair_yes:
            edge = fair_yes - yes_price
            return edge, "YES", fair_yes
        else:
            fair_no = 1.0 - yes_price
            edge = fair_no - no_price
            return edge, "NO", fair_no

    # 2. Order book mid dislocation
    if orderbook:
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        if bids and asks:
            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            if spread > 0.025:
                if yes_price < mid - 0.025:
                    return spread / 2, "YES", mid
                elif no_price < (1.0 - mid) - 0.025:
                    return spread / 2, "NO", 1.0 - mid

    # 3. Aggressive: high-payout plays — low-price tokens with volume signal
    # Buy the cheapest side if it's priced 0.04-0.28 with meaningful volume (matches scoring)
    vol = opportunity.get("volume_24h", 0)
    liquidity = opportunity.get("liquidity", 0)
    days_left = opportunity.get("days_left")
    if vol > 2000 or liquidity > 1000:
        # Near-resolution bonus: tighter price range and stronger edge signal for short-dated markets
        max_price = 0.28
        base_edge = 0.05
        if days_left is not None and days_left <= 3:
            max_price = 0.35  # allow slightly higher-priced bets when resolving very soon
            base_edge = 0.06

        # Skip if the expensive side is > 0.90: market has very high conviction the cheap side loses
        # (e.g. BTC>$68k YES=0.945 — buying NO at 0.055 is near-certain loss)
        if yes_price <= max_price and yes_price >= 0.04 and no_price <= 0.90:
            return base_edge, "YES", yes_price + base_edge
        if no_price <= max_price and no_price >= 0.04 and yes_price <= 0.90:
            return base_edge, "NO", no_price + base_edge

    return 0.0, "YES", yes_price


def place_market_buy(client: ClobClient, token_id: str, amount_usdc: float) -> Optional[dict]:
    """Place a market BUY order. amount_usdc = USDC to spend."""
    try:
        args = MarketOrderArgs(
            token_id=token_id,
            amount=amount_usdc,
            side=BUY,
        )
        signed = client.create_market_order(args)
        resp = client.post_order(signed)
        return resp
    except Exception as e:
        print(f"[ORDER] BUY failed: {e}")
        return None


def place_market_sell(client: ClobClient, token_id: str, shares: float, current_price: float) -> Optional[dict]:
    """Place a market SELL order. shares = number of tokens to sell."""
    try:
        # Try market order first
        args = MarketOrderArgs(
            token_id=token_id,
            amount=shares,
            side=SELL,
        )
        signed = client.create_market_order(args)
        resp = client.post_order(signed)
        return resp
    except Exception as e:
        print(f"[ORDER] Market SELL failed ({e}), trying limit sell at bid-1tick")
        try:
            # Fallback: limit sell slightly below current price to ensure fill
            sell_price = max(0.01, round(current_price - 0.01, 2))
            tick = client.get_tick_size(token_id) if hasattr(client, 'get_tick_size') else 0.01
            sell_price = max(float(tick), sell_price)
            args2 = OrderArgs(
                token_id=token_id,
                price=sell_price,
                size=shares,
                side=SELL,
            )
            signed2 = client.create_order(args2)
            resp2 = client.post_order(signed2)
            return resp2
        except Exception as e2:
            print(f"[ORDER] Limit SELL also failed: {e2}")
            return None


def check_and_close_positions(client: ClobClient, state: dict, balance: float) -> float:
    """Check open positions and close if TP/SL hit. Returns updated balance estimate."""
    positions = state.get("positions", [])
    still_open = []

    for pos in positions:
        try:
            token_id = pos["token_id"]
            entry_price = pos["entry_price"]
            side = pos.get("side", "YES")
            shares = pos.get("shares", 0)

            # Get current price
            try:
                raw_book = client.get_order_book(token_id)
                book = orderbook_to_dict(raw_book)
                bids = book.get("bids", [])
                if bids:
                    current_price = float(bids[0]["price"])
                elif book.get("last_trade_price"):
                    current_price = float(book["last_trade_price"])
                else:
                    still_open.append(pos)
                    continue
            except Exception:
                still_open.append(pos)
                continue

            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

            should_close = False
            reason = ""
            # Near-resolution: close regardless of side when token approaches full payout
            if current_price >= 0.92:
                should_close = True
                reason = f"Near-resolution {current_price:.3f}"
            elif pnl_pct <= -0.55:
                should_close = True
                reason = f"SL {pnl_pct*100:.1f}%"
            # TP only applies to higher-priced entries (e.g. 50/50 markets).
            # For aggressive low-price entries (< 0.20), hold to near-resolution
            # to capture 5-10x gains needed for the 10x goal.
            elif entry_price >= 0.20 and pnl_pct >= 0.60:
                should_close = True
                reason = f"TP +{pnl_pct*100:.1f}%"

            if should_close:
                close_resp = None
                if shares > 0:
                    close_resp = place_market_sell(client, token_id, shares, current_price)

                pnl_usdc = shares * (current_price - entry_price) if shares > 0 else 0
                send(
                    f"{reason}: {pos['question'][:50]}\n"
                    f"  {side} | entry={entry_price:.3f} → {current_price:.3f}\n"
                    f"  Shares={shares:.2f} | PnL≈${pnl_usdc:.2f}"
                    + (f" | sell_resp={close_resp}" if close_resp else " | SELL FAILED")
                )
                closed_rec = {
                    **pos,
                    "exit_price": current_price,
                    "pnl_pct": pnl_pct,
                    "pnl_usdc": pnl_usdc,
                    "closed_at": str(datetime.now(timezone.utc)),
                    "close_reason": reason,
                }
                state.setdefault("trades", []).append(closed_rec)
                if shares > 0 and pnl_usdc != 0:
                    balance += pnl_usdc
            else:
                still_open.append(pos)

        except Exception as e:
            print(f"[POSITIONS] Error checking position: {e}")
            still_open.append(pos)

    state["positions"] = still_open
    return balance


def run_session(client: ClobClient, balance: float) -> None:
    """Main trading session logic."""
    state = load_state()
    state["sessions"] = state.get("sessions", 0) + 1
    session_num = state["sessions"]

    send(f"Session #{session_num} | Balance: ${balance:.2f} USDC | Open: {len(state['positions'])}")

    if balance < 5.0:
        send("Balance too low to trade.")
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
    opps = find_opportunities(top_n=30)
    if not opps:
        send("No opportunities found this session.")
        save_state(state)
        return

    existing_token_ids = {p["token_id"] for p in state["positions"]}

    trades_placed = 0
    for opp in opps:
        if open_count + trades_placed >= MAX_OPEN_POSITIONS:
            break

        yes_id = opp.get("yes_token_id")
        no_id = opp.get("no_token_id")

        if yes_id in existing_token_ids or no_id in existing_token_ids:
            continue

        try:
            raw_book = client.get_order_book(yes_id) if yes_id else None
            book = orderbook_to_dict(raw_book)
        except Exception:
            book = None

        edge, side, fair_price = estimate_edge(opp, book)

        if edge < MIN_EDGE:
            continue

        token_id = yes_id if side == "YES" else no_id
        entry_price = opp["yes_price"] if side == "YES" else opp["no_price"]

        if entry_price <= 0:
            continue

        # Kelly sizing — more aggressive for near-resolution opportunities
        odds = 1.0 / entry_price
        days_left = opp.get("days_left")
        kelly_frac = 0.25  # base fraction
        if days_left is not None and days_left <= 1:
            kelly_frac = 0.50  # more aggressive for same-day resolution
        elif days_left is not None and days_left <= 3:
            kelly_frac = 0.35

        k = kelly_fraction(fair_price, odds, fraction=kelly_frac)
        size = min(k * balance, MAX_POSITION_USDC)

        # Floor: $5 for near-resolution, $2 otherwise
        min_size = 5.0 if (days_left is not None and days_left <= 3) else 2.0
        size = max(min_size, round(size, 2))

        if size > balance * 0.25:
            size = round(balance * 0.25, 2)

        if size > balance * 0.95:
            size = round(balance * 0.95, 2)

        # Place order
        result = place_market_buy(client, token_id, size)
        if result:
            # Estimate shares received (USDC / price, approx)
            shares_est = round(size / entry_price, 4)
            # Try to get actual fill from response
            try:
                fill_price = float(result.get("price", entry_price) or entry_price)
                shares_est = round(size / fill_price, 4)
            except Exception:
                pass

            pos = {
                "token_id": token_id,
                "market_id": opp["market_id"],
                "question": opp["question"],
                "side": side,
                "entry_price": entry_price,
                "fair_price": fair_price,
                "edge": edge,
                "size_usdc": size,
                "shares": shares_est,
                "opened_at": str(datetime.now(timezone.utc)),
            }
            state["positions"].append(pos)
            trades_placed += 1
            send(
                f"BUY: {opp['question'][:60]}\n"
                f"  {side} @ {entry_price:.3f} | fair={fair_price:.3f} | edge={edge:.3f}\n"
                f"  Size: ${size:.2f} ({shares_est:.2f} shares) | Vol24h: ${opp['volume_24h']:.0f}"
            )
        else:
            print(f"[SESSION] Order failed for {opp['question'][:50]}")

    if trades_placed == 0:
        send("No trades placed this session (edge threshold not met).")

    save_state(state)
    print(f"[SESSION] Done. Trades: {trades_placed}. Open: {len(state['positions'])}")
