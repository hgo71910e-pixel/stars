import os
import asyncio
from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.database import (
    get_balance, add_balance, block_user, unblock_user, add_log,
    get_total_orders, get_total_stars, get_total_premium,
)

router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "1896247728"))


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# ─── Keyboards ────────────────────────────────────────────────────────────────

def build_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="admin_help_balance")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_help_block"),
         InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_help_unblock")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_help_broadcast")],
    ])


# ─── /admin ───────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔧 Панель администратора", reply_markup=build_admin_keyboard())


# ─── Статистика ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()

    try:
        from db.database import get_all_users
        users = await get_all_users()
        total_users = len(users)
        total_orders = 0
        total_stars = 0
        total_premium = 0
        for u in users:
            uid = u["user_id"]
            total_orders += await get_total_orders(uid)
            total_stars += await get_total_stars(uid)
            total_premium += await get_total_premium(uid)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при получении статистики: {e}")
        return

    text = (
        "📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"📦 Всего заказов: {total_orders}\n"
        f"⭐ Продано звёзд: {total_stars}\n"
        f"💎 Продано Premium: {total_premium}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)


# ─── Подсказки по командам ────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin_help_balance")
async def admin_help_balance(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(
        "💰 Пополнение баланса\n\nКоманда:\n/add_balance <user_id> <сумма>\n\nПример:\n/add_balance 123456789 500",
        reply_markup=kb
    )


@router.callback_query(lambda c: c.data == "admin_help_block")
async def admin_help_block(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(
        "🚫 Блокировка пользователя\n\nКоманда:\n/block <user_id>\n\nПример:\n/block 123456789",
        reply_markup=kb
    )


@router.callback_query(lambda c: c.data == "admin_help_unblock")
async def admin_help_unblock(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(
        "✅ Разблокировка пользователя\n\nКоманда:\n/unblock <user_id>\n\nПример:\n/unblock 123456789",
        reply_markup=kb
    )


@router.callback_query(lambda c: c.data == "admin_help_broadcast")
async def admin_help_broadcast(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(
        "📢 Рассылка\n\nКоманда:\n/broadcast <текст>\n\nПример:\n/broadcast Привет всем!",
        reply_markup=kb
    )


# ─── Назад ────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.answer()
    await callback.message.edit_text("🔧 Панель администратора", reply_markup=build_admin_keyboard())


# ─── /add_balance ─────────────────────────────────────────────────────────────

@router.message(Command("add_balance"))
async def cmd_add_balance(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 3:
        return await message.answer("Использование: /add_balance <user_id> <сумма>")
    try:
        target_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        return await message.answer("Неверный формат. Пример: /add_balance 123456789 500")

    await add_balance(target_id, amount)
    await add_log(target_id, "admin_add_balance", f"+{amount} RUB от администратора")
    await message.answer(f"✅ Баланс пользователя {target_id} пополнен на {amount:.2f} RUB")


# ─── /block ───────────────────────────────────────────────────────────────────

@router.message(Command("block"))
async def cmd_block(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 2:
        return await message.answer("Использование: /block <user_id>")
    try:
        target_id = int(parts[1])
    except ValueError:
        return await message.answer("Неверный user_id")

    await block_user(target_id)
    await message.answer(f"🚫 Пользователь {target_id} заблокирован")


# ─── /unblock ─────────────────────────────────────────────────────────────────

@router.message(Command("unblock"))
async def cmd_unblock(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 2:
        return await message.answer("Использование: /unblock <user_id>")
    try:
        target_id = int(parts[1])
    except ValueError:
        return await message.answer("Неверный user_id")

    await unblock_user(target_id)
    await message.answer(f"✅ Пользователь {target_id} разблокирован")


# ─── /broadcast ───────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    bot: Bot = message.bot
    text = message.text[len("/broadcast"):].strip()
    if not text:
        return await message.answer("Укажите текст: /broadcast <текст>")

    try:
        from db.database import get_all_users
        users = await get_all_users()
    except Exception as e:
        return await message.answer(f"❌ Ошибка получения пользователей: {e}")

    sent = 0
    failed = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(f"📢 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


# ─── /balance ─────────────────────────────────────────────────────────────────

@router.message(Command("balance"))
async def cmd_balance(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 2:
        return await message.answer("Использование: /balance <user_id>")
    try:
        target_id = int(parts[1])
    except ValueError:
        return await message.answer("Неверный user_id")

    balance = await get_balance(target_id)
    await message.answer(f"💰 Баланс пользователя {target_id}: {balance:.2f} RUB")
