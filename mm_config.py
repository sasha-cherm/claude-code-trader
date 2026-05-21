"""
Shared config, globals, and utilities for BTC 15-min candle spread scalper.
"""

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone, timedelta

import requests

# ─── Config ──────────────────────────────────────────────────────────────────
ORDER_SIZE = 6.0
POLL_SEC = 1.0
GAMMA = "https://gamma-api.polymarket.com"
TRADE_LOG = "logs/btc_15m_mm_trades.jsonl"
MIN_SIZE = 5.0
TICK = 0.01
MIN_BALANCE = 3.0         # only need one leg
SELL_DEADLINE = 0          # (legacy, unused in fair-value mode)
ENTER_NORMAL = 840         # 14 min before start
MAKER_FEE = 0.0            # maker fee rate (0 for GTC limit orders on Polymarket)

# ─── Mutable globals ─────────────────────────────────────────────────────────
running = True
traded_candles: set[int] = set()


def set_running(val):
    global running
    running = val


def _sig(s, _):
    global running
    print(f"\n[MM] Signal {s}, stopping...")
    running = False

signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


# ─── Utilities ────────────────────────────────────────────────────────────────

def utcnow():
    return datetime.now(timezone.utc)


def log_trade(entry):
    os.makedirs("logs", exist_ok=True)
    with open(TRADE_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _retry(fn, retries=3, delay=2, tag="MM"):
    """Retry a callable up to `retries` times with `delay`s between attempts."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < retries:
                print(f"[{tag}] retry {attempt+1}/{retries}: {e}")
                time.sleep(delay)
            else:
                raise


def _get_gamma(path, retries=3):
    """GET from Gamma API with retries on timeout/network errors."""
    def _do():
        return requests.get(f"{GAMMA}{path}", timeout=10)
    return _retry(_do, retries=retries, tag="GAMMA")


def cancel_all_open_orders():
    """Cancel all open orders on the CLOB (cleanup before restart)."""
    try:
        from trader.client import get_client
        client = get_client()
        orders = client.get_open_orders()
        if not orders:
            return
        oids = [o.get("id") or o.get("orderID") for o in orders
                if isinstance(o, dict) and o.get("status") == "LIVE"]
        oids = [o for o in oids if o]
        if oids:
            print(f"[MM] Cancelling {len(oids)} stale orders from previous instance")
            client.cancel_orders(oids)
    except Exception as e:
        print(f"[MM] Stale order cancel error: {e}")


def kill_other_instances():
    """Kill any other btc_15m_mm.py processes and cancel their open orders."""
    my_pid = os.getpid()
    found = False
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "btc_15m_mm.py"], text=True
        ).strip()
        for line in out.splitlines():
            pid = int(line)
            if pid != my_pid:
                print(f"[MM] Killing old instance PID {pid}")
                os.kill(pid, signal.SIGKILL)
                found = True
    except subprocess.CalledProcessError:
        pass  # no other instances
    if found:
        time.sleep(1)
        cancel_all_open_orders()
