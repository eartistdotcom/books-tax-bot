import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import parse
import store


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "books.db")
SAMPLES = (
    "Takealot, R1,150.00, 14 Nov 2026, office chair",
    "Pick n Pay, R1,234.56, 14 Nov 2026, office consumables",
    "Vodacom, R899.00, 14 Nov 2026, phone and data",
)

SELFTEST_CONN = None
SELFTEST_MODE = False


def format_rands(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}R{whole:,}.{fraction:02d}"


def format_zar(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def current_month():
    return time.strftime("%Y-%m")


def menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "Record a receipt", "callback_data": "cmd:examples"},
                {"text": "Books", "callback_data": "cmd:books"},
            ],
            [
                {"text": "VAT this month", "callback_data": "cmd:vat"},
                {"text": "Tax pack (CSV)", "callback_data": "cmd:pack"},
            ],
            [
                {"text": "Help", "callback_data": "cmd:help"},
                {"text": "Clear", "callback_data": "cmd:clear"},
            ],
        ]
    }


def examples_keyboard():
    buttons = [
        [{"text": line, "callback_data": f"ex:{index}"}]
        for index, line in enumerate(SAMPLES)
    ]
    buttons.append([{"text": "Menu", "callback_data": "cmd:help"}])
    return {"inline_keyboard": buttons}


def help_text():
    return (
        "Send a receipt as: vendor, amount, date, description\n"
        "Example: Takealot, R1,150.00, 14 Nov 2026, office chair"
    )


def entries_for(month=None):
    if SELFTEST_CONN is not None:
        return store.list_entries(SELFTEST_CONN, month)

    conn = store.connect(DB_PATH)
    try:
        return store.list_entries(conn, month)
    finally:
        conn.close()


def record_receipt(line):
    try:
        entry = parse.parse_receipt(line)
    except ValueError as error:
        return (
            f"{error}\n"
            "Expected format: vendor, amount, date, description\n"
            "Choose a sample receipt:",
            examples_keyboard(),
            None,
        )

    if SELFTEST_CONN is not None:
        added = store.insert_entry(SELFTEST_CONN, entry)
    else:
        conn = store.connect(DB_PATH)
        try:
            added = store.insert_entry(conn, entry)
        finally:
            conn.close()

    if not added:
        return "Already recorded.", menu_keyboard(), None

    text = (
        f"Recorded: {entry['vendor']}\n"
        f"Gross: {format_rands(entry['gross_cents'])}\n"
        f"Net: {format_rands(entry['net_cents'])}\n"
        f"VAT: {format_rands(entry['vat_cents'])}\n"
        f"Date: {entry['date']}"
    )
    return text, menu_keyboard(), None


def books_response():
    entries = entries_for()
    if not entries:
        return "No entries yet.", menu_keyboard(), None

    headers = ("date", "vendor", "gross", "vat")
    rows = [
        (
            str(entry[1]),
            str(entry[2]),
            format_rands(entry[4]),
            format_rands(entry[6]),
        )
        for entry in entries
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(headers[index].ljust(widths[index]) for index in range(4))
    ]
    lines.extend(
        "  ".join(row[index].ljust(widths[index]) for index in range(4))
        for row in rows
    )
    return "\n".join(lines), menu_keyboard(), None


def vat_response():
    month = current_month()
    entries = entries_for(month)
    gross = sum(entry[4] for entry in entries)
    vat = sum(entry[6] for entry in entries)
    text = (
        f"Month: {month}\n"
        f"Gross sales: {format_rands(gross)}\n"
        f"Output VAT: {format_rands(vat)}\n"
        f"Entries: {len(entries)}"
    )
    return text, menu_keyboard(), None


def make_taxpack(entries):
    import io

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["date", "vendor", "description", "net_zar", "vat_zar", "gross_zar"]
    )
    for entry in entries:
        writer.writerow(
            [
                entry[1],
                entry[2],
                entry[3],
                format_zar(entry[5]),
                format_zar(entry[6]),
                format_zar(entry[4]),
            ]
        )
    return output.getvalue()


def pack_response():
    month = current_month()
    entries = entries_for(month)
    csv_text = make_taxpack(entries)
    filename = "taxpack.csv"
    if not SELFTEST_MODE:
        with open(os.path.join(BASE_DIR, filename), "w", newline="", encoding="utf-8") as handle:
            handle.write(csv_text)

    return (
        f"Tax pack saved to {filename} ({len(entries)} rows).",
        menu_keyboard(),
        (filename, csv_text.encode("utf-8")),
    )


def handle_command(command):
    if command == "books":
        return books_response()
    if command == "vat":
        return vat_response()
    if command == "pack":
        return pack_response()
    if command == "examples":
        return "Choose a sample receipt to record:", examples_keyboard(), None
    if command == "help":
        return help_text(), menu_keyboard(), None
    if command in ("clear", "start"):
        return "Choose an option:", menu_keyboard(), None
    return "Unknown command. Send /help for instructions.", menu_keyboard(), None


def handle_text(text):
    stripped = text.strip()
    if stripped.startswith("/"):
        command = stripped.split()[0][1:].split("@", 1)[0].lower()
        return handle_command(command)
    return record_receipt(stripped)


def handle_callback_data(data):
    if data.startswith("cmd:"):
        return handle_command(data[4:])
    if data.startswith("ex:"):
        try:
            index = int(data[3:])
            line = SAMPLES[index]
        except (ValueError, IndexError):
            return "That sample is not available.", examples_keyboard(), None
        return record_receipt(line)
    return "Choose an option:", menu_keyboard(), None


def api_request(token, method, payload, timeout=60):
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API request failed")
    return result["result"]


def send_document(token, chat_id, filename, content):
    boundary = f"----copilot{time.time_ns()}"
    chunks = []

    def add_field(name, value):
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    add_field("chat_id", chat_id)
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="document"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            b"Content-Type: text/csv; charset=utf-8\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API request failed")
    return result["result"]


def send_response(token, chat_id, result):
    text, keyboard, document = result
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": keyboard,
    }
    api_request(token, "sendMessage", payload)
    if document is not None:
        filename, content = document
        send_document(token, chat_id, filename, content)


def process_update(token, update):
    update_id = update.get("update_id")

    callback = update.get("callback_query")
    if callback:
        api_request(
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback["id"]},
        )
        print(f"answered update {update_id}", flush=True)

        result = handle_callback_data(callback.get("data", ""))
        text, keyboard, document = result
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        edit_payload = {
            "chat_id": chat.get("id"),
            "message_id": message.get("message_id"),
            "text": text,
            "reply_markup": keyboard,
        }
        try:
            api_request(token, "editMessageText", edit_payload)
        except Exception:
            api_request(
                token,
                "sendMessage",
                {
                    "chat_id": chat.get("id"),
                    "text": text,
                    "reply_markup": keyboard,
                },
            )
        if document is not None:
            filename, content = document
            send_document(token, chat.get("id"), filename, content)
        return

    message = update.get("message")
    if message and isinstance(message.get("text"), str):
        result = handle_text(message["text"])
        send_response(token, message["chat"]["id"], result)
        print(f"answered update {update_id}", flush=True)


def load_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token

    token_path = os.path.join(BASE_DIR, "bot_token.txt")
    try:
        with open(token_path, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        token = ""

    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN or add a token to bot_token.txt.")
    return token


def startup(token):
    try:
        os.remove(DB_PATH)
    except FileNotFoundError:
        pass

    while True:
        try:
            me = api_request(token, "getMe", {})
            api_request(
                token,
                "setMyCommands",
                {
                    "commands": [
                        {"command": "books", "description": "List recorded receipts"},
                        {"command": "vat", "description": "Show this month's VAT"},
                        {"command": "pack", "description": "Create a CSV tax pack"},
                        {"command": "examples", "description": "Choose a sample receipt"},
                        {"command": "clear", "description": "Show the menu"},
                        {"command": "help", "description": "Show usage help"},
                    ]
                },
            )
            print(f"running as @{me['username']}", flush=True)
            return
        except Exception as error:
            print(type(error).__name__, flush=True)
            time.sleep(3)


def run(token):
    startup(token)
    offset = None

    while True:
        try:
            payload = {
                "timeout": 50,
                "allowed_updates": ["message", "callback_query"],
            }
            if offset is not None:
                payload["offset"] = offset

            updates = api_request(token, "getUpdates", payload, timeout=60)
            for update in updates:
                process_update(token, update)
                offset = update["update_id"] + 1
        except Exception as error:
            print(type(error).__name__, flush=True)
            time.sleep(3)


def selftest():
    global SELFTEST_CONN, SELFTEST_MODE

    SELFTEST_CONN = store.connect(":memory:")
    SELFTEST_MODE = True

    try:
        for command in ("books", "vat", "pack", "examples", "clear", "help"):
            result = handle_text(f"/{command}")
            print(f"/{command}:\n{result[0]}")

        for index in range(len(SAMPLES)):
            result = handle_callback_data(f"ex:{index}")
            print(f"ex:{index}:\n{result[0]}")

        for command in ("examples", "books", "vat", "pack", "help", "clear"):
            result = handle_callback_data(f"cmd:{command}")
            print(f"cmd:{command}:\n{result[0]}")
    finally:
        SELFTEST_CONN.close()
        SELFTEST_CONN = None
        SELFTEST_MODE = False


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        selftest()
    else:
        try:
            run(load_token())
        except RuntimeError as error:
            print(error, file=sys.stderr)
            raise SystemExit(1)