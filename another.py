import logging
import asyncio
import aiohttp
import aiosqlite
import json
import telebot
from telebot import types
import re
from typing import List, Tuple, Optional
from dataclasses import dataclass

with open('config.json', 'r', encoding='utf-8') as config_file:
    CONFIG = json.load(config_file)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(CONFIG['bot']['api_token'])

@dataclass
class Thread:
    id: int
    title: str

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    async def init(self):
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute('''CREATE TABLE IF NOT EXISTS threads 
                                   (id INTEGER PRIMARY KEY, thread_id TEXT UNIQUE)''')
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def add_thread(self, thread_id: str) -> bool:
        try:
            await self.conn.execute("INSERT INTO threads (thread_id) VALUES (?)", (thread_id,))
            await self.conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def delete_thread(self, thread_id: str):
        await self.conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
        await self.conn.commit()

    async def get_all_threads(self) -> List[str]:
        async with self.conn.execute("SELECT thread_id FROM threads") as cursor:
            return [row[0] for row in await cursor.fetchall()]

class APIClient:
    def __init__(self, base_url: str, auth_token: str):
        self.base_url = base_url
        self.headers = {
            "accept": "application/json",
            "authorization": f"Bearer {auth_token}"
        }

    async def bump_thread(self, thread_id: str) -> Tuple[Optional[str], str]:
        url = f"{self.base_url}/threads/{thread_id}/bump"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers) as response:
                response_data = await response.json()
                logger.info(f"Response for thread {thread_id}: {response_data}")
                if response.status == 200:
                    try:
                        error_message = response_data["errors"][0]
                        time_match = re.search(r'(\d+)\s+часов\s+(\d+)\s+минут\s+(\d+)\s+секунд', error_message)
                        if time_match:
                            hours, minutes, seconds = map(int, time_match.groups())
                            return (None, f"Согласно вашим правам вы можете поднимать тему раз в 12 часов. "
                                          f"Вы должны подождать {hours} часов, {minutes} минут, {seconds} секунд, "
                                          f"чтобы поднять тему {thread_id}.")
                        else:
                            return (None, f"Ошибка для темы {thread_id}: {error_message}")
                    except (IndexError, KeyError):
                        return (None, f"Вы подняли тему {thread_id}.")
                else:
                    return (None, f"Ошибка при поднятии темы {thread_id}: {response.status}")

    async def get_thread_title(self, thread_id: str) -> str:
        url = f"{self.base_url}/threads/{thread_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    thread_data = await response.json()
                    return thread_data["thread"]["thread_title"]
                return "Unknown Title"

class BumpBot:
    def __init__(self, db_manager: DatabaseManager, api_client: APIClient):
        self.db_manager = db_manager
        self.api_client = api_client

    async def add_threads(self, thread_ids: List[str]) -> List[str]:
        added_threads = []
        for thread_id in thread_ids:
            if thread_id.isdigit() and await self.db_manager.add_thread(thread_id):
                added_threads.append(thread_id)
        return added_threads

    async def delete_thread(self, thread_id: str):
        await self.db_manager.delete_thread(thread_id)

    async def list_threads(self) -> List[Thread]:
        threads = []
        for thread_id in await self.db_manager.get_all_threads():
            title = await self.api_client.get_thread_title(thread_id)
            threads.append(Thread(id=thread_id, title=title))
            await asyncio.sleep(3)
        return threads

    async def bump_all_threads(self) -> List[str]:
        messages = []
        for thread_id in await self.db_manager.get_all_threads():
            _, message = await self.api_client.bump_thread(thread_id)
            messages.append(message)
            await asyncio.sleep(5)
        return messages

db_manager = DatabaseManager(CONFIG['database']['path'])
api_client = APIClient(CONFIG['api']['base_url'], CONFIG['api']['auth_token'])
bump_bot = BumpBot(db_manager, api_client)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        types.InlineKeyboardButton("Список тем для апа", callback_data='list_threads'),
        types.InlineKeyboardButton("Добавить тему", callback_data='add_thread'),
        types.InlineKeyboardButton("Удалить тему", callback_data='delete_thread'),
        types.InlineKeyboardButton("Поднять темы", callback_data='bump_threads'),
        types.InlineKeyboardButton("Автор", url=CONFIG['bot']['author_url'])
    )
    bot.send_photo(message.chat.id, CONFIG['bot']['img_url'],
                   caption="Привет! Я бот для поднятия тем. Выбери действие:",
                   reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == 'add_thread')
def process_add_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.from_user.id, "Введите ID тем через запятую для добавления:")

@bot.message_handler(func=lambda message: ',' in message.text)
def add_threads(message):
    thread_ids = [tid.strip() for tid in message.text.split(',')]
    added_threads = asyncio.run(bump_bot.add_threads(thread_ids))
    if added_threads:
        bot.reply_to(message, f"Добавлены темы с ID: {', '.join(added_threads)}")
    else:
        bot.reply_to(message, "Не удалось добавить темы. Убедитесь, что вы ввели корректные ID через запятую.")
    send_welcome(message)

@bot.callback_query_handler(func=lambda call: call.data == 'delete_thread')
def process_delete_callback(call):
    bot.answer_callback_query(call.id)
    threads = asyncio.run(bump_bot.list_threads())
    if not threads:
        bot.send_message(call.from_user.id, "Список тем пуст.")
        return
    keyboard = types.InlineKeyboardMarkup()
    for thread in threads:
        keyboard.add(types.InlineKeyboardButton(f"{thread.id} - {thread.title}", callback_data=f'delete_{thread.id}'))
    bot.send_message(call.from_user.id, "Выберите тему для удаления:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def process_delete_thread_callback(call):
    thread_id = call.data.split('_')[1]
    asyncio.run(bump_bot.delete_thread(thread_id))
    bot.answer_callback_query(call.id, text=f"Тема {thread_id} удалена.")
    threads = asyncio.run(bump_bot.list_threads())
    if threads:
        process_delete_callback(call)
    else:
        send_welcome(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'list_threads')
def process_list_callback(call):
    threads = asyncio.run(bump_bot.list_threads())
    if threads:
        thread_info = [f"{thread.id} - {thread.title} (<a href='https://zelenka.guru/threads/{thread.id}'>Перейти</a>)"
                       for thread in threads]
        bot.send_message(call.from_user.id, "Список тем:\n" + "\n".join(thread_info), parse_mode='HTML')
    else:
        bot.send_message(call.from_user.id, "Список тем пуст.")
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'bump_threads')
def process_bump_callback(call):
    bot.answer_callback_query(call.id)
    messages = asyncio.run(bump_bot.bump_all_threads())
    for message in messages:
        bot.send_message(call.from_user.id, message)
    send_welcome(call.message)

async def scheduled_bump():
    while True:
        await asyncio.sleep(CONFIG['scheduling']['bump_interval_hours'] * 3600)
        await bump_bot.bump_all_threads()

async def main():
    await db_manager.init()
    asyncio.create_task(scheduled_bump())
    await bot.polling(none_stop=True)

if __name__ == '__main__':
    asyncio.run(main())
