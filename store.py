import hashlib
import sqlite3
from datetime import datetime


def connect(path="books.db"):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY,
            date TEXT,
            vendor TEXT,
            description TEXT,
            gross_cents INTEGER,
            net_cents INTEGER,
            vat_cents INTEGER,
            hash TEXT UNIQUE,
            created TEXT
        )
        """
    )
    conn.commit()
    return conn


def insert_entry(conn, entry_dict):
    entry_hash = hashlib.sha256(
        f"{entry_dict['date']}|{entry_dict['vendor']}|{entry_dict['gross_cents']}".encode(
            "utf-8"
        )
    ).hexdigest()

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO entries (
            date, vendor, description, gross_cents, net_cents, vat_cents, hash, created
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_dict["date"],
            entry_dict["vendor"],
            entry_dict["description"],
            entry_dict["gross_cents"],
            entry_dict["net_cents"],
            entry_dict["vat_cents"],
            entry_hash,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


def list_entries(conn, month=None):
    if month is not None:
        cursor = conn.execute(
            "SELECT * FROM entries WHERE date LIKE ? ORDER BY date DESC, id DESC",
            (f"{month}%",),
        )
    else:
        cursor = conn.execute("SELECT * FROM entries ORDER BY date DESC, id DESC")

    return cursor.fetchall()