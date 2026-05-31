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
        # ── Таблица users ──────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    BIGINT PRIMARY KEY,
                username   TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance    NUMERIC(12,2) DEFAULT 0
            )
        """)

        for sql in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS total_balance  NUMERIC(12,2) DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked     BOOLEAN       DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS registered_at  TIMESTAMPTZ   DEFAULT NOW()",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by    BIGINT        DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_balance    NUMERIC(12,2) DEFAULT 0",
        ]:
            await conn.execute(sql)

        # ── Таблица logs ───────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                action     TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for sql in [
            "ALTER TABLE logs ADD COLUMN IF NOT EXISTS details TEXT DEFAULT ''",
        ]:
            await conn.execute(sql)

        # ── Таблица ton_orders ─────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ton_orders (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL,
                amount     NUMERIC(12,4) NOT NULL,
                wallet     TEXT NOT NULL,
                price      NUMERIC(12,2) NOT NULL,
                status     TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)


# ─── Базовые функции ──────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str, first_name: str, referred_by: int = None):
    async with pool.acquire() as conn:
        # Проверяем, есть ли уже пользователь
        exists = await conn.fetchval(
            "SELECT user_id FROM users WHERE user_id = $1", user_id
        )
        if exists:
            # Просто обновляем имя/юзернейм, не трогаем referred_by
            await conn.execute("""
                UPDATE users SET username = $2, first_name = $3 WHERE user_id = $1
            """, user_id, username, first_name)
            return False
        else:
            # Новый пользователь — записываем реферера если есть
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, referred_by)
                VALUES ($1, $2, $3, $4)
            """, user_id, username, first_name, referred_by)
            # Начисляем 2 RUB рефереру за приглашение
            if referred_by:
                await conn.execute("""
                    UPDATE users
                       SET balance     = balance + 2,
                           ref_balance = ref_balance + 2
                     WHERE user_id = $1
                """, referred_by)
            return True


async def get_balance(user_id: int) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance FROM users WHERE user_id = $1", user_id
        )
        return float(row["balance"]) if row else 0.0


async def deduct_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        # Списываем у покупателя
        await conn.execute("""
            UPDATE users
               SET balance       = balance - $2,
                   total_balance = total_balance + $2
             WHERE user_id = $1
        """, user_id, amount)

        # Реферальное вознаграждение выплачивается при регистрации (в upsert_user)


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
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT user_id, username, first_name,
                   balance, total_balance, registered_at
              FROM users
             WHERE user_id = $1
        """, user_id)
        return dict(row) if row else {}


async def get_total_orders(user_id: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS cnt FROM logs
             WHERE user_id = $1 AND action IN ('buy_stars', 'buy_premium', 'buy_ton')
        """, user_id)
        return int(row["cnt"]) if row else 0


async def get_order_history(user_id: int, limit: int = 20) -> list:
    """Возвращает список заказов (buy_stars, buy_premium) для пользователя."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, action, details, created_at FROM logs
             WHERE user_id = $1 AND action IN ('buy_stars', 'buy_premium', 'buy_ton')
             ORDER BY created_at DESC
             LIMIT $2
        """, user_id, limit)
        return [
            {
                "id":         r["id"],
                "action":     r["action"],
                "details":    r["details"] or "",
                "created_at": r["created_at"],
            }
            for r in rows
        ]


async def get_total_premium(user_id: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS cnt FROM logs
             WHERE user_id = $1 AND action = 'buy_premium'
        """, user_id)
        return int(row["cnt"]) if row else 0


async def get_total_stars(user_id: int) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT details FROM logs
             WHERE user_id = $1 AND action = 'buy_stars'
        """, user_id)
        total = 0
        for r in rows:
            details = r["details"] or ""
            try:
                total += int(details.split(" stars")[0].strip())
            except Exception:
                pass
        return total


# ─── Реферальная система ──────────────────────────────────────────────────────

async def get_ref_stats(user_id: int) -> dict:
    """Количество рефералов и суммарная прибыль с них."""
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE referred_by = $1", user_id
        )
        ref_balance = await conn.fetchval(
            "SELECT COALESCE(ref_balance, 0) FROM users WHERE user_id = $1", user_id
        )
        return {
            "count":       int(count or 0),
            "ref_balance": float(ref_balance or 0),
        }


async def get_referred_by(user_id: int):
    """Получить ID реферера пользователя."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT referred_by FROM users WHERE user_id = $1", user_id
        )
        return row["referred_by"] if row else None


# ─── Функции для админки ──────────────────────────────────────────────────────

async def get_all_users() -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, username, first_name,
                   balance, total_balance, is_blocked, registered_at
              FROM users
             ORDER BY registered_at DESC
        """)
        return [
            {
                "user_id":    r["user_id"],
                "username":   r["username"],
                "first_name": r["first_name"],
                "balance":    float(r["balance"]),
                "spent":      float(r["total_balance"]),
                "blocked":    r["is_blocked"],
                "joined_at":  str(r["registered_at"]),
            }
            for r in rows
        ]


async def get_user(user_id: int):
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
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT action, details, created_at FROM logs
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
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = $2 WHERE user_id = $1",
            user_id, blocked
        )


async def set_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = $2 WHERE user_id = $1",
            user_id, amount
        )


async def add_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = balance + $2 WHERE user_id = $1",
            user_id, amount
        )


# ─── TON заявки ───────────────────────────────────────────────────────────────

async def create_ton_order(user_id: int, amount: float, wallet: str, price: float) -> int:
    """Создаёт заявку на покупку TON. Возвращает order_id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO ton_orders (user_id, amount, wallet, price)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, user_id, amount, wallet, price)
        return row["id"]


async def get_ton_order(order_id: int) -> dict:
    """Возвращает заявку по ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ton_orders WHERE id = $1", order_id
        )
        if not row:
            return None
        return {
            "id":         row["id"],
            "user_id":    row["user_id"],
            "amount":     float(row["amount"]),
            "wallet":     row["wallet"],
            "price":      float(row["price"]),
            "status":     row["status"],
            "created_at": str(row["created_at"]),
        }


async def set_ton_order_status(order_id: int, status: str):
    """Обновляет статус заявки: pending / done / cancelled."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ton_orders SET status = $2 WHERE id = $1",
            order_id, status
        )


async def get_order_by_id(order_id: int) -> dict:
    """Возвращает заказ из logs по ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, action, details, created_at FROM logs WHERE id = $1",
            order_id
        )
        if not row:
            return None
        return {
            "id":         row["id"],
            "user_id":    row["user_id"],
            "action":     row["action"],
            "details":    row["details"] or "",
            "created_at": row["created_at"],
        }
