"""Two-way Telegram communication for the trading agent.

Supports:
- Sending messages/summaries to user
- Receiving commands from user between sessions
- Persistent offset tracking so messages aren't re-read
"""
import json
import os
import requests
from trader.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

OFFSET_FILE = os.path.join(os.path.dirname(__file__), "..", "telegram_offset.json")


def _load_offset() -> int:
    try:
        with open(OFFSET_FILE) as f:
            return json.load(f).get("offset", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def _save_offset(offset: int):
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


def send(message: str, parse_mode: str = None) -> bool:
    """Send a message to the user via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TG] {message}")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TG SEND FAILED] {e}")
        return False


def get_user_messages() -> list[dict]:
    """Fetch new messages from user since last check.

    Returns list of dicts: [{"text": "...", "date": unix_ts, "from": "name"}, ...]
    """
    if not TELEGRAM_BOT_TOKEN:
        return []
    try:
        offset = _load_offset()
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 1, "limit": 50}
        if offset:
            params["offset"] = offset
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not data.get("ok"):
            return []

        messages = []
        max_id = offset
        for update in data.get("result", []):
            uid = update["update_id"]
            if uid >= max_id:
                max_id = uid + 1
            msg = update.get("message", {})
            # Only process messages from our chat
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id == TELEGRAM_CHAT_ID:
                messages.append({
                    "text": msg.get("text", ""),
                    "date": msg.get("date", 0),
                    "from": msg.get("from", {}).get("first_name", "unknown"),
                })

        if max_id > offset:
            _save_offset(max_id)

        return messages
    except Exception as e:
        print(f"[TG RECV FAILED] {e}")
        return []


def send_session_summary(balance: float, positions: list, session_num: int,
                         trades_today: list = None, notes: str = ""):
    """Send a formatted session summary to user."""
    lines = [
        f"📊 Session {session_num} Summary",
        f"💰 Balance: ${balance:.2f}",
        f"📈 Campaign: $100 → ${balance:.2f} ({(balance/100-1)*100:+.1f}%)",
    ]
    if positions:
        lines.append(f"\n🎯 Open positions ({len(positions)}):")
        for p in positions:
            lines.append(f"  • {p.get('question','?')[:40]} @ {p.get('entry_price','?')}")
    else:
        lines.append("📭 No open positions")

    if trades_today:
        wins = sum(1 for t in trades_today if (t.get('pnl_usdc') or 0) > 0)
        losses = len(trades_today) - wins
        pnl = sum(t.get('pnl_usdc') or 0 for t in trades_today)
        lines.append(f"\n📋 Today: {wins}W/{losses}L, PnL: ${pnl:+.2f}")

    if notes:
        lines.append(f"\n📝 {notes}")

    send("\n".join(lines))


def check_user_commands() -> dict:
    """Check for user commands and return parsed intent.

    Supported commands:
    - /status - request portfolio status
    - /stop - halt all trading
    - /resume - resume trading
    - /bet <amount> <market> <side> - manual trade instruction
    - any text - treated as general instruction for the agent

    Returns: {"commands": [...], "instructions": [...]}
    """
    messages = get_user_messages()
    result = {"commands": [], "instructions": []}

    for msg in messages:
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        if text.startswith("/status"):
            result["commands"].append({"type": "status"})
        elif text.startswith("/stop"):
            result["commands"].append({"type": "stop"})
        elif text.startswith("/resume"):
            result["commands"].append({"type": "resume"})
        elif text.startswith("/bet"):
            result["commands"].append({"type": "bet", "raw": text})
        elif text.startswith("/"):
            result["commands"].append({"type": "unknown", "raw": text})
        else:
            result["instructions"].append(text)

    return result
