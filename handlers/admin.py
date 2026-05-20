from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os

LOG_CHAT_ID = -1003908388893

async def _send_log(text: str) -> None:
    try:
        _bot = Bot(token=os.getenv("BOT_TOKEN"))
        await _bot.send_message(chat_id=LOG_CHAT_ID, text=text, parse_mode="HTML")
        await _bot.session.close()
    except Exception:
        pass
from db.database import (
    get_all_users, get_user, get_logs, get_stats,
    set_blocked, set_balance, add_balance
)

ADMIN_USERNAME = "tntks"

router = Router()


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_give_balance = State()


def is_admin(user: types.User) -> bool:
    return user.username and user.username.lower() == ADMIN_USERNAME.lower()


def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="adm_users_0")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="adm_find")],
    ])


def user_kb(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    block_text = "✅ Разблокировать" if blocked else "🚫 Заблокировать"
    block_cb = f"adm_unblock_{user_id}" if blocked else f"adm_block_{user_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Выдать баланс", callback_data=f"adm_give_{user_id}")],
        [InlineKeyboardButton(text=block_text, callback_data=block_cb)],
        [InlineKeyboardButton(text="📋 Логи", callback_data=f"adm_logs_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_find")],
    ])


# ─── /admin ───────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user):
        return  # молчим
    await message.answer("🛠 Админ панель", reply_markup=admin_main_kb())


# ─── Статистика ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user):
        return
    s = await get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total']}</b>\n"
        f"🚫 Заблокировано: <b>{s['blocked']}</b>\n"
        f"💸 Всего потрачено: <b>{s['total_spent']:.2f} RUB</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ─── Список пользователей ─────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data.startswith("adm_users_"))
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user):
        return
    page = int(callback.data.split("_")[-1])
    per = 8
    users = await get_all_users()
    total = len(users)
    chunk = users[page * per:(page + 1) * per]

    lines = []
    for u in chunk:
        name = f"@{u['username']}" if u['username'] else u['first_name']
        blocked = " 🚫" if u['blocked'] else ""
        lines.append(f"{name}{blocked} — {u['spent']:.0f} RUB | <code>{u['user_id']}</code>")

    text = f"👥 Пользователи ({total}):\n\n" + "\n".join(lines)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_users_{page-1}"))
    if (page + 1) * per < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_users_{page+1}"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                                     parse_mode="HTML")
    await callback.answer()


# ─── Найти пользователя ───────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "adm_find")
async def adm_find(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await callback.message.edit_text("🔍 Введите user_id пользователя:",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                         [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
                                     ]))
    await state.set_state(AdminStates.waiting_user_id)
    await callback.answer()


@router.message(AdminStates.waiting_user_id)
async def adm_find_user(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    await message.delete()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID")
        return

    u = await get_user(uid)
    if not u:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return

    name = f"@{u['username']}" if u['username'] else u['first_name']
    text = (
        f"👤 <b>{name}</b> (<code>{uid}</code>)\n\n"
        f"📅 Зашёл: {u['joined_at'][:10]}\n"
        f"💰 Баланс: {u['balance']:.2f} RUB\n"
        f"💸 Потратил: {u['spent']:.2f} RUB\n"
        f"🚫 Заблокирован: {'Да' if u['blocked'] else 'Нет'}"
    )
    await message.answer(text, reply_markup=user_kb(uid, bool(u['blocked'])), parse_mode="HTML")
    await state.clear()


# ─── Блокировка ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data.startswith("adm_block_"))
async def adm_block(callback: types.CallbackQuery):
    if not is_admin(callback.from_user):
        return
    uid = int(callback.data.split("_")[-1])
    await set_blocked(uid, True)
    u = await get_user(uid)
    name = f"@{u['username']}" if u['username'] else u['first_name']
    await callback.message.edit_reply_markup(reply_markup=user_kb(uid, True))
    await callback.answer(f"🚫 {name} заблокирован")
    await _send_log(f"🚫 <b>Блокировка пользователя</b>\nID: <code>{uid}</code> | {name}")


@router.callback_query(lambda c: c.data.startswith("adm_unblock_"))
async def adm_unblock(callback: types.CallbackQuery):
    if not is_admin(callback.from_user):
        return
    uid = int(callback.data.split("_")[-1])
    await set_blocked(uid, False)
    u = await get_user(uid)
    name = f"@{u['username']}" if u['username'] else u['first_name']
    await callback.message.edit_reply_markup(reply_markup=user_kb(uid, False))
    await callback.answer(f"✅ {name} разблокирован")
    await _send_log(f"✅ <b>Разблокировка пользователя</b>\nID: <code>{uid}</code> | {name}")


# ─── Выдать баланс ────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data.startswith("adm_give_"))
async def adm_give(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_give_balance)
    await state.update_data(target_uid=uid)
    await callback.answer("Введите сумму в следующем сообщении", show_alert=True)


@router.message(AdminStates.waiting_give_balance)
async def adm_give_amount(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    await message.delete()
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("❌ Неверная сумма")
        return
    data = await state.get_data()
    uid = data["target_uid"]
    await add_balance(uid, amount)
    u = await get_user(uid)
    name = f"@{u['username']}" if u['username'] else u['first_name']
    new_bal = u['balance'] + amount
    await message.answer(f"✅ Выдано {amount:.2f} RUB → {name}\nНовый баланс: {new_bal:.2f} RUB")
    await _send_log(
        f"💰 <b>Выдача баланса (админ)</b>\n"
        f"Получатель: <code>{uid}</code> | {name}\n"
        f"Сумма: <b>+{amount:.2f} RUB</b>\n"
        f"Новый баланс: {new_bal:.2f} RUB"
    )
    await state.clear()


# ─── Логи ─────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data.startswith("adm_logs_"))
async def adm_logs(callback: types.CallbackQuery):
    if not is_admin(callback.from_user):
        return
    uid = int(callback.data.split("_")[-1])
    logs = await get_logs(uid, 10)
    if not logs:
        await callback.answer("Логов нет", show_alert=True)
        return
    lines = [f"<code>{l['at']}</code> {l['action']} {l['detail']}" for l in logs]
    text = f"📋 Последние логи (<code>{uid}</code>):\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_find")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ─── Назад в главную админ-панель ─────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "adm_back")
async def adm_back(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.clear()
    await callback.message.edit_text("🛠 Админ панель", reply_markup=admin_main_kb())
    await callback.answer()
    
