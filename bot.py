import csv
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request

import ocr
import parse
import store


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "books.db")
SAMPLES = (
    "Takealot, R1,150.00, 14 Nov 2026, office chair",
    "Pick n Pay, R1,234.56, 14 Nov 2026, office consumables",
    "Vodacom, R899.00, 17 Nov 2026, phone and data",
)
SALE_SAMPLES = (
    "Dlamini Plumbing, R5,750.00, 17 Nov 2026, invoice 22",
    "Mokoena Repairs, R2,300.00, 18 Nov 2026, invoice 23",
)

WELCOME = (
    "I keep your books and work out the VAT.\n\n"
    "\U0001F4F8 Send me a photo of a receipt and I will read it.\n"
    "Or paste a line like this:\n"
    "Takealot, R1,150.00, 14 Nov 2026, office chair"
)

REPLY_LABEL_COMMANDS = {
    "📒 books": "books",
    "books": "books",
    "🧾 vat": "vat",
    "vat": "vat",
    "📊 tax report": "pack",
    "tax report": "pack",
    "❓ help": "help",
    "help": "help",
}

PENDING_PHOTOS = {}
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


def month_name(month):
    return time.strftime("%B %Y", time.strptime(month, "%Y-%m"))


def menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "➕ Record a purchase", "callback_data": "cmd:add_in"},
                {"text": "💰 Record a sale", "callback_data": "cmd:add_out"},
            ],
            [
                {"text": "Books", "callback_data": "cmd:books"},
                {"text": "VAT this month", "callback_data": "cmd:vat"},
            ],
            [
                {"text": "Download tax report", "callback_data": "cmd:pack"},
                {"text": "Help", "callback_data": "cmd:help"},
            ],
            [{"text": "Clear", "callback_data": "cmd:clear"}],
        ]
    }


def reply_keyboard():
    return {
        "keyboard": [
            [{"text": "📒 Books"}, {"text": "🧾 VAT"}],
            [{"text": "📊 Tax report"}, {"text": "❓ Help"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def examples_keyboard(kind="in"):
    samples = SALE_SAMPLES if kind == "out" else SAMPLES
    buttons = [
        [{"text": line, "callback_data": f"ex:{kind}:{index}"}]
        for index, line in enumerate(samples)
    ]
    buttons.append([{"text": "Menu", "callback_data": "cmd:help"}])
    return {"inline_keyboard": buttons}


def photo_confirmation_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "✅ It's a purchase", "callback_data": "cfm:in"}],
            [{"text": "✅ It's a sale", "callback_data": "cfm:out"}],
            [{"text": "✏️ No, I'll type it", "callback_data": "cfm:no"}],
        ]
    }


def help_text():
    return (
        "Send one receipt per line: vendor, amount, date, description\n"
        "Example: Takealot, R1,150.00, 14 Nov 2026, office chair\n\n"
        "\U0001F4F8 Send a photo of a receipt and I will read it for you.\n\n"
        "📒 Books lists what is recorded, 🧾 VAT totals the month, "
        "📊 Tax report sends the CSV for your accountant."
    )


def entries_for(month=None):
    if SELFTEST_CONN is not None:
        return store.list_entries(SELFTEST_CONN, month)

    conn = store.connect(DB_PATH)
    try:
        return store.list_entries(conn, month)
    finally:
        conn.close()


def no_receipts_response():
    return (
        "No receipts yet.",
        {
            "inline_keyboard": [
                [{"text": "Record a sample receipt", "callback_data": "cmd:add_in"}]
            ]
        },
        None,
    )


def record_receipt(line, kind="in"):
    try:
        entry = parse.parse_receipt(line, kind=kind)
    except ValueError as error:
        return (
            f"{error}\n"
            "Expected format: vendor, amount, date, description\n"
            "Choose a sample receipt:",
            examples_keyboard(kind),
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

    month = entry["date"][:7]
    month_entries = entries_for(month)
    gross = sum(row[4] for row in month_entries)
    vat = sum(row[6] for row in month_entries)
    count = len(month_entries)
    count_word = "entry" if count == 1 else "entries"

    text = (
        f"Recorded: {entry['vendor']}\n"
        f"Amount: {format_rands(entry['gross_cents'])}\n"
        f"VAT: {format_rands(entry['vat_cents'])}\n"
        f"Net: {format_rands(entry['net_cents'])}\n"
        f"Date: {entry['date']}\n"
        f"{month_name(month)} so far: {format_rands(gross)} gross, "
        f"{format_rands(vat)} VAT, {count} {count_word}"
    )
    return text, menu_keyboard(), None


def books_response():
    entries = entries_for()
    if not entries:
        return no_receipts_response()

    headers = ("date", "dir", "vendor", "gross", "vat")
    rows = [
        (
            str(entry[1]),
            "SALE" if entry[9] == "out" else "BUY",
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
        "  ".join(headers[index].ljust(widths[index]) for index in range(5))
    ]
    lines.extend(
        "  ".join(row[index].ljust(widths[index]) for index in range(5))
        for row in rows
    )
    return "\n".join(lines), menu_keyboard(), None


def vat_response():
    month = current_month()
    entries = entries_for(month)
    sales = [entry for entry in entries if entry[9] == "out"]
    purchases = [entry for entry in entries if entry[9] == "in"]

    sales_gross = sum(entry[4] for entry in sales)
    output_vat = sum(entry[6] for entry in sales)
    purchases_gross = sum(entry[4] for entry in purchases)
    input_vat = sum(entry[6] for entry in purchases)

    sales_word = "entry" if len(sales) == 1 else "entries"
    purchases_word = "entry" if len(purchases) == 1 else "entries"

    text = (
        f"{month_name(month)}\n"
        f"Sales: {len(sales)} {sales_word}, {format_rands(sales_gross)} gross, "
        f"{format_rands(output_vat)} output VAT\n"
        f"Purchases: {len(purchases)} {purchases_word}, "
        f"{format_rands(purchases_gross)} gross, "
        f"{format_rands(input_vat)} input VAT"
    )
    if output_vat >= input_vat:
        text += f"\nNet VAT owed: {format_rands(output_vat - input_vat)}"
    else:
        text += f"\nNet VAT refundable: {format_rands(input_vat - output_vat)}"

    return text, menu_keyboard(), None


def make_taxpack(entries):
    import io

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["date", "kind", "vendor", "description", "net_zar", "vat_zar", "gross_zar"]
    )
    for entry in entries:
        writer.writerow(
            [
                entry[1],
                entry[9],
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
    filename = f"taxpack-{month}.csv"
    if not SELFTEST_MODE:
        with open(
            os.path.join(BASE_DIR, filename), "w", newline="", encoding="utf-8"
        ) as handle:
            handle.write(csv_text)

    rows_word = "row" if len(entries) == 1 else "rows"
    return (
        f"Download tax report for {month} ({len(entries)} {rows_word}).",
        menu_keyboard(),
        (filename, csv_text.encode("utf-8")),
    )


def delete_database():
    if SELFTEST_CONN is not None:
        SELFTEST_CONN.execute("DELETE FROM entries")
        SELFTEST_CONN.commit()
        return

    try:
        os.remove(DB_PATH)
    except FileNotFoundError:
        pass


def handle_command(command):
    if command == "books":
        return books_response()
    if command == "vat":
        return vat_response()
    if command == "pack":
        return pack_response()
    if command in ("examples", "add_in"):
        return "Choose a purchase receipt to record:", examples_keyboard("in"), None
    if command == "add_out":
        return "Choose a sale receipt to record:", examples_keyboard("out"), None
    if command == "help":
        return help_text(), menu_keyboard(), None
    if command == "clear":
        delete_database()
        return "Deleted. Nothing of yours stays with me.", menu_keyboard(), None
    if command == "start":
        return WELCOME, menu_keyboard(), None
    return "Unknown command. Send /help for instructions.", menu_keyboard(), None


def handle_text(text):
    stripped = text.strip()
    reply_command = REPLY_LABEL_COMMANDS.get(stripped.casefold())
    if reply_command:
        return handle_command(reply_command)

    if stripped.startswith("/"):
        parts = stripped.split(maxsplit=1)
        command = parts[0][1:].split("@", 1)[0].lower()
        if command == "sale":
            if len(parts) == 1:
                return handle_command("add_out")
            return record_receipt(parts[1], "out")
        return handle_command(command)

    if stripped.casefold().startswith("sale,"):
        return record_receipt(stripped.split(",", 1)[1].strip(), "out")
    return record_receipt(stripped, "in")


def handle_callback_data(data, chat_id=None):
    if data.startswith("cmd:"):
        return handle_command(data[4:])

    if data.startswith("ex:"):
        try:
            _, kind, index_text = data.split(":", 2)
            samples = SALE_SAMPLES if kind == "out" else SAMPLES
            if kind not in ("in", "out"):
                raise ValueError
            line = samples[int(index_text)]
        except (ValueError, IndexError):
            return "That sample is not available.", examples_keyboard(), None
        return record_receipt(line, kind)

    if data.startswith("cfm:"):
        kind = data[4:]
        if kind == "no":
            if chat_id is not None:
                PENDING_PHOTOS.pop(chat_id, None)
            return "No problem. Send the receipt details as text.", menu_keyboard(), None
        if kind in ("in", "out") and chat_id in PENDING_PHOTOS:
            line = PENDING_PHOTOS.pop(chat_id)
            return record_receipt(line, kind)
        return "That receipt photo is no longer available.", menu_keyboard(), None

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


def send_tax_report_confirmation(token, chat_id, filename):
    api_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": f"{filename} is attached above. It opens in Excel or Google Sheets.",
            "reply_markup": menu_keyboard(),
        },
    )


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
        send_tax_report_confirmation(token, chat_id, filename)


def download_photo(token, photo):
    file_info = api_request(token, "getFile", {"file_id": photo["file_id"]})
    file_path = file_info["file_path"]
    url = (
        f"https://api.telegram.org/file/bot{token}/"
        f"{urllib.parse.quote(file_path, safe='/')}"
    )
    with urllib.request.urlopen(url, timeout=60) as response:
        image_data = response.read()

    suffix = os.path.splitext(file_path)[1] or ".jpg"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temporary_path = handle.name
            handle.write(image_data)
        return ocr.receipt_line(temporary_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def photo_response(token, message):
    photos = message.get("photo") or []
    if not photos:
        return "No receipt photo was found.", menu_keyboard(), None

    photo = max(
        photos,
        key=lambda item: (
            item.get("file_size", 0),
            item.get("width", 0) * item.get("height", 0),
        ),
    )
    try:
        line = download_photo(token, photo)
        entry = parse.parse_receipt(line)
        chat_id = message["chat"]["id"]
        PENDING_PHOTOS[chat_id] = line
        text = (
            f"I read:\n"
            f"Vendor: {entry['vendor']}\n"
            f"Gross: {format_rands(entry['gross_cents'])}\n"
            f"VAT: {format_rands(entry['vat_cents'])}\n"
            f"Net: {format_rands(entry['net_cents'])}\n"
            f"Date: {entry['date']}\n\n"
            "Is this a purchase or a sale?"
        )
        return text, photo_confirmation_keyboard(), None
    except Exception as error:
        return f"Could not read that receipt photo: {error}", menu_keyboard(), None


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

        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        result = handle_callback_data(
            callback.get("data", ""),
            chat.get("id"),
        )
        text, keyboard, document = result
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
            send_tax_report_confirmation(token, chat.get("id"), filename)
        return

    message = update.get("message")
    if message and message.get("photo"):
        result = photo_response(token, message)
        send_response(token, message["chat"]["id"], result)
        print(f"answered update {update_id}", flush=True)
        return

    if message and isinstance(message.get("text"), str):
        text = message["text"]
        if text.strip().split()[0:1] == ["/start"]:
            api_request(
                token,
                "sendMessage",
                {
                    "chat_id": message["chat"]["id"],
                    "text": "Use the buttons below.",
                    "reply_markup": reply_keyboard(),
                },
            )

        result = handle_text(text)
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
                        {"command": "pack", "description": "Download tax report"},
                        {"command": "examples", "description": "Choose a sample receipt"},
                        {"command": "sale", "description": "Record a sale"},
                        {"command": "clear", "description": "Delete everything kept"},
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
                offset = update["update_id"] + 1
                process_update(token, update)
        except Exception as error:
            print(type(error).__name__, flush=True)
            time.sleep(3)


def selftest():
    global SELFTEST_CONN, SELFTEST_MODE

    SELFTEST_CONN = store.connect(":memory:")
    SELFTEST_MODE = True

    try:
        purchase = "Selftest Shop, R115.00, 17 Nov 2026, typed purchase"
        sale = "sale, Selftest Buyer, R230.00, 17 Nov 2026, typed sale"
        slash_sale = "/sale Selftest Client, R345.00, 17 Nov 2026, slash sale"

        print(f"typed purchase:\n{handle_text(purchase)[0]}")
        print(f"typed sale:\n{handle_text(sale)[0]}")
        print(f"/sale:\n{handle_text(slash_sale)[0]}")
        print(f"books:\n{handle_callback_data('cmd:books')[0]}")
        print(f"two-sided VAT:\n{vat_response()[0]}")

        PENDING_PHOTOS[1] = "Photo Purchase, R460.00, 17 Nov 2026, receipt photo"
        print(f"cfm:in:\n{handle_callback_data('cfm:in', 1)[0]}")
        PENDING_PHOTOS[1] = "Photo Sale, R575.00, 17 Nov 2026, receipt photo"
        print(f"cfm:out:\n{handle_callback_data('cfm:out', 1)[0]}")

        print(f"clear:\n{handle_callback_data('cmd:clear')[0]}")
        print(f"books after clear:\n{handle_text('/books')[0]}")
    finally:
        SELFTEST_CONN.close()
        SELFTEST_CONN = None
        SELFTEST_MODE = False
        PENDING_PHOTOS.clear()


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        selftest()
    else:
        try:
            run(load_token())
        except RuntimeError as error:
            print(error, file=sys.stderr)
            raise SystemExit(1)
