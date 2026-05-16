import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PHOTO_FILE_ID = os.getenv("PHOTO_FILE_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2


def get_user_balance(user_id: int) -> float:
    return 0.0


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Пополнить баланс",
                callback_data="top_up",
                icon_custom_emoji_id="5289970176052179025"
            )
        ],
        [
            InlineKeyboardButton(
                text="Звёзды",
                callback_data="buy_stars",
                icon_custom_emoji_id="5346309121794659890"
            ),
            InlineKeyboardButton(
                text="Премиум",
                callback_data="buy_premium",
                icon_custom_emoji_id="5274026806477857971"
            )
        ]
    ])


# Временный обработчик — отправь боту фото, он вернёт file_id
@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    balance = get_user_balance(user.id)

    hello_emoji = "⭐"
    arrow_emoji = "👇"

    greeting = f"{hello_emoji} Привет, {username}\n\n"
    line2     = "У нас вы можете приобрести TG Stars и TG Premium.\n\n"
    line3     = f"Ваш текущий баланс: {balance:.2f} ₽\n\n"
    line4     = f"Выбери действие ниже {arrow_emoji}"

    text = greeting + line2 + line3 + line4

    entities = [
        MessageEntity(type="custom_emoji", offset=0,
                      length=utf16_len(hello_emoji),
                      custom_emoji_id="5470092785094765546"),
        MessageEntity(type="blockquote",
                      offset=utf16_len(greeting),
                      length=utf16_len(line2.rstrip('\n'))),
        MessageEntity(type="blockquote",
                      offset=utf16_len(greeting + line2),
                      length=utf16_len(line3.rstrip('\n'))),
        MessageEntity(type="custom_emoji",
                      offset=utf16_len(greeting + line2 + line3 + "Выбери действие ниже "),
                      length=utf16_len(arrow_emoji),
                      custom_emoji_id="5193202823411546657"),
    ]

    if PHOTO_FILE_ID:
        await message.answer_photo(
            photo=PHOTO_FILE_ID,
            caption=text,
            reply_markup=build_main_keyboard(),
            caption_entities=entities
        )
    else:
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
    
