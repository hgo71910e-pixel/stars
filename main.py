import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PHOTO_FILE_ID = os.getenv("PHOTO_FILE_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

COMMISSION = 0.08  # 8%
MIN_AMOUNT = 10


class TopUpStates(StatesGroup):
    waiting_amount = State()


def utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


def get_user_balance(user_id: int) -> float:
    return 0.0


def make_entity(type, offset_str, emoji_str, emoji_id=None):
    e = {"type": type, "offset": utf16_len(offset_str), "length": utf16_len(emoji_str)}
    if emoji_id:
        e["custom_emoji_id"] = emoji_id
    return MessageEntity(**e)


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить баланс", callback_data="top_up",
                              icon_custom_emoji_id="5289970176052179025")],
        [InlineKeyboardButton(text="Звёзды", callback_data="buy_stars",
                              icon_custom_emoji_id="5346309121794659890"),
         InlineKeyboardButton(text="Премиум", callback_data="buy_premium",
                              icon_custom_emoji_id="5274026806477857971")]
    ])


def build_payment_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="СБП Рубли | 8%", callback_data="pay_sbp",
                              icon_custom_emoji_id="5368446439800197476")]
    ])


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"

    greeting = f"{e1} Привет, {username}\n\n"
    line2     = f"{e2} У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3     = f"{e3} Ваш текущий баланс: {balance:.2f} RUB\n\n"
    line4     = f"Выбери действие ниже {e4}"
    text = greeting + line2 + line3 + line4

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

    if PHOTO_FILE_ID:
        await message.answer_photo(photo=PHOTO_FILE_ID, caption=text,
                                   reply_markup=build_main_keyboard(),
                                   caption_entities=entities)
    else:
        await message.answer(text=text, reply_markup=build_main_keyboard(), entities=entities)


# ─── Пополнить баланс ─────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "top_up")
async def top_up_menu(callback: types.CallbackQuery):
    e = "⭐"
    text = f"{e} Выберите способ пополнения из предложенных:"
    entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e),
                              custom_emoji_id="5368446439800197476")]
    await callback.message.answer(text, reply_markup=build_payment_method_keyboard(),
                                  entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "pay_sbp")
async def pay_sbp(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "Пополнение через Platega\n"
        "Комиссия платежной системы: 8%\n"
        "Минимальное пополнение: 10 RUB\n\n"
        "⭐ Введите сумму:"
    )
    e = "⭐"
    prefix = "Пополнение через Platega\nКомиссия платежной системы: 8%\nМинимальное пополнение: 10 RUB\n\n"
    entities = [MessageEntity(type="custom_emoji", offset=utf16_len(prefix),
                              length=utf16_len(e), custom_emoji_id="5289970176052179025")]
    await callback.message.answer(text, entities=entities)
    await state.set_state(TopUpStates.waiting_amount)
    await callback.answer()


@dp.message(TopUpStates.waiting_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        err_e = "⭐"
        err_text = f"{err_e} Минимальное пополнение 10 RUB"
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(err_e),
                                      custom_emoji_id="5273914604752216432")]
        err_msg = await message.answer(err_text, entities=err_entities)
        await asyncio.sleep(2)
        await err_msg.delete()
        return

    if amount < MIN_AMOUNT:
        err_e = "⭐"
        err_text = f"{err_e} Минимальное пополнение 10 RUB"
        err_entities = [MessageEntity(type="custom_emoji", offset=0, length=utf16_len(err_e),
                                      custom_emoji_id="5273914604752216432")]
        err_msg = await message.answer(err_text, entities=err_entities)
        await asyncio.sleep(2)
        await err_msg.delete()
        return

    total = round(amount * (1 + COMMISSION), 2)

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"
    line1 = f"{e1} Готово!\n"
    line2 = f"{e2} Сумма к оплате: {total:.2f} RUB\n"
    line3 = f"{e3} Сумма к получению: {amount:.2f} RUB\n"
    line4 = f"{e4} Для оплаты нажмите кнопку ниже:"
    text = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=utf16_len(e1),
                      custom_emoji_id="5260463209562776385"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e2), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5289970176052179025"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(e4), custom_emoji_id="5193202823411546657"),
    ]

    await message.answer(text, entities=entities)
    await state.clear()


@dp.callback_query(lambda c: c.data in ["buy_stars", "buy_premium"])
async def handle_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
