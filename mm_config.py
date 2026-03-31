"""
Shared config, globals, and utilities for BTC 15-min candle spread scalper.
"""

import json
import os
import signal
import subprocess
import math
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
SELL_DEADLINE = 0          # close at candle start if SELL not filled
ENTER_NORMAL = 600         # 10 min before start (no streak)
ENTER_STREAK = 300         # 5 min before start (streak detected)

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


def kill_other_instances():
    """Kill any other btc_15m_mm.py processes before starting."""
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "btc_15m_mm.py"], text=True
        ).strip()
        for line in out.splitlines():
            pid = int(line)
            if pid != my_pid:
                print(f"[MM] Killing old instance PID {pid}")
                os.kill(pid, signal.SIGKILL)
    except subprocess.CalledProcessError:
        pass  # no other instances
