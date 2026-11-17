# South African Books and VAT Bot

One line in, a set of books out — for the small business that keeps its records in a
WhatsApp message or a shoebox.

## The problem

A plumber, a spaza, a one-person agency in South Africa has to charge and claim VAT at 15%,
and has to hand something to an accountant at year end. What they actually have is a pile of
slips and a phone. Bookkeepers cost more than the paperwork is worth at that size, so the
records get reconstructed once a year, badly, and the VAT is guessed.

This bot takes a sentence — *"Takealot, R1,150.00, 14 Nov 2026, office chair"* — or a photo of
the slip, and turns it into a books entry: vendor, date, gross, the VAT split out, and the net.
It knows a **purchase** from a **sale**, so it reports the VAT you can claim back separately
from the VAT you owe. Then it answers the two questions that matter: **what is my VAT this
month**, and **give me the file my accountant wants**.

## How to run it

```bash
python main.py demo          # seed a month, see the books, VAT and the tax pack
```

Or step by step:

```bash
python main.py add "Takealot, R1,150.00, 14 Nov 2026, office chair"
python main.py add --sale "Dlamini Plumbing, R5,750.00, 17 Nov 2026, invoice 22"
python main.py books
python main.py vat --month 2026-11
python main.py taxpack --month 2026-11 --out taxpack.csv
```

On Telegram: put your BotFather token in `bot_token.txt` beside `bot.py`, then

```bash
python bot.py
```

You can type a receipt, send a **photo** of one, or tap the buttons.
`python bot.py --selftest` exercises every command and button without a token or a network.

Requires Python 3.10 or newer. The bot and the CLI use nothing but the standard library.
Reading a photo needs **Tesseract** installed locally — no cloud service, no key, no token.
On Windows install it from the UB Mannheim build and point the bot at it if it is not on PATH:

```
set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

Without Tesseract, typed receipts still work and a photo gets a plain explanation instead of an
error.

## How we kept tokens low

- **No model runs at runtime.** Receipts are parsed by a fixed grammar, photos are read by
  Tesseract on the same machine, and VAT is integer arithmetic in code. The language model wrote
  the code; it does not do the books. Every rand on screen comes from cents and one formula, so a
  wrong number is a bug we can find, not something we cannot explain.
- **One file per prompt, each with a done-test.** Every prompt named a single module and the
  assertion that proved it, so each response was a small file rather than a rewrite — nothing was
  generated twice and nothing had to be re-read to be fixed.
- **Nothing is regenerated.** A stored entry is never re-parsed and VAT is never recomputed from
  the text; every report is derived from the database, so the second VAT report and the tax pack
  cost exactly zero.

## Deliberate limits

- A comma inside a vendor name breaks a typed line. Send a photo, or rename the vendor.
- VAT is treated as inclusive at 15%. Zero-rated and exempt supplies are not modelled.
- One user, one currency, no auth: it is a local tool, not a service. Everyone messaging the bot
  shares one set of books, and `/clear` deletes it.
- The books are deleted when `bot.py` starts. Nothing of the user's is kept between runs.
- Reading a photo gets the total, the date and the first line that looks like a shop name. It
  does not itemise, and a crumpled slip may need typing instead.

## Files

- `main.py` — the command line: add, books, vat, taxpack, demo
- `bot.py` — the Telegram channel: buttons, photos, confirm-before-saving
- `ocr.py` — a receipt photo to one typed line, using local Tesseract
- `money.py` — rands to cents, and the VAT split, in integers
- `parse.py` — one receipt line to an entry, as a purchase or a sale
- `store.py` — SQLite, with a hash guard so the same receipt cannot be entered twice
