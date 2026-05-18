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

        await conn.execute("""
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ DEFAULT NOW()
        """)

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


# ─── Базовые функции ──────────────────────────────────────────────────────────

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
               SET balance       = balance - $2,
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


# ─── Функции для профиля ──────────────────────────────────────────────────────

async def get_user_info(user_id: int) -> dict:
    """Полная информация о пользователе для экрана профиля."""
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
    """Суммарное количество купленных звёзд.
    details формат: '150 stars -> @username'
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


# ─── Функции для админки ──────────────────────────────────────────────────────

async def get_all_users() -> list:
    """Все пользователи для списка в админке."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, username, first_name,
                   balance, total_balance, is_blocked, registered_at
              FROM users
             ORDER BY registered_at DESC
        """)
        result = []
        for r in rows:
            result.append({
                "user_id":    r["user_id"],
                "username":   r["username"],
                "first_name": r["first_name"],
                "balance":    float(r["balance"]),
                "spent":      float(r["total_balance"]),
                "blocked":    r["is_blocked"],
                "joined_at":  str(r["registered_at"]),
            })
        return result


async def get_user(user_id: int):
    """Один пользователь для карточки в админке."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT user_id, username, first_name,
                   balance, total_balance, is_blocked, registered_at
              FROM users
             WHERE user_id = $1
        """, user_id)
        if not row:
            return None
        return {
            "user_id":    row["user_id"],
            "username":   row["username"],
            "first_name": row["first_name"],
            "balance":    float(row["balance"]),
            "spent":      float(row["total_balance"]),
            "blocked":    row["is_blocked"],
            "joined_at":  str(row["registered_at"]),
        }


async def get_logs(user_id: int, limit: int = 10) -> list:
    """Последние N логов пользователя для админки."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT action, details, created_at
              FROM logs
             WHERE user_id = $1
             ORDER BY created_at DESC
             LIMIT $2
        """, user_id, limit)
        return [
            {
                "action": r["action"],
                "detail": r["details"] or "",
                "at":     str(r["created_at"])[:19],
            }
            for r in rows
        ]


async def get_stats() -> dict:
    """Общая статистика для админки."""
    async with pool.acquire() as conn:
        total   = await conn.fetchval("SELECT COUNT(*) FROM users")
        blocked = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
        spent   = await conn.fetchval("SELECT COALESCE(SUM(total_balance), 0) FROM users")
        return {
            "total":       int(total),
            "blocked":     int(blocked),
            "total_spent": float(spent),
        }


async def set_blocked(user_id: int, blocked: bool):
    """Заблокировать / разблокировать пользователя."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET is_blocked = $2 WHERE user_id = $1
        """, user_id, blocked)


async def set_balance(user_id: int, amount: float):
    """Установить баланс пользователю (точное значение)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET balance = $2 WHERE user_id = $1
        """, user_id, amount)


async def add_balance(user_id: int, amount: float):
    """Пополнить баланс пользователю."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET balance = balance + $2 WHERE user_id = $1
        """, user_id, amount)
                
