import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Премиум эмодзи (кастомные)
EMOJI_HELLO    = "<tg-emoji emoji-id='547009278509'>⭐</tg-emoji>"
EMOJI_ARROW    = "<tg-emoji emoji-id='519320282341'>👇</tg-emoji>"
EMOJI_WALLET   = "<tg-emoji emoji-id='528997017605'>💳</tg-emoji>"
EMOJI_STARS    = "<tg-emoji emoji-id='534630912179'>⭐</tg-emoji>"
EMOJI_PREMIUM  = "<tg-emoji emoji-id='527402680647'>💎</tg-emoji>"


def get_user_balance(user_id: int) -> float:
    # Пока что возвращает 0, потом подключим БД
    return 0.0


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{EMOJI_WALLET} Пополнить баланс",
                callback_data="top_up"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{EMOJI_STARS} Звёзды",
                callback_data="buy_stars"
            ),
            InlineKeyboardButton(
                text=f"{EMOJI_PREMIUM} Премиум",
                callback_data="buy_premium"
            )
        ]
    ])


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    text = (
        f"{EMOJI_HELLO} Привет, {username}\n\n"
        f"<blockquote>У нас вы можете приобрести TG Stars и TG Premium.</blockquote>\n\n"
        f"<blockquote>Ваш текущий баланс: {balance:.2f} ₽</blockquote>\n\n"
        f"Выбери действие ниже {EMOJI_ARROW}"
    )

    await message.answer(
        text,
        reply_markup=build_main_keyboard(),
        parse_mode="HTML"
    )


# Заглушки для кнопок (пока не работают, просто не падают)
@dp.callback_query(lambda c: c.data in ["top_up", "buy_stars", "buy_premium"])
async def handle_buttons(callback: types.CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=False)


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
  
