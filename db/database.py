import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

pool: asyncpg.Pool = None


async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       BIGINT PRIMARY KEY,
                username      TEXT DEFAULT '',
                first_name    TEXT DEFAULT '',
                balance       NUMERIC(12,2) DEFAULT 0,
                total_balance NUMERIC(12,2) DEFAULT 0,
                is_blocked    BOOLEAN DEFAULT FALSE,
                registered_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Добавляем registered_at если таблица уже существовала без неё
        await conn.execute("""
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ DEFAULT NOW()
        """)

        # Добавляем total_balance если таблица уже существовала без неё
        await conn.execute("""
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS total_balance NUMERIC(12,2) DEFAULT 0
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                action     TEXT,
                details    TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)


async def upsert_user(user_id: int, username: str, first_name: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
                SET username   = EXCLUDED.username,
                    first_name = EXCLUDED.first_name
        """, user_id, username, first_name)


async def get_balance(user_id: int) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance FROM users WHERE user_id = $1", user_id
        )
        return float(row["balance"]) if row else 0.0


async def deduct_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
               SET balance = balance - $2,
                   total_balance = total_balance + $2
             WHERE user_id = $1
        """, user_id, amount)


async def add_log(user_id: int, action: str, details: str = ""):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO logs (user_id, action, details)
            VALUES ($1, $2, $3)
        """, user_id, action, details)


async def is_blocked(user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_blocked FROM users WHERE user_id = $1", user_id
        )
        return bool(row["is_blocked"]) if row else False


# ─── Новые функции для профиля ────────────────────────────────────────────────

async def get_user_info(user_id: int) -> dict:
    """Возвращает полную информацию о пользователе для профиля."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT user_id, username, first_name,
                   balance, total_balance, registered_at
              FROM users
             WHERE user_id = $1
        """, user_id)
        return dict(row) if row else {}


async def get_total_orders(user_id: int) -> int:
    """Количество успешных покупок звёзд."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS cnt
              FROM logs
             WHERE user_id = $1
               AND action = 'buy_stars'
        """, user_id)
        return int(row["cnt"]) if row else 0


async def get_total_stars(user_id: int) -> int:
    """Суммарное количество купленных звёзд по логам.
    details формат: '150 stars → @username'
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT details
              FROM logs
             WHERE user_id = $1
               AND action = 'buy_stars'
        """, user_id)
        total = 0
        for r in rows:
            details = r["details"] or ""
            try:
                total += int(details.split(" stars")[0].strip())
            except Exception:
                pass
        return total
        
