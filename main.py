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

    # Используем обычные эмодзи как placeholder — длина 1 символ каждый
    # Важно: НЕ используем parse_mode вместе с entities!
    hello_emoji = "⭐"   # offset 0, length 2 (эмодзи = 2 UTF-16)
    arrow_emoji = "👇"

    greeting = f"{hello_emoji} Привет, {username}\n\n"
    line2 = f"У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3 = f"Ваш текущий баланс: {balance:.2f} ₽\n\n"
    line4 = f"Выбери действие ниже {arrow_emoji}"

    text = greeting + line2 + line3 + line4

    # Считаем offset для blockquote и кастомных эмодзи
    # Эмодзи занимают 2 UTF-16 единицы
    offset_hello = 0

    offset_blockquote1 = len(greeting)
    len_blockquote1 = len(line2) - 1  # без \n

    offset_blockquote2 = len(greeting + line2)
    len_blockquote2 = len(line3) - 1  # без \n

    offset_arrow = len(greeting + line2 + line3 + "Выбери действие ниже ")

    entities = [
        MessageEntity(type="custom_emoji", offset=offset_hello, length=2,
                      custom_emoji_id="547009278509"),
        MessageEntity(type="blockquote", offset=offset_blockquote1, length=len_blockquote1),
        MessageEntity(type="blockquote", offset=offset_blockquote2, length=len_blockquote2),
        MessageEntity(type="custom_emoji", offset=offset_arrow, length=2,
                      custom_emoji_id="519320282341"),
    ]

    await message.answer(
        text=text,
        reply_markup=build_main_keyboard(),
        entities=entities
        # parse_mode НЕ указываем — entities и parse_mode несовместимы
    )


@dp.callback_query(lambda c: c.data in ["top_up", "buy_stars", "buy_premium"])
async def handle_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
