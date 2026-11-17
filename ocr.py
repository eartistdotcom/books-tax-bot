import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime


EXAMPLE = "Takealot, R1,150.00, 14 Nov 2026, receipt photo"
EXCLUDED_VENDOR_WORDS = (
    "vat",
    "invoice",
    "tax",
    "tel",
    "reg",
    "date",
    "receipt",
    "till",
    "cashier",
    "total",
)
AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])(?:\d{1,3}(?:[ ,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d.,])"
)


def _tesseract_command():
    configured = os.environ.get("TESSERACT_CMD", "").strip()
    if configured:
        found = shutil.which(configured)
        if found:
            return found
        if os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured

    return shutil.which("tesseract")


def available():
    return _tesseract_command() is not None


def text_from_image(path):
    command = _tesseract_command()
    if command is None:
        raise RuntimeError(
            "Tesseract was not found. Install it or set TESSERACT_CMD to its path."
        )

    try:
        result = subprocess.run(
            [command, os.fspath(path), "stdout", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Tesseract timed out while reading the image.") from error
    except OSError as error:
        raise RuntimeError("Tesseract could not be started.") from error

    if result.returncode != 0:
        details = result.stderr.strip()
        message = "Tesseract could not read the image."
        if details:
            message = f"{message} {details}"
        raise RuntimeError(message)

    return result.stdout


def _parse_amount(value):
    amount = value.replace(" ", "")
    comma = amount.rfind(",")
    dot = amount.rfind(".")

    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
        thousands_separator = "." if decimal_separator == "," else ","
        amount = amount.replace(thousands_separator, "")
        amount = amount.replace(decimal_separator, ".")
    elif comma >= 0:
        trailing_digits = len(amount) - comma - 1
        if trailing_digits in (1, 2):
            amount = amount.replace(",", ".")
        else:
            amount = amount.replace(",", "")
    elif dot >= 0:
        trailing_digits = len(amount) - dot - 1
        if trailing_digits not in (1, 2):
            amount = amount.replace(".", "")

    whole, separator, fraction = amount.partition(".")
    cents = int(whole) * 100
    if separator:
        cents += int(fraction.ljust(2, "0"))
    return cents


def _find_date(text):
    patterns = (
        (re.compile(r"(?<!\d)\d{2}/\d{2}/\d{4}(?!\d)"), "%d/%m/%Y"),
        (re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"), "%Y-%m-%d"),
        (
            re.compile(r"(?<!\d)\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}(?!\d)"),
            None,
        ),
    )

    for pattern, date_format in patterns:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group()
        try:
            if date_format:
                return datetime.strptime(value, date_format).date()
            for fmt in ("%d %b %Y", "%d %B %Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
        except ValueError:
            continue

    return date.today()


def receipt_line(path):
    text = text_from_image(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(" ".join(lines)) < 10:
        raise ValueError(
            f"Not enough receipt text was recognized. Type a line like: {EXAMPLE}"
        )

    vendor = None
    for line in lines:
        if sum(character.isalpha() for character in line) < 3:
            continue
        lowered = line.casefold()
        if any(word in lowered for word in EXCLUDED_VENDOR_WORDS):
            continue
        vendor = line
        break

    if not vendor:
        raise ValueError(
            f"Could not identify the vendor. Type a line like: {EXAMPLE}"
        )

    def amounts_on_line(line):
        return [
            _parse_amount(match.group())
            for match in AMOUNT_PATTERN.finditer(line)
        ]

    total_amounts = [
        amount
        for line in lines
        if "total" in line.casefold()
        for amount in amounts_on_line(line)
    ]

    if total_amounts:
        total_cents = total_amounts[-1]
    else:
        all_amounts = [
            amount
            for line in lines
            for amount in amounts_on_line(line)
        ]
        if not all_amounts:
            raise ValueError(
                f"Could not find a receipt total. Type a line like: {EXAMPLE}"
            )
        total_cents = max(all_amounts)

    whole, fraction = divmod(total_cents, 100)
    amount_text = f"R{whole:,}.{fraction:02d}"
    receipt_date = _find_date(text).strftime("%d %b %Y")
    return f"{vendor}, {amount_text}, {receipt_date}, receipt photo"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python ocr.py IMAGE_PATH\nExample: python ocr.py receipt.jpg")
        raise SystemExit(2)

    ocr_text = text_from_image(sys.argv[1])
    print(ocr_text)
    print(receipt_line(sys.argv[1]))