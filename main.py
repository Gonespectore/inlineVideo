import os
import logging
import asyncpg
import httpx
from fastapi import FastAPI, Request
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, InlineQueryHandler, ChosenInlineResultHandler, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
IMDB_API_KEY = os.getenv("IMDB_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# === FASTAPI ===
app = FastAPI()

# === IMDB ===
async def search_imdb(query: str, max_results=10):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://imdb-api.com/en/API/SearchMovie",
            params={"apiKey": IMDB_API_KEY, "expression": query}
        )
        return r.json().get("results", [])[:max_results] if r.status_code == 200 else []

async def get_imdb_details(imdb_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://imdb-api.com/en/API/Title/{IMDB_API_KEY}/{imdb_id}")
        return r.json() if r.status_code == 200 else None

# === DB ===
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await conn.close()

async def save_user(user_id, username):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        user_id, username
    )
    await conn.close()

# === TELEGRAM HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("🎬 Tapez @ce_bot nom_du_film pour chercher !")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        await update.inline_query.answer([], cache_time=1)
        return

    results = []
    movies = await search_imdb(query)
    for m in movies:
        results.append(
            InlineQueryResultArticle(
                id=f"imdb_{m['id']}",
                title=m["title"],
                description=m.get("description", "").split("–")[0].strip() or "N/A",
                thumbnail_url=m.get("image", "https://via.placeholder.com/100"),
                input_message_content=InputTextMessageContent(
                    f"🎬 <b>{m['title']}</b>\n\n🔍 Chargement...",
                    parse_mode=ParseMode.HTML
                )
            )
        )
    await update.inline_query.answer(results[:10], cache_time=300)

async def chosen_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result_id = update.chosen_inline_result.result_id
    user = update.chosen_inline_result.from_user

    if result_id.startswith("imdb_"):
        imdb_id = result_id.replace("imdb_", "")
        movie = await get_imdb_details(imdb_id)
        if movie and not movie.get("errorMessage"):
            text = (
                f"🎬 <b>{movie.get('title', 'N/A')}</b> ({movie.get('year', 'N/A')})\n"
                f"⭐ {movie.get('imDbRating', 'N/A')}/10\n"
                f"🎭 {movie.get('genres', 'N/A')}\n\n"
                f"{movie.get('plot', 'Aucune description.')}\n\n"
                f"🔗 <a href='https://www.imdb.com/title/{imdb_id}/'>IMDB</a>"
            )
            photo = movie.get("image")
            try:
                if photo:
                    await context.bot.send_photo(user.id, photo, caption=text, parse_mode=ParseMode.HTML)
                else:
                    await context.bot.send_message(user.id, text, parse_mode=ParseMode.HTML)
            except:
                await context.bot.send_message(user.id, "✅ Fiche du film envoyée.")
        else:
            await context.bot.send_message(user.id, "❌ Film non trouvé.")

# === LANCEMENT ===
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(InlineQueryHandler(inline_query))
telegram_app.add_handler(ChosenInlineResultHandler(chosen_result))

@app.on_event("startup")
async def startup():
    await init_db()
    if WEBHOOK_URL:
        await telegram_app.bot.set_webhook(WEBHOOK_URL)

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
def health():
    return {"status": "inline bot ready"}