import os
import json
import uuid
import sqlite3
import asyncio
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ForceReply
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from aiogram.types import InputRichMessage

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = os.getenv("DB_PATH", "data.sqlite3")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not WEBAPP_URL:
    raise RuntimeError("WEBAPP_URL is missing. For Render use https://YOUR-SERVICE.onrender.com")

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    html TEXT NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS saved_messages (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    html TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

# V2 channel publishing/editing fields (safe for existing SQLite DBs)
for table, coldef in [("saved_messages", "chat_id TEXT"), ("saved_messages", "message_id INTEGER"), ("drafts", "target_chat TEXT"), ("drafts", "saved_id TEXT")]:
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
    except sqlite3.OperationalError:
        pass
db.commit()

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

class NewMessage(StatesGroup):
    waiting_name = State()

def home_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Create New Message")],
            [KeyboardButton(text="📁 My Saved Messages")]
        ],
        resize_keyboard=True
    )

def composer_keyboard(draft_id: str):
    url = f"{WEBAPP_URL}/app?draft_id={draft_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Open Composer", web_app=WebAppInfo(url=url))]
    ])

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🤖 <b>Rich Message Bot</b>\n\n"
        "Create Telegram Rich Messages with headings, lists, tables, quotes, "
        "media, expandable sections, formulas and more.",
        reply_markup=home_keyboard()
    )

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Cancelled.", reply_markup=home_keyboard())

@router.message(F.text == "📝 Create New Message")
async def create_start(message: Message, state: FSMContext):
    await state.set_state(NewMessage.waiting_name)
    await message.answer(
        "✏️ <b>Please reply to this message with the name of your new Rich Message:</b>",
        reply_markup=ForceReply(selective=True)
    )

@router.message(NewMessage.waiting_name, F.text)
async def create_name(message: Message, state: FSMContext):
    name = message.text.strip()[:100]
    if not name:
        await message.answer("Please enter a name.")
        return
    draft_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO drafts(id,user_id,name,html) VALUES(?,?,?,?)",
        (draft_id, message.from_user.id, name, "")
    )
    db.commit()
    await state.clear()
    await message.answer(
        f"✅ <b>Message {name}</b> created!\n\n"
        "Click the button below to compose your Rich Message.",
        reply_markup=composer_keyboard(draft_id)
    )

@router.message(F.text == "📁 My Saved Messages")
async def saved_messages(message: Message):
    rows = db.execute(
        "SELECT id,name FROM saved_messages WHERE user_id=? ORDER BY updated_at DESC LIMIT 30",
        (message.from_user.id,)
    ).fetchall()
    if not rows:
        await message.answer("📁 <b>My Saved Messages</b>\n\nNo saved messages yet.")
        return
    buttons = [[InlineKeyboardButton(text=f"📄 {name}", callback_data=f"open:{sid}")]
               for sid, name in rows]
    await message.answer(
        "📁 <b>My Saved Messages</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("open:"))
async def open_saved(callback: CallbackQuery):
    sid = callback.data.split(":", 1)[1]
    row = db.execute(
        "SELECT name,html FROM saved_messages WHERE id=? AND user_id=?",
        (sid, callback.from_user.id)
    ).fetchone()
    if not row:
        await callback.answer("Not found", show_alert=True)
        return
    name, html = row
    draft_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO drafts(id,user_id,name,html,saved_id) VALUES(?,?,?,?,?)",
        (draft_id, callback.from_user.id, name, html, sid)
    )
    db.commit()
    await callback.message.answer(
        f"📄 <b>{name}</b>\n\nOpen it in the composer:",
        reply_markup=composer_keyboard(draft_id)
    )
    await callback.answer()

# Mini App API ---------------------------------------------------------------

async def api_get_draft(request):
    draft_id = request.match_info["draft_id"]
    row = db.execute(
        "SELECT id,user_id,name,html,saved_id FROM drafts WHERE id=?",
        (draft_id,)
    ).fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "Draft not found"}, status=404)
    return web.json_response({
        "ok": True,
        "id": row[0],
        "user_id": row[1],
        "name": row[2],
        "html": row[3]
    })

async def api_save_draft(request):
    draft_id = request.match_info["draft_id"]
    data = await request.json()
    html = str(data.get("html", ""))
    name = str(data.get("name", "Rich Message"))[:100]
    if len(html) > 350000:
        return web.json_response({"ok": False, "error": "Message is too large"}, status=400)

    row = db.execute("SELECT user_id FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "Draft not found"}, status=404)

    db.execute(
        "UPDATE drafts SET name=?,html=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (name, html, draft_id)
    )
    db.commit()

    sid = uuid.uuid4().hex
    db.execute(
        """INSERT INTO saved_messages(id,user_id,name,html)
           VALUES(?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name,html=excluded.html,
           updated_at=CURRENT_TIMESTAMP""",
        (sid, row[0], name, html)
    )
    db.commit()

    try:
        await bot.send_rich_message(
            chat_id=row[0],
            rich_message=InputRichMessage(
                html=html,
                skip_entity_detection=False
            )
        )
    except Exception as e:
        return web.json_response({
            "ok": False,
            "error": f"Telegram rejected the rich message: {e}"
        }, status=400)

    return web.json_response({"ok": True, "message": "Rich message sent and saved."})

async def api_send_channel(request):
    draft_id = request.match_info["draft_id"]
    data = await request.json()
    html = str(data.get("html", ""))
    name = str(data.get("name", "Rich Message"))[:100]
    chat_id = str(data.get("chat_id", "")).strip()
    if not chat_id:
        return web.json_response({"ok": False, "error": "Enter a channel @username or chat ID."}, status=400)
    if len(html) > 32768:
        return web.json_response({"ok": False, "error": "Rich message is over 32K characters."}, status=400)
    row = db.execute("SELECT user_id FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "Draft not found"}, status=404)
    try:
        sent = await bot.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=html, skip_entity_detection=False)
        )
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Telegram rejected it: {e}"}, status=400)
    sid = uuid.uuid4().hex
    db.execute("""INSERT INTO saved_messages(id,user_id,name,html,chat_id,message_id)
                   VALUES(?,?,?,?,?,?)""", (sid, row[0], name, html, chat_id, sent.message_id))
    db.execute("UPDATE drafts SET name=?,html=?,target_chat=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (name, html, chat_id, draft_id))
    db.commit()
    return web.json_response({"ok": True, "message": "Posted to channel and saved.", "message_id": sent.message_id, "chat_id": chat_id, "saved_id": sid})

async def api_edit_channel(request):
    sid = request.match_info["saved_id"]
    data = await request.json()
    html = str(data.get("html", ""))
    name = str(data.get("name", "Rich Message"))[:100]
    row = db.execute("SELECT user_id,chat_id,message_id FROM saved_messages WHERE id=?", (sid,)).fetchone()
    if not row or row[0] != int(data.get("user_id", 0)):
        return web.json_response({"ok": False, "error": "Saved message not found"}, status=404)
    if not row[1] or not row[2]:
        return web.json_response({"ok": False, "error": "This saved message has no channel post."}, status=400)
    try:
        await bot.edit_message_text(chat_id=row[1], message_id=row[2],
            rich_message=InputRichMessage(html=html, skip_entity_detection=False))
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Telegram rejected the edit: {e}"}, status=400)
    db.execute("UPDATE saved_messages SET name=?,html=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (name, html, sid))
    db.commit()
    return web.json_response({"ok": True, "message": "Channel post updated."})

async def api_preview(request):
    # Browser preview uses the same HTML the user is composing.
    data = await request.json()
    return web.json_response({"ok": True, "html": str(data.get("html", ""))})

async def health(request):
    return web.Response(text="OK")

async def app_handler(request):
    return web.FileResponse(Path(__file__).parent / "web" / "index.html")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/app", app_handler)
    app.router.add_get("/api/draft/{draft_id}", api_get_draft)
    app.router.add_post("/api/draft/{draft_id}", api_save_draft)
    app.router.add_post("/api/channel/{draft_id}", api_send_channel)
    app.router.add_post("/api/channel/edit/{saved_id}", api_edit_channel)
    app.router.add_post("/api/preview", api_preview)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print(f"Web server running on :{PORT}")
    print("Bot polling started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
