import os
import asyncpg
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                joined_at   TEXT,
                balance     REAL DEFAULT 0.0,
                spent       REAL DEFAULT 0.0,
                blocked     INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT,
                action      TEXT,
                detail      TEXT,
                created_at  TEXT
            )
        """)


async def upsert_user(user_id: int, username: str, first_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", user_id)
        if not existing:
            await conn.execute(
                "INSERT INTO users (user_id, username, first_name, joined_at) VALUES ($1,$2,$3,$4)",
                user_id, username, first_name, datetime.now().isoformat()
            )
        else:
            await conn.execute(
                "UPDATE users SET username=$1, first_name=$2 WHERE user_id=$3",
                username, first_name, user_id
            )


async def get_user(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def get_all_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY joined_at DESC")
        return [dict(r) for r in rows]


async def get_balance(user_id: int) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id=$1", user_id)
        return row["balance"] if row else 0.0


async def set_balance(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance=$1 WHERE user_id=$2", amount, user_id)


async def add_balance(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance=balance+$1 WHERE user_id=$2", amount, user_id
        )


async def deduct_balance(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance=balance-$1, spent=spent+$1 WHERE user_id=$2",
            amount, user_id
        )


async def set_blocked(user_id: int, blocked: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET blocked=$1 WHERE user_id=$2", int(blocked), user_id
        )


async def is_blocked(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT blocked FROM users WHERE user_id=$1", user_id)
        return bool(row["blocked"]) if row else False


async def add_log(user_id: int, action: str, detail: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO logs (user_id, action, detail, created_at) VALUES ($1,$2,$3,$4)",
            user_id, action, detail, datetime.now().isoformat()
        )


async def get_logs(user_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, detail, created_at FROM logs WHERE user_id=$1 ORDER BY id DESC LIMIT $2",
            user_id, limit
        )
        return [{"action": r["action"], "detail": r["detail"], "at": r["created_at"][:16]} for r in rows]


async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        blocked = await conn.fetchval("SELECT COUNT(*) FROM users WHERE blocked=1")
        total_spent = await conn.fetchval("SELECT SUM(spent) FROM users") or 0.0
        return {"total": total, "blocked": blocked, "total_spent": total_spent}
        
