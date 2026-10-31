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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ТВОЙ ADMIN ID
ADMIN_ID = 1780243441 

# Ссылка на портал
PORTAL_URL = "https://misu-portal.vercel.app" 

session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER))
bot = Bot(token=config.TOKEN, session=session)
dp = Dispatcher()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://postgres.ptcofqwsvyytcnoerazu:22E%23bS%23aMcN%40L6A@aws-0-eu-north-1.pooler.supabase.com:5432/postgres"
)

def get_db():
    return psycopg2.connect(DATABASE_URL)

# === СТАРТ (КАРТИНКА + 3 КНОПКИ + ID В ССЫЛКЕ) ===
@dp.message(CommandStart())
async def cmd_start(message: Message):
    # ВОТ ТУТ МЫ ДОБАВЛЯЕМ ?user_id=... К ССЫЛКЕ НА ПОРТАЛ
    portal_url_with_id = f"{PORTAL_URL}?user_id={message.from_user.id}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=portal_url_with_id))],
        [InlineKeyboardButton(text="Join the community", url="https://t.me/theportal")],
        [InlineKeyboardButton(text="Contact support", url="https://t.me/zovmode")]
    ])
    
    caption_text = "Welcome to Portals! Discover, trade, and collect unique digital gifts in our marketplace. Start exploring now!"
    
    # Твой file_id картинки
    photo_file_id = "AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E"

    try:
        await message.answer_photo(photo=photo_file_id, caption=caption_text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка отправки картинки: {e}")
        await message.answer(caption_text, reply_markup=kb)

# === ОБРАБОТКА ПОКУПКИ ПОДАРКА ИЗ МИНИ-АППА ===
async def handle_buy_gift(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        gift_name = data.get("gift_name")
        gift_id = data.get("gift_id")
        price_gram = float(data.get("price_gram"))
        
        # Начисляем 100 кристаллов за 1 GRAM
        crystals_reward = int(price_gram * 100)
        
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT gram_balance, balance FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        
        if not row or float(row[0]) < price_gram:
            cur.close(); con.close()
            return web.json_response({"status": "error", "message": "Недостаточно GRAM"}, status=400)
        
        new_gram = float(row[0]) - price_gram
        new_crystals = int(row[1] or 0) + crystals_reward
        
        # Списываем грам, начисляем кристаллы, добавляем в инвентарь
        cur.execute("UPDATE users SET gram_balance = %s, balance = %s WHERE user_id = %s", (new_gram, new_crystals, user_id))
        cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id) VALUES (%s, %s, %s)", (user_id, gift_name, gift_id))
        
        con.commit(); cur.close(); con.close()
        
        return web.json_response({"status": "ok", "crystals": crystals_reward, "new_gram": new_gram})
    except Exception as e:
        logging.error(f"Ошибка покупки подарка: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# === ПОПОЛНЕНИЕ ЧЕРЕЗ ЗВЕЗДЫ ===
async def handle_buy_stars(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        coin = data.get("coin")
        amount = float(data.get("amount"))
        stars = int(data.get("stars"))

        await bot.send_invoice(
            chat_id=user_id,
            title=f"Покупка {amount} {coin}",
            description=f"Оплата {stars} Stars",
            payload=f"buycrypto_{coin}_{amount}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="XTR", amount=stars)],
        )
        return web.json_response({"status": "ok"})
    except Exception as e:
        logging.error(f"Ошибка запроса Stars: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def success_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("buycrypto_"):
        parts = payload.split("_")
        coin = parts[1]; amount = float(parts[2]); user_id = message.from_user.id
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        if not cur.fetchone(): cur.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
        balance_field = f"{coin.lower()}_balance"
        cur.execute(f"UPDATE users SET {balance_field} = {balance_field} + %s WHERE user_id = %s", (amount, user_id))
        con.commit(); cur.close(); con.close()
        await message.answer(f"Куплено {amount} {coin}!")

# === АДМИН-ПАНЕЛЬ ===
@dp.message(Command("admin_panel"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Обнулить всё", callback_data="reset_all_balances")]])
    await message.answer("Админ-панель:", reply_markup=kb)

@dp.callback_query(F.data == "reset_all_balances")
async def reset_all_balances(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET usdt_balance = 0, gram_balance = 0, sol_balance = 0, trx_balance = 0, balance = 0")
    con.commit(); cur.close(); con.close()
    await callback.message.answer("Все балансы обнулены.")
    await callback.answer()

# === ВЕБ-СЕРВЕР ===
async def handle_ping(request): return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', handle_ping)
    app.router.add_post('/buy', handle_buy_stars)       # Пополнение
    app.router.add_post('/buy_gift', handle_buy_gift)   # Покупка подарка в портале
    
    for route in list(app.router.routes()): cors.add(route)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()
    logging.info("ВЕБ-СЕРВЕР ЗАПУЩЕН")

async def main():
    asyncio.create_task(start_web_server())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e: logging.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
