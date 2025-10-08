import os
import re
import html
import asyncio
from typing import Optional, Dict, Any

import httpx
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters
)

# ===== CONFIGURATION =====
BOT_TOKEN = "TON_TOKEN_ICI"  # Remplace par ton token
OWNER_ID = 123456789  # Ton ID Telegram (obligatoire pour la sécurité)
TMDB_API_KEY = "ta_cle_tmdb_ici"  # Optionnel, mais requis pour /movie

# Footer par défaut
FOOTER = "@WorldZPrime"

# Polices "grasses" via caractères Unicode (éviter Markdown/HTML pour compatibilité)
def bold(text: str) -> str:
    # Mapping Unicode pour gras (ASCII + quelques lettres)
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    trans = str.maketrans(normal, bold)
    return text.translate(trans)

# ===== API AniList (animes) =====
async def fetch_anime_data(title: str) -> Optional[Dict[str, Any]]:
    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        title { romaji english native }
        format
        status
        genres
        startDate { year month day }
        endDate { year month day }
        studios(isMain: true) { nodes { name } }
        episodes
        duration
        popularity
        averageScore
        description(asHtml: false)
        coverImage { large }
        countryOfOrigin
      }
    }
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                "https://graphql.anilist.co",
                json={"query": query, "variables": {"search": title}}
            )
            data = resp.json()
            if "errors" in data or not data.get("data", {}).get("Media"):
                return None
            return data["data"]["Media"]
        except Exception:
            return None

# ===== API TMDB (films/séries) =====
async def fetch_movie_data(title: str) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Recherche
            search_resp = await client.get(
                f"https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title, "include_adult": "false"}
            )
            results = search_resp.json().get("results", [])
            if not results:
                return None
            movie_id = results[0]["id"]

            # Détails
            details_resp = await client.get(
                f"https://api.themoviedb.org/3/movie/{movie_id}",
                params={"api_key": TMDB_API_KEY, "append_to_response": "credits"}
            )
            return details_resp.json()
        except Exception:
            return None

# ===== Formatage =====
def format_anime(data: Dict[str, Any]) -> str:
    # Drapeau par pays
    flag_map = {"JP": "🇯🇵", "KR": "🇰🇷", "CN": "🇨🇳", "US": "🇺🇸"}
    flag = flag_map.get(data.get("countryOfOrigin", "JP"), "🌐")

    titles = data["title"]
    main_title = titles.get("romaji") or titles.get("english") or titles.get("native", "???")
    alt_titles = " / ".join(filter(None, [
        titles.get("english"),
        titles.get("native"),
        titles.get("romaji")
    ]))
    if alt_titles == main_title:
        alt_titles = main_title

    fmt = data.get("format", "?").replace("_", " ").title()
    status = data.get("status", "?").title()
    genres = " / ".join([f"{get_genre_emoji(g)} {g}" for g in data.get("genres", [])]) or "?"

    start = data.get("startDate", {})
    end = data.get("endDate", {})
    start_str = f"{start.get('day', '?')} {month_name(start.get('month'))} {start.get('year', '?')}" if start.get('year') else "?"
    end_str = f"{end.get('day', '?')} {month_name(end.get('month'))} {end.get('year', '?')}" if end.get('year') else "?"

    studio = data["studios"]["nodes"][0]["name"] if data["studios"]["nodes"] else "?"

    episodes = data.get("episodes") or "?"
    duration = f"{data.get('duration', '?')} min/épisode" if data.get("duration") else "?"

    popularity = f"#{data.get('popularity', '?')}"
    score = data.get("averageScore")
    rating = "★" * (score // 20) + "☆" * (5 - score // 20) if score else "?"

    desc = html.unescape(data.get("description", "Aucune description."))
    desc = re.sub(r'<[^>]+>', '', desc)  # Supprime balises HTML restantes
    desc = desc[:500] + "..." if len(desc) > 500 else desc

    msg = f"""{flag} {bold('𝗔𝗻𝗶𝗺𝗲')}: {main_title} / {alt_titles}

☾ - {bold('𝗙𝗼𝗿𝗺𝗮𝘁')}: {fmt}
☾ - {bold('𝗦𝘁𝗮𝘁𝘂𝘁')}: {status}
☾ - {bold('𝗚𝗲𝗻𝗿𝗲𝘀')}: {genres}

☾ - {bold('𝗔𝗻𝗻é𝗲')}: {start.get('year', '?')}
☾ - {bold('𝗗é𝗯𝘂𝘁')}: {start_str}
☾ - {bold('𝗙𝗶𝗻')}: {end_str}
☾ - {bold('𝗦𝘁𝘂𝗱𝗶𝗼')}: {studio}
☾ - {bold('𝗘𝗽𝗶𝘀𝗼𝗱𝗲𝘀')}: {episodes}
☾ - {bold('𝗗𝘂𝗿𝗲‌𝗲')}: {duration}
☾ - {bold('𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁é')}: {popularity}
☾ - {bold('𝗡𝗼𝘁𝗲')}: {rating}

╔═══『 ✦ 』═══╗
    {FOOTER}
╚═══『 ✦ 』═══╝

{bold('𝗥𝗲𝘀𝘂𝗺𝗲‌')}:
{desc}"""
    return msg

def format_movie(data: Dict[str, Any]) -> str:
    flag = "🇺🇸"  # TMDB = majoritairement US
    title = data.get("title", "???")
    release = data.get("release_date", "")
    year = release[:4] if release else "?"

    genres = " / ".join([f"{get_genre_emoji(g['name'])} {g['name']}" for g in data.get("genres", [])]) or "?"

    runtime = f"{data.get('runtime', '?')} min" if data.get("runtime") else "?"
    popularity = f"#{int(data.get('popularity', 0))}" if data.get("popularity") else "?"
    vote = data.get("vote_average", 0)
    rating = "★" * int(vote // 2) + "☆" * (5 - int(vote // 2)) if vote > 0 else "?"

    desc = html.unescape(data.get("overview", "Aucune description."))
    desc = desc[:500] + "..." if len(desc) > 500 else desc

    msg = f"""{flag} {bold('𝗙𝗶𝗹𝗺')}: {title}

☾ - {bold('𝗦𝘁𝗮𝘁𝘂𝘁')}: Released
☾ - {bold('𝗚𝗲𝗻𝗿𝗲𝘀')}: {genres}

☾ - {bold('𝗔𝗻𝗻é𝗲')}: {year}
☾ - {bold('𝗗𝘂𝗿é𝗲')}: {runtime}
☾ - {bold('𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁é')}: {popularity}
☾ - {bold('𝗡𝗼𝘁𝗲')}: {rating}

╔═══『 ✦ 』═══╗
    {FOOTER}
╚═══『 ✦ 』═══╝

{bold('𝗥𝗲𝘀𝘂𝗺𝗲‌')}:
{desc}"""
    return msg

# ===== Utilitaires =====
def get_genre_emoji(genre: str) -> str:
    emojis = {
        "Action": "🔫", "Aventure": "🌍", "Adventure": "🌍",
        "Fantaisie": "⚔", "Fantasy": "⚔", "Drame": "🎭", "Drama": "🎭",
        "Comédie": "😂", "Comedy": "😂", "Sci-Fi": "🚀", "Science Fiction": "🚀",
        "Horreur": "👻", "Horror": "👻", "Romance": "❤️", "Thriller": "🔪",
        "Mystery": "🕵️", "Crime": "👮", "Animation": "🎨", "Documentary": "📽️"
    }
    return emojis.get(genre, "🎬")

def month_name(month_num: Optional[int]) -> str:
    months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return months[month_num] if month_num and 1 <= month_num <= 12 else "?"

# ===== Commandes =====
async def set_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global FOOTER
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("UsageId : /setfooter @nouveaufooter")
        return
    FOOTER = " ".join(context.args)
    await update.message.reply_text(f"✅ Footer mis à jour : {FOOTER}")

async def cmd_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("UsageId : /anime <titre>")
        return
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Recherche : {query}...")
    data = await fetch_anime_data(query)
    if not data:
        await update.message.reply_text("❌ Aucun anime trouvé.")
        return

    msg = format_anime(data)
    image = data.get("coverImage", {}).get("large")

    # Envoi
    try:
        if image and len(msg) <= 1024:
            await update.message.reply_photo(photo=image, caption=msg)
        else:
            if image:
                await update.message.reply_photo(photo=image)
            await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Erreur envoi : {e}")

async def cmd_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("UsageId : /movie <titre>")
        return
    if not TMDB_API_KEY:
        await update.message.reply_text("❌ TMDB_API_KEY non configurée.")
        return
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Recherche film : {query}...")
    data = await fetch_movie_data(query)
    if not data:
        await update.message.reply_text("❌ Aucun film trouvé.")
        return

    msg = format_movie(data)
    poster_path = data.get("poster_path")
    image = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None

    try:
        if image and len(msg) <= 1024:
            await update.message.reply_photo(photo=image, caption=msg)
        else:
            if image:
                await update.message.reply_photo(photo=image)
            await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Erreur envoi : {e}")

# ===== Lancement =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("setfooter", set_footer))
    app.add_handler(CommandHandler("anime", cmd_anime))
    app.add_handler(CommandHandler("movie", cmd_movie))
    print("✅ Bot démarré !")
    app.run_polling()

if __name__ == "__main__":
    main()