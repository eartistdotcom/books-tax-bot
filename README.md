# South African Books and VAT Bot

## The problem it solves

Small businesses across Africa often need a simple way to keep everyday business purchases organised without relying on constant internet access or expensive accounting software. This command-line tool records receipt details, calculates the VAT portion of VAT-inclusive amounts at South Africa’s 15% rate, summarises a month’s entries, and exports a CSV tax pack for an accountant.

## How to run it

Requires Python 3 and uses only the standard library. It runs offline.

```sh
python main.py add "Takealot, R1,150.00, 14 Nov 2026, office chair"
python main.py books
python main.py books --month 2026-11
python main.py vat
python main.py vat --month 2026-11
python main.py taxpack
python main.py taxpack --month 2026-11 --out november.csv
python main.py demo
```

Entries are stored in `books.db`. The `demo` command removes that database, adds three sample receipts, and creates `taxpack.csv`.

## How we kept tokens low

- No model runs at runtime; VAT is calculated with integer arithmetic in code.
- Each file was written from one prompt with a done-test, so nothing was generated twice.
- Stored entries are never re-parsed, so repeat reports cost nothing.

## Deliberate limits

Vendor names containing commas are not supported. VAT is assumed to be included in the amount and calculated at 15%. The tool has no authentication.