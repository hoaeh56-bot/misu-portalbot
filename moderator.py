import asyncio
import logging
import os
import psycopg2
import aiohttp_cors
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

ADMIN_ID = 1780243441 
PORTAL_URL = "https://misu-portal.vercel.app" 

session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER))
bot = Bot(token=config.TOKEN, session=session)
dp = Dispatcher()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres.ptcofqwsvyytcnoerazu:22E%23bS%23aMcN%40L6A@aws-0-eu-north-1.pooler.supabase.com:5432/postgres")
def get_db(): return psycopg2.connect(DATABASE_URL)

# === СТАРТ (СКАЧИВАЕМ АВАТАРКУ И СОХРАНЯЕМ ПРОФИЛЬ) ===
@dp.message(CommandStart())
async def cmd_start(message: Message):
    avatar_url = ""
    try:
        # Пытаемся получить аватарку пользователя
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            file = await bot.get_file(file_id)
            avatar_url = f"https://api.telegram.org/file/bot{config.TOKEN}/{file.file_path}"
    except Exception as e:
        logging.error(f"Не удалось получить аву: {e}")

    try:
        con = get_db(); cur = con.cursor()
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or "Пользователь"
        
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (message.from_user.id,))
        if cur.fetchone():
            cur.execute("UPDATE users SET username = %s, first_name = %s, avatar_url = %s WHERE user_id = %s", (username, first_name, avatar_url, message.from_user.id))
        else:
            wallet = 'T' + str(message.from_user.id) + 'CRYPTO'
            cur.execute("INSERT INTO users (user_id, username, first_name, avatar_url, wallet_address) VALUES (%s, %s, %s, %s, %s)", (message.from_user.id, username, first_name, avatar_url, wallet))
        con.commit(); cur.close(); con.close()
    except Exception as e:
        logging.error(f"Ошибка профиля: {e}")

    portal_url = f"{PORTAL_URL}?user_id={message.from_user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=portal_url))]
    ])
    photo_file_id = "AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E"
    try: await message.answer_photo(photo=photo_file_id, caption="Welcome to Portals!", reply_markup=kb)
    except: await message.answer("Welcome to Portals!", reply_markup=kb)

# === ПРИЕМ ЗАЯВКИ НА ВЫВОД ОТ САЙТА ===
async def handle_notify(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        gift_name = data.get("gift_name")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Зачислить в инвентарь", callback_data=f"approve_{user_id}_{gift_name}")]
        ])
        await bot.send_message(
            ADMIN_ID, 
            f"🔔 **Заявка на вывод!**\n\nЮзер `{user_id}` переслал подарок: **{gift_name}**.\n\nПроверь аккаунт и нажми кнопку:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# === КНОПКА ПОДТВЕРЖДЕНИЯ ДЛЯ ТЕБЯ ===
@dp.callback_query(F.data.startswith("approve_"))
async def process_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Только для админа!", show_alert=True)
        
    parts = callback.data.split("_", 2)
    user_id = int(parts[1])
    gift_name = parts[2]
    
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id, status) VALUES (%s, %s, 'manual', 'inventory')", (user_id, gift_name))
        con.commit(); cur.close(); con.close()
        
        await callback.message.edit_text(f"✅ Подарок '{gift_name}' зачислен юзеру {user_id}!")
        await bot.send_message(user_id, f"🎁 Ваш подарок '{gift_name}' успешно зачислен в инвентарь!")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")

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

# === ВЕБ-СЕРВЕР ===
async def handle_ping(request): return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', handle_ping)
    app.router.add_post('/buy_gift', handle_buy_gift)
    app.router.add_post('/notify_admin', handle_notify)
    for route in list(app.router.routes()): cors.add(route)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()

async def main():
    asyncio.create_task(start_web_server())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e: logging.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
