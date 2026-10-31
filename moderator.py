import asyncio
import logging
import os
import psycopg2
import aiohttp_cors
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, BusinessConnection
)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

ADMIN_ID = 1780243441 
PORTAL_URL = "https://misu-portal.vercel.app" 
PORTAL_BOT_TOKEN = "1780243445:wEWoLT8Cbm2xJHSReMfxV51kCtpIPdfLOJ5"

session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER))

# Два разных бота
bot = Bot(token=config.TOKEN, session=session)               
portal_bot = Bot(token=PORTAL_BOT_TOKEN, session=session)    

# Два разных диспетчера (чтобы боты не конфликтовали)
dp_main = Dispatcher()
dp_portal = Dispatcher()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres.ptcofqwsvyytcnoerazu:22E%23bS%23aMcN%40L6A@aws-0-eu-north-1.pooler.supabase.com:5432/postgres")
def get_db(): return psycopg2.connect(DATABASE_URL)

# ==========================================
# ОСНОВНОЙ БОТ (КНОПКИ, СТАРТ)
# ==========================================
@dp_main.message(CommandStart())
async def cmd_start(message: Message):
    try:
        con = get_db(); cur = con.cursor()
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or "Пользователь"
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (message.from_user.id,))
        if cur.fetchone():
            cur.execute("UPDATE users SET username = %s, first_name = %s WHERE user_id = %s", (username, first_name, message.from_user.id))
        else:
            wallet = 'T' + str(message.from_user.id) + 'CRYPTO'
            cur.execute("INSERT INTO users (user_id, username, first_name, wallet_address) VALUES (%s, %s, %s, %s)", (message.from_user.id, username, first_name, wallet))
        con.commit(); cur.close(); con.close()
    except Exception as e:
        logging.error(f"Ошибка профиля: {e}")

    portal_url_with_id = f"{PORTAL_URL}?user_id={message.from_user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=portal_url_with_id))],
        [InlineKeyboardButton(text="Join the community", url="https://t.me/theportal")],
        [InlineKeyboardButton(text="Contact support", url="https://t.me/zovmode")]
    ])
    photo_file_id = "AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E"
    try: await message.answer_photo(photo=photo_file_id, caption="Welcome to Portals!", reply_markup=kb)
    except: await message.answer("Welcome to Portals!", reply_markup=kb)

# ==========================================
# БИЗНЕС-БОТ: ЛОВИМ ID ПОДКЛЮЧЕНИЯ
# ==========================================
@dp_portal.business_connection()
async def on_business_connection(connection: BusinessConnection):
    # Вот он — уникальный ID подключения
    connection_id = connection.id
    
    logging.info("==============================================")
    logging.info(f"🔥 БОТ ПОДКЛЮЧЕН! Business Connection ID: {connection_id}")
    logging.info("==============================================")
    
    # Сохраняем его в файл и в базу (на всякий случай)
    try:
        with open("business_connection_id.txt", "w") as f:
            f.write(connection_id)
            
        con = get_db(); cur = con.cursor()
        # Создаем таблицу для настроек, если ее нет
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key text primary key,
                value text
            )
        """)
        cur.execute("INSERT INTO settings (key, value) VALUES ('business_connection_id', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (connection_id, connection_id))
        con.commit(); cur.close(); con.close()
        logging.info("ID сохранен в базу данных.")
    except Exception as e:
        logging.error(f"Ошибка сохранения ID: {e}")

# ==========================================
# ВЕБ-СЕРВЕР (ДЛЯ САЙТА)
# ==========================================
async def handle_buy_gift(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        gift_id = data.get("gift_id")
        price_gram = float(data.get("price_gram"))
        seller_id = data.get("seller_id")
        
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT name FROM market_items WHERE id = %s AND is_sold = false", (gift_id,))
        item = cur.fetchone()
        if not item: return web.json_response({"status": "error", "message": "Уже продан"}, status=400)
        
        cur.execute("SELECT gram_balance, balance FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row or float(row[0]) < price_gram: return web.json_response({"status": "error", "message": "Мало GRAM"}, status=400)
        
        new_gram = float(row[0]) - price_gram
        new_crystals = int(row[1] or 0) + int(price_gram * 100)
        
        cur.execute("UPDATE users SET gram_balance = %s, balance = %s WHERE user_id = %s", (new_gram, new_crystals, user_id))
        if seller_id: cur.execute("UPDATE users SET gram_balance = gram_balance + %s WHERE user_id = %s", (price_gram, seller_id))
        cur.execute("UPDATE market_items SET is_sold = true WHERE id = %s", (gift_id,))
        cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id, status) VALUES (%s, %s, %s, 'inventory')", (user_id, item[0], gift_id))
        con.commit(); cur.close(); con.close()
        
        return web.json_response({"status": "ok", "crystals": int(price_gram*100)})
    except Exception as e: 
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_ping(request): 
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', handle_ping)
    app.router.add_post('/buy_gift', handle_buy_gift)
    for route in list(app.router.routes()): cors.add(route)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()
    logging.info("ВЕБ-СЕРВЕР ЗАПУЩЕН")

# ==========================================
# ЗАПУСК
# ==========================================
async def main():
    asyncio.create_task(start_web_server())
    
    # Очистка
    logging.info("Очистка старых вебхуков...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await portal_bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.error(f"Ошибка очистки: {e}")
    
    # Запуск
    logging.info("Запуск основного бота...")
    asyncio.create_task(dp_main.start_polling(bot))
    
    logging.info("Запуск бизнес-бота (ожидание подключения)...")
    await dp_portal.start_polling(portal_bot)

if __name__ == "__main__":
    asyncio.run(main())
