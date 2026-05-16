import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def utf16_len(s: str) -> int:
    """Длина строки в UTF-16 единицах — именно так считает Telegram"""
    return len(s.encode('utf-16-le')) // 2


def get_user_balance(user_id: int) -> float:
    return 0.0


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💳 Пополнить баланс",
                callback_data="top_up"
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Звёзды",
                callback_data="buy_stars"
            ),
            InlineKeyboardButton(
                text="💎 Премиум",
                callback_data="buy_premium"
            )
        ]
    ])


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    hello_emoji = "⭐"
    arrow_emoji = "👇"

    greeting   = f"{hello_emoji} Привет, {username}\n\n"
    line2      = "У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3      = f"Ваш текущий баланс: {balance:.2f} ₽\n\n"
    line4      = f"Выбери действие ниже {arrow_emoji}"

    text = greeting + line2 + line3 + line4

    # Точный расчёт offset в UTF-16 (как требует Telegram)
    offset_hello       = 0
    len_hello          = utf16_len(hello_emoji)

    offset_blockquote1 = utf16_len(greeting)
    len_blockquote1    = utf16_len(line2.rstrip('\n'))

    offset_blockquote2 = utf16_len(greeting + line2)
    len_blockquote2    = utf16_len(line3.rstrip('\n'))

    offset_arrow       = utf16_len(greeting + line2 + line3 + "Выбери действие ниже ")
    len_arrow          = utf16_len(arrow_emoji)

    entities = [
        MessageEntity(type="custom_emoji", offset=offset_hello,
                      length=len_hello, custom_emoji_id="547009278509"),
        MessageEntity(type="blockquote",   offset=offset_blockquote1,
                      length=len_blockquote1),
        MessageEntity(type="blockquote",   offset=offset_blockquote2,
                      length=len_blockquote2),
        MessageEntity(type="custom_emoji", offset=offset_arrow,
                      length=len_arrow,    custom_emoji_id="519320282341"),
    ]

    await message.answer(
        text=text,
        reply_markup=build_main_keyboard(),
        entities=entities
    )


@dp.callback_query(lambda c: c.data in ["top_up", "buy_stars", "buy_premium"])
async def handle_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
