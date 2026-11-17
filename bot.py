"""Telegram wrapper around the books and tax engine.

Standard library only: no pip install, no framework. Long-polls the Bot API with
urllib, hands each message to the same parse/store functions the CLI uses, and
answers with the same text the CLI prints.

The database is ephemeral: it is removed when the bot starts, and no receipt data
is kept after the demo. Nothing here calls a model at runtime.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

from parse import parse_receipt
from store import connect, insert_entry, list_entries

DB_PATH = os.environ.get("BOOKS_DB", "books.db")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_token.txt")

HELP = (
    "Books and tax bot. Send one line per receipt:\n\n"
    "Takealot, R1,150.00, 14 Nov 2026, office chair\n\n"
    "Commands:\n"
    "/books - what is recorded\n"
    "/vat - this month's VAT\n"
    "/pack - CSV tax pack\n"
    "/clear - delete everything (no receipt data is kept)\n"
    "/help - this message"
)


def format_rands(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}R{whole:,}.{fraction:02d}"


def rows_text(month=None):
    conn = connect(DB_PATH)
    try:
        entries = list_entries(conn, month)
    finally:
        conn.close()

    if not entries:
        return "No entries yet."

    lines = []
    for entry in entries:
        lines.append(
            f"{entry[1]}  {entry[2]}  {format_rands(entry[4])} (VAT {format_rands(entry[6])})"
        )
    return "\n".join(lines)


def vat_text(month):
    conn = connect(DB_PATH)
    try:
        entries = list_entries(conn, month)
    finally:
        conn.close()

    gross = sum(entry[4] for entry in entries)
    vat = sum(entry[6] for entry in entries)
    return (
        f"Month {month}\n"
        f"Gross sales  {format_rands(gross)}\n"
        f"Output VAT   {format_rands(vat)}\n"
        f"Entries      {len(entries)}"
    )


def pack_text(month):
    conn = connect(DB_PATH)
    try:
        entries = list_entries(conn, month)
    finally:
        conn.close()

    if not entries:
        return "No entries yet, so nothing to pack."

    lines = ["date,vendor,description,net_zar,vat_zar,gross_zar"]
    for entry in entries:
        lines.append(
            f"{entry[1]},{entry[2]},{entry[3]},"
            f"{entry[5] / 100:.2f},{entry[6] / 100:.2f},{entry[4] / 100:.2f}"
        )
    return "```\n" + "\n".join(lines) + "\n```"


def clear_all():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    return "Deleted. Nothing of yours is kept."


def current_month():
    return time.strftime("%Y-%m")


def answer(text):
    """Turn one incoming message into one reply. No network, no model."""
    text = (text or "").strip()
    if not text:
        return HELP

    lowered = text.lower()
    if lowered in ("/start", "/help", "help"):
        return HELP
    if lowered == "/books":
        return rows_text()
    if lowered == "/vat":
        return vat_text(current_month())
    if lowered == "/pack":
        return pack_text(current_month())
    if lowered == "/clear":
        return clear_all()

    try:
        entry = parse_receipt(text)
    except ValueError as error:
        return f"{error}\n\nSend it like this:\nTakealot, R1,150.00, 14 Nov 2026, office chair"

    conn = connect(DB_PATH)
    try:
        added = insert_entry(conn, entry)
    finally:
        conn.close()

    if not added:
        return "Already recorded — the same receipt is not entered twice."

    return (
        f"Recorded.\n{entry['vendor']}  {format_rands(entry['gross_cents'])}\n"
        f"VAT {format_rands(entry['vat_cents'])}  net {format_rands(entry['net_cents'])}\n"
        f"Type /vat to see the month."
    )


def api(method, payload):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(payload).encode()
    with urllib.request.urlopen(url, data=data, timeout=60) as response:
        return json.loads(response.read().decode())


def send(chat_id, text):
    api("sendMessage", {"chat_id": chat_id, "text": text})


def run():
    offset = None
    while True:
        payload = {"timeout": 50}
        if offset is not None:
            payload["offset"] = offset
        try:
            update = api("getUpdates", payload)
        except Exception as error:  # network blip: wait and retry
            print(f"poll failed: {error}", flush=True)
            time.sleep(3)
            continue

        for item in update.get("result", []):
            offset = item["update_id"] + 1
            message = item.get("message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            if not chat_id:
                continue
            reply = answer(message.get("text", ""))
            print(f"answered chat {chat_id}: {reply.splitlines()[0][:40]}", flush=True)
            send(chat_id, reply)


def load_token():
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return os.environ["TELEGRAM_BOT_TOKEN"]
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as handle:
            value = handle.read().strip()
        if value:
            return value
    return None


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        for line in (
            "/start",
            "Takealot, R1,150.00, 14 Nov 2026, office chair",
            "Takealot, R1,150.00, 14 Nov 2026, office chair",
            "junk",
            "/books",
            "/vat",
            "/pack",
        ):
            print(f"— {line}")
            print(answer(line))
            print()
        raise SystemExit(0)

    TOKEN = load_token()
    if not TOKEN:
        print(
            "No token. Save the BotFather token in bot_token.txt next to this file,\n"
            "or set TELEGRAM_BOT_TOKEN. Never paste it into a chat.",
            flush=True,
        )
        raise SystemExit(1)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    me = api("getMe", {})
    print(f"running as @{me['result']['username']}", flush=True)
    run()
