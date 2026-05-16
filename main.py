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

COMMISSION = 0.08
MIN_AMOUNT = 10
STARS_RATE = 1.25


class TopUpStates(StatesGroup):
    waiting_amount = State()


class StarsStates(StatesGroup):
    calculator = State()


def utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


def get_user_balance(user_id: int) -> float:
    return 0.0


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Пополнить баланс", callback_data="top_up",
                                 icon_custom_emoji_id="5289970176052179025",
                                 style="primary")
        ],
        [
            InlineKeyboardButton(text="Звёзды", callback_data="buy_stars",
                                 icon_custom_emoji_id="5346309121794659890",
                                 style="success"),
            InlineKeyboardButton(text="Премиум", callback_data="buy_premium",
                                 icon_custom_emoji_id="5274026806477857971",
                                 style="success")
        ],
        [
            InlineKeyboardButton(text="Эмодзи пак", callback_data="emoji_pack",
                                 icon_custom_emoji_id="5190573182439954711",
                                 style="primary")
        ],
        [
            InlineKeyboardButton(text="Мой профиль", callback_data="my_profile",
                                 icon_custom_emoji_id="5870994129244131212"),
            InlineKeyboardButton(text="Рефка", callback_data="referral",
                                 icon_custom_emoji_id="5870772616305839506")
        ],
        [
            InlineKeyboardButton(text="Информация", callback_data="info",
                                 icon_custom_emoji_id="5870609858520158157"),
            InlineKeyboardButton(text="Отзывы", callback_data="reviews",
                                 icon_custom_emoji_id="5870753782874246579")
        ],
    ])


def build_stars_keyboard(calc_on: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Калькулятор",
                callback_data="stars_calc_off" if calc_on else "stars_calc_on",
                icon_custom_emoji_id="5415756135925829889",
                style="primary" if calc_on else None
            )
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")
        ]
    ])


def build_payment_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="СБП Рубли | 8%", callback_data="pay_sbp",
                              icon_custom_emoji_id="5368446439800197476")]
    ])


def build_enter_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="top_up")]
    ])


def stars_main_text(user_id: int) -> tuple[str, list]:
    balance = get_user_balance(user_id)
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"
    line1 = f"{e1} Покупка Telegram Stars\n\n"
    line2 = f"Курс 1 {e2} = {STARS_RATE} RUB\n"
    line3 = f"{e3} Ваш баланс: {balance:.2f} RUB"
    text = line1 + line2 + line3

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5472256585323522641"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + "Курс 1 "),
                      length=utf16_len(e2), custom_emoji_id="5346309121794659890"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(e3), custom_emoji_id="5377746319601324795"),
    ]
    return text, entities


def stars_calc_text(price_line: str = "") -> tuple[str, list]:
    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"
    quote = "Здесь ты можешь посмотреть цену перед покупкой"
    line1 = f"{e1} Калькулятор\n\n"
    line2 = f"{quote}\n\n"
    line3 = f"Курс 1 {e2} = {STARS_RATE} RUB\n"
    extra = f"{e3} Цена: {price_line} RUB" if price_line else ""
    text = line1 + line2 + line3 + extra

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(e1), custom_emoji_id="5415756135925829889"),
        MessageEntity(type="blockquote", offset=utf16_len(line1),
                      length=utf16_len(quote)),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + "Курс 1 "),
                      length=utf16_len(e2), custom_emoji_id="5346309121794659890"),
    ]

    if price_line:
        entities.append(MessageEntity(type="custom_emoji",
                                      offset=utf16_len(line1 + line2 + line3),
                                      length=utf16_len(e3),
                                      custom_emoji_id="5260463209562776385"))

    return text, entities


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"
    greeting = f"{e1} Привет, {username}\n\n"
    line2    = f"{e2} У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3    = f"{e3} Ваш текущий баланс: {balance:.2f} RUB\n\n"
    line4    = f"Выбери действие ниже {e4}"
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


# ─── Звёзды ───────────────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "buy_stars")
async def buy_stars_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, entities = stars_main_text(callback.from_user.id)
    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_stars_keyboard(calc_on=False),
                                        caption_entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    e1 = "⭐"; e2 = "⭐"; e3 = "⭐"; e4 = "👇"
    greeting = f"{e1} Привет, {username}\n\n"
    line2    = f"{e2} У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3    = f"{e3} Ваш текущий баланс: {balance:.2f} RUB\n\n"
    line4    = f"Выбери действие ниже {e4}"
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

    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_main_keyboard(),
                                        caption_entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_calc_on")
async def stars_calc_on(callback: types.CallbackQuery, state: FSMContext):
    text, entities = stars_calc_text()
    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_stars_keyboard(calc_on=True),
                                        caption_entities=entities)
    await state.set_state(StarsStates.calculator)
    await state.update_data(bot_msg_id=callback.message.message_id)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stars_calc_off")
async def stars_calc_off(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, entities = stars_main_text(callback.from_user.id)
    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_stars_keyboard(calc_on=False),
                                        caption_entities=entities)
    await callback.answer()


@dp.message(StarsStates.calculator)
async def calc_stars(message: types.Message, state: FSMContext):
    await message.delete()
    try:
        stars = float(message.text.replace(",", "."))
        if stars <= 0:
            raise ValueError
        price = round(stars * STARS_RATE, 2)
        price_line = str(price)
    except ValueError:
        return

    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    text, entities = stars_calc_text(price_line)

    if bot_msg_id:
        await bot.edit_message_caption(chat_id=message.chat.id, message_id=bot_msg_id,
                                       caption=text,
                                       reply_markup=build_stars_keyboard(calc_on=True),
                                       caption_entities=entities)


# ─── Пополнить баланс ─────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "top_up")
async def top_up_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    e1 = "⭐"
    line1 = "Выберите способ пополнения из предложенных:\n\n"
    line2 = f"{e1} СБП - оплата рублями через QR-код"
    text = line1 + line2

    entities = [
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(e1), custom_emoji_id="5368446439800197476"),
    ]

    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_payment_method_keyboard(),
                                        caption_entities=entities)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "pay_sbp")
async def pay_sbp(callback: types.CallbackQuery, state: FSMContext):
    ei = "⭐"
    line1 = "Пополнение через Platega\n\n"
    line2 = f"{ei} Комиссия платежной системы: 8%\n"
    line3 = f"{ei} Минимальное пополнение: 10 RUB\n\n"
    line4 = f"{ei} Введите сумму:"
    text = line1 + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=utf16_len(line1),
                      length=utf16_len(ei), custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2),
                      length=utf16_len(ei), custom_emoji_id="5870609858520158157"),
        MessageEntity(type="custom_emoji", offset=utf16_len(line1 + line2 + line3),
                      length=utf16_len(ei), custom_emoji_id="5289970176052179025"),
    ]

    await callback.message.edit_caption(caption=text,
                                        reply_markup=build_enter_amount_keyboard(),
                                        caption_entities=entities)
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

    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    await state.clear()

    if bot_msg_id:
        await bot.edit_message_caption(chat_id=message.chat.id, message_id=bot_msg_id,
                                       caption=text, caption_entities=entities)


@dp.callback_query(lambda c: c.data in [
    "buy_premium", "emoji_pack", "my_profile", "info", "referral", "reviews"
])
async def handle_stub_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
