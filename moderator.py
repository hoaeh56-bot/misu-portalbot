import asyncio, logging, os, psycopg2, aiohttp_cors
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import config

logging.basicConfig(level=logging.INFO)
ADMIN_ID = 1780243441
PORTAL_URL = "https://misu-portal.vercel.app"

session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER))
bot = Bot(token=config.TOKEN, session=session)
dp = Dispatcher()
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres.ptcofqwsvyytcnoerazu:22E%23bS%23aMcN%40L6A@aws-0-eu-north-1.pooler.supabase.com:5432/postgres")
def get_db(): return psycopg2.connect(DATABASE_URL)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    avatar_url = ""
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            file = await bot.get_file(file_id)
            avatar_url = f"{config.API_SERVER}/file/bot{config.TOKEN}/{file.file_path}"
    except Exception as e:
        logging.error(f"Ава: {e}")

    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (message.from_user.id,))
        if cur.fetchone():
            cur.execute("UPDATE users SET username=%s, first_name=%s, avatar_url=%s WHERE user_id=%s", (message.from_user.username or "", message.from_user.first_name or "User", avatar_url, message.from_user.id))
        else:
            cur.execute("INSERT INTO users (user_id, username, first_name, avatar_url, wallet_address) VALUES (%s,%s,%s,%s,%s)", (message.from_user.id, message.from_user.username or "", message.from_user.first_name or "User", avatar_url, 'T'+str(message.from_user.id)))
        con.commit(); cur.close(); con.close()
    except Exception as e: logging.error(f"DB: {e}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open Portals", web_app=WebAppInfo(url=f"{PORTAL_URL}?user_id={message.from_user.id}"))],
        [InlineKeyboardButton(text="Join the community", url="https://t.me/theportal")],
        [InlineKeyboardButton(text="Contact support", url="https://t.me/zovmode")]
    ])
    try: await message.answer_photo(photo="AgACAgUAAxkBAAEkFMxq5h_wwNR23b-9n7xdcqax53MvQwACaxVrG3VpMFf7gjXKqUmioQEAAwIAA3kAAz0E", caption="Welcome to Portals!", reply_markup=kb)
    except: await message.answer("Welcome to Portals!", reply_markup=kb)

async def notify(request):
    d = await request.json()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зачислить", callback_data=f"ap_{d['user_id']}_{d['gift_name']}")]])
    await bot.send_message(ADMIN_ID, f"Заявка от {d['user_id']}: {d['gift_name']}", reply_markup=kb)
    return web.json_response({"status":"ok"})

@dp.callback_query(F.data.startswith("ap_"))
async def approve(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    p = c.data.split("_", 2); uid = int(p[1]); gname = p[2]
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO inventory (user_id, gift_name, gift_id, status) VALUES (%s,%s,'manual','inventory')", (uid, gname))
    con.commit(); cur.close(); con.close()
    await c.message.edit_text(f"✅ {gname} зачислен!")
    await bot.send_message(uid, f"🎁 {gname} в инвентаре!")

async def buy(request):
    d = await request.json()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name FROM market_items WHERE id=%s AND is_sold=false", (d["gift_id"],))
    item = cur.fetchone()
    if not item: return web.json_response({"status":"error"}, status=400)
    cur.execute("SELECT gram_balance,balance FROM users WHERE user_id=%s", (d["user_id"],))
    row = cur.fetchone()
    if not row or float(row[0])<float(d["price_gram"]): return web.json_response({"status":"error"}, status=400)
    ng = float(row[0])-float(d["price_gram"]); nc = int(row[1] or 0)+int(float(d["price_gram"])*100)
    cur.execute("UPDATE users SET gram_balance=%s,balance=%s WHERE user_id=%s", (ng,nc,d["user_id"]))
    if d.get("seller_id"): cur.execute("UPDATE users SET gram_balance=gram_balance+%s WHERE user_id=%s", (d["price_gram"], d["seller_id"]))
    cur.execute("UPDATE market_items SET is_sold=true WHERE id=%s", (d["gift_id"],))
    cur.execute("INSERT INTO inventory (user_id,gift_name,gift_id,status) VALUES (%s,%s,%s,'inventory')", (d["user_id"], item[0], d["gift_id"]))
    con.commit(); cur.close(); con.close()
    return web.json_response({"status":"ok","crystals":nc})

async def ping(r): return web.Response(text="OK")

async def ws():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get('/', ping)
    app.router.add_post('/notify_admin', notify)
    app.router.add_post('/buy_gift', buy)
    for r in list(app.router.routes()): cors.add(r)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000))).start()

async def main():
    asyncio.create_task(ws())
    logging.info("Старт...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e: logging.error(f"POLL: {e}")

if __name__ == "__main__":
    asyncio.run(main())
