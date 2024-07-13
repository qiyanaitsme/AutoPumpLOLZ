import logging
import asyncio
import requests
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils import executor
import re

API_TOKEN = ''
IMG_URL = 'https://wallpapers-clan.com/wp-content/uploads/2024/04/dark-anime-girl-with-red-eyes-desktop-wallpaper-preview.jpg'
AUTH_TOKEN = ''
AUTHOR_URL = 'https://lolz.live/qiyanalol/'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

conn = sqlite3.connect('threads.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS threads (id INTEGER PRIMARY KEY, thread_id TEXT UNIQUE)''')
conn.commit()


def bump_thread(thread_id):
    url = f"https://api.zelenka.guru/threads/{thread_id}/bump"
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {AUTH_TOKEN}"
    }
    response = requests.post(url, headers=headers)
    response_data = response.json()
    logger.info(f"Response for thread {thread_id}: {response_data}")
    if response.status_code == 200:
        try:
            error_message = response_data["errors"][0]
            time_match = re.search(r'(\d+)\s+часов\s+(\d+)\s+минут\s+(\d+)\s+секунд', error_message)
            if time_match:
                hours, minutes, seconds = map(int, time_match.groups())
                return (
                    None,
                    f"Согласно вашим правам вы можете поднимать тему раз в 12 часов. Вы должны подождать {hours} часов, {minutes} минут, {seconds} секунд, чтобы поднять тему {thread_id}."
                )
            else:
                return (
                    None,
                    f"Ошибка для темы {thread_id}: {error_message}"
                )
        except (IndexError, KeyError):
            return (
                None,
                f"Вы подняли тему {thread_id}."
            )
    else:
        return (
            None,
            f"Ошибка при поднятии темы {thread_id}: {response.status_code}"
        )


def get_all_threads():
    cursor.execute("SELECT thread_id FROM threads")
    return cursor.fetchall()


def add_thread_to_db(thread_id):
    try:
        cursor.execute("INSERT INTO threads (thread_id) VALUES (?)", (thread_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_thread_from_db(thread_id):
    cursor.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
    conn.commit()


def get_thread_title(thread_id):
    url = f"https://api.zelenka.guru/threads/{thread_id}"
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {AUTH_TOKEN}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        thread_data = response.json()
        return thread_data["thread"]["thread_title"]
    return "Unknown Title"


@dp.callback_query_handler(lambda c: c.data == 'add_thread')
async def process_add_callback(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Введите ID тем через запятую для добавления:")


@dp.message_handler(lambda message: ',' in message.text)
async def add_threads(message: types.Message):
    thread_ids = message.text.split(',')
    added_threads = []
    for thread_id in thread_ids:
        thread_id = thread_id.strip()
        if thread_id.isdigit():
            if add_thread_to_db(thread_id):
                added_threads.append(thread_id)
            else:
                await message.reply(f"Тема с ID {thread_id} уже есть в списке.")
    if added_threads:
        await message.reply(f"Добавлены темы с ID: {', '.join(added_threads)}")
    else:
        await message.reply("Не удалось добавить темы. Убедитесь, что вы ввели корректные ID через запятую.")
    await send_welcome(message)


@dp.callback_query_handler(lambda c: c.data == 'delete_thread')
async def process_delete_callback(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    threads = get_all_threads()
    if not threads:
        await bot.send_message(callback_query.from_user.id, "Список тем пуст.")
        return
    keyboard = InlineKeyboardMarkup()
    for thread in threads:
        keyboard.add(InlineKeyboardButton(thread[0], callback_data=f'delete_{thread[0]}'))
    await bot.send_message(callback_query.from_user.id, "Выберите тему для удаления:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('delete_'))
async def process_delete_thread_callback(callback_query: CallbackQuery):
    thread_id = callback_query.data.split('_')[1]
    delete_thread_from_db(thread_id)
    await bot.answer_callback_query(callback_query.id, text=f"Тема {thread_id} удалена.")
    threads = get_all_threads()
    if threads:
        await process_delete_callback(callback_query)
    else:
        await send_welcome(callback_query.message)


@dp.callback_query_handler(lambda c: c.data == 'list_threads')
async def process_list_callback(callback_query: CallbackQuery):
    threads = get_all_threads()
    if threads:
        thread_info = []
        for thread in threads:
            thread_id = thread[0]
            thread_title = await asyncio.to_thread(get_thread_title, thread_id)
            thread_link = f"{thread_id} - {thread_title} (<a href='https://zelenka.guru/threads/{thread_id}'>Перейти</a>)"
            thread_info.append(thread_link)
            await asyncio.sleep(3)
        await bot.send_message(callback_query.from_user.id, "Список тем:\n" + "\n".join(thread_info),
                               parse_mode=ParseMode.HTML)
    else:
        await bot.send_message(callback_query.from_user.id, "Список тем пуст.")
    await send_welcome(callback_query.message)


@dp.callback_query_handler(lambda c: c.data == 'bump_threads')
async def process_bump_callback(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bump_all_threads(callback_query.from_user.id)
    await send_welcome(callback_query.message)


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=3).add(
        InlineKeyboardButton("Список тем для апа", callback_data='list_threads'),
        InlineKeyboardButton("Добавить тему", callback_data='add_thread'),
        InlineKeyboardButton("Удалить тему", callback_data='delete_thread'),
        InlineKeyboardButton("Поднять темы", callback_data='bump_threads'),
        InlineKeyboardButton("Автор", url=AUTHOR_URL)
    )
    await message.reply_photo(IMG_URL, caption="Привет! Я бот для поднятия тем. Выбери действие:",
                              reply_markup=keyboard)


async def scheduled_bump():
    while True:
        await asyncio.sleep(12 * 3600)
        await bump_all_threads()


async def bump_all_threads(user_id=None):
    threads = get_all_threads()
    if not threads:
        if user_id:
            await bot.send_message(user_id, "Список тем пуст.")
        return

    for thread in threads:
        thread_id = thread[0]
        result = bump_thread(thread_id)
        if user_id:
            await bot.send_message(user_id, result[1])
        await asyncio.sleep(5)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(scheduled_bump())
    executor.start_polling(dp, skip_updates=True)
