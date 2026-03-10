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
from trader.notify import send
from trader.strategy import run_session


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


if __name__ == "__main__":
    main()
