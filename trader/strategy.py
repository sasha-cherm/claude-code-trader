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

from trader.markets import days_until_end

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from trader.config import (
    MAX_POSITION_USDC,
    MAX_POSITION_PCT,
    MIN_POSITION_USDC,
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

    # 3. High-payout plays — low-price tokens with volume, resolving soon
    # Only enter with sufficient volume and near-term resolution for capital velocity
    vol = opportunity.get("volume_24h", 0)
    liquidity = opportunity.get("liquidity", 0)
    days_left = opportunity.get("days_left")
    if (vol > 5000 or liquidity > 2000) and days_left is not None and days_left <= 2:
        max_price = 0.30
        base_edge = 0.06
        # Skip tokens priced too low (<0.08) — near-certain losers
        # Skip if the expensive side is > 0.85: overwhelming market conviction against us
        if yes_price <= max_price and yes_price >= 0.08 and no_price < 0.85:
            return base_edge, "YES", yes_price + base_edge
        if no_price <= max_price and no_price >= 0.08 and yes_price < 0.85:
            return base_edge, "NO", no_price + base_edge

    # 4. Competitive market plays — only with orderbook dislocation (real edge)
    # Don't enter 50/50 coin-flip bets without a pricing signal
    if opportunity.get("is_competitive") and (vol > 10000 or liquidity > 5000):
        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            if bids and asks:
                best_bid = float(bids[0]["price"])
                best_ask = float(asks[0]["price"])
                mid = (best_bid + best_ask) / 2.0
                spread = best_ask - best_bid
                # Only enter when there's meaningful spread dislocation
                if yes_price < mid - 0.015 and spread > 0.025:
                    return max(spread / 2, 0.04), "YES", mid
                elif no_price < (1.0 - mid) - 0.015 and spread > 0.025:
                    return max(spread / 2, 0.04), "NO", 1.0 - mid

    return 0.0, "YES", yes_price


def place_market_buy(client: ClobClient, token_id: str, amount_usdc: float) -> Optional[dict]:
    """
    Place a BUY order spending ~amount_usdc USDC.
    Uses a limit order at best ask so shares (takerAmount) can be rounded to 2 decimal
    places — the CLOB rejects market orders whose takerAmount exceeds 2 decimal places.
    """
    from math import floor
    from py_clob_client.clob_types import OrderArgs

    try:
        # Get best ask price from order book
        raw_book = client.get_order_book(token_id)
        from trader.client import orderbook_to_dict
        book = orderbook_to_dict(raw_book)
        asks = book.get("asks", [])
        if asks:
            fill_price = float(asks[0]["price"])
        else:
            # Fallback: try last trade price
            bids = book.get("bids", [])
            if bids:
                fill_price = float(bids[0]["price"]) + 0.01
            else:
                raise ValueError("No orderbook liquidity")

        # Round shares to 2 decimal places (CLOB taker amount max 2 decimals)
        shares = floor((amount_usdc / fill_price) * 100) / 100.0
        if shares < 0.01:
            raise ValueError(f"Too few shares at price {fill_price}")

        args = OrderArgs(
            token_id=token_id,
            price=fill_price,
            size=shares,
            side=BUY,
        )
        signed = client.create_order(args)
        resp = client.post_order(signed)
        return resp
    except Exception as e:
        print(f"[ORDER] BUY failed: {e}")
        return None


def get_actual_shares(client: ClobClient, token_id: str) -> float:
    """Query actual on-chain conditional token balance (6-decimal)."""
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        result = client.get_balance_allowance(params)
        raw = int(result.get("balance", 0))
        return raw / 1_000_000
    except Exception as e:
        print(f"[SELL] Could not get actual shares for {token_id[:16]}: {e}")
        return 0.0


def place_market_sell(client: ClobClient, token_id: str, shares: float, current_price: float) -> Optional[dict]:
    """Place a SELL limit order. Uses actual on-chain balance to avoid over-selling."""
    from math import floor

    # Use actual balance to avoid "not enough balance" errors from estimation drift
    actual = get_actual_shares(client, token_id)
    if actual > 0 and actual < shares:
        print(f"[ORDER] Adjusting sell shares: state={shares:.4f} → actual={actual:.4f}")
        shares = floor(actual * 100) / 100.0  # floor to 2 decimals

    if shares <= 0:
        print("[ORDER] No shares to sell.")
        return None

    try:
        # Limit sell at best bid for immediate fill
        raw_book = client.get_order_book(token_id)
        from trader.client import orderbook_to_dict
        book = orderbook_to_dict(raw_book)
        bids = book.get("bids", [])
        if bids:
            sell_price = float(bids[0]["price"])
        else:
            sell_price = max(0.01, round(current_price - 0.01, 2))

        args = OrderArgs(
            token_id=token_id,
            price=sell_price,
            size=shares,
            side=SELL,
        )
        signed = client.create_order(args)
        resp = client.post_order(signed)
        return resp
    except Exception as e:
        print(f"[ORDER] Limit SELL failed: {e}")
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
            end_date = pos.get("end_date", "")

            # Check if market is past its end date — if so, don't try to sell,
            # wait for on-chain settlement instead
            days_remaining = days_until_end(end_date) if end_date else None
            market_expired = days_remaining is not None and days_remaining < -0.04  # ~1 hour past

            # Try to get current price from orderbook
            current_price = None
            market_resolved = False

            if market_expired:
                # Market ended — treat as resolved, skip orderbook query
                market_resolved = True
                print(f"[POSITIONS] Market expired ({abs(days_remaining):.1f}d ago): {pos['question'][:50]}")
            else:
                try:
                    raw_book = client.get_order_book(token_id)
                    book = orderbook_to_dict(raw_book)
                    bids = book.get("bids", [])
                    if bids:
                        current_price = float(bids[0]["price"])
                    elif book.get("last_trade_price"):
                        current_price = float(book["last_trade_price"])
                except Exception as e:
                    err_str = str(e)
                    # 404 = orderbook gone = market resolved/settled
                    if "404" in err_str or "No orderbook" in err_str:
                        market_resolved = True
                        print(f"[POSITIONS] Market resolved (no orderbook): {pos['question'][:50]}")

            # If market resolved/expired, check if shares still exist on-chain
            if market_resolved:
                actual = get_actual_shares(client, token_id)
                # If shares == 0, settlement already happened (won = USDC credited, lost = shares burned)
                # If shares > 0, settlement still pending — keep tracking
                if actual <= 0.01:
                    # Settlement complete — position is done
                    # We can't know exact PnL since settlement is automatic,
                    # but we can check if our USDC balance went up
                    send(
                        f"SETTLED: {pos['question'][:50]}\n"
                        f"  {side} @ {entry_price:.3f} | size=${pos.get('size_usdc', 0):.2f} | shares gone → settlement complete"
                    )
                    state.setdefault("trades", []).append({
                        **pos,
                        "exit_price": None,
                        "pnl_pct": None,
                        "pnl_usdc": None,
                        "closed_at": str(datetime.now(timezone.utc)),
                        "close_reason": "settled",
                    })
                else:
                    # Shares still on-chain — settlement pending, keep tracking
                    send(
                        f"RESOLVED (pending): {pos['question'][:50]}\n"
                        f"  {side} @ {entry_price:.3f} | on-chain={actual:.2f} shares | awaiting settlement"
                    )
                    still_open.append(pos)
                continue

            # If past end_date and no price available, clean up after 3 hours
            if current_price is None:
                if end_date:
                    days_remaining = days_until_end(end_date)
                    if days_remaining is not None and days_remaining < -0.125:  # 3 hours
                        send(
                            f"EXPIRED (no price): {pos['question'][:50]}\n"
                            f"  {side} | shares={shares:.2f} @ entry={entry_price:.3f}"
                        )
                        state.setdefault("trades", []).append({
                            **pos,
                            "exit_price": None,
                            "pnl_pct": None,
                            "pnl_usdc": None,
                            "closed_at": str(datetime.now(timezone.utc)),
                            "close_reason": "expired/no-price",
                        })
                        continue
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
            # TP: for entries >= 0.20, take profit at +60%
            # For entries < 0.20, take profit at +200% (3x) or hold to near-resolution
            # This captures meaningful gains while still allowing big wins
            elif entry_price >= 0.20 and pnl_pct >= 0.60:
                should_close = True
                reason = f"TP +{pnl_pct*100:.1f}%"
            elif entry_price < 0.20 and pnl_pct >= 2.0:
                should_close = True
                reason = f"TP +{pnl_pct*100:.1f}% (low-entry)"

            if should_close:
                close_resp = None
                sell_succeeded = False
                if shares > 0:
                    close_resp = place_market_sell(client, token_id, shares, current_price)
                    if close_resp is not None:
                        # Verify sell actually filled by checking on-chain balance
                        import time
                        time.sleep(1)  # brief wait for settlement
                        remaining = get_actual_shares(client, token_id)
                        sell_succeeded = remaining < 0.5  # less than 0.5 shares = filled
                        if not sell_succeeded:
                            print(f"[ORDER] Sell order placed but not filled. Remaining: {remaining:.2f} shares")

                # Only count PnL if sell actually went through
                if sell_succeeded:
                    pnl_usdc = shares * (current_price - entry_price)
                    pnl_pct_final = pnl_pct
                else:
                    # Sell failed — shares still held, mark as failed close attempt
                    pnl_usdc = 0.0
                    pnl_pct_final = None

                send(
                    f"{reason}: {pos['question'][:50]}\n"
                    f"  {side} | entry={entry_price:.3f} -> {current_price:.3f}\n"
                    f"  Shares={shares:.2f} | PnL=${pnl_usdc:.2f}"
                    + (f" | SOLD" if sell_succeeded else " | SELL FAILED (holding)")
                )

                if sell_succeeded:
                    closed_rec = {
                        **pos,
                        "exit_price": current_price,
                        "pnl_pct": pnl_pct_final,
                        "pnl_usdc": pnl_usdc,
                        "closed_at": str(datetime.now(timezone.utc)),
                        "close_reason": reason,
                    }
                    state.setdefault("trades", []).append(closed_rec)
                    balance += pnl_usdc
                else:
                    # Keep position open if sell failed — retry next session
                    still_open.append(pos)
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

        if not token_id or entry_price <= 0:
            continue

        # Kelly sizing — aggressive with bankroll for 10x goal
        odds = 1.0 / entry_price
        days_left = opp.get("days_left")
        volume = opp.get("volume_24h", 0)
        score = opp.get("score", 0)

        # Base Kelly fraction scales with conviction signals
        kelly_frac = 0.25
        if days_left is not None and days_left <= 1:
            kelly_frac = 0.50  # same-day resolution: highest conviction
        elif days_left is not None and days_left <= 3:
            kelly_frac = 0.40

        # Boost for high-volume markets (more liquid = more reliable pricing)
        if volume > 50000:
            kelly_frac *= 1.2
        elif volume > 10000:
            kelly_frac *= 1.1

        # Boost for near-arb opportunities
        if opp.get("is_near_arb"):
            kelly_frac *= 1.3

        k = kelly_fraction(fair_price, odds, fraction=kelly_frac)
        # Progressive sizing: scale with bankroll
        max_for_bankroll = min(balance * MAX_POSITION_PCT, MAX_POSITION_USDC)
        size = min(k * balance, max_for_bankroll)
        size = max(MIN_POSITION_USDC, round(size, 2))

        # Cap at 25% of remaining balance per trade
        if size > balance * 0.25:
            size = round(balance * 0.25, 2)

        if size > balance * 0.95:
            size = round(balance * 0.95, 2)

        # Place order
        result = place_market_buy(client, token_id, size)
        if result:
            from math import floor
            # Query actual on-chain balance for precise share count
            shares_est = get_actual_shares(client, token_id)
            if shares_est <= 0:
                # Fallback to estimate if query fails
                fill_price = float((result or {}).get("price", entry_price) or entry_price)
                if fill_price <= 0:
                    fill_price = entry_price
                shares_est = floor((size / fill_price) * 100) / 100.0

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
                "end_date": opp.get("end_date", ""),
                "days_left_at_entry": opp.get("days_left"),
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
