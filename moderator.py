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
    InlineKeyboardButton, WebAppInfo, CallbackQuery, FSInputFile
)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from PIL import Image, ImageDraw, ImageFont
import config

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

ADMIN_ID = 1780243441 
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

pending_action = None
pending_coin = "USDT"

# === ГЕНЕРАЦИЯ КАРТИНКИ ЧЕКА ===
def generate_check_image(amount, coin, title="Crypto Check"):
    width, height = 800, 400
    img = Image.new('RGB', (width, height), color='#1e1e1e')
    draw = ImageDraw.Draw(img)

    colors = {'USDT': (38, 161, 123), 'GRAM': (0, 136, 204), 'SOL': (153, 69, 255), 'TRX': (255, 0, 0)}
    base_color = colors.get(coin, (25, 118, 210))

    for y in range(height):
        r = int(base_color[0] * (0.2 + 0.8 * (y / height)))
        g = int(base_color[1] * (0.2 + 0.8 * (y / height)))
        b = int(base_color[2] * (0.2 + 0.8 * (y / height)))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        font_icon = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_icon = ImageFont.load_default()

    icon_size = 120
    icon_x = 80
    icon_y = (height - icon_size) // 2

    icon_path = f"{coin.lower()}.png"
    try:
        icon = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size))
        img.paste(icon, (icon_x, icon_y), icon)
    except:
        draw.ellipse((icon_x, icon_y, icon_x + icon_size, icon_y + icon_size), fill="white")
        bbox = draw.textbbox((0, 0), coin[0], font=font_icon)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((icon_x + (icon_size - w) / 2, icon_y + (icon_size - h) / 2 - 15), coin[0], font=font_icon, fill=base_color)

    amount_text = f"{amount}"
    draw.text((240, height // 2 - 80), amount_text, font=font_large, fill="white")
    draw.text((250, height // 2 + 40), coin, font=font_small, fill="#eeeeee")
    draw.text((80, height - 60), title, font=font_small, fill="#cccccc")

    filepath = f"check_{amount}_{coin}_{title}.png"
    img.save(filepath)
    return filepath

# === СТАРТ ===
@dp.message(CommandStart())
async def cmd_start(message: Message):
    global pending_action, pending_coin
    pending_action = None
    pending_coin = "USDT"

    args = message.text.split()
    if len(args) > 1:
        if args[1].startswith("check_"):
            await process_check_activation(message, args[1].replace("check_", ""))
            return
        elif args[1].startswith("pay_"):
            await process_invoice_payment(message, args[1].replace("pay_", ""))
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=PORTAL_URL))],
        [InlineKeyboardButton(text="Join the community", url="https://t.me/theportal")],
        [InlineKeyboardButton(text="Contact support", url="https://t.me/zovmode")]
    ])
    
    caption_text = (
        "Welcome to Portals! Discover, trade, and collect unique digital gifts in our marketplace. Start exploring now!"
    )

    # Твой file_id для картинки
    photo_file_id = "AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E"

    try:
        await message.answer_photo(
            photo=photo_file_id,
            caption=caption_text,
            reply_markup=kb
        )
    except Exception as e:
        logging.error(f"Ошибка отправки картинки: {e}")
        await message.answer(caption_text, reply_markup=kb)

# === СКРЫТОЕ МЕНЮ (ЧЕКИ, СЧЕТА) ===
@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    wallet_url = f"https://misu-site.vercel.app/?user_id={message.from_user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Кошелек", web_app=WebAppInfo(url=wallet_url))],
        [InlineKeyboardButton(text="Создать чек", callback_data="create_check_menu"), 
         InlineKeyboardButton(text="Создать счет", callback_data="create_invoice_menu")]
    ])
    await message.answer("Дополнительные функции:", reply_markup=kb)

@dp.message(Command("send"))
async def cmd_send_in_chat(message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.answer("Использование: /send 10 TRX\nДоступные валюты: USDT, GRAM, SOL, TRX")
    try:
        amount = float(args[1])
        coin = args[2].upper()
        if coin not in ['USDT', 'GRAM', 'SOL', 'TRX']:
            return await message.answer("Неверная валюта.")
    except:
        return await message.answer("Ошибка. Пример: /send 10 TRX")
    await create_check_logic(message, amount, coin)

@dp.message(Command("invoice"))
async def cmd_invoice_in_chat(message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.answer("Использование: /invoice 50 USDT")
    try:
        amount = float(args[1])
        coin = args[2].upper()
        if coin not in ['USDT', 'GRAM', 'SOL', 'TRX']:
            return await message.answer("Неверная валюта.")
    except:
        return await message.answer("Ошибка. Пример: /invoice 50 USDT")
    await create_invoice_logic(message, amount, coin)

@dp.callback_query(F.data == "create_check_menu")
async def check_currency_menu(callback: CallbackQuery):
    global pending_action
    pending_action = "check"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="USDT", callback_data="curr_USDT"), InlineKeyboardButton(text="GRAM", callback_data="curr_GRAM")],
        [InlineKeyboardButton(text="SOL", callback_data="curr_SOL"), InlineKeyboardButton(text="TRX", callback_data="curr_TRX")]
    ])
    await callback.message.edit_text("Выберите валюту для чека:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "create_invoice_menu")
async def invoice_currency_menu(callback: CallbackQuery):
    global pending_action
    pending_action = "invoice"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="USDT", callback_data="curr_USDT"), InlineKeyboardButton(text="GRAM", callback_data="curr_GRAM")],
        [InlineKeyboardButton(text="SOL", callback_data="curr_SOL"), InlineKeyboardButton(text="TRX", callback_data="curr_TRX")]
    ])
    await callback.message.edit_text("Выберите валюту для счета:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("curr_"))
async def ask_amount(callback: CallbackQuery):
    global pending_coin
    pending_coin = callback.data.replace("curr_", "")
    await callback.message.edit_text(f"Введите сумму в {pending_coin}:")
    await callback.answer()

@dp.message(F.text.regexp(r'^\d+(\.\d+)?$'))
async def handle_amount_input(message: Message):
    global pending_action, pending_coin
    amount = float(message.text)
    if pending_action == "check":
        await create_check_logic(message, amount, pending_coin)
    elif pending_action == "invoice":
        await create_invoice_logic(message, amount, pending_coin)
    pending_action = None

async def create_check_logic(message: Message, amount: float, coin: str):
    if amount <= 0: return await message.answer("Сумма должна быть больше 0")
    balance_field = f"{coin.lower()}_balance"
    con = get_db(); cur = con.cursor()
    cur.execute(f"SELECT {balance_field} FROM users WHERE user_id = %s", (message.from_user.id,))
    row = cur.fetchone()
    if not row or row[0] < amount:
        cur.close(); con.close()
        return await message.answer(f"Недостаточно {coin} на балансе.")
    cur.execute(f"UPDATE users SET {balance_field} = {balance_field} - %s WHERE user_id = %s", (amount, message.from_user.id))
    cur.execute("INSERT INTO checks (creator_id, amount, coin, is_activated) VALUES (%s, %s, %s, false) RETURNING id", (message.from_user.id, amount, coin))
    check_id = cur.fetchone()[0]
    con.commit(); cur.close(); con.close()

    img_path = generate_check_image(amount, coin, "Crypto Check")
    caption = f"Чек на {amount} {coin}\n\nЧтобы активировать, нажмите кнопку ниже."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Получить {amount} {coin}", url=f"https://t.me/cryptobot?start=check_{check_id}")]
    ])
    photo = FSInputFile(img_path)
    await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=caption, reply_markup=kb)
    if os.path.exists(img_path): os.remove(img_path)

async def create_invoice_logic(message: Message, amount: float, coin: str):
    if amount <= 0: return await message.answer("Сумма должна быть больше 0")
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO checks (creator_id, amount, coin, is_activated) VALUES (%s, %s, %s, false) RETURNING id", (message.from_user.id, amount, coin))
    invoice_id = cur.fetchone()[0]
    con.commit(); cur.close(); con.close()

    img_path = generate_check_image(amount, coin, "Payment Invoice")
    caption = f"Счет на оплату: {amount} {coin}\n\nНажмите кнопку ниже, чтобы оплатить."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {amount} {coin}", url=f"https://t.me/cryptobot?start=pay_{invoice_id}")]
    ])
    photo = FSInputFile(img_path)
    await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=caption, reply_markup=kb)
    if os.path.exists(img_path): os.remove(img_path)

async def process_check_activation(message: Message, check_id: str):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT amount, coin, is_activated, creator_id FROM checks WHERE id = %s", (check_id,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return await message.answer("Чек не найден.")
    amount, coin, is_activated, creator_id = row
    if is_activated: cur.close(); con.close(); return await message.answer("Этот чек уже активирован.")
    if creator_id == message.from_user.id: cur.close(); con.close(); return await message.answer("Нельзя активировать свой же чек.")
    balance_field = f"{coin.lower()}_balance"
    cur.execute(f"UPDATE users SET {balance_field} = {balance_field} + %s WHERE user_id = %s", (amount, message.from_user.id))
    cur.execute("UPDATE checks SET is_activated = true, activated_by = %s WHERE id = %s", (message.from_user.id, check_id))
    con.commit(); cur.close(); con.close()
    await message.answer(f"Вы активировали чек и получили {amount} {coin}!")
    try:
        user_info = await bot.get_chat(message.from_user.id)
        name = user_info.first_name or "Пользователь"
        if user_info.username: name = f"@{user_info.username}"
        user_link = f'<a href="tg://user?id={message.from_user.id}">{name}</a>'
        await bot.send_message(creator_id, f"🔔 Ваш чек на {amount} {coin} активировал {user_link}!", parse_mode="HTML")
    except Exception as e:
        logging.error(f"ОШИБКА УВЕДОМЛЕНИЯ: {e}")

async def process_invoice_payment(message: Message, invoice_id: str):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT amount, coin, is_activated, creator_id FROM checks WHERE id = %s", (invoice_id,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return await message.answer("Счет не найден.")
    amount, coin, is_activated, creator_id = row
    if is_activated: cur.close(); con.close(); return await message.answer("Этот счет уже оплачен.")
    if creator_id == message.from_user.id: cur.close(); con.close(); return await message.answer("Нельзя оплатить свой же счет.")
    balance_field = f"{coin.lower()}_balance"
    cur.execute(f"SELECT {balance_field} FROM users WHERE user_id = %s", (message.from_user.id,))
    payer = cur.fetchone()
    if not payer or payer[0] < amount:
        cur.close(); con.close()
        return await message.answer(f"Недостаточно {coin} для оплаты счета.")
    cur.execute(f"UPDATE users SET {balance_field} = {balance_field} - %s WHERE user_id = %s", (amount, message.from_user.id))
    cur.execute(f"UPDATE users SET {balance_field} = {balance_field} + %s WHERE user_id = %s", (amount, creator_id))
    cur.execute("UPDATE checks SET is_activated = true, activated_by = %s WHERE id = %s", (message.from_user.id, invoice_id))
    con.commit(); cur.close(); con.close()
    await message.answer(f"Вы оплатили счет на {amount} {coin}!")
    try:
        user_info = await bot.get_chat(message.from_user.id)
        name = user_info.first_name or "Пользователь"
        if user_info.username: name = f"@{user_info.username}"
        user_link = f'<a href="tg://user?id={message.from_user.id}">{name}</a>'
        await bot.send_message(creator_id, f"🔔 Ваш счет на {amount} {coin} оплатил {user_link}!", parse_mode="HTML")
    except Exception as e:
        logging.error(f"ОШИБКА УВЕДОМЛЕНИЯ: {e}")

@dp.message(Command("admin_panel"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Обнулить балансы", callback_data="reset_all_balances")]])
    await message.answer("Админ-панель:", reply_markup=kb)

@dp.callback_query(F.data == "reset_all_balances")
async def reset_all_balances(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET usdt_balance = 0, gram_balance = 0, sol_balance = 0, trx_balance = 0")
    con.commit(); cur.close(); con.close()
    await callback.message.answer("Все балансы обнулены.")
    await callback.answer()

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

# === ВЕБ-СЕРВЕР ===
async def handle_ping(request): return web.Response(text="OK")

async def handle_buy_request(request):
    try:
        data = await request.json()
        user_id, coin, amount, stars = int(data.get("user_id")), data.get("coin"), float(data.get("amount")), int(data.get("stars"))
        await bot.send_invoice(chat_id=user_id, title=f"Покупка {amount} {coin}", description=f"Оплата {stars} Stars", payload=f"buycrypto_{coin}_{amount}", provider_token="", currency="XTR", prices=[LabeledPrice(label="XTR", amount=stars)])
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error"}, status=500)

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', handle_ping)
    app.router.add_post('/buy', handle_buy_request)
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
