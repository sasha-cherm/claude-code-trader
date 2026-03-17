"""Telegram notifications and bidirectional messaging."""
import json
import os
import requests
from trader.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_UPDATE_OFFSET_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "tg_offset.txt")


def send(message: str, parse_mode: str = None) -> None:
    """Send a message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[NOTIFY] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[NOTIFY FAILED] {e}\n[MSG] {message}")


def get_updates() -> list[dict]:
    """Fetch new messages sent TO the bot since last check.

    Returns list of message dicts with keys: text, from_id, date, message_id.
    Only returns messages from the configured chat.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return []

    offset = _load_offset()
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 1, "allowed_updates": '["message"]'}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"[TG] getUpdates failed: {e}")
        return []

    if not data.get("ok"):
        return []

    messages = []
    max_update_id = offset - 1 if offset else 0
    for update in data.get("result", []):
        uid = update.get("update_id", 0)
        max_update_id = max(max_update_id, uid)
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            continue
        text = msg.get("text", "")
        if text:
            messages.append({
                "text": text,
                "from_id": msg.get("from", {}).get("id"),
                "date": msg.get("date"),
                "message_id": msg.get("message_id"),
            })

    if max_update_id >= (offset or 0):
        _save_offset(max_update_id + 1)

    return messages


def send_session_summary(balance: float, positions: list, recent_trades: list = None) -> None:
    """Send a formatted session summary to Telegram."""
    lines = ["📊 *Session Summary*", f"💰 Balance: ${balance:.2f} USDC"]

    if positions:
        lines.append(f"\n📂 Open Positions ({len(positions)}):")
        for p in positions:
            q = p.get("question", "?")[:40]
            entry = p.get("entry_price", 0)
            lines.append(f"  • {q} @ {entry:.2f}")
    else:
        lines.append("📂 No open positions")

    if recent_trades:
        wins = sum(1 for t in recent_trades if (t.get("pnl_usdc") or 0) > 0)
        losses = sum(1 for t in recent_trades if (t.get("pnl_usdc") or 0) < 0)
        total_pnl = sum(t.get("pnl_usdc") or 0 for t in recent_trades)
        lines.append(f"\n📈 Recent: {wins}W/{losses}L, PnL: ${total_pnl:+.2f}")

    pct = ((balance - 100) / 100) * 100
    lines.append(f"\n🎯 Campaign: $100 → ${balance:.2f} ({pct:+.1f}%)")
    lines.append(f"🏁 Target: $1000")

    send("\n".join(lines), parse_mode="Markdown")


def check_user_commands() -> list[str]:
    """Check for user messages and return any command texts.

    Recognized commands:
      status - request current portfolio status
      sell <market> - request to sell a position
      buy <market> <amount> - manual buy request
      stop - pause automated trading
      go - resume automated trading

    Returns raw text of each message for the caller to interpret.
    """
    messages = get_updates()
    commands = []
    for msg in messages:
        text = msg["text"].strip()
        commands.append(text)
        print(f"[TG] User message: {text}")
    return commands


def _load_offset() -> int:
    try:
        with open(_UPDATE_OFFSET_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_offset(offset: int) -> None:
    os.makedirs(os.path.dirname(_UPDATE_OFFSET_FILE), exist_ok=True)
    with open(_UPDATE_OFFSET_FILE, "w") as f:
        f.write(str(offset))
