import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "quant_scalp.db"


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_stocks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT NOT NULL,
                code      TEXT,
                buy_price REAL NOT NULL,
                buy_time  TEXT NOT NULL,
                status    TEXT DEFAULT 'active'
            )
        """)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()


def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def add_tracked_stock(name: str, code: str, buy_price: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tracked_stocks (name, code, buy_price, buy_time) VALUES (?, ?, ?, ?)",
            (name, code, buy_price, datetime.now().isoformat())
        )
        conn.commit()


def get_active_stocks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_stocks WHERE status = 'active'"
        ).fetchall()
        return [dict(r) for r in rows]


def close_stock(name: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_stocks SET status = 'closed' WHERE name = ? AND status = 'active'",
            (name,)
        )
        conn.commit()


def get_stock_record(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tracked_stocks WHERE name = ? ORDER BY id DESC LIMIT 1",
            (name,)
        ).fetchone()
        return dict(row) if row else None
