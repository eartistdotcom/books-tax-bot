import argparse
import csv
import os
from datetime import date

from parse import parse_receipt
from store import connect, insert_entry, list_entries


def format_rands(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}R{whole:,}.{fraction:02d}"


def format_zar(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def current_month():
    return date.today().strftime("%Y-%m")


def month_entries(month):
    conn = connect()
    try:
        return list_entries(conn, month)
    finally:
        conn.close()


def print_books(month=None):
    entries = month_entries(month)
    if not entries:
        print("no entries yet")
        return 0

    headers = ("date", "vendor", "gross", "vat")
    rows = [
        (entry[1], entry[2], format_rands(entry[4]), format_rands(entry[6]))
        for entry in entries
    ]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return 0


def print_vat(month):
    entries = month_entries(month)
    gross = sum(entry[4] for entry in entries)
    vat = sum(entry[6] for entry in entries)

    print(f"month         {month}")
    print(f"gross sales   {format_rands(gross)}")
    print(f"output VAT    {format_rands(vat)}")
    print(f"entries       {len(entries)}")
    return 0


def write_taxpack(month, out):
    entries = month_entries(month)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
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

    print(f"wrote {out} ({len(entries)} rows)")
    return 0


def add_line(line):
    try:
        entry = parse_receipt(line)
    except ValueError as error:
        print(error)
        return 2

    conn = connect()
    try:
        if insert_entry(conn, entry):
            print("added")
        else:
            print("already recorded")
    finally:
        conn.close()
    return 0


def demo():
    if os.path.exists("books.db"):
        os.remove("books.db")

    for line in (
        "Takealot, R1,150.00, 14 Nov 2026, office chair",
        "Pick n Pay, R1,234.56, 14 Nov 2026, office consumables",
        "Vodacom, R899.00, 17 Nov 2026, phone and data",
    ):
        add_line(line)

    month = current_month()
    print()
    print_books(month)
    print()
    print_vat(month)
    print()
    write_taxpack(month, "taxpack.csv")
    return 0


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("receipt", help="receipt line to record")

    books_parser = subparsers.add_parser("books")
    books_parser.add_argument("--month", help='filter by month, e.g. "2026-11"')

    vat_parser = subparsers.add_parser("vat")
    vat_parser.add_argument("--month", default=current_month(), help="YYYY-MM")

    pack_parser = subparsers.add_parser("taxpack")
    pack_parser.add_argument("--month", default=current_month(), help="YYYY-MM")
    pack_parser.add_argument("--out", default="taxpack.csv", help="output file")

    subparsers.add_parser("demo")

    args = parser.parse_args()

    if args.command == "add":
        return add_line(args.receipt)
    if args.command == "books":
        return print_books(args.month)
    if args.command == "vat":
        return print_vat(args.month)
    if args.command == "taxpack":
        return write_taxpack(args.month, args.out)
    return demo()


if __name__ == "__main__":
    raise SystemExit(main())