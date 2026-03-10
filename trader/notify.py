"""Telegram notifications."""
import requests
from trader.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[NOTIFY] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print(f"[NOTIFY FAILED] {e}\n[MSG] {message}")
