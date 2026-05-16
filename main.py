import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    MessageEntity
)
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()


def get_user_balance(user_id: int) -> float:
    return 0.0


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💳 Пополнить баланс",
                callback_data="top_up",
                icon_custom_emoji_id="528997017605"
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Звёзды",
                callback_data="buy_stars",
                icon_custom_emoji_id="534630912179"
            ),
            InlineKeyboardButton(
                text="💎 Премиум",
                callback_data="buy_premium",
                icon_custom_emoji_id="527402680647"
            )
        ]
    ])


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    # Текст сообщения — эмодзи-заглушки на месте кастомных
    text = (
        f"⭐ Привет, {username}\n\n"
        f"У нас вы можете приобрести TG Stars и TG Premium.\n\n"
        f"Ваш текущий баланс: {balance:.2f} ₽\n\n"
        f"Выбери действие ниже 👇"
    )

    # entities для кастомных эмодзи в тексте
    # Позиция 0 — первый символ "⭐" (1 символ)
    entities = [
        MessageEntity(
            type="custom_emoji",
            offset=0,
            length=1,
            custom_emoji_id="547009278509"  # приветственный эмодзи
        )
    ]

    await message.answer(
        text,
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
    
