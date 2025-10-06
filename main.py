import os
import logging
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN manquant dans les variables d'environnement.")
if not IMDB_API_KEY:
    raise ValueError("❌ IMDB_API_KEY manquant dans les variables d'environnement.")

# === FASTAPI ===
app = FastAPI()

# === IMDB ===
# === IMDB ===
async def search_imdb(query: str, max_results=10):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://imdb-api.com/en/API/SearchMovie",  # ✅ pas d'espace
            params={"apiKey": IMDB_API_KEY, "expression": query}
        )
        return r.json().get("results", [])[:max_results] if r.status_code == 200 else []

async def get_imdb_details(imdb_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"https://imdb-api.com/en/API/Title/{IMDB_API_KEY}/{imdb_id}")  # ✅ pas d'espace
        return r.json() if r.status_code == 200 else None

# === TELEGRAM HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Bienvenue !\n\nTapez <b>@votre_bot nom_du_film</b> dans n'importe quelle discussion pour une recherche instantanée !",
        parse_mode=ParseMode.HTML
    )

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        await update.inline_query.answer([], cache_time=1)
        return

    movies = await search_imdb(query)
    results = []
    for m in movies:
        title = m.get("title", "N/A")
        year = m.get("description", "").split("–")[0].strip() or "N/A"
        imdb_id = m.get("id", "")
        image = m.get("image", "https://via.placeholder.com/100?text=No+Image")

        results.append(
            InlineQueryResultArticle(
                id=f"imdb_{imdb_id}",
                title=title,
                description=year,
                thumbnail_url=image,
                input_message_content=InputTextMessageContent(
                    f"🎬 <b>{title}</b> ({year})\n\n🔍 Chargement des détails...",
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
                f"⭐ Note : {movie.get('imDbRating', 'N/A')}/10\n"
                f"🎭 Genres : {movie.get('genres', 'N/A')}\n\n"
                f"{movie.get('plot', 'Aucune description disponible.')}\n\n"
                f"🔗 <a href='https://www.imdb.com/title/{imdb_id}/'>Voir sur IMDB</a>"
            )
            photo = movie.get("image")
            try:
                if photo:
                    await context.bot.send_photo(user.id, photo, caption=text, parse_mode=ParseMode.HTML)
                else:
                    await context.bot.send_message(user.id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.error(f"Erreur envoi message: {e}")
                await context.bot.send_message(user.id, "✅ Fiche du film chargée.")
        else:
            await context.bot.send_message(user.id, "❌ Impossible de charger les détails du film.")
    else:
        await context.bot.send_message(user.id, "❌ Résultat invalide.")

# === LANCEMENT ===
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(InlineQueryHandler(inline_query))
telegram_app.add_handler(ChosenInlineResultHandler(chosen_result))

@app.on_event("startup")
async def startup():
    logging.info("Démarrage du bot...")
    if WEBHOOK_URL:
        await telegram_app.bot.set_webhook(WEBHOOK_URL)
        logging.info(f"Webhook défini : {WEBHOOK_URL}")
    else:
        logging.warning("WEBHOOK_URL non défini — mode webhook désactivé")

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
def health():
    return {"status": "✅ MovieBot Inline Ready"}