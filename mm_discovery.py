"""
Market discovery: find next BTC 15-min candle, detect streaks.
"""

import json
from datetime import datetime, timezone

from mm_config import _get_gamma, utcnow, traded_candles


def find_next_candle():
    """Return info dict for the next unstarted 15-min BTC candle, or None."""
    now_ts = int(utcnow().timestamp())
    base = ((now_ts // 900) + 1) * 900

    for i in range(6):
        ts = base + i * 900
        if ts in traded_candles:
            continue
        slug = f"btc-updown-15m-{ts}"
        try:
            r = _get_gamma(f"/events/slug/{slug}")
            if r.status_code != 200:
                continue
            mkt = r.json().get("markets", [None])[0]
            if not mkt:
                continue
            tokens = json.loads(mkt.get("clobTokenIds", "[]"))
            outcomes = json.loads(mkt.get("outcomes", "[]"))
            if len(tokens) < 2:
                continue
            up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)
            dn_idx = 1 - up_idx
            return {
                "up_token": tokens[up_idx],
                "dn_token": tokens[dn_idx],
                "candle_start": datetime.fromtimestamp(ts, tz=timezone.utc),
                "question": mkt.get("question", slug),
                "slug": slug,
            }
        except Exception as e:
            print(f"[MM] discovery {slug}: {e}")
            continue
    return None


def get_streak():
    """Check last resolved 15-min candles. Returns (count, color) e.g. (4, 'UP')."""
    now_ts = int(utcnow().timestamp())
    current_boundary = (now_ts // 900) * 900

    streak = 0
    last_color = None

    for i in range(1, 8):  # check up to 7 past candles
        ts = current_boundary - i * 900
        slug = f"btc-updown-15m-{ts}"
        try:
            r = _get_gamma(f"/events/slug/{slug}")
            if r.status_code != 200:
                break
            mkt = r.json().get("markets", [None])[0]
            if not mkt or not mkt.get("closed"):
                break
            outcomes = json.loads(mkt.get("outcomes", "[]"))
            prices = json.loads(mkt.get("outcomePrices", "[]"))
            if len(outcomes) < 2 or len(prices) < 2:
                break
            up_idx = next((j for j, o in enumerate(outcomes) if o.lower() == "up"), 0)
            color = "UP" if float(prices[up_idx]) > 0.5 else "DN"

            if last_color is None:
                last_color = color
                streak = 1
            elif color == last_color:
                streak += 1
            else:
                break  # streak broken
        except Exception as e:
            print(f"[MM] streak {slug}: {e}")
            break

    return streak, last_color or "NONE"
