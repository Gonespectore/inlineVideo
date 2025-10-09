import os
import re
import html
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import httpx
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variables d'environnement
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")

# Validation de la configuration
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN est requis")
if not OWNER_ID:
    raise ValueError("❌ OWNER_ID est requis")
if not WEBHOOK_URL and ENVIRONMENT == "production":
    raise ValueError("❌ WEBHOOK_URL est requis en production")

# État dynamique
_footer = os.environ.get("FOOTER", "@WorldZPrime")
_cache = {}  # Cache simple pour réduire les appels API

# --- UTILITAIRES ---
def bold(text: str) -> str:
    """Convertit le texte en caractères Unicode gras."""
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold_chars = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    return text.translate(str.maketrans(normal, bold_chars))

def get_flag(country: str) -> str:
    """Retourne le drapeau correspondant au pays."""
    flags = {
        "JP": "🇯🇵", "KR": "🇰🇷", "CN": "🇨🇳", "US": "🇺🇸",
        "FR": "🇫🇷", "GB": "🇬🇧", "DE": "🇩🇪", "ES": "🇪🇸",
        "IT": "🇮🇹", "CA": "🇨🇦", "AU": "🇦🇺", "IN": "🇮🇳"
    }
    return flags.get(country, "🌐")

def get_genre_emoji(genre: str) -> str:
    """Retourne l'emoji correspondant au genre."""
    emojis = {
        "Action": "🔫", "Adventure": "🌍", "Fantasy": "⚔", "Drama": "🎭",
        "Comedy": "😂", "Sci-Fi": "🚀", "Horror": "👻", "Romance": "❤️",
        "Thriller": "😱", "Mystery": "🔍", "Crime": "🚔", "Animation": "🎨",
        "Documentary": "📹", "Family": "👨‍👩‍👧", "Music": "🎵", "War": "⚔️",
        "History": "📜", "Sport": "⚽", "Western": "🤠"
    }
    return emojis.get(genre, "🎬")

def month_name(m: int) -> str:
    """Retourne le nom du mois en français."""
    months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return months[m] if 1 <= m <= 12 else "?"

def is_owner(user_id: int) -> bool:
    """Vérifie si l'utilisateur est le propriétaire."""
    return user_id == OWNER_ID

def sanitize_text(text: str, max_length: int = 480) -> str:
    """Nettoie et tronque le texte."""
    text = re.sub(r'<[^>]+>', '', html.unescape(text)).strip()
    return (text[:max_length] + "...") if len(text) > max_length else (text or "Aucune description.")

# --- API AVEC GESTION D'ERREURS ET CACHE ---
async def fetch_anime(title: str) -> Optional[Dict[str, Any]]:
    """Récupère les informations d'un anime depuis AniList."""
    cache_key = f"anime:{title.lower()}"
    if cache_key in _cache:
        logger.info(f"Cache hit pour: {title}")
        return _cache[cache_key]

    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id title { romaji english native } format status genres
        startDate { year month day } endDate { year month day }
        studios(isMain: true) { nodes { name } } episodes duration
        popularity averageScore description(asHtml: false)
        coverImage { large } countryOfOrigin season seasonYear
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://graphql.anilist.co",
                json={"query": query, "variables": {"search": title.strip()}},
                headers={"Content-Type": "application/json", "Accept": "application/json"}
            )
            r.raise_for_status()
            data = r.json().get("data", {}).get("Media")
            if data:
                _cache[cache_key] = data
                logger.info(f"✅ Anime trouvé: {data['title']['romaji']}")
            return data
    except httpx.TimeoutException:
        logger.error(f"⏱️ Timeout lors de la recherche: {title}")
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erreur HTTP {e.response.status_code}: {title}")
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
    return None

async def fetch_movie(title: str) -> Optional[Dict[str, Any]]:
    """Récupère les informations d'un film depuis TMDB."""
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY non configurée")
        return None

    cache_key = f"movie:{title.lower()}"
    if cache_key in _cache:
        logger.info(f"Cache hit pour: {title}")
        return _cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Recherche
            search = await client.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title.strip(), "language": "fr-FR"}
            )
            search.raise_for_status()
            results = search.json().get("results", [])
            
            if not results:
                return None
            
            movie_id = results[0]["id"]
            
            # Détails
            details = await client.get(
                f"https://api.themoviedb.org/3/movie/{movie_id}",
                params={"api_key": TMDB_API_KEY, "language": "fr-FR"}
            )
            details.raise_for_status()
            data = details.json()
            
            _cache[cache_key] = data
            logger.info(f"✅ Film trouvé: {data.get('title')}")
            return data
            
    except httpx.TimeoutException:
        logger.error(f"⏱️ Timeout lors de la recherche: {title}")
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erreur HTTP {e.response.status_code}: {title}")
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
    return None

# --- FORMATTAGE ---
def format_anime(data: Dict[str, Any]) -> str:
    """Formate les données d'un anime."""
    flag = get_flag(data.get("countryOfOrigin", "JP"))
    titles = data["title"]
    main = titles.get("romaji") or titles.get("english") or "???"
    alts = list(dict.fromkeys(filter(None, [titles.get("english"), titles.get("native"), titles.get("romaji")])))
    alt_str = " / ".join(alts[:2]) if alts else main

    fmt = data.get("format", "?").replace("_", " ").title()
    status = {"FINISHED": "Terminé", "RELEASING": "En cours", "NOT_YET_RELEASED": "À venir", "CANCELLED": "Annulé"}.get(
        data.get("status", "?"), data.get("status", "?")
    )
    genres = " / ".join(f"{get_genre_emoji(g)} {g}" for g in data.get("genres", [])[:4]) or "?"

    start = data.get("startDate", {})
    end = data.get("endDate", {})
    start_str = f"{start.get('day', '?')} {month_name(start.get('month') or 0)} {start.get('year', '?')}" if start.get('year') else "?"
    end_str = f"{end.get('day', '?')} {month_name(end.get('month') or 0)} {end.get('year', '?')}" if end.get('year') else "?"

    studio = data["studios"]["nodes"][0]["name"] if data.get("studios", {}).get("nodes") else "?"
    episodes = data.get("episodes", "?")
    duration = f"{data.get('duration', '?')} min/ép"
    popularity = f"#{data.get('popularity', '?')}"
    score = data.get("averageScore")
    rating = "★" * (score // 20) + "☆" * (5 - score // 20) if score else "?"

    desc = sanitize_text(data.get("description", ""))

    return f"""{flag} {bold('𝗔𝗻𝗶𝗺𝗲')}: {main}
{alt_str}

☾ {bold('𝗙𝗼𝗿𝗺𝗮𝘁')}: {fmt}
☾ {bold('𝗦𝘁𝗮𝘁𝘂𝘁')}: {status}
☾ {bold('𝗚𝗲𝗻𝗿𝗲𝘀')}: {genres}

☾ {bold('𝗔𝗻𝗻é𝗲')}: {start.get('year', '?')}
☾ {bold('𝗗é𝗯𝘂𝘁')}: {start_str}
☾ {bold('𝗙𝗶𝗻')}: {end_str}
☾ {bold('𝗦𝘁𝘂𝗱𝗶𝗼')}: {studio}
☾ {bold('𝗘𝗽𝗶𝘀𝗼𝗱𝗲𝘀')}: {episodes}
☾ {bold('𝗗𝘂𝗿é𝗲')}: {duration}
☾ {bold('𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁é')}: {popularity}
☾ {bold('𝗡𝗼𝘁𝗲')}: {rating} ({score}/100)

╔═══『 ✦ 』═══╗
    {_footer}
╚═══『 ✦ 』═══╝

{bold('𝗥𝗲𝘀𝘂𝗺𝗲')}:
{desc}"""

def format_movie(data: Dict[str, Any]) -> str:
    """Formate les données d'un film."""
    release = data.get("release_date", "")
    year = release[:4] if release else "?"
    genres = " / ".join(f"{get_genre_emoji(g['name'])} {g['name']}" for g in data.get("genres", [])[:4]) or "?"
    runtime = f"{data.get('runtime', '?')} min" if data.get("runtime") else "?"
    popularity = f"#{int(data.get('popularity', 0))}" if data.get("popularity") else "?"
    vote = data.get("vote_average", 0)
    rating = "★" * int(vote // 2) + "☆" * (5 - int(vote // 2)) if vote >= 1 else "?"

    desc = sanitize_text(data.get("overview", ""))

    return f"""🇺🇸 {bold('𝗙𝗶𝗹𝗺')}: {data.get('title', '???')}

☾ {bold('𝗦𝘁𝗮𝘁𝘂𝘁')}: Sorti
☾ {bold('𝗚𝗲𝗻𝗿𝗲𝘀')}: {genres}

☾ {bold('𝗔𝗻𝗻é𝗲')}: {year}
☾ {bold('𝗗𝘂𝗿é𝗲')}: {runtime}
☾ {bold('𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁é')}: {popularity}
☾ {bold('𝗡𝗼𝘁𝗲')}: {rating} ({vote}/10)

╔═══『 ✦ 』═══╗
    {_footer}
╚═══『 ✦ 』═══╝

{bold('𝗥𝗲𝘀𝘂𝗺𝗲')}:
{desc}"""

# --- COMMANDES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Accès refusé. Bot réservé au propriétaire.")
        return
    
    welcome = f"""👋 {bold('Bienvenue')} !

🎬 Commandes disponibles :
/anime <titre> - Recherche un anime
/movie <titre> - Recherche un film
/setfooter <texte> - Change le footer
/stats - Statistiques du bot
/clearcache - Vide le cache
/help - Affiche cette aide

🤖 Bot développé par {_footer}"""
    
    await update.message.reply_text(welcome)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help."""
    if not is_owner(update.effective_user.id):
        return
    await start(update, context)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stats - Affiche les statistiques."""
    if not is_owner(update.effective_user.id):
        return
    
    stats_text = f"""📊 {bold('Statistiques')}

• Cache: {len(_cache)} entrées
• Footer actuel: {_footer}
• Environnement: {ENVIRONMENT}
• TMDB: {'✅ Configuré' if TMDB_API_KEY else '❌ Non configuré'}

🕐 Uptime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    await update.message.reply_text(stats_text)

async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /clearcache - Vide le cache."""
    if not is_owner(update.effective_user.id):
        return
    
    global _cache
    count = len(_cache)
    _cache.clear()
    await update.message.reply_text(f"🗑️ Cache vidé ({count} entrées supprimées)")
    logger.info(f"Cache cleared by {update.effective_user.id}")

async def set_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /setfooter - Change le footer."""
    global _footer
    
    if not is_owner(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text(f"📝 Usage: /setfooter <nouveau footer>\n\nFooter actuel: {_footer}")
        return
    
    _footer = " ".join(context.args)
    await update.message.reply_text(f"✅ Footer mis à jour:\n{_footer}")
    logger.info(f"Footer changed to: {_footer}")

async def anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /anime - Recherche un anime."""
    if not is_owner(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("📝 Usage: /anime <titre>\n\nExemple: /anime Naruto")
        return
    
    title = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 Recherche en cours: {title}...")
    
    try:
        data = await fetch_anime(title)
        if not data:
            await msg.edit_text("❌ Aucun anime trouvé. Essayez un autre titre.")
            return
        
        formatted = format_anime(data)
        img = data.get("coverImage", {}).get("large")
        
        if img and len(formatted) <= 1024:
            await update.message.reply_photo(img, caption=formatted)
            await msg.delete()
        else:
            if img:
                await update.message.reply_photo(img)
            await msg.edit_text(formatted)
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        await msg.edit_text("❌ Erreur lors de l'envoi. Réessayez.")
    except Exception as e:
        logger.error(f"Unexpected error in anime command: {e}")
        await msg.edit_text("❌ Erreur inattendue. Contactez le développeur.")

async def movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /movie - Recherche un film."""
    if not is_owner(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("📝 Usage: /movie <titre>\n\nExemple: /movie Inception")
        return
    
    if not TMDB_API_KEY:
        await update.message.reply_text("❌ TMDB_API_KEY non configurée. Contactez le développeur.")
        return
    
    title = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 Recherche en cours: {title}...")
    
    try:
        data = await fetch_movie(title)
        if not data:
            await msg.edit_text("❌ Aucun film trouvé. Essayez un autre titre.")
            return
        
        formatted = format_movie(data)
        poster = data.get("poster_path")
        img = f"https://image.tmdb.org/t/p/original{poster}" if poster else None
        
        if img and len(formatted) <= 1024:
            await update.message.reply_photo(img, caption=formatted)
            await msg.delete()
        else:
            if img:
                await update.message.reply_photo(img)
            await msg.edit_text(formatted)
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        await msg.edit_text("❌ Erreur lors de l'envoi. Réessayez.")
    except Exception as e:
        logger.error(f"Unexpected error in movie command: {e}")
        await msg.edit_text("❌ Erreur inattendue. Contactez le développeur.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les erreurs globales."""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Une erreur s'est produite. Le développeur a été notifié."
            )
        except Exception:
            pass

async def post_init(application: Application):
    """Initialisation post-startup."""
    # Définir les commandes du bot
    commands = [
        BotCommand("start", "Démarrer le bot"),
        BotCommand("anime", "Rechercher un anime"),
        BotCommand("movie", "Rechercher un film"),
        BotCommand("setfooter", "Changer le footer"),
        BotCommand("stats", "Voir les statistiques"),
        BotCommand("clearcache", "Vider le cache"),
        BotCommand("help", "Aide"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Commandes du bot configurées")

# --- LANCEMENT ---
def main():
    """Point d'entrée principal."""
    logger.info("🚀 Démarrage du bot...")
    
    # Construction de l'application
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("clearcache", clear_cache))
    app.add_handler(CommandHandler("setfooter", set_footer))
    app.add_handler(CommandHandler("anime", anime))
    app.add_handler(CommandHandler("movie", movie))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    # Démarrage
    if ENVIRONMENT == "production" and WEBHOOK_URL:
        logger.info(f"🌐 Mode webhook: {WEBHOOK_URL}/webhook")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="/webhook",  # ✅ C'est ce que le serveur écoute localement
            webhook_url=f"{WEBHOOK_URL}/webhook",  # ✅ C'est ce que Telegram utilise
            allowed_updates=Update.ALL_TYPES
        )
    else:
        logger.info("🔄 Mode polling (développement)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()