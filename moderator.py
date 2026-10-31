import asyncio
import logging
import os
import psycopg2
import aiohttp_cors
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, PreCheckoutQuery, LabeledPrice, InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo, CallbackQuery
)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

ADMIN_ID = 1780243441 
PORTAL_URL = "https://misu-portal.vercel.app" 

# === ТВОЙ НОВЫЙ ТОКЕН ОТ БИЗНЕС-БОТА (@portal_gifts_bot) ===
PORTAL_BOT_TOKEN = "1780243445:wEWoLT8Cbm2xJHSReMfxV51kCtpIPdfLOJ5"

# Создаем сессию для подключения к серверам Missgram
session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER))

# Твой основной бот (который в config.py)
bot = Bot(token=config.TOKEN, session=session)

# Твой новый бизнес-бот (который ловит подарки)
portal_bot = Bot(token=PORTAL_BOT_TOKEN, session=session)

dp = Dispatcher()

# Твоя база данных
DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://postgres.ptcofqwsvyytcnoerazu:22E%23bS%23aMcN%40L6A@aws-0-eu-north-1.pooler.supabase.com:5432/postgres"
)

def get_db():
    return psycopg2.connect(DATABASE_URL)

# === СТАРТ ОСНОВНОГО БОТА (КНОПКИ) ===
@dp.message(CommandStart())
async def cmd_start(message: Message):
    # 1. Сохраняем юзернейм и имя в базу
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
        logging.error(f"Ошибка сохранения профиля: {e}")

    # 2. Отправляем картинку и кнопки
    portal_url_with_id = f"{PORTAL_URL}?user_id={message.from_user.id}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=portal_url_with_id))],
        [InlineKeyboardButton(text="Join the community", url="https://t.me/theportal")],
        [InlineKeyboardButton(text="Contact support", url="https://t.me/zovmode")]
    ])
    
    caption_text = "Welcome to Portals! Discover, trade, and collect unique digital gifts in our marketplace. Start exploring now!"
    photo_file_id = "AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E"

    try:
        await message.answer_photo(photo=photo_file_id, caption=caption_text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка отправки картинки: {e}")
        await message.answer(caption_text, reply_markup=kb)

# === БИЗНЕС-БОТ ЛОВИТ ПОДАРКИ НА АККАУНТЕ ===
@dp.business_message()
async def handle_business_message(message: Message):
    # Проверяем, что пришел именно подарок
    if message.gift:
        sender_id = message.from_user.id if message.from_user else None
        
        # Название подарка (в разных версиях API может быть по-разному)
        gift_name = f"Gift ID: {message.gift.id}" 
        
        logging.info(f"🎁 Поймали подарок {gift_name} от {sender_id}")
        
        if sender_id:
            try:
                # Добавляем в инвентарь на портале
                con = get_db(); cur = con.cursor()
                cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id, status) VALUES (%s, %s, 'from_account', 'inventory')", (sender_id, gift_name))
                con.commit(); cur.close(); con.close()
                
                # Уведомляем юзера (через основного бота)
                await bot.send_message(
                    sender_id, 
                    f"🎁 Подарок успешно зачислен в ваш инвентарь на портале!\n\nЗайдите в мини-апп и выставьте его на продажу."
                )
            except Exception as e:
                logging.error(f"Ошибка при добавлении подарка в базу: {e}")
    else:
        # Логируем обычные сообщения на аккаунт (чтобы видеть, что бизнес-бот работает)
        logging.info(f"Бизнес-сообщение от {message.from_user.id}: {message.text}")

# === ПОКУПКА ПОДАРКА ИЗ МИНИ-АППА ===
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
        if not item: 
            cur.close(); con.close()
            return web.json_response({"status": "error", "message": "Уже продан"}, status=400)
        
        cur.execute("SELECT gram_balance, balance FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row or float(row[0]) < price_gram: 
            cur.close(); con.close()
            return web.json_response({"status": "error", "message": "Мало GRAM"}, status=400)
        
        new_gram = float(row[0]) - price_gram
        new_crystals = int(row[1] or 0) + int(price_gram * 100)
        
        cur.execute("UPDATE users SET gram_balance = %s, balance = %s WHERE user_id = %s", (new_gram, new_crystals, user_id))
        if seller_id: 
            cur.execute("UPDATE users SET gram_balance = gram_balance + %s WHERE user_id = %s", (price_gram, seller_id))
            
        cur.execute("UPDATE market_items SET is_sold = true WHERE id = %s", (gift_id,))
        cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id, status) VALUES (%s, %s, %s, 'inventory')", (user_id, item[0], gift_id))
        con.commit(); cur.close(); con.close()
        
        return web.json_response({"status": "ok", "crystals": int(price_gram*100)})
    except Exception as e: 
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# === ВЕБ-СЕРВЕР (ДЛЯ СВЯЗИ С САЙТОМ) ===
async def handle_ping(request): 
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', handle_ping)
    app.router.add_post('/buy_gift', handle_buy_gift)
    
    for route in list(app.router.routes()): 
        cors.add(route)
        
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()
    logging.info("ВЕБ-СЕРВЕР ЗАПУЩЕН")

# === ЗАПУСК ВСЕГО ===
async def main():
    # Запускаем веб-сервер
    asyncio.create_task(start_web_server())
    
    # Запускаем основного бота (для кнопок)
    logging.info("Запуск основного бота...")
    asyncio.create_task(dp.start_polling(bot))
    
    # Запускаем бизнес-бота (для подарков)
    logging.info("Запуск бизнес-бота...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(portal_bot)
    except Exception as e: 
        logging.error(f"Ошибка бизнес-бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())
