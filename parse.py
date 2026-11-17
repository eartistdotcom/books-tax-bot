from datetime import datetime

from money import to_cents, vat_split


EXPECTED = "expected: vendor, amount, date, description"
DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d")


def _parse_date(value):
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {value}")


def parse_receipt(line):
    fields = [part.strip() for part in line.split(",")]

    # Find the date field so commas in a thousands-formatted amount (or
    # description) don't turn one logical field into multiple fields.
    date_index = None
    for index in range(2, len(fields)):
        try:
            _parse_date(fields[index])
            date_index = index
            break
        except ValueError:
            continue

    if date_index is None:
        if len(fields) != 4:
            raise ValueError(EXPECTED)
        vendor, amount, date_text, description = fields
    else:
        if date_index < 2 or date_index >= len(fields) - 1:
            raise ValueError(EXPECTED)
        vendor = fields[0]
        amount = ",".join(fields[1:date_index]).strip()
        date_text = fields[date_index]
        description = ",".join(fields[date_index + 1:]).strip()

    date = _parse_date(date_text)
    gross_cents = to_cents(amount)
    net_cents, vat_cents = vat_split(gross_cents)

    return {
        "date": date.isoformat(),
        "vendor": vendor,
        "description": description,
        "gross_cents": gross_cents,
        "net_cents": net_cents,
        "vat_cents": vat_cents,
    }


if __name__ == "__main__":
    samples = [
        "Takealot, R1,150.00, 14 Nov 2026, office chair",
        "Stationery Shop, R230.00, 2026-11-14, printer paper",
        "Fuel Stop, R805.00, 15 Nov 2026, business travel",
        "Coffee House, R57.50, 2026-11-16, client meeting",
        "Tech Store, R2,300.00, 17 Nov 2026, monitor",
    ]

    for sample in samples:
        print(parse_receipt(sample))