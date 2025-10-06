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
OMDB_API_KEY = os.getenv("OMDB_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN manquant.")
if not OMDB_API_KEY:
    raise ValueError("❌ OMDB_API_KEY manquant.")

app = FastAPI()

# === OMDb API ===
async def search_omdb(query: str, max_results=10):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "http://www.omdbapi.com/",
            params={"apikey": OMDB_API_KEY, "s": query}
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("Response") == "True":
                return data.get("Search", [])[:max_results]
        return []

async def get_omdb_details(imdb_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "http://www.omdbapi.com/",
            params={"apikey": OMDB_API_KEY, "i": imdb_id}
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("Response") == "True":
                return data
        return None

# === UTILS ===
def clean_poster_url(url: str) -> str:
    if not url or url == "N/A":
        return "https://via.placeholder.com/300x450/333333/FFFFFF?text=🎬+Affiche+non+dispo"
    return url if url.startswith("http") else "https://via.placeholder.com/300x450/333333/FFFFFF?text=🎬+Affiche+non+dispo"

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Tapez <b>@votre_bot nom_du_film</b> pour une recherche instantanée !",
        parse_mode=ParseMode.HTML
    )

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        await update.inline_query.answer([], cache_time=1)
        return

    movies = await search_omdb(query)
    results = []
    for m in movies:
        title = m.get("Title", "N/A")
        year = m.get("Year", "N/A")
        imdb_id = m.get("imdbID", "")
        poster = clean_poster_url(m.get("Poster", ""))

        results.append(
            InlineQueryResultArticle(
                id=f"omdb_{imdb_id}",
                title=title,
                description=year,
                thumbnail_url=poster,
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

    if result_id.startswith("omdb_"):
        imdb_id = result_id.replace("omdb_", "")
        movie = await get_omdb_details(imdb_id)
        if movie:
            title = movie.get("Title", "N/A")
            year = movie.get("Year", "N/A")
            rating = movie.get("imdbRating", "N/A")
            genre = movie.get("Genre", "N/A")
            plot = movie.get("Plot", "Aucune description.")
            poster = clean_poster_url(movie.get("Poster"))

            text = (
                f"🎬 <b>{title}</b> ({year})\n"
                f"⭐ Note : {rating}/10\n"
                f"🎭 Genres : {genre}\n\n"
                f"{plot}\n\n"
                f"🔗 <a href='https://www.imdb.com/title/{imdb_id}/'>Voir sur IMDB</a>"
            )

            try:
                if "placeholder" not in poster:
                    await context.bot.send_photo(user.id, photo=poster, caption=text, parse_mode=ParseMode.HTML)
                else:
                    await context.bot.send_message(user.id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.error(f"Erreur envoi photo: {e}")
                await context.bot.send_message(user.id, text, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(user.id, "❌ Film non trouvé.")
    else:
        await context.bot.send_message(user.id, "❌ Résultat invalide.")

# === LANCEMENT ===
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(InlineQueryHandler(inline_query))
telegram_app.add_handler(ChosenInlineResultHandler(chosen_result))

@app.on_event("startup")
async def startup():
    logging.info("✅ Bot démarré avec OMDb.")
    if WEBHOOK_URL:
        await telegram_app.bot.set_webhook(WEBHOOK_URL)

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
def health():
    return {"status": "✅ Bot OMDb - Inline activé"}