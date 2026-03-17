#!/usr/bin/env python3
"""
Main entry point for the Polymarket trader.
Called by session_runner.sh via Claude agent each session.
"""
import sys
import traceback
from datetime import datetime, timezone

from trader.client import get_client, get_usdc_balance
from trader.config import TARGET_BALANCE_USDC
from trader.notify import send, send_session_summary, check_user_commands
from trader.strategy import run_session, load_state


def handle_user_commands(client, state):
    """Check Telegram for user commands and respond."""
    commands = check_user_commands()
    for cmd in commands:
        cmd_lower = cmd.lower().strip()
        if cmd_lower in ("status", "s", "/status"):
            balance = get_usdc_balance(client)
            send_session_summary(balance, state.get("positions", []),
                                 state.get("trades", [])[-5:])
        elif cmd_lower in ("positions", "pos", "/positions"):
            positions = state.get("positions", [])
            if not positions:
                send("No open positions.")
            else:
                lines = [f"Open positions ({len(positions)}):"]
                for p in positions:
                    lines.append(f"  • {p['question'][:45]} | {p['side']} @ {p['entry_price']:.3f} | ${p.get('size_usdc', 0):.2f}")
                send("\n".join(lines))
        elif cmd_lower.startswith("stop"):
            send("Trading paused. Send 'go' to resume.")
            return "stop"
        elif cmd_lower in ("go", "resume", "/go"):
            send("Trading resumed.")
        else:
            send(f"Unknown command: {cmd}\nCommands: status, positions, stop, go")
    return None


def main():
    now = datetime.now(timezone.utc).isoformat()
    print(f"[MAIN] Starting session at {now}")

    try:
        client = get_client()
    except Exception as e:
        msg = f"Failed to initialize client: {e}"
        print(f"[MAIN] {msg}")
        send(f"TRADER ERROR: {msg}")
        sys.exit(1)

    balance = get_usdc_balance(client)
    print(f"[MAIN] Balance: ${balance:.2f} USDC")

    # Check user commands from Telegram
    state = load_state()
    action = handle_user_commands(client, state)
    if action == "stop":
        print("[MAIN] User requested stop via Telegram.")
        return

    if balance <= 0:
        print("[MAIN] Balance is 0 — funds not yet deposited or not bridged to CLOB. Skipping.")
        send("Polymarket balance is $0. Waiting for funds.")
        return

    if balance >= TARGET_BALANCE_USDC:
        send(f"GOAL REACHED! Balance: ${balance:.2f} USDC >= ${TARGET_BALANCE_USDC:.2f}")
        print("[MAIN] Target reached!")
        return

    try:
        run_session(client, balance)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[MAIN] Session error: {e}\n{tb}")
        send(f"SESSION ERROR: {e}")

    # Send session summary at end
    balance = get_usdc_balance(client)
    state = load_state()
    recent = state.get("trades", [])[-5:]
    send_session_summary(balance, state.get("positions", []), recent)


if __name__ == "__main__":
    main()
