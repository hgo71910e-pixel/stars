import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from db.database import (
    init_db, upsert_user, get_balance, deduct_balance, add_log, is_blocked,
    get_user_info, get_total_orders, get_total_stars, get_total_premium,
    get_ref_stats, get_order_history
)
from handlers.admin import router as admin_router

load_dotenv()

BOT_TOKEN      = os.getenv("BOT_TOKEN")
PHOTO_FILE_ID  = os.getenv("PHOTO_FILE_ID")
SPLIT_API_KEY  = os.getenv("SPLIT_API_KEY")  # добавь в .env: SPLIT_API_KEY=eyJhbG...

SPLIT_BASE     = "https://api.split.tg"
SPLIT_PARTNER  = "stars_bot"  # твоё имя партнёра на split.tg

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
dp.include_router(admin_router)

COMMISSION = 0.08
MIN_AMOUNT = 10
STARS_RATE = 1.30
STARS_MIN  = 50
USD_RATE   = 90.0
REF_PCT    = 5

PREMIUM_PRICES = {
    "3":  0,
    "6":  0,
    "12": 0,
}


# ─── Split.tg API ─────────────────────────────────────────────────────────────

def split_headers() -> dict:
    return {
        "Authorization": f"Bearer {SPLIT_API_KEY}",
        "Content-Type":  "application/json",
    }


async def split_check_recipient(username: str) -> dict | None:
    """Проверяет получателя звёзд по username. Возвращает данные или None."""
    try:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{SPLIT_BASE}/recipients/stars",
                headers=split_headers(),
                json={"username": username}
            )
            data = await r.json()
            if data.get("ok"):
                return data.get("message")
    except Exception:
        pass
    return None


async def split_buy_stars(username: str, quantity: int, user_id: int) -> bool:
    """
    Покупает звёзды через Split.tg (payment_method: balance).
    Списывается с TON-баланса на split.tg/partner.
    Возвращает True при успехе, иначе бросает Exception.
    """
    async with aiohttp.ClientSession() as s:
        r = await s.post(
            f"{SPLIT_BASE}/buy/stars",
            headers=split_headers(),
            json={
                "username":       username,
                "quantity":       quantity,
                "payment_method": "balance",
                "custom_fee":     0,
                "partner": {
                    "name":             SPLIT_PARTNER,
                    "external_user_id": user_id,
                    "comment":          f"tg_bot_user_{user_id}"
                }
            }
        )
        data = await r.json()

        if not data.get("ok"):
            raise Exception(data.get("error_message") or "Split API error")

        msg     = data.get("message") or {}
        invoice = msg.get("invoice") or {}
        status  = invoice.get("status", "")

        # При методе balance статус должен быть completed/pending/paid
        if status in ("completed", "paid", "pending", "processing"):
            return True

        # Если invoice пустой но ok=True — тоже считаем успехом
        if not invoice and data.get("ok"):
            return True

        raise Exception(f"Неожиданный статус инвойса: {status!r}")


async def split_get_price(quantity: int) -> float:
    """Получает закупочную цену в USD для N звёзд (POST /buy/estimate)."""
    try:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{SPLIT_BASE}/buy/estimate",
                headers=split_headers(),
                json={
                    "quantity": quantity,
                    "product":  "stars",
                    "method":   "balance"
                }
            )
            data = await r.json()
            if data.get("ok"):
                return float(data["message"]["usd_amount"])
    except Exception:
        pass
    return 0.0


async def split_get_balance() -> float:
    """Возвращает текущий TON-баланс на split.tg (в нанотонах → TON)."""
    try:
        async with aiohttp.ClientSession() as s:
            r    = await s.get(f"{SPLIT_BASE}/balance/ton", headers=split_headers())
            data = await r.json()
            if data.get("ok"):
                info = data["message"]
                # available в нанотонах
                return int(info.get("available", 0)) / 1e9
    except Exception:
        pass
    return 0.0


# ─── FSM States ───────────────────────────────────────────────────────────────

class TopUpStates(StatesGroup):
    waiting_amount = State()


class StarsStates(StatesGroup):
    calculator         = State()
    enter_stars_self   = State()
    confirm_self       = State()
    enter_friend_user  = State()
    enter_stars_friend = State()
    confirm_friend     = State()


class ReviewStates(StatesGroup):
    waiting_review = State()


class PremiumStates(StatesGroup):
    confirm_self = State()


def utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


BACK_EMOJI = "5258236805890710909"
ADMIN_ID   = 1896247728


def back_btn(callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="Назад",
        callback_data=callback_data,
        icon_custom_emoji_id=BACK_EMOJI,
        style="danger"
    )


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить баланс", callback_data="top_up",
                              icon_custom_emoji_id="5289970176052179025", style="primary")],
        [InlineKeyboardButton(text="Звёзды", callback_data="buy_stars",
                              icon_custom_emoji_id="5346309121794659890", style="success"),
         InlineKeyboardButton(text="Премиум", callback_data="buy_premium",
                              icon_custom_emoji_id="5274026806477857971", style="success")],
        [InlineKeyboardButton(text="Эмодзи пак", callback_data="emoji_pack",
                              icon_custom_emoji_id="5190573182439954711", style="primary")],
        [InlineKeyboardButton(text="Мой профиль", callback_data="my_profile",
                              icon_custom_emoji_id="5870994129244131212"),
         InlineKeyboardButton(text="Рефка", callback_data="referral",
                              icon_custom_emoji_id="5870772616305839506")],
        [InlineKeyboardButton(text="Информация", callback_data="info",
                              icon_custom_emoji_id="5870609858520158157"),
         InlineKeyboardButton(text="Отзывы", callback_data="reviews",
                              icon_custom_emoji_id="5870753782874246579")],
    ])


def build_who_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Себе", callback_data="stars_self"),
         InlineKeyboardButton(text="Другу", callback_data="stars_friend")],
        [back_btn("back_to_main")]
    ])


def build_enter_stars_keyboard(calc_on: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Калькулятор",
            callback_data="stars_calc_off" if calc_on else "stars_calc_on",
            icon_custom_emoji_id="5415756135925829889",
            style="primary" if calc_on else None)],
        [back_btn("stars_who")]
    ])


def build_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="stars_confirm",
                              style="success")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="stars_cancel",
                              style="danger")]
    ])


def build_payment_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="СБП Рубли | 8%", callback_data="pay_sbp",
                              icon_custom_emoji_id="5368446439800197476")],
        [back_btn("back_to_main")]
    ])


def build_enter_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [back_btn("top_up")]
    ])


def build_premium_who_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Себе", callback_data="premium_self"),
         InlineKeyboardButton(text="Другу", callback_data="premium_friend")],
        [back_btn("back_to_main")]
    ])


def build_premium_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 месяца",  callback_data="premium_period_3")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="premium_period_6")],
        [InlineKeyboardButton(text="12 месяцев", callback_data="premium_period_12")],
        [back_btn("buy_premium")]
    ])


def build_premium_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="premium_confirm",
                              style="success")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_premium",
                              style="danger")]
    ])


# ─── Тексты ───────────────────────────────────────────────────────────────────

async def start_text(username: str, user_id: int):
    balance = await get_balance(user_id)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"

    greeting = f"{e1} Привет, {username}\n\n"
    line2    = f"{e2} У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3    = f"{e3} Ваш текущий баланс: {balance:.2f} RUB\n\n"
    line4    = f"Выбери действие ниже {e4}"
    text     = greeting + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5269579312008299587"),
        MessageEntity(type="blockquote", offset=utf16_len(greeting),
                      length=utf16_len(line2.rstrip('\n'))),
        MessageEntity(type="custom_emoji", offset=utf16_len(greeting),
                      length=utf16_len(e2), custom_emoji_id="5346284060660494696"),
        MessageEntity(type="blockquote", offset=utf16_len(greeting + line2),
                      length=utf16_len(line3.rstrip('\n'))),
        MessageEntity(type="custom_emoji", offset=utf16_len(greeting + line2),
                      length=utf16_len(e3), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(greeting + line2 + line3 + "Выбери действие ниже "),
                      length=utf16_len(e4), custom_emoji_id="5193202823411546657"),
    ]
    return text, entities


async def stars_main_text(user_id: int):
    balance = await get_balance(user_id)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    line1 = f"{e1} Покупка Telegram Stars\n\n"
    line2 = f"Курс 1 {e2} = {STARS_RATE} RUB\n"
    line3 = f"{e3} Ваш баланс: {balance:.2f} RUB\n\n"
    line4 = f"{e4} Выберите, кому вы хотите приобрести звезды:"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5472256585323522641"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + "Курс 1 "),
                      length=utf16_len(e2), custom_emoji_id="5346309121794659890"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5377746319601324795"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5346309121794659890"),
    ]
    return text, entities


async def stars_enter_text(user_id: int, recipient: str):
    balance = await get_balance(user_id)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    line1 = f"Кому: {recipient}\n\n"
    line2 = f"Курс 1 {e1} = {STARS_RATE} RUB\n"
    line3 = f"{e2} Ваш баланс: {balance:.2f} RUB\n"
    line4 = f"{e3} Минимум: {STARS_MIN}\n\n"
    line5 = f"{e4} Введи количество звезд:"
    text  = line1 + line2 + line3 + line4 + line5

    entities = [
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + "Курс 1 "),
                      length=utf16_len(e1), custom_emoji_id="5346309121794659890"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e2), custom_emoji_id="5377746319601324795"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e3), custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3 + line4),
                      length=utf16_len(e4), custom_emoji_id="5346309121794659890"),
    ]
    return text, entities


async def stars_no_funds_text(user_id: int, stars: int):
    balance  = await get_balance(user_id)
    required = round(stars * STARS_RATE, 2)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    line1 = f"{e1} Недостаточно средств!\n\n"
    line2 = f"{e2} Ваш баланс: {balance:.2f} RUB\n"
    line3 = f"{e3} Требуется: {required:.2f} RUB\n\n"
    line4 = f"{e4} Пополните баланс для продолжения"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5447644880824181073"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5870609858520158157"),
    ]
    return text, entities


def stars_confirm_text(recipient: str, stars: int):
    total_rub = round(stars * STARS_RATE, 2)
    total_usd = round(total_rub / USD_RATE, 2)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    line1 = f"{e1} Подтверждение\n\n"
    line2 = f"{e2} Получатель: {recipient}\n"
    line3 = f"{e3} Количество: {stars}\n"
    line4 = f"{e4} Итого к оплате: {total_rub} RUB ({total_usd}$)"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5260463209562776385"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5870994129244131212"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5346309121794659890"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5377746319601324795"),
    ]
    return text, entities


def stars_calc_text(price_line: str = ""):
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"
    quote = "Здесь ты можешь посмотреть цену перед покупкой"

    line1 = f"{e1} Калькулятор\n\n"
    line2 = f"{quote}\n\n"
    line3 = f"Курс 1 {e2} = {STARS_RATE} RUB\n"
    extra = f"{e3} Цена: {price_line} RUB" if price_line else ""
    text  = line1 + line2 + line3 + extra

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5415756135925829889"),
        MessageEntity(type="blockquote", offset=utf16_len(line1), length=utf16_len(quote)),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + "Курс 1 "),
                      length=utf16_len(e2), custom_emoji_id="5346309121794659890"),
    ]
    if price_line:
        entities.append(MessageEntity(
            type="custom_emoji",
            offset=utf16_len(line1 + line2 + line3),
            length=utf16_len(e3),
            custom_emoji_id="5260463209562776385"
        ))
    return text, entities


# ─── Утилита: показать главную ────────────────────────────────────────────────

async def show_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user     = callback.from_user
    username = f"@{user.username}" if user.username else user.first_name
    text, entities = await start_text(username, user.id)
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_main_keyboard(),
        caption_entities=entities
    )


# ─── Handlers ─────────────────────────────────────────────────────────────────

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if await is_blocked(user.id):
        return

    referred_by = None
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith("ref_"):
            try:
                ref_id = int(param[4:])
                if ref_id != user.id:
                    referred_by = ref_id
            except ValueError:
                pass

    await upsert_user(user.id, user.username or "", user.first_name, referred_by)
    await add_log(user.id, "start")

    username = f"@{user.username}" if user.username else user.first_name
    text, entities = await start_text(username, user.id)
    if PHOTO_FILE_ID:
        await message.answer_photo(
            photo=PHOTO_FILE_ID,
            caption=text,
            reply_markup=build_main_keyboard(),
            caption_entities=entities
        )
    else:
        await message.answer(text=text, reply_markup=build_main_keyboard(), entities=entities)


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await show_main(callback, state)
    await callback.answer()


# ─── Звёзды ───────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "buy_stars")
async def buy_stars_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, entities = await stars_main_text(callback.from_user.id)
    await callback.message.edit_caption(
        caption=text, reply_markup=build_who_keyboard(), caption_entities=entities
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_who")
async def stars_who(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, entities = await stars_main_text(callback.from_user.id)
    await callback.message.edit_caption(
        caption=text, reply_markup=build_who_keyboard(), caption_entities=entities
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_self")
async def stars_self(callback: types.CallbackQuery, state: FSMContext):
    user      = callback.from_user
    recipient = f"@{user.username}" if user.username else user.first_name
    text, entities = await stars_enter_text(user.id, recipient)
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_enter_stars_keyboard(),
        caption_entities=entities
    )
    await state.set_state(StarsStates.enter_stars_self)
    await state.update_data(bot_msg_id=callback.message.message_id, recipient=recipient)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_friend")
async def stars_friend(callback: types.CallbackQuery, state: FSMContext):
    e1 = "⭐"
    text = f"{e1} Введите @username пользователя, которому хотите купить звезды:"
    entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                              custom_emoji_id="5771887475421090729")]
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("stars_who")]])
    await callback.message.edit_caption(
        caption=text,
        reply_markup=kb,
        caption_entities=entities
    )
    await state.set_state(StarsStates.enter_friend_user)
    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.answer()


@dp.message(StarsStates.enter_friend_user)
async def process_friend_username(message: types.Message, state: FSMContext):
    await message.delete()
    data       = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    user_id    = message.from_user.id

    raw = message.text.strip().lstrip("@")
    if not raw:
        return

    recipient = f"@{raw}"
    text, entities = await stars_enter_text(user_id, recipient)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Калькулятор", callback_data="stars_calc_on",
                              icon_custom_emoji_id="5415756135925829889")],
        [back_btn("stars_who")]
    ])
    if bot_msg_id:
        await bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            caption=text,
            reply_markup=kb,
            caption_entities=entities
        )
    await state.set_state(StarsStates.enter_stars_friend)
    await state.update_data(bot_msg_id=bot_msg_id, recipient=recipient)


@dp.message(StarsStates.enter_stars_friend)
async def process_stars_friend(message: types.Message, state: FSMContext):
    await message.delete()
    data       = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    recipient  = data.get("recipient", "")
    user_id    = message.from_user.id

    try:
        stars = int(message.text.strip())
        if stars < STARS_MIN:
            raise ValueError
    except ValueError:
        e        = "⭐"
        err_text = f"{e} Минимум {STARS_MIN} звёзд"
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e),
                                      custom_emoji_id="5273914604752216432")]
        err_msg = await message.answer(err_text, entities=err_entities)
        await asyncio.sleep(2)
        await err_msg.delete()
        return

    balance  = await get_balance(user_id)
    required = round(stars * STARS_RATE, 2)

    if balance < required:
        text, entities = await stars_no_funds_text(user_id, stars)
        if bot_msg_id:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=bot_msg_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn("stars_who")]]),
                caption_entities=entities
            )
    else:
        await state.update_data(stars=stars)
        text, entities = stars_confirm_text(recipient, stars)
        if bot_msg_id:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=bot_msg_id,
                caption=text,
                reply_markup=build_confirm_keyboard(),
                caption_entities=entities
            )
        await state.set_state(StarsStates.confirm_friend)


@dp.callback_query(lambda c: c.data == "stars_calc_on")
async def stars_calc_on(callback: types.CallbackQuery, state: FSMContext):
    text, entities = stars_calc_text()
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_enter_stars_keyboard(calc_on=True),
        caption_entities=entities
    )
    await state.set_state(StarsStates.calculator)
    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_calc_off")
async def stars_calc_off(callback: types.CallbackQuery, state: FSMContext):
    data      = await state.get_data()
    recipient = data.get("recipient", "")
    user      = callback.from_user
    if not recipient:
        recipient = f"@{user.username}" if user.username else user.first_name
    text, entities = await stars_enter_text(user.id, recipient)
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_enter_stars_keyboard(calc_on=False),
        caption_entities=entities
    )
    await state.set_state(StarsStates.enter_stars_self)
    await state.update_data(bot_msg_id=callback.message.message_id, recipient=recipient)
    await callback.answer()


@dp.message(StarsStates.calculator)
async def calc_stars(message: types.Message, state: FSMContext):
    await message.delete()
    try:
        stars = float(message.text.replace(",", "."))
        if stars <= 0:
            raise ValueError
        price      = round(stars * STARS_RATE, 2)
        price_line = str(price)
    except ValueError:
        return
    data       = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    text, entities = stars_calc_text(price_line)
    if bot_msg_id:
        await bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            caption=text,
            reply_markup=build_enter_stars_keyboard(calc_on=True),
            caption_entities=entities
        )


@dp.message(StarsStates.enter_stars_self)
async def process_stars(message: types.Message, state: FSMContext):
    await message.delete()
    data       = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    recipient  = data.get("recipient", "")
    user_id    = message.from_user.id

    try:
        stars = int(message.text.strip())
        if stars < STARS_MIN:
            raise ValueError
    except ValueError:
        e        = "⭐"
        err_text = f"{e} Минимум {STARS_MIN} звёзд"
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e),
                                      custom_emoji_id="5273914604752216432")]
        err_msg = await message.answer(err_text, entities=err_entities)
        await asyncio.sleep(2)
        await err_msg.delete()
        return

    balance  = await get_balance(user_id)
    required = round(stars * STARS_RATE, 2)

    if balance < required:
        text, entities = await stars_no_funds_text(user_id, stars)
        if bot_msg_id:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=bot_msg_id,
                caption=text,
                reply_markup=build_enter_stars_keyboard(),
                caption_entities=entities
            )
    else:
        await state.update_data(stars=stars)
        text, entities = stars_confirm_text(recipient, stars)
        if bot_msg_id:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=bot_msg_id,
                caption=text,
                reply_markup=build_confirm_keyboard(),
                caption_entities=entities
            )
        await state.set_state(StarsStates.confirm_self)


@dp.callback_query(lambda c: c.data == "stars_confirm")
async def stars_confirm(callback: types.CallbackQuery, state: FSMContext):
    data      = await state.get_data()
    stars     = data.get("stars")
    recipient = data.get("recipient", "")
    user_id   = callback.from_user.id
    username  = recipient.lstrip("@")
    total_rub = round(stars * STARS_RATE, 2)

    await callback.answer("⏳ Обрабатываем заказ...", show_alert=False)

    try:
        # 1. Проверяем получателя в Split
        recip_data = await split_check_recipient(username)
        if not recip_data:
            raise Exception("Пользователь не найден в Telegram")

        # 2. Покупаем звёзды через Split
        await split_buy_stars(username, stars, user_id)

        # 3. Списываем баланс и пишем лог
        await deduct_balance(user_id, total_rub)
        await add_log(user_id, "buy_stars", f"{stars} stars → @{username}")

        e1   = "⭐"
        text = f"{e1} Готово, звёзды придут в течении нескольких минут"
        entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                                  custom_emoji_id="5260463209562776385")]
        await state.clear()
        await callback.message.edit_caption(
            caption=text,
            reply_markup=build_main_keyboard(),
            caption_entities=entities
        )

    except Exception as e:
        err_reason = str(e)
        await add_log(user_id, "buy_stars_error", err_reason)

        # Уведомляем админа с полной причиной
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❌ Ошибка покупки звёзд\n"
                f"👤 user_id: <code>{user_id}</code>\n"
                f"⭐ Stars: {stars} → @{username}\n"
                f"💬 Причина: <code>{err_reason}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Формируем понятное сообщение пользователю
        if "не найден" in err_reason.lower() or "recipient" in err_reason.lower():
            user_msg = "Пользователь не найден в Telegram или не может получить звёзды"
        elif "balance" in err_reason.lower() or "insufficient" in err_reason.lower():
            user_msg = "Недостаточно средств на балансе сервиса. Попробуйте позже"
        elif "timeout" in err_reason.lower() or "connect" in err_reason.lower():
            user_msg = "Сервис временно недоступен. Попробуйте через несколько минут"
        elif "api" in err_reason.lower() or "split" in err_reason.lower():
            user_msg = f"Ошибка платёжного сервиса: {err_reason}"
        else:
            user_msg = f"Ошибка: {err_reason}"

        e1 = "⭐"
        err_text = (
            f"{e1} Покупка не выполнена\n\n"
            f"Причина: {user_msg}\n\n"
            f"Поддержка: @tntks"
        )
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                                      custom_emoji_id="5447644880824181073")]
        await callback.message.edit_caption(
            caption=err_text,
            reply_markup=build_main_keyboard(),
            caption_entities=err_entities
        )


@dp.callback_query(lambda c: c.data == "stars_cancel")
async def stars_cancel(callback: types.CallbackQuery, state: FSMContext):
    await show_main(callback, state)
    await callback.answer()


# ─── Пополнить баланс ─────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "top_up")
async def top_up_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    e1    = "⭐"
    line1 = "Выберите способ пополнения из предложенных:\n\n"
    line2 = f"{e1} СБП - оплата рублями через QR-код"
    text  = line1 + line2
    entities = [MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                              length=utf16_len(e1), custom_emoji_id="5368446439800197476")]
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_payment_method_keyboard(),
        caption_entities=entities
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "pay_sbp")
async def pay_sbp(callback: types.CallbackQuery, state: FSMContext):
    ei    = "⭐"
    line1 = f"{ei} Пополнение через Platega\n\n"
    line2 = f"{ei} Комиссия платежной системы: 8%\n"
    line3 = f"{ei} Минимальное пополнение: 10 RUB\n\n"
    line4 = f"{ei} Введите сумму:"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(ei), custom_emoji_id="5303530109360174452"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(ei), custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(ei), custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(ei), custom_emoji_id="5289970176052179025"),
    ]
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_enter_amount_keyboard(),
        caption_entities=entities
    )
    await state.set_state(TopUpStates.waiting_amount)
    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.answer()


@dp.message(TopUpStates.waiting_amount)
async def process_amount(message: types.Message, state: FSMContext):
    await message.delete()
    try:
        amount = float(message.text.replace(",", "."))
        if amount < MIN_AMOUNT:
            raise ValueError
    except ValueError:
        e        = "⭐"
        err_text = f"{e} Минимальное пополнение 10 RUB"
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e),
                                      custom_emoji_id="5273914604752216432")]
        err_msg = await message.answer(err_text, entities=err_entities)
        await asyncio.sleep(2)
        await err_msg.delete()
        return

    total = round(amount * (1 + COMMISSION), 2)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"

    line1 = f"{e1} Готово!\n\n"
    line2 = f"{e2} Сумма к оплате: {total:.2f} RUB\n"
    line3 = f"{e3} Сумма к получению: {amount:.2f} RUB\n"
    line4 = f"{e4} Для оплаты нажмите кнопку ниже:"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5260463209562776385"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5193202823411546757"),
    ]
    data       = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    await state.clear()
    if bot_msg_id:
        await bot.edit_message_caption(
            chat_id=message.chat.id, message_id=bot_msg_id,
            caption=text, caption_entities=entities
        )


# ─── Мой профиль ──────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "my_profile")
async def my_profile(callback: types.CallbackQuery):
    user    = callback.from_user
    user_id = user.id

    info          = await get_user_info(user_id)
    orders        = await get_total_orders(user_id)
    stars         = await get_total_stars(user_id)
    premium       = await get_total_premium(user_id)
    balance       = float(info.get("balance", 0) or 0)
    total_balance = float(info.get("total_balance", 0) or 0)
    registered_at = info.get("registered_at")
    reg_str       = registered_at.strftime("%d.%m.%Y") if registered_at else "—"
    username      = f"@{user.username}" if user.username else user.first_name

    e_title = "⭐"; e_id = "⭐"; e_user = "⭐"; e_bal = "⭐"
    e_ord = "⭐"; e_star = "⭐"; e_prem = "⭐"; e_date = "⭐"

    line0 = f"{e_title} Мой профиль\n\n"
    line1 = f"{e_id}ID: {user_id}\n"
    line2 = f"{e_user}Username: {username}\n\n"
    line3 = f"{e_bal}Текущий баланс: {balance:.2f} RUB\n"
    line4 = f"Улетело: {total_balance:.2f} RUB\n\n"
    line5 = f"{e_ord}Всего заказов: {orders}\n"
    line6 = f"{e_star}Всего куплено звезд: {stars}\n"
    line7 = f"{e_prem}Всего куплено премиум: {premium}\n\n"
    line8 = f"{e_date}Дата регистрации: {reg_str}"
    text  = line0 + line1 + line2 + line3 + line4 + line5 + line6 + line7 + line8

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e_title), custom_emoji_id="5870994129244131212"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line0),
                      length=utf16_len(e_id), custom_emoji_id="5936017305585586269"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line0 + line1),
                      length=utf16_len(e_user), custom_emoji_id="5771887475421090729"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line0 + line1 + line2),
                      length=utf16_len(e_bal), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line0 + line1 + line2 + line3 + line4),
                      length=utf16_len(e_ord), custom_emoji_id="5346267284518239633"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line0 + line1 + line2 + line3 + line4 + line5),
                      length=utf16_len(e_star), custom_emoji_id="5346309121794659890"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line0 + line1 + line2 + line3 + line4 + line5 + line6),
                      length=utf16_len(e_prem), custom_emoji_id="5274026806477857971"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line0 + line1 + line2 + line3 + line4 + line5 + line6 + line7),
                      length=utf16_len(e_date), custom_emoji_id="5967412305338568701"),
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="История заказов",
            callback_data="order_history",
            icon_custom_emoji_id="5444856076954520455"
        )],
        [back_btn("back_to_main")]
    ])
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "order_history")
async def order_history(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    orders  = await get_order_history(user_id)

    e1 = "⭐"

    if not orders:
        text     = f"{e1} У вас нету заказов"
        entities = [MessageEntity(type="custom_emoji", offset=0,
                                  length=utf16_len(e1), custom_emoji_id="5273914604752216432")]
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("my_profile")]])
        await callback.message.edit_caption(caption=text, reply_markup=kb,
                                            caption_entities=entities)
        await callback.answer()
        return

    line1    = f"{e1} История покупок:\n"
    text     = line1
    entities = [MessageEntity(type="custom_emoji", offset=0,
                              length=utf16_len(e1), custom_emoji_id="5444856076954520455")]

    buttons = []
    for order in orders:
        action   = order["action"]
        detail   = order["details"] or ""
        date_str = str(order["created_at"])[:16].replace("T", " ")
        if action == "buy_stars":
            qty   = detail.split(" stars")[0].strip()
            label = f"⭐ Stars — {qty} шт. | {date_str}"
        elif action == "buy_premium":
            label = f"💎 Premium — {detail} | {date_str}"
        else:
            label = f"📦 {action} | {date_str}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"order_detail_{order['id']}"
        )])

    buttons.append([back_btn("my_profile")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("order_detail_"))
async def order_detail(callback: types.CallbackQuery):
    from db.database import get_order_by_id
    order_id = int(callback.data.split("_")[-1])
    order    = await get_order_by_id(order_id)

    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    action  = order["action"]
    details = order["details"] or ""
    created = str(order["created_at"])[:16].replace("T", " ")

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    if action == "buy_stars":
        parts     = details.split(" stars → ")
        qty       = parts[0].strip() if parts else "?"
        recipient = parts[1].strip() if len(parts) > 1 else "—"
        price     = round(int(qty) * STARS_RATE, 2) if qty.isdigit() else "?"

        line1 = f"{e1} Продукт: Telegram Stars - {qty} Stars\n"
        line2 = f"{e2} Цена: {price}₽\n"
        line3 = f"{e3} Дата: {created}\n"
        line4 = f"{e4} Получатель: ({recipient})"
        text  = line1 + line2 + line3 + line4

        entities = [
            MessageEntity(type="custom_emoji", offset=0,
                          length=utf16_len(e1), custom_emoji_id="5258389041006518073"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                          length=utf16_len(e2), custom_emoji_id="5289970176052179025"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                          length=utf16_len(e3), custom_emoji_id="5967412305338568701"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                          length=utf16_len(e4), custom_emoji_id="5870994129244131212"),
        ]
    elif action == "buy_premium":
        line1 = f"{e1} Продукт: Telegram Premium - {details}\n"
        line2 = f"{e2} Дата: {created}"
        text  = line1 + line2
        entities = [
            MessageEntity(type="custom_emoji", offset=0,
                          length=utf16_len(e1), custom_emoji_id="5258389041006518073"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                          length=utf16_len(e2), custom_emoji_id="5967412305338568701"),
        ]
    else:
        line1 = f"{e1} Действие: {action}\n"
        line2 = f"{e2} Детали: {details}\n"
        line3 = f"{e3} Дата: {created}"
        text  = line1 + line2 + line3
        entities = [
            MessageEntity(type="custom_emoji", offset=0,
                          length=utf16_len(e1), custom_emoji_id="5258389041006518073"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                          length=utf16_len(e2), custom_emoji_id="5289970176052179025"),
            MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                          length=utf16_len(e3), custom_emoji_id="5967412305338568701"),
        ]

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("order_history")]])
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await callback.answer()


# ─── Рефка ────────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "referral")
async def show_referral(callback: types.CallbackQuery):
    user    = callback.from_user
    user_id = user.id

    stats    = await get_ref_stats(user_id)
    count    = stats["count"]
    profit   = stats["ref_balance"]

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"; e5 = "⭐"

    line1 = f"{e1} Рефка\n\n"
    line2 = f"Получай +{REF_PCT}%  за каждую покупку реферала!\n\n"
    line3 = f"{e2} Приглашено рефералов: {count}\n"
    line4 = f"{e3} Прибыль от реф. программы: {profit:.2f} RUB\n\n"
    line5 = f"{e4} Ваша реферальная ссылка:\n"
    line6 = f"{ref_link}\n\n"
    line7 = f"{e5}Вывод доступен через поддержку"
    text  = line1 + line2 + line3 + line4 + line5 + line6 + line7

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5870772616305839506"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e2), custom_emoji_id="5870695289714643076"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e3), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3 + line4),
                      length=utf16_len(e4), custom_emoji_id="6028171274939797252"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line1 + line2 + line3 + line4 + line5 + line6),
                      length=utf16_len(e5), custom_emoji_id="5879814368572478751"),
        MessageEntity(type="url",
                      offset=utf16_len(line1 + line2 + line3 + line4 + line5),
                      length=utf16_len(ref_link)),
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("back_to_main")]])
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await callback.answer()


# ─── Премиум ──────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    e1 = "⭐"; e2 = "⭐"

    line1 = f"{e1} Покупка Telegram Premium\n\n"
    line2 = f"{e2} Выберите, кому вы хотите приобрести премиум:"
    text  = line1 + line2

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5472256585323522641"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5274026806477857971"),
    ]

    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_premium_who_keyboard(),
        caption_entities=entities
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "premium_self")
async def premium_self(callback: types.CallbackQuery, state: FSMContext):
    user = callback.from_user

    if user.is_premium:
        e        = "⭐"
        err_text = f"{e} Ошибка! У пользователя уже есть Telegram Premium!"
        err_ent  = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e),
                                  custom_emoji_id="5273914604752216432")]
        err_msg  = await callback.message.answer(err_text, entities=err_ent)
        await callback.answer()
        await asyncio.sleep(1)
        await err_msg.delete()
        return

    e1    = "⭐"
    line1 = f"{e1} Выберите период подписки:"
    text  = line1

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5274026806477857971"),
    ]

    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_premium_period_keyboard(),
        caption_entities=entities
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "premium_friend")
async def premium_friend(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


@dp.callback_query(lambda c: c.data.startswith("premium_period_"))
async def premium_period(callback: types.CallbackQuery, state: FSMContext):
    months = callback.data.split("_")[-1]
    price  = PREMIUM_PRICES[months]
    user   = callback.from_user

    await state.update_data(months=months, price=price)

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"

    line1 = f"{e1} Подтверждение\n\n"
    line2 = f"{e2} Получатель: @{user.username or user.first_name}\n"
    line3 = f"{e3} Период: {months} мес.\n"
    line4 = f"{e4} Итого к оплате: {price} RUB"
    text  = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5260463209562776385"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5870994129244131212"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5274026806477857971"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5377746319601324795"),
    ]

    await callback.message.edit_caption(
        caption=text,
        reply_markup=build_premium_confirm_keyboard(),
        caption_entities=entities
    )
    await state.set_state(PremiumStates.confirm_self)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "premium_confirm")
async def premium_confirm(callback: types.CallbackQuery, state: FSMContext):
    # TODO: подключить МРКТ API здесь
    await state.clear()
    await callback.answer("Скоро будет доступно!", show_alert=True)


# ─── Информация ───────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "info")
async def show_info(callback: types.CallbackQuery):
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "⭐"; e5 = "⭐"

    line1 = f"{e1} Информация\n\n"
    line2 = f"Для ознакомления с правилами сервиса воспользуйтесь ссылками ниже {e2}\n\n"
    line3 = f"{e3} Политика конфиденциальности\n"
    line4 = f"{e4} Пользовательское соглашение\n\n"
    line5 = f"{e5} Тех. Поддержка: @tntks"
    text  = line1 + line2 + line3 + line4 + line5

    e_len = utf16_len("⭐") + utf16_len(" ")

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(line1 + "Для ознакомления с правилами сервиса воспользуйтесь ссылками ниже "),
                      length=utf16_len(e2), custom_emoji_id="5193202823411546657"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5875206779196935950"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5875206779196935950"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3 + line4),
                      length=utf16_len(e5), custom_emoji_id="5938252440926163756"),
        MessageEntity(type="text_link",
                      offset=utf16_len(line1 + line2) + e_len,
                      length=utf16_len("Политика конфиденциальности"),
                      url="https://telegra.ph/Politika-konfidencialnosti-04-01-26"),
        MessageEntity(type="text_link",
                      offset=utf16_len(line1 + line2 + line3) + e_len,
                      length=utf16_len("Пользовательское соглашение"),
                      url="https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19"),
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("back_to_main")]])
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await callback.answer()


# ─── Отзывы ───────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "reviews")
async def show_reviews(callback: types.CallbackQuery, state: FSMContext):
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"
    line1 = f"{e1} Отзывы\n\n"
    line2 = f"{e2} Посмотреть все отзывы можно тут\n"
    line3 = f"{e3} Следующим сообщением можешь оставить отзыв, он окажется там"
    text  = line1 + line2 + line3

    e_len = utf16_len("⭐") + utf16_len(" ")
    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5870753782874246579"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5823396554345549784"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5870753782874246579"),
        MessageEntity(type="text_link",
                      offset=utf16_len(line1) + e_len + utf16_len("Посмотреть все отзывы можно "),
                      length=utf16_len("тут"),
                      url="https://t.me/urbiex"),
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("back_to_main")]])
    await callback.message.edit_caption(caption=text, reply_markup=kb,
                                        caption_entities=entities)
    await state.set_state(ReviewStates.waiting_review)
    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.answer()


@dp.message(ReviewStates.waiting_review)
async def receive_review(message: types.Message, state: FSMContext):
    user     = message.from_user
    username = f"@{user.username}" if user.username else user.first_name

    await bot.send_message(
        ADMIN_ID,
        f"📝 Новый отзыв от {username} (<code>{user.id}</code>):\n\n{message.text}",
        parse_mode="HTML"
    )

    await message.delete()
    await state.clear()

    e1 = "⭐"
    conf_text     = f"{e1} Спасибо! Твой отзыв отправлен на проверку."
    conf_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                                   custom_emoji_id="5260463209562776385")]
    conf_msg = await message.answer(conf_text, entities=conf_entities)

    await asyncio.sleep(2)
    await conf_msg.delete()

    text, entities = await start_text(username, user.id)
    if PHOTO_FILE_ID:
        await message.answer_photo(photo=PHOTO_FILE_ID, caption=text,
                                   reply_markup=build_main_keyboard(),
                                   caption_entities=entities)
    else:
        await message.answer(text=text, reply_markup=build_main_keyboard(), entities=entities)


# ─── Заглушки ─────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "emoji_pack")
async def handle_stub_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    await init_db()
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Меню")
    ])
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
