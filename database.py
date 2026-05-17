import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                joined_at   TEXT,
                balance     REAL DEFAULT 0.0,
                spent       REAL DEFAULT 0.0,
                blocked     INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                action      TEXT,
                detail      TEXT,
                created_at  TEXT
            )
        """)
        conn.commit()


def upsert_user(user_id: int, username: str, first_name: str):
    with get_conn() as conn:
        existing = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
                (user_id, username, first_name, datetime.now().isoformat())
            )
            conn.commit()
        else:
            conn.execute(
                "UPDATE users SET username=?, first_name=? WHERE user_id=?",
                (username, first_name, user_id)
            )
            conn.commit()


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        cols = ["user_id", "username", "first_name", "joined_at", "balance", "spent", "blocked"]
        return dict(zip(cols, row))


def get_all_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY joined_at DESC").fetchall()
        cols = ["user_id", "username", "first_name", "joined_at", "balance", "spent", "blocked"]
        return [dict(zip(cols, r)) for r in rows]


def get_balance(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0.0


def set_balance(user_id: int, amount: float):
    with get_conn() as conn:
        conn.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))
        conn.commit()


def add_balance(user_id: int, amount: float):
    with get_conn() as conn:
        conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
        conn.commit()


def deduct_balance(user_id: int, amount: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance=balance-?, spent=spent+? WHERE user_id=?",
            (amount, amount, user_id)
        )
        conn.commit()


def set_blocked(user_id: int, blocked: bool):
    with get_conn() as conn:
        conn.execute("UPDATE users SET blocked=? WHERE user_id=?", (int(blocked), user_id))
        conn.commit()


def is_blocked(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row[0]) if row else False


def add_log(user_id: int, action: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (user_id, action, detail, created_at) VALUES (?,?,?,?)",
            (user_id, action, detail, datetime.now().isoformat())
        )
        conn.commit()


def get_logs(user_id: int, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT action, detail, created_at FROM logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [{"action": r[0], "detail": r[1], "at": r[2][:16]} for r in rows]


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        blocked = conn.execute("SELECT COUNT(*) FROM users WHERE blocked=1").fetchone()[0]
        total_spent = conn.execute("SELECT SUM(spent) FROM users").fetchone()[0] or 0.0
        return {"total": total, "blocked": blocked, "total_spent": total_spent}
