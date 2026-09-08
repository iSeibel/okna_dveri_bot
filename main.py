import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re
import json

import aiosqlite
import schedule
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from bs4 import BeautifulSoup
import aiohttp
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
AMOCRM_DOMAIN = os.getenv("AMOCRM_DOMAIN", "your_domain.amocrm.ru")
AMOCRM_CLIENT_ID = os.getenv("AMOCRM_CLIENT_ID", "your_client_id")
AMOCRM_CLIENT_SECRET = os.getenv("AMOCRM_CLIENT_SECRET", "your_client_secret")
AMOCRM_REDIRECT_URI = os.getenv("AMOCRM_REDIRECT_URI", "https://localhost")
AMOCRM_ACCESS_TOKEN = os.getenv("AMOCRM_ACCESS_TOKEN", "")
AMOCRM_REFRESH_TOKEN = os.getenv("AMOCRM_REFRESH_TOKEN", "")

# ID администраторов
def get_admin_ids():
    """Получаем список ID администраторов из .env файла"""
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    logging.info(f"ADMIN_IDS из .env: '{admin_ids_str}'")
    
    admin_ids = []
    if admin_ids_str:
        for id_str in re.split(r'[,\s]+', admin_ids_str):
            id_str = id_str.strip()
            if id_str and id_str.isdigit():
                admin_ids.append(int(id_str))
    
    logging.info(f"Распознанные ID администраторов: {admin_ids}")
    return admin_ids

ADMIN_IDS = get_admin_ids()

def is_admin(user_id: int) -> bool:
    """Проверяем, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ ДЛЯ FSM ---
class UserStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_amount = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_consultant_message = State()

# --- БАЗА ДАННЫХ ---
DB_PATH = "bot_database.db"

# Города Беларуси
CITIES = {
    "minsk": "🏙 Минск",
    "grodno": "🏙 Гродно",
    "brest": "🏙 Брест",
    "vitebsk": "🏙 Витебск",
    "gomel": "🏙 Гомель",
    "mogilev": "🏙 Могилев"
}

# --- ФУНКЦИИ ДЛЯ AMOCRM ---
def update_env_file(key: str, value: str):
    """Обновляем значение в .env файле"""
    try:
        with open('.env', 'r') as f:
            lines = f.readlines()
        
        with open('.env', 'w') as f:
            for line in lines:
                if line.startswith(f"{key}="):
                    f.write(f"{key}={value}\n")
                else:
                    f.write(line)
        logging.info(f"Обновлен {key} в .env файле")
    except Exception as e:
        logging.error(f"Ошибка обновления .env файла: {e}")

async def refresh_amocrm_token():
    """Обновление access token AmoCRM"""
    global AMOCRM_ACCESS_TOKEN, AMOCRM_REFRESH_TOKEN
    
    if not AMOCRM_REFRESH_TOKEN:
        logging.warning("Не настроен refresh token для AmoCRM")
        return False
    
async def send_welcome_message_with_button():
    """Отправляет приветственное сообщение с кнопкой Старт"""
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 НАЧАТЬ",
                    url=f"https://t.me/{bot_username}?start=start"
                )
            ]
        ])
        
        text = """
👋 **Добро пожаловать!**

Использовать помощника.

Он поможет вам:
📞 Заказать звонок консультанта
💬 Начать переписку с консультантом
💰 Узнать актуальные курсы валют
❓ Изучить ответы на частые вопросы
📞 Получить наши контакты 
"""
        
        await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        logging.info("Приветственное сообщение с кнопкой отправлено")
        
    except Exception as e:
        logging.error(f"Ошибка отправки кнопки: {e}")   
    try:
        url = f"https://{AMOCRM_DOMAIN}/oauth2/access_token"
        
        data = {
            "client_id": AMOCRM_CLIENT_ID,
            "client_secret": AMOCRM_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": AMOCRM_REFRESH_TOKEN,
            "redirect_uri": AMOCRM_REDIRECT_URI
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    AMOCRM_ACCESS_TOKEN = result['access_token']
                    if 'refresh_token' in result:
                        AMOCRM_REFRESH_TOKEN = result['refresh_token']
                    
                    # Обновляем .env файл
                    update_env_file('AMOCRM_ACCESS_TOKEN', AMOCRM_ACCESS_TOKEN)
                    update_env_file('AMOCRM_REFRESH_TOKEN', AMOCRM_REFRESH_TOKEN)
                    
                    logging.info("Токен AmoCRM успешно обновлен")
                    return True
                else:
                    logging.error(f"Ошибка обновления токена: {response.status}")
                    logging.error(await response.text())
                    return False
    except Exception as e:
        logging.error(f"Ошибка при обновлении токена: {e}")
        return False

async def create_amocrm_lead(name: str, phone: str, user_data: Dict) -> Optional[str]:
    """Создаем сделку в AmoCRM"""
    global AMOCRM_ACCESS_TOKEN
    
    if not AMOCRM_ACCESS_TOKEN:
        logging.warning("Не настроен токен AmoCRM. Пропускаем создание сделки.")
        return None
    
    try:
        headers = {
            'Authorization': f'Bearer {AMOCRM_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Создаем контакт
        contact_data = [{
            "name": name,
            "custom_fields_values": [
                {
                    "field_code": "PHONE",
                    "values": [{"value": phone, "enum_code": "WORK"}]
                },
                {
                    "field_code": "EMAIL",
                    "values": [{"value": f"telegram_{user_data.get('user_id', '')}@telegram.com"}]
                }
            ]
        }]
        
        async with aiohttp.ClientSession() as session:
            # Создаем контакт
            async with session.post(
                f'https://{AMOCRM_DOMAIN}/api/v4/contacts',
                headers=headers,
                json=contact_data
            ) as response:
                if response.status in [200, 201]:
                    contact_result = await response.json()
                    contact_id = contact_result['_embedded']['contacts'][0]['id']
                    
                    # Создаем сделку
                    lead_data = [{
                        "name": f"Заявка с Telegram бота - {name}",
                        "contacts_id": [contact_id],
                        "custom_fields_values": [
                            {
                                "field_code": "PHONE",
                                "values": [{"value": phone}]
                            }
                        ]
                    }]
                    
                    async with session.post(
                        f'https://{AMOCRM_DOMAIN}/api/v4/leads',
                        headers=headers,
                        json=lead_data
                    ) as lead_response:
                        if lead_response.status in [200, 201]:
                            lead_result = await lead_response.json()
                            lead_id = lead_result['_embedded']['leads'][0]['id']
                            
                            logging.info(f"Создана сделка в AmoCRM с ID: {lead_id}")
                            return str(lead_id)
                        else:
                            logging.error(f"Ошибка создания сделки: {lead_response.status}")
                            logging.error(await lead_response.text())
                            return None
                            
                elif response.status == 401:
                    # Токен истек, пробуем обновить
                    logging.warning("Токен AmoCRM истек, пробуем обновить")
                    if await refresh_amocrm_token():
                        # Повторяем запрос
                        return await create_amocrm_lead(name, phone, user_data)
                    else:
                        return None
                else:
                    logging.error(f"Ошибка создания контакта: {response.status}")
                    logging.error(await response.text())
                    return None
                    
    except Exception as e:
        logging.error(f"Ошибка при работе с AmoCRM: {e}")
        return None

async def init_db():
    """Инициализация базы данных с проверкой структуры"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Создаем таблицу users
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP
                )
            """)
            
            # Создаем таблицу user_settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    receive_currency_updates BOOLEAN DEFAULT TRUE,
                    preferred_currency TEXT DEFAULT 'USD',
                    preferred_bank TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Создаем таблицу callback_requests
            await db.execute("""
                CREATE TABLE IF NOT EXISTS callback_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    phone_number TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'new',
                    amocrm_lead_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Создаем таблицу chat_messages
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_text TEXT,
                    direction TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Создаем таблицу chat_sessions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Проверяем существование и структуру таблицы currency_rates
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='currency_rates'"
            )
            table_exists = await cursor.fetchone()
            
            if table_exists:
                cursor = await db.execute("PRAGMA table_info(currency_rates)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'bank_name' not in column_names:
                    await db.execute("DROP TABLE IF EXISTS currency_rates")
                    table_exists = None
                    logging.info("Старая таблица currency_rates удалена")
            
            if not table_exists:
                await db.execute("""
                    CREATE TABLE currency_rates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        currency TEXT,
                        bank_name TEXT,
                        buy_rate REAL,
                        sell_rate REAL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logging.info("Создана новая таблица currency_rates")
            
            # Создаем индексы
            await db.execute("CREATE INDEX IF NOT EXISTS idx_currency_rates_currency ON currency_rates(currency)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_currency_rates_updated ON currency_rates(updated_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_callback_requests_user ON callback_requests(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_callback_requests_created ON callback_requests(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_sessions_started ON chat_sessions(started_at)")
            
            await db.commit()
            logging.info("База данных успешно инициализирована")
            
    except Exception as e:
        logging.error(f"Ошибка при инициализации БД: {e}")
        raise

async def save_user(user_id: int, username: str, first_name: str, last_name: str):
    """Сохраняем пользователя в БД"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_activity)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, username, first_name, last_name))
            await db.commit()
    except Exception as e:
        logging.error(f"Ошибка при сохранении пользователя: {e}")

async def update_user_activity(user_id: int):
    """Обновляем время последней активности"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            await db.commit()
    except Exception as e:
        logging.error(f"Ошибка при обновлении активности: {e}")

async def save_callback_request(user_id: int, username: str, first_name: str, last_name: str, phone_number: str):
    """Сохраняем заявку на обратный звонок"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO callback_requests (user_id, username, first_name, last_name, phone_number)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, first_name, last_name, phone_number))
            await db.commit()
            return cursor.lastrowid
    except Exception as e:
        logging.error(f"Ошибка при сохранении заявки: {e}")
        return None

async def save_chat_message(user_id: int, message_text: str, direction: str):
    """Сохраняем сообщение чата"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO chat_messages (user_id, message_text, direction)
                VALUES (?, ?, ?)
            """, (user_id, message_text, direction))
            await db.commit()
    except Exception as e:
        logging.error(f"Ошибка при сохранении сообщения: {e}")

async def start_chat_session(user_id: int) -> int:
    """Начинаем новую сессию чата"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO chat_sessions (user_id) VALUES (?)
            """, (user_id,))
            await db.commit()
            return cursor.lastrowid
    except Exception as e:
        logging.error(f"Ошибка при создании сессии чата: {e}")
        return None

async def end_chat_session(session_id: int):
    """Завершаем сессию чата"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE chat_sessions SET ended_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (session_id,))
            await db.commit()
    except Exception as e:
        logging.error(f"Ошибка при завершении сессии чата: {e}")

# --- ФУНКЦИИ ДЛЯ СТАТИСТИКИ ---
async def get_bot_statistics(period: str) -> Dict:
    """Получаем статистику использования бота за указанный период"""
    now = datetime.now()
    
    if period == 'day':
        start_date = now - timedelta(days=1)
    elif period == 'week':
        start_date = now - timedelta(weeks=1)
    elif period == 'month':
        start_date = now - timedelta(days=30)
    elif period == '3months':
        start_date = now - timedelta(days=90)
    elif period == '6months':
        start_date = now - timedelta(days=180)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:
        start_date = now - timedelta(days=7)
    
    start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
    
    stats = {
        'period': period,
        'start_date': start_date_str,
        'total_users': 0,
        'new_users': 0,
        'active_users': 0,
        'callback_requests': 0,
        'chat_sessions': 0,
        'total_messages': 0,
        'user_messages': 0,
    }
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Общее количество пользователей
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            stats['total_users'] = (await cursor.fetchone())[0]
            
            # Новые пользователи за период
            cursor = await db.execute("""
                SELECT COUNT(*) FROM users 
                WHERE created_at >= ?
            """, (start_date_str,))
            stats['new_users'] = (await cursor.fetchone())[0]
            
            # Активные пользователи за период
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT user_id) FROM users 
                WHERE last_activity >= ?
            """, (start_date_str,))
            stats['active_users'] = (await cursor.fetchone())[0]
            
            # Заявки на звонок за период
            cursor = await db.execute("""
                SELECT COUNT(*) FROM callback_requests 
                WHERE created_at >= ?
            """, (start_date_str,))
            stats['callback_requests'] = (await cursor.fetchone())[0]
            
            # Сессии чатов за период
            cursor = await db.execute("""
                SELECT COUNT(*) FROM chat_sessions 
                WHERE started_at >= ?
            """, (start_date_str,))
            stats['chat_sessions'] = (await cursor.fetchone())[0]
            
            # Сообщения в чатах за период
            cursor = await db.execute("""
                SELECT COUNT(*) FROM chat_messages 
                WHERE created_at >= ?
            """, (start_date_str,))
            stats['total_messages'] = (await cursor.fetchone())[0]
            
            # Сообщения от пользователей за период
            cursor = await db.execute("""
                SELECT COUNT(*) FROM chat_messages 
                WHERE created_at >= ? AND direction = 'from_user'
            """, (start_date_str,))
            stats['user_messages'] = (await cursor.fetchone())[0]
            
    except Exception as e:
        logging.error(f"Ошибка при получении статистики: {e}")
    
    return stats

# --- ПАРСИНГ КУРСОВ ВАЛЮТ ---
async def parse_currency_rates() -> Dict[str, Dict]:
    """Парсим курсы валют с сайта myfin.by"""
    urls = {
        "USD": "https://myfin.by/currency/minsk/usd",
        "EUR": "https://myfin.by/currency/minsk/eur",
        "RUB": "https://myfin.by/currency/minsk/rub"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    }
    
    rates = {"USD": {"banks": []}, "EUR": {"banks": []}, "RUB": {"banks": []}}
    
    try:
        async with aiohttp.ClientSession() as session:
            for currency, url in urls.items():
                try:
                    logging.info(f"Парсим {currency} с {url}")
                    
                    async with session.get(url, headers=headers, timeout=15) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            tables = soup.find_all('table')
                            for table in tables:
                                rows = table.find_all('tr')
                                for row in rows[1:]:
                                    cells = row.find_all(['td', 'th'])
                                    if len(cells) >= 3:
                                        process_bank_row(cells, currency, rates)
                            
                            bank_divs = soup.find_all('div', class_=re.compile(r'bank|row|rate', re.I))
                            for div in bank_divs:
                                name_elem = div.find(class_=re.compile(r'name|bank|title', re.I))
                                buy_elem = div.find(class_=re.compile(r'buy|bid|purchase', re.I))
                                sell_elem = div.find(class_=re.compile(r'sell|ask|sale', re.I))
                                
                                if name_elem and buy_elem and sell_elem:
                                    bank_name = name_elem.get_text(strip=True)
                                    buy_text = buy_elem.get_text(strip=True)
                                    sell_text = sell_elem.get_text(strip=True)
                                    
                                    buy_match = re.search(r'(\d+[.,]\d+)', buy_text)
                                    sell_match = re.search(r'(\d+[.,]\d+)', sell_text)
                                    
                                    if buy_match and sell_match and bank_name:
                                        try:
                                            buy_rate = float(buy_match.group(1).replace(',', '.'))
                                            sell_rate = float(sell_match.group(1).replace(',', '.'))
                                            
                                            if buy_rate > 0 and sell_rate > 0:
                                                add_bank_rate(rates, currency, bank_name, buy_rate, sell_rate)
                                        except ValueError:
                                            continue
                            
                            currency_rows = soup.find_all('tr', class_=re.compile(r'row|bank|rate', re.I))
                            for row in currency_rows:
                                cells = row.find_all(['td', 'th'])
                                if len(cells) >= 3:
                                    process_bank_row(cells, currency, rates)
                            
                            logging.info(f"Для {currency} найдено банков: {len(rates[currency]['banks'])}")
                            
                            if not rates[currency]["banks"]:
                                logging.warning(f"Не найдены данные для {currency}, пробуем JSON")
                                json_data = await parse_myfin_json(html, currency)
                                if json_data.get("banks"):
                                    rates[currency] = json_data
                        else:
                            logging.error(f"Ошибка {response.status} для {currency}")
                            
                except Exception as e:
                    logging.error(f"Ошибка парсинга {currency}: {e}")
                    continue
                
                await asyncio.sleep(1)
        
        calculate_best_rates(rates)
        return rates
        
    except Exception as e:
        logging.error(f"Общая ошибка парсинга: {e}")
        return rates

def process_bank_row(cells, currency: str, rates: Dict):
    """Обработка строки таблицы с данными банка"""
    try:
        bank_cell = cells[0].get_text(strip=True)
        buy_cell = cells[1].get_text(strip=True)
        sell_cell = cells[2].get_text(strip=True)
        
        if any(word in bank_cell.upper() for word in ['БАНК', 'НАЗВАНИЕ', 'BANK', 'NAME']):
            return
        
        bank_name = re.sub(r'\s+', ' ', bank_cell)
        bank_name = re.sub(r'[^\w\s\-\.\(\)]', '', bank_name).strip()
        
        if not bank_name:
            return
        
        buy_match = re.search(r'(\d+[.,]\d+)', buy_cell)
        sell_match = re.search(r'(\d+[.,]\d+)', sell_cell)
        
        if buy_match and sell_match:
            buy_rate = float(buy_match.group(1).replace(',', '.'))
            sell_rate = float(sell_match.group(1).replace(',', '.'))
            
            if buy_rate > 0 and sell_rate > 0 and buy_rate < 1000:
                add_bank_rate(rates, currency, bank_name, buy_rate, sell_rate)
    except Exception as e:
        logging.debug(f"Ошибка обработки строки: {e}")

def add_bank_rate(rates: Dict, currency: str, bank_name: str, buy_rate: float, sell_rate: float):
    """Добавляем курс банка с проверкой на дубликаты"""
    if currency not in rates:
        rates[currency] = {"banks": []}
    
    for bank in rates[currency]["banks"]:
        if bank["bank"] == bank_name:
            if buy_rate > bank["buy"]:
                bank["buy"] = buy_rate
            if sell_rate < bank["sell"]:
                bank["sell"] = sell_rate
            return
    
    rates[currency]["banks"].append({
        "bank": bank_name,
        "buy": buy_rate,
        "sell": sell_rate
    })

def calculate_best_rates(rates: Dict):
    """Вычисляем лучшие курсы для каждой валюты"""
    for currency, data in rates.items():
        if data.get("banks"):
            data["banks"].sort(key=lambda x: x["buy"], reverse=True)
            
            best_buy = data["banks"][0]
            best_sell = min(data["banks"], key=lambda x: x["sell"])
            
            data["best_buy"] = best_buy["buy"]
            data["best_sell"] = best_sell["sell"]
            data["best_buy_bank"] = best_buy["bank"]
            data["best_sell_bank"] = best_sell["bank"]
            
            logging.info(f"{currency}: найдено {len(data['banks'])} банков")
        else:
            data["best_buy"] = 0
            data["best_sell"] = 0
            data["best_buy_bank"] = "Нет данных"
            data["best_sell_bank"] = "Нет данных"
            logging.warning(f"{currency}: банки не найдены")

async def parse_myfin_json(html: str, currency: str) -> Dict:
    """Альтернативный парсинг через JSON данные на странице"""
    result = {"banks": []}
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        scripts = soup.find_all('script')
        
        for script in scripts:
            script_text = script.string
            if script_text:
                json_matches = re.findall(r'\{[^{}]*\}', script_text)
                
                for json_str in json_matches:
                    try:
                        data = json.loads(json_str)
                        
                        if isinstance(data, dict) and 'banks' in data:
                            for bank in data['banks']:
                                if isinstance(bank, dict):
                                    bank_name = bank.get('name', bank.get('bank_name', ''))
                                    buy_rate = bank.get('buy_rate', bank.get('buy', 0))
                                    sell_rate = bank.get('sell_rate', bank.get('sell', 0))
                                    
                                    if bank_name and buy_rate and sell_rate:
                                        try:
                                            result["banks"].append({
                                                "bank": str(bank_name),
                                                "buy": float(buy_rate),
                                                "sell": float(sell_rate)
                                            })
                                        except (ValueError, TypeError):
                                            continue
                    except json.JSONDecodeError:
                        continue
                        
    except Exception as e:
        logging.error(f"Ошибка парсинга JSON для {currency}: {e}")
    
    return result

async def get_currency_rates() -> Dict[str, Dict]:
    """Получаем курсы с несколькими вариантами парсинга"""
    rates = await parse_currency_rates()
    
    missing_currencies = []
    for currency in ["USD", "EUR", "RUB"]:
        if currency not in rates or not rates[currency].get("banks"):
            missing_currencies.append(currency)
    
    if missing_currencies:
        logging.warning(f"Недостающие валюты: {missing_currencies}")
        db_rates = await get_currency_rates_from_db()
        
        for currency in missing_currencies:
            if currency in db_rates and db_rates[currency].get("banks"):
                rates[currency] = db_rates[currency]
                logging.info(f"Восстановлены данные для {currency} из БД")
    
    calculate_best_rates(rates)
    return rates

async def save_currency_rates(rates: Dict[str, Dict]):
    """Сохраняем курсы в БД"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM currency_rates")
            
            for currency, data in rates.items():
                if "banks" in data:
                    for bank_data in data["banks"][:10]:
                        await db.execute("""
                            INSERT INTO currency_rates (currency, bank_name, buy_rate, sell_rate)
                            VALUES (?, ?, ?, ?)
                        """, (currency, bank_data["bank"], bank_data["buy"], bank_data["sell"]))
            
            await db.commit()
            logging.info("Курсы валют сохранены в БД")
    except Exception as e:
        logging.error(f"Ошибка при сохранении курсов: {e}")

async def get_currency_rates_from_db() -> Dict[str, Dict]:
    """Получаем последние курсы из БД"""
    rates = {"USD": {"banks": []}, "EUR": {"banks": []}, "RUB": {"banks": []}}
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT currency, bank_name, buy_rate, sell_rate 
                FROM currency_rates 
                ORDER BY currency, buy_rate DESC
            """)
            rows = await cursor.fetchall()
            
            for row in rows:
                currency, bank_name, buy_rate, sell_rate = row
                if currency in rates:
                    rates[currency]["banks"].append({
                        "bank": bank_name,
                        "buy": buy_rate,
                        "sell": sell_rate
                    })
            
            calculate_best_rates(rates)
    
    except Exception as e:
        logging.error(f"Ошибка при получении курсов из БД: {e}")
    
    return rates

async def parse_currency_rates_city(currency: str, city: str = "minsk") -> Dict:
    """Парсим курсы валют для конкретного города"""
    url = f"https://myfin.by/currency/{city}/{currency.lower()}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    }
    
    result = {"banks": []}
    
    try:
        logging.info(f"Парсим {currency} в городе {city} с {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    tables = soup.find_all('table')
                    for table in tables:
                        rows = table.find_all('tr')
                        for row in rows[1:]:
                            cells = row.find_all(['td', 'th'])
                            if len(cells) >= 3:
                                temp_rates = {currency: result}
                                process_bank_row(cells, currency, temp_rates)
                    
                    bank_divs = soup.find_all('div', class_=re.compile(r'bank|row|rate', re.I))
                    for div in bank_divs:
                        name_elem = div.find(class_=re.compile(r'name|bank|title', re.I))
                        buy_elem = div.find(class_=re.compile(r'buy|bid|purchase', re.I))
                        sell_elem = div.find(class_=re.compile(r'sell|ask|sale', re.I))
                        
                        if name_elem and buy_elem and sell_elem:
                            bank_name = name_elem.get_text(strip=True)
                            buy_text = buy_elem.get_text(strip=True)
                            sell_text = sell_elem.get_text(strip=True)
                            
                            buy_match = re.search(r'(\d+[.,]\d+)', buy_text)
                            sell_match = re.search(r'(\d+[.,]\d+)', sell_text)
                            
                            if buy_match and sell_match and bank_name:
                                try:
                                    buy_rate = float(buy_match.group(1).replace(',', '.'))
                                    sell_rate = float(sell_match.group(1).replace(',', '.'))
                                    
                                    if buy_rate > 0 and sell_rate > 0:
                                        add_bank_rate({currency: result}, currency, bank_name, buy_rate, sell_rate)
                                except ValueError:
                                    continue
                    
                    currency_rows = soup.find_all('tr', class_=re.compile(r'row|bank|rate', re.I))
                    for row in currency_rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 3:
                            temp_rates = {currency: result}
                            process_bank_row(cells, currency, temp_rates)
                    
                    logging.info(f"Для {currency} в {city} найдено банков: {len(result['banks'])}")
                    
                    if not result["banks"]:
                        logging.warning(f"Не найдены данные для {currency} в {city}, пробуем JSON")
                        json_data = await parse_myfin_json(html, currency)
                        if json_data.get("banks"):
                            result = json_data
                    
                else:
                    logging.error(f"Ошибка {response.status} для {currency} в {city}")
                    
    except Exception as e:
        logging.error(f"Ошибка парсинга {currency} в {city}: {e}")
    
    if result["banks"]:
        result["banks"].sort(key=lambda x: x["buy"], reverse=True)
    
    return result

async def get_top5_banks_for_city(currency: str, city: str) -> Dict:
    """Получаем топ-5 банков для конкретного города"""
    rates = await parse_currency_rates_city(currency, city)
    
    if rates.get("banks"):
        top5 = rates["banks"][:5]
        
        return {
            "currency": currency,
            "city": city,
            "banks": top5
        }
    
    return {}

# --- КЛАВИАТУРЫ ---
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура с кнопками для обычных пользователей"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Заказать звонок"), KeyboardButton(text="💬 Начать переписку")],
            [KeyboardButton(text="💰 Курсы валют")],
            [KeyboardButton(text="❓ Частые вопросы"), KeyboardButton(text="📞 Наши контакты")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )
    return keyboard

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для администраторов"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Заказать звонок"), KeyboardButton(text="💬 Начать переписку")],
            [KeyboardButton(text="💰 Курсы валют"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="❓ Частые вопросы"), KeyboardButton(text="📞 Наши контакты")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )
    return keyboard

def get_statistics_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора периода статистики"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 День", callback_data="stats_day"),
            InlineKeyboardButton(text="📅 Неделя", callback_data="stats_week"),
            InlineKeyboardButton(text="📅 Месяц", callback_data="stats_month")
        ],
        [
            InlineKeyboardButton(text="📅 3 месяца", callback_data="stats_3months"),
            InlineKeyboardButton(text="📅 6 месяцев", callback_data="stats_6months"),
            InlineKeyboardButton(text="📅 Год", callback_data="stats_year")
        ]
    ])
    return keyboard

def get_currency_keyboard() -> InlineKeyboardMarkup:
    """Инлайн клавиатура для выбора валюты"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 Доллар", callback_data="currency_USD"),
            InlineKeyboardButton(text="💶 Евро", callback_data="currency_EUR"),
            InlineKeyboardButton(text="🇷🇺 Рубль РФ", callback_data="currency_RUB")
        ],
        [
            InlineKeyboardButton(text="🏦 Лучшие курсы", callback_data="best_rates"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_rates")
        ]
    ])
    return keyboard

def get_bank_keyboard(currency: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора банка"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 Все банки", callback_data=f"all_banks_{currency}"),
            InlineKeyboardButton(text="🔝 Топ-5 по городам", callback_data=f"top5_cities_{currency}")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_currencies")
        ]
    ])
    return keyboard

def get_city_keyboard_for_currency(currency: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора города с учетом валюты"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏙 Минск", callback_data=f"city_top_{currency}_minsk"),
            InlineKeyboardButton(text="🏙 Гродно", callback_data=f"city_top_{currency}_grodno"),
            InlineKeyboardButton(text="🏙 Брест", callback_data=f"city_top_{currency}_brest")
        ],
        [
            InlineKeyboardButton(text="🏙 Витебск", callback_data=f"city_top_{currency}_vitebsk"),
            InlineKeyboardButton(text="🏙 Гомель", callback_data=f"city_top_{currency}_gomel"),
            InlineKeyboardButton(text="🏙 Могилев", callback_data=f"city_top_{currency}_mogilev")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_currencies")
        ]
    ])
    return keyboard

def get_consultant_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для чата с консультантом"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📞 Заказать звонок", callback_data="request_callback"),
            InlineKeyboardButton(text="❌ Завершить чат", callback_data="end_chat")
        ]
    ])
    return keyboard

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Обработчик команды /start"""
    user = message.from_user
    await save_user(user.id, user.username, user.first_name, user.last_name)
    
    logging.info(f"Пользователь {user.first_name} (ID: {user.id}) запустил бота")
    
    welcome_text = f"""
👋 Здравствуйте, {user.first_name}!

🔍 **Позвольте вам помочь:**
- 📞 Заказать звонок
- 💬 Начать переписку с консультантом
- 💰 Показывать актуальные курсы валют
- ❓ Ответы на частые вопросы
- 📞 Наши контакты
"""

    if is_admin(user.id):
        welcome_text += "\n🔐 **У вас есть права администратора!**\n"
        welcome_text += "📊 Доступна функция статистики\n"
        await message.answer(welcome_text, reply_markup=get_admin_keyboard())
    else:
        await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("myid"))
async def get_my_id(message: types.Message):
    """Показывает ID пользователя"""
    user = message.from_user
    is_admin_user = is_admin(user.id)
    
    text = f"👤 Ваш ID: {user.id}\n"
    text += f"👑 Статус: {'Администратор' if is_admin_user else 'Пользователь'}"
    
    await message.answer(text)

@dp.message(Command("get_username"))
async def get_bot_username(message: types.Message):
    """Показывает username бота"""
    bot_info = await bot.get_me()
    await message.answer(f"Username бота: @{bot_info.username}")

@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
📚 **Доступные команды:**

/start - Начать работу с ботом
/rates - Показать курсы валют
/help - Показать эту справку
/myid - Показать ваш ID

**Основные функции:**
📞 Заказать звонок - оставьте заявку
💬 Начать переписку - чат с консультантом
💰 Курсы валют - актуальные курсы
❓ Частые вопросы - ответы на популярные вопросы
📞 Наши контакты - контактная информация
"""
    await message.answer(help_text, parse_mode="Markdown")

@dp.message(Command("rates"))
async def rates_command(message: types.Message):
    """Обработчик команды /rates"""
    await update_user_activity(message.from_user.id)
    await show_rates(message)

@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    """Обработчик команды /stats для администраторов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    
    await message.answer(
        "📊 **Статистика использования бота**\n\n"
        "Выберите период для просмотра статистики:",
        reply_markup=get_statistics_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("send_button"))
async def send_button_command(message: types.Message):
    """Команда для отправки кнопки в канал (только для админов)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await send_welcome_message_with_button()
    await message.answer("✅ Кнопка отправлена в канал!")

# --- ОБРАБОТЧИКИ ДЛЯ ЗАКАЗА ЗВОНКА ---
@dp.message(lambda message: message.text == "📞 Заказать звонок")
async def button_callback_request(message: types.Message, state: FSMContext):
    """Обработчик кнопки заказа звонка"""
    await update_user_activity(message.from_user.id)
    
    await message.answer(
        "📞 **Заказ звонка**\n\n"
        "Пожалуйста, укажите ваше имя:",
        parse_mode="Markdown"
    )
    
    await state.set_state(UserStates.waiting_for_name)

@dp.callback_query(lambda c: c.data == 'request_callback')
async def callback_request_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик callback для заказа звонка"""
    await callback_query.message.answer(
        "📞 **Заказ звонка**\n\n"
        "Пожалуйста, укажите ваше имя:",
        parse_mode="Markdown"
    )
    
    await state.set_state(UserStates.waiting_for_name)
    await callback_query.answer()

@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Обработка введенного имени"""
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Имя должно содержать минимум 2 символа. Попробуйте еще раз:")
        return
    
    await state.update_data(name=name)
    
    contact_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
            [KeyboardButton(text="⌨️ Ввести вручную")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(
        f"Отлично, {name}! Теперь укажите ваш номер телефона.\n\n"
        "Вы можете нажать кнопку ниже, чтобы отправить ваш номер автоматически, "
        "или ввести его вручную в формате: +375 XX XXX-XX-XX",
        reply_markup=contact_keyboard
    )
    
    await state.set_state(UserStates.waiting_for_phone)

@dp.message(UserStates.waiting_for_phone, lambda message: message.contact is not None)
async def process_contact(message: types.Message, state: FSMContext):
    """Обработка полученного контакта"""
    if message.contact:
        phone = message.contact.phone_number
        phone_clean = re.sub(r'[\s\-\(\)]', '', phone)
        
        if not phone_clean.startswith('375'):
            if phone_clean.startswith('+'):
                phone_clean = '375' + phone_clean[1:]
            elif phone_clean.startswith('80'):
                phone_clean = '375' + phone_clean[2:]
            else:
                phone_clean = '375' + phone_clean
        
        if not re.match(r'^375\d{9}$', phone_clean):
            await message.answer(
                "❌ К сожалению, ваш номер не похож на белорусский. "
                "Пожалуйста, введите номер вручную в формате: +375 XX XXX-XX-XX"
            )
            return
        
        await complete_callback_request(message, state, phone_clean)

@dp.message(UserStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    """Обработка введенного телефона вручную"""
    if message.text == "⌨️ Ввести вручную":
        await message.answer(
            "Пожалуйста, введите ваш номер телефона в формате:\n"
            "+375 XX XXX-XX-XX\n\n"
            "Например: +375 29 123-45-67",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return
    
    phone = message.text.strip()
    phone_clean = re.sub(r'[\s\-\(\)]', '', phone)
    
    if phone_clean.startswith('0'):
        phone_clean = '375' + phone_clean[1:]
    elif phone_clean.startswith('80'):
        phone_clean = '375' + phone_clean[2:]
    elif phone_clean.startswith('+'):
        phone_clean = phone_clean[1:]
    elif phone_clean.startswith('375'):
        pass
    elif len(phone_clean) == 9:
        phone_clean = '375' + phone_clean
    elif len(phone_clean) == 7:
        await message.answer(
            "❌ Пожалуйста, укажите полный номер с кодом оператора.\n"
            "Например: +375 29 123-45-67"
        )
        return
    else:
        await message.answer(
            "❌ Неверный формат телефона. Пожалуйста, используйте формат:\n"
            "+375 XX XXX-XX-XX\n\n"
        )
        return
    
    if not re.match(r'^375\d{9}$', phone_clean):
        await message.answer(
            "❌ Неверный формат телефона. Пожалуйста, используйте формат:\n"
            "+375 XX XXX-XX-XX"
        )
        return
    
    await complete_callback_request(message, state, phone_clean)

async def complete_callback_request(message: types.Message, state: FSMContext, phone_clean: str):
    """Завершение обработки заявки на звонок"""
    user_data = await state.get_data()
    name = user_data.get('name', message.from_user.first_name)
    
    user = message.from_user
    
    request_id = await save_callback_request(
        user.id,
        user.username,
        name,
        user.last_name or "",
        phone_clean
    )
    
    # Отправляем в AmoCRM
    amocrm_lead_id = await create_amocrm_lead(
        name,
        phone_clean,
        {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name
        }
    )
    
    if request_id and amocrm_lead_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE callback_requests 
                SET amocrm_lead_id = ?, status = 'sent_to_amocrm'
                WHERE id = ?
            """, (amocrm_lead_id, request_id))
            await db.commit()
    
    await message.answer(
        f"✅ Спасибо за заявку! Консультант свяжется с вами в ближайшее время.",
        reply_markup=get_admin_keyboard() if is_admin(user.id) else get_main_keyboard()
    )
    
    logging.info(f"Создана заявка на звонок: {name}, {phone_clean}, user_id: {user.id}")
    
    await state.clear()

# --- ОБРАБОТЧИКИ ДЛЯ ЧАТА С КОНСУЛЬТАНТОМ ---
@dp.message(lambda message: message.text == "💬 Начать переписку")
async def button_start_chat(message: types.Message, state: FSMContext):
    """Обработчик кнопки начала переписки"""
    await update_user_activity(message.from_user.id)
    
    session_id = await start_chat_session(message.from_user.id)
    await state.update_data(chat_session_id=session_id)
    
    await message.answer(
        "💬 **Чат с консультантом**\n\n"
        "Вы можете задать любой вопрос. Консультант ответит вам в ближайшее время.\n\n"
        "Для завершения чата используйте кнопку ниже.",
        reply_markup=get_consultant_keyboard(),
        parse_mode="Markdown"
    )
    
    await state.set_state(UserStates.waiting_for_consultant_message)

@dp.message(UserStates.waiting_for_consultant_message)
async def process_consultant_message(message: types.Message, state: FSMContext):
    """Обработка сообщений в чате с консультантом"""
    user = message.from_user
    
    await save_chat_message(user.id, message.text, 'from_user')
    
    try:
        consultant_notification = (
            f"💬 **Новое сообщение от пользователя**\n\n"
            f"👤 Имя: {user.first_name} {user.last_name or ''}\n"
            f"🆔 ID: {user.id}\n"
            f"📱 Username: @{user.username or 'нет'}\n\n"
            f"📝 Сообщение: {message.text}"
        )
        
        if GROUP_CHAT_ID:
            await bot.send_message(GROUP_CHAT_ID, consultant_notification)
    except Exception as e:
        logging.error(f"Ошибка отправки уведомления консультанту: {e}")
    
    await message.answer(
        "✅ Ваше сообщение отправлено консультанту. "
        "Ожидайте ответа в ближайшее время.",
        reply_markup=get_consultant_keyboard()
    )

@dp.callback_query(lambda c: c.data == 'end_chat')
async def end_chat(callback_query: types.CallbackQuery, state: FSMContext):
    """Завершение чата с консультантом"""
    user_data = await state.get_data()
    session_id = user_data.get('chat_session_id')
    
    if session_id:
        await end_chat_session(session_id)
    
    user = callback_query.from_user
    
    await callback_query.message.answer(
        "👋 Чат с консультантом завершен. "
        "Если у вас появятся вопросы, вы всегда можете начать новый чат.",
        reply_markup=get_admin_keyboard() if is_admin(user.id) else get_main_keyboard()
    )
    
    await state.clear()
    await callback_query.answer()

# --- ОБРАБОТЧИКИ КНОПОК ---
@dp.message(lambda message: message.text == "💰 Курсы валют")
async def button_rates(message: types.Message):
    """Обработчик кнопки курсы валют"""
    await update_user_activity(message.from_user.id)
    await show_rates(message)

@dp.message(lambda message: message.text == "📊 Статистика")
async def button_statistics(message: types.Message):
    """Обработчик кнопки статистики (только для администраторов)"""
    user_id = message.from_user.id

    # Проверяем, является ли пользователь администратором
    if not is_admin(user_id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    
    if is_admin(user_id):
        await message.answer(
            "📊 **Статистика использования бота**\n\n"
            "Выберите период для просмотра статистики:",
            reply_markup=get_statistics_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ У вас нет доступа к этой функции.")

@dp.message(lambda message: message.text == "❓ Частые вопросы")
async def button_faq(message: types.Message):
    """Обработчик кнопки частые вопросы"""
    await update_user_activity(message.from_user.id)
    
    faq_text = """
❓ **Частые вопросы**

**1. Можно ли сразу узнать цену замены окон?**
Для получения точной суммы стоимости изготовления и монтажа продукции наш специалист должен произвести точный замер с учётом выбора материалов и опций, которые вы предпочтёте - это абсолютно бесплатно.

**2. Как быстро делается замер?**
В среднем процедура занимает не более 30 минут, в зависимости от масштаба объекта. Свяжитесь с нашим консультантом удобным для вас способом для согласования даты и времени для замера.

**3. Можно ли узнать стоимость окна/двери по имеющимся данным о размерах?**
Да. Для этого лучше всего использовать функцию "Начать переписку" и указать интересующую вас и уже имеющуюся информацию.
"""
    
    await message.answer(faq_text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "📞 Наши контакты")
async def button_contacts(message: types.Message):
    """Обработчик кнопки наши контакты"""
    await update_user_activity(message.from_user.id)
    
    contacts_text = """
📞 **Наши контакты**

🏢 **ЧУП «ГЭДВИЛ»**

📋 **УНП:** 491630821

📍 **Адрес:**
г. Гомель, Достоевского д.1/каб.313

📱 **Телефоны:**
+375 (29) 338-10-38
+375 (33) 356-10-41

🕐 **Режим работы:**
Пн-Пт: 9:00 - 19:00
Сб-Вс: выходной
"""
    
    await message.answer(contacts_text, parse_mode="Markdown")

# --- ОБРАБОТЧИКИ CALLBACK QUERIES ---
# --- ОБРАБОТЧИКИ CALLBACK QUERIES ---
@dp.callback_query(lambda c: c.data == 'start_bot')
async def process_start_button(callback_query: types.CallbackQuery):
    """Обработка нажатия кнопки Старт"""
    user = callback_query.from_user
    
    await save_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
👋 Привет, {user.first_name}!

Спасибо, что решили воспользоваться нашим помощником!

Выберите действие:
"""
    
    if is_admin(user.id):
        await callback_query.message.answer(
            welcome_text,
            reply_markup=get_admin_keyboard()
        )
    else:
        await callback_query.message.answer(
            welcome_text,
            reply_markup=get_main_keyboard()
        )
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith('stats_'))

@dp.callback_query(lambda c: c.data.startswith('stats_'))
async def process_stats_callback(callback_query: types.CallbackQuery):
    """Обработка выбора периода статистики"""
    
    # Проверяем, является ли пользователь администратором
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ У вас нет доступа к статистике.", show_alert=True)
        return
    
    period = callback_query.data.split('_')[1]
    
    stats = await get_bot_statistics(period)
    
    period_names = {
        'day': 'за последний день',
        'week': 'за последнюю неделю',
        'month': 'за последний месяц',
        '3months': 'за последние 3 месяца',
        '6months': 'за последние 6 месяцев',
        'year': 'за последний год'
    }
    
    text = f"📊 **Статистика использования бота**\n"
    text += f"📅 Период: {period_names.get(period, 'неизвестный период')}\n\n"
    
    text += "👥 **Пользователи:**\n"
    text += f"• Всего пользователей: {stats['total_users']}\n"
    text += f"• Новых за период: {stats['new_users']}\n"
    text += f"• Активных за период: {stats['active_users']}\n\n"
    
    text += "📞 **Заявки на звонок:**\n"
    text += f"• Всего заявок: {stats['callback_requests']}\n\n"
    
    text += "💬 **Чаты с консультантом:**\n"
    text += f"• Начато чатов: {stats['chat_sessions']}\n"
    text += f"• Сообщений всего: {stats['total_messages']}\n"
    text += f"• Сообщений от пользователей: {stats['user_messages']}\n\n"
    
    text += f"🕐 Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    
    # Отправляем статистику ТОЛЬКО в чат, где была нажата кнопка (админу)
    await callback_query.message.answer(text, parse_mode="Markdown")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith('currency_'))
async def process_currency_callback(callback_query: types.CallbackQuery):
    """Обработка выбора валюты"""
    try:
        currency = callback_query.data.split('_')[1]
        logging.info(f"Выбрана валюта: {currency}")
        
        rates = await get_currency_rates_from_db()
        
        # Если данных нет, пробуем получить свежие
        if not rates or not any(rates.get(curr, {}).get("best_buy") for curr in ["USD", "EUR", "RUB"]):
            logging.info("Нет данных в БД, получаем свежие курсы")
            rates = await get_currency_rates()
            if rates:
                await save_currency_rates(rates)
        
        currency_names = {
            'USD': '💵 Доллар США',
            'EUR': '💶 Евро',
            'RUB': '🇷🇺 Российский рубль'
        }
        
        if currency in rates and rates[currency].get("best_buy"):
            data = rates[currency]
            text = f"""
{currency_names.get(currency, currency)}

🏦 **Лучший курс покупки:**
{data['best_buy_bank']}: {data['best_buy']:.4f} BYN

💰 **Лучший курс продажи:**
{data['best_sell_bank']}: {data['best_sell']:.4f} BYN

🕐 Обновлено: {datetime.now().strftime("%d.%m.%Y %H:%M")}
"""
            logging.info(f"Отправляем информацию по {currency}")
            
            await callback_query.message.answer(
                text,
                reply_markup=get_bank_keyboard(currency),
                parse_mode="Markdown"
            )
        else:
            logging.warning(f"Нет данных для {currency}")
            await callback_query.message.answer(
                f"❌ Не удалось получить курс для {currency_names.get(currency, currency)}. "
                "Попробуйте обновить курсы."
            )
        
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в process_currency_callback: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith('all_banks_'))
async def process_all_banks(callback_query: types.CallbackQuery):
    """Показать все банки по валюте"""
    try:
        currency = callback_query.data.split('_')[2]
        logging.info(f"Запрос всех банков для {currency}")
        
        rates = await get_currency_rates_from_db()
        
        if currency in rates and rates[currency]["banks"]:
            text = f"🏦 **Курсы {currency} во всех банках:**\n\n"
            
            for i, bank in enumerate(rates[currency]["banks"][:20], 1):
                text += f"{i}. {bank['bank']}: {bank['buy']:.4f} / {bank['sell']:.4f}\n"
            
            await callback_query.message.answer(text, parse_mode="Markdown")
        else:
            await callback_query.message.answer("❌ Нет данных о банках. Попробуйте обновить курсы.")
        
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в process_all_banks: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith('top5_cities_'))
async def process_top5_cities(callback_query: types.CallbackQuery):
    """Показ выбора города для топ-5"""
    try:
        currency = callback_query.data.split('_')[2]
        logging.info(f"Запрос топ-5 по городам для {currency}")
        
        await callback_query.message.answer(
            f"Выберите город для просмотра топ-5 банков по {currency}:",
            reply_markup=get_city_keyboard_for_currency(currency)
        )
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в process_top5_cities: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith('city_top_'))
async def process_city_top(callback_query: types.CallbackQuery):
    """Обработка выбора города для топ-5 с валютой"""
    try:
        parts = callback_query.data.split('_')
        currency = parts[2]
        city = parts[3]
        
        logging.info(f"Запрос топ-5 для {currency} в городе {city}")
        
        await callback_query.answer(f"🔍 Ищу лучшие курсы в {CITIES.get(city, city)}...")
        
        top5_data = await get_top5_banks_for_city(currency, city)
        
        if top5_data and top5_data.get("banks"):
            currency_names = {
                'USD': '💵 Доллар США',
                'EUR': '💶 Евро',
                'RUB': '🇷🇺 Российский рубль'
            }
            
            text = f"🔝 **Топ-5 банков в {CITIES.get(city, city)}**\n"
            text += f"Валюта: {currency_names.get(currency, currency)}\n\n"
            
            for i, bank in enumerate(top5_data["banks"], 1):
                text += f"{i}. {bank['bank']}\n"
                text += f"   📈 Покупка: {bank['buy']:.4f} BYN\n"
                text += f"   📉 Продажа: {bank['sell']:.4f} BYN\n\n"
            
            text += f"🕐 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            
            await callback_query.message.answer(text, parse_mode="Markdown")
        else:
            await callback_query.message.answer(
                f"❌ Не удалось получить данные для {CITIES.get(city, city)}. "
                "Возможно, нет данных по этой валюте в данном городе."
            )
        
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в process_city_top: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith('top5_cities_'))
async def process_top5_cities(callback_query: types.CallbackQuery):
    """Показ выбора города для топ-5"""
    currency = callback_query.data.split('_')[2]
    
    await callback_query.message.answer(
        f"Выберите город для просмотра топ-5 банков по {currency}:",
        reply_markup=get_city_keyboard_for_currency(currency)
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith('city_top_'))
async def process_city_top(callback_query: types.CallbackQuery):
    """Обработка выбора города для топ-5 с валютой"""
    parts = callback_query.data.split('_')
    currency = parts[2]
    city = parts[3]
    
    await callback_query.answer(f"🔍 Ищу лучшие курсы в {CITIES.get(city, city)}...")
    
    top5_data = await get_top5_banks_for_city(currency, city)
    
    if top5_data and top5_data.get("banks"):
        currency_names = {
            'USD': '💵 Доллар США',
            'EUR': '💶 Евро',
            'RUB': '🇷🇺 Российский рубль'
        }
        
        text = f"🔝 **Топ-5 банков в {CITIES.get(city, city)}**\n"
        text += f"Валюта: {currency_names.get(currency, currency)}\n\n"
        
        for i, bank in enumerate(top5_data["banks"], 1):
            text += f"{i}. {bank['bank']}\n"
            text += f"   📈 Покупка: {bank['buy']:.4f} BYN\n"
            text += f"   📉 Продажа: {bank['sell']:.4f} BYN\n\n"
        
        text += f"🕐 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        
        await callback_query.message.answer(text, parse_mode="Markdown")
    else:
        await callback_query.message.answer(
            f"❌ Не удалось получить данные для {CITIES.get(city, city)}. "
            "Возможно, нет данных по этой валюте в данном городе."
        )
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'best_rates')
async def process_best_rates(callback_query: types.CallbackQuery):
    """Показать лучшие курсы"""
    await show_best_rates(callback_query.message)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'refresh_rates')
async def process_refresh_rates(callback_query: types.CallbackQuery):
    """Обновление курсов"""
    await callback_query.answer("🔄 Обновляю курсы...")
    
    rates = await get_currency_rates()
    if rates:
        await save_currency_rates(rates)
        await show_rates(callback_query.message)
    else:
        await callback_query.message.answer("❌ Не удалось получить курсы валют")
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'back_to_currencies')
async def process_back(callback_query: types.CallbackQuery):
    """Возврат к выбору валюты"""
    await show_rates(callback_query.message)
    await callback_query.answer()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def show_rates(message: types.Message):
    """Показать курсы валют"""
    rates = await get_currency_rates_from_db()
    
    if not any(rates.get(curr, {}).get("best_buy") for curr in ["USD", "EUR", "RUB"]):
        rates = await get_currency_rates()
        if rates:
            await save_currency_rates(rates)
    
    if rates and any(rates.get(curr, {}).get("best_buy") for curr in ["USD", "EUR", "RUB"]):
        text = "💰 **Актуальные курсы валют**\n\n"
        text += "Лучшие курсы в банках:\n\n"
        
        currency_data = [
            ("USD", "💵 Доллар США"),
            ("EUR", "💶 Евро"),
            ("RUB", "🇷🇺 Рос. рубль")
        ]
        
        for code, name in currency_data:
            if code in rates and rates[code].get("best_buy"):
                data = rates[code]
                text += f"{name}:\n"
                text += f"  📈 Покупка: {data['best_buy']:.4f} ({data['best_buy_bank']})\n"
                text += f"  📉 Продажа: {data['best_sell']:.4f} ({data['best_sell_bank']})\n\n"
            else:
                text += f"{name}: Нет данных\n\n"
        
        text += f"🕐 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        text += "\n\n💡 Нажмите на валюту ниже для детальной информации:"
        
        await message.answer(
            text,
            reply_markup=get_currency_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Не удалось получить курсы валют. Попробуйте позже или используйте /rates для повторной попытки.")

async def show_best_rates(message: types.Message):
    """Показать лучшие курсы"""
    rates = await get_currency_rates_from_db()
    
    if not any(rates.get(curr, {}).get("banks") for curr in ["USD", "EUR", "RUB"]):
        rates = await get_currency_rates()
        if rates:
            await save_currency_rates(rates)
    
    if rates and any(rates.get(curr, {}).get("banks") for curr in ["USD", "EUR", "RUB"]):
        text = "🏦 **Лучшие курсы в банках Минска**\n\n"
        
        for currency, name in [("USD", "💵 Доллар"), ("EUR", "💶 Евро"), ("RUB", "🇷🇺 Рубль")]:
            if currency in rates and rates[currency].get("banks"):
                data = rates[currency]
                text += f"{name}:\n"
                
                top_buy = sorted(data["banks"], key=lambda x: x["buy"], reverse=True)[:3]
                text += "  Лучшие для продажи валюты:\n"
                for i, bank in enumerate(top_buy, 1):
                    text += f"    {i}. {bank['bank']}: {bank['buy']:.4f}\n"
                
                top_sell = sorted(data["banks"], key=lambda x: x["sell"])[:3]
                text += "  Лучшие для покупки валюты:\n"
                for i, bank in enumerate(top_sell, 1):
                    text += f"    {i}. {bank['bank']}: {bank['sell']:.4f}\n"
                
                text += "\n"
            else:
                text += f"{name}: Нет данных\n\n"
        
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("❌ Не удалось получить данные о курсах")

# --- ФУНКЦИЯ ДЛЯ ЕЖЕДНЕВНОЙ ОТПРАВКИ ---
async def send_daily_rates_to_group():
    """Ежедневная отправка курсов в группу"""
    try:
        rates = await get_currency_rates()
        if rates:
            await save_currency_rates(rates)
            
            text = "📊 **Ежедневные курсы валют в Минске**\n\n"
            text += "🏦 Лучшие курсы в банках:\n\n"
            
            currency_data = [
                ("USD", "💵 Доллар США"),
                ("EUR", "💶 Евро"),
                ("RUB", "🇷🇺 Рос. рубль")
            ]
            
            for code, name in currency_data:
                if code in rates and rates[code].get("best_buy"):
                    data = rates[code]
                    text += f"{name}:\n"
                    text += f"  📈 Покупка: {data['best_buy']:.4f} BYN ({data['best_buy_bank']})\n"
                    text += f"  📉 Продажа: {data['best_sell']:.4f} BYN ({data['best_sell_bank']})\n\n"
                else:
                    text += f"{name}: Нет данных\n\n"
            
            text += f"🕐 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            text += "\n\n🌐 Источник: myfin.by"
            text += "\n📱 @okna_dveri_bel"
            
            await bot.send_message(
                GROUP_CHAT_ID,
                text,
                parse_mode="Markdown"
            )
            logging.info("Курсы валют отправлены в группу")
        else:
            logging.error("Не удалось получить курсы для отправки в группу")
    except Exception as e:
        logging.error(f"Ошибка при отправке в группу: {e}")

# --- ФУНКЦИЯ ДЛЯ ПЛАНИРОВЩИКА ---
async def scheduler():
    """Планировщик задач"""
    schedule.every().day.at("10:00").do(
        lambda: asyncio.create_task(send_daily_rates_to_group())
    )
    
    schedule.every(4).hours.do(
        lambda: asyncio.create_task(update_rates_silently())
    )
    
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

async def update_rates_silently():
    """Тихое обновление курсов"""
    try:
        rates = await get_currency_rates()
        if rates:
            await save_currency_rates(rates)
            logging.info("Курсы обновлены автоматически")
    except Exception as e:
        logging.error(f"Ошибка при автоматическом обновлении: {e}")

# --- ЗАПУСК БОТА ---
async def main():
    """Главная функция"""
    try:
        # Инициализируем БД
        await init_db()
        
        # Получаем курсы при запуске
        logging.info("Получаем начальные курсы...")
        initial_rates = await get_currency_rates()
        if initial_rates:
            await save_currency_rates(initial_rates)
            logging.info("Начальные курсы загружены")
        else:
            logging.warning("Не удалось получить начальные курсы")

    
    
        # Запускаем планировщик в фоне
        asyncio.create_task(scheduler())
        
        # Удаляем webhook перед запуском polling
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook удалён")
        
        # Запускаем бота
        logging.info("Бот запущен")
        await dp.start_polling(bot)
        
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())