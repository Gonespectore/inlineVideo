import os
import re
import html
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import httpx
import asyncpg
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variables d'environnement
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
DATABASE_URL = os.environ.get("DATABASE_URL")

# ✅ Parsing des IDs autorisés
def parse_owner_ids() -> set[int]:
    """Parse OWNER_IDS depuis les variables d'environnement."""
    owner_ids_str = os.environ.get("OWNER_IDS", "").strip()
    if not owner_ids_str:
        owner_id = os.environ.get("OWNER_ID")
        if owner_id:
            try:
                return {int(owner_id)}
            except ValueError:
                raise ValueError(f"❌ OWNER_ID invalide : {owner_id}")
        raise ValueError("❌ OWNER_IDS ou OWNER_ID requis")
    
    try:
        ids = set()
        for part in re.split(r"[,\s]+", owner_ids_str):
            if part:
                ids.add(int(part))
        if not ids:
            raise ValueError("❌ Aucun ID valide trouvé")
        return ids
    except ValueError as e:
        raise ValueError(f"❌ Format invalide pour OWNER_IDS : {owner_ids_str}") from e

AUTHORIZED_USER_IDS = parse_owner_ids()

# Validation de la configuration
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN est requis")
if not AUTHORIZED_USER_IDS:
    raise ValueError("❌ Au moins un utilisateur autorisé requis")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL est requis (PostgreSQL)")
if not WEBHOOK_URL and ENVIRONMENT == "production":
    raise ValueError("❌ WEBHOOK_URL est requis en production")

logger.info(f"✅ {len(AUTHORIZED_USER_IDS)} utilisateur(s) autorisé(s)")

# Pool de connexions PostgreSQL
db_pool = None

# Cache en mémoire
_cache = {}

# --- TRADUCTIONS ---
TRANSLATIONS = {
    "fr": {
        "access_denied": "⛔ Accès refusé. Bot réservé aux utilisateurs autorisés.",
        "welcome": "👋 Bienvenue",
        "commands_available": "🎬 Commandes disponibles :",
        "search_anime": "Rechercher un anime",
        "search_movie": "Rechercher un film",
        "change_footer": "Changer le footer",
        "change_language": "Changer la langue",
        "show_stats": "Voir les statistiques",
        "clear_cache": "Vider le cache",
        "show_help": "Affiche cette aide",
        "bot_by": "🤖 Bot développé par",
        "searching": "🔍 Recherche en cours:",
        "no_results": "❌ Aucun résultat trouvé. Essayez un autre titre.",
        "select_result": "📋 Sélectionnez un résultat :",
        "usage": "📝 Usage:",
        "example": "Exemple:",
        "footer_updated": "✅ Footer mis à jour:",
        "current_footer": "Footer actuel:",
        "language_updated": "✅ Langue changée en:",
        "current_language": "Langue actuelle:",
        "cache_cleared": "🗑️ Cache vidé ({count} entrées supprimées)",
        "stats": "📊 Statistiques",
        "cache": "Cache",
        "entries": "entrées",
        "users_authorized": "Utilisateurs autorisés",
        "environment": "Environnement",
        "configured": "✅ Configuré",
        "not_configured": "❌ Non configuré",
        "time": "🕐 Heure",
        "error_sending": "❌ Erreur lors de l'envoi. Réessayez.",
        "error_unexpected": "❌ Erreur inattendue. Contactez le développeur.",
        "tmdb_not_configured": "❌ TMDB_API_KEY non configurée.",
        "anime": "𝗔𝗻𝗶𝗺𝗲",
        "film": "𝗙𝗶𝗹𝗺",
        "format": "𝗙𝗼𝗿𝗺𝗮𝘁",
        "status": "𝗦𝘁𝗮𝘁𝘂𝘁",
        "genres": "𝗚𝗲𝗻𝗿𝗲𝘀",
        "year": "𝗔𝗻𝗻é𝗲",
        "start": "𝗗é𝗯𝘂𝘁",
        "end": "𝗙𝗶𝗻",
        "studio": "𝗦𝘁𝘂𝗱𝗶𝗼",
        "episodes": "𝗘𝗽𝗶𝘀𝗼𝗱𝗲𝘀",
        "duration": "𝗗𝘂𝗿é𝗲",
        "popularity": "𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁é",
        "rating": "𝗡𝗼𝘁𝗲",
        "summary": "𝗥𝗲𝘀𝘂𝗺𝗲",
        "status_finished": "Terminé",
        "status_releasing": "En cours",
        "status_upcoming": "À venir",
        "status_cancelled": "Annulé",
        "status_released": "Sorti",
        "no_description": "Aucune description.",
    },
    "en": {
        "access_denied": "⛔ Access denied. Bot reserved for authorized users.",
        "welcome": "👋 Welcome",
        "commands_available": "🎬 Available commands:",
        "search_anime": "Search an anime",
        "search_movie": "Search a movie",
        "change_footer": "Change footer",
        "change_language": "Change language",
        "show_stats": "View statistics",
        "clear_cache": "Clear cache",
        "show_help": "Show this help",
        "bot_by": "🤖 Bot developed by",
        "searching": "🔍 Searching:",
        "no_results": "❌ No results found. Try another title.",
        "select_result": "📋 Select a result:",
        "usage": "📝 Usage:",
        "example": "Example:",
        "footer_updated": "✅ Footer updated:",
        "current_footer": "Current footer:",
        "language_updated": "✅ Language changed to:",
        "current_language": "Current language:",
        "cache_cleared": "🗑️ Cache cleared ({count} entries removed)",
        "stats": "📊 Statistics",
        "cache": "Cache",
        "entries": "entries",
        "users_authorized": "Authorized users",
        "environment": "Environment",
        "configured": "✅ Configured",
        "not_configured": "❌ Not configured",
        "time": "🕐 Time",
        "error_sending": "❌ Error sending. Try again.",
        "error_unexpected": "❌ Unexpected error. Contact developer.",
        "tmdb_not_configured": "❌ TMDB_API_KEY not configured.",
        "anime": "𝗔𝗻𝗶𝗺𝗲",
        "film": "𝗠𝗼𝘃𝗶𝗲",
        "format": "𝗙𝗼𝗿𝗺𝗮𝘁",
        "status": "𝗦𝘁𝗮𝘁𝘂𝘀",
        "genres": "𝗚𝗲𝗻𝗿𝗲𝘀",
        "year": "𝗬𝗲𝗮𝗿",
        "start": "𝗦𝘁𝗮𝗿𝘁",
        "end": "𝗘𝗻𝗱",
        "studio": "𝗦𝘁𝘂𝗱𝗶𝗼",
        "episodes": "𝗘𝗽𝗶𝘀𝗼𝗱𝗲𝘀",
        "duration": "𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻",
        "popularity": "𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝘁𝘆",
        "rating": "𝗥𝗮𝘁𝗶𝗻𝗴",
        "summary": "𝗦𝘂𝗺𝗺𝗮𝗿𝘆",
        "status_finished": "Finished",
        "status_releasing": "Releasing",
        "status_upcoming": "Upcoming",
        "status_cancelled": "Cancelled",
        "status_released": "Released",
        "no_description": "No description.",
    },
    "es": {
        "access_denied": "⛔ Acceso denegado. Bot reservado para usuarios autorizados.",
        "welcome": "👋 Bienvenido",
        "commands_available": "🎬 Comandos disponibles:",
        "search_anime": "Buscar un anime",
        "search_movie": "Buscar una película",
        "change_footer": "Cambiar pie de página",
        "change_language": "Cambiar idioma",
        "show_stats": "Ver estadísticas",
        "clear_cache": "Limpiar caché",
        "show_help": "Mostrar esta ayuda",
        "bot_by": "🤖 Bot desarrollado por",
        "searching": "🔍 Buscando:",
        "no_results": "❌ No se encontraron resultados. Intenta otro título.",
        "select_result": "📋 Selecciona un resultado:",
        "usage": "📝 Uso:",
        "example": "Ejemplo:",
        "footer_updated": "✅ Pie de página actualizado:",
        "current_footer": "Pie de página actual:",
        "language_updated": "✅ Idioma cambiado a:",
        "current_language": "Idioma actual:",
        "cache_cleared": "🗑️ Caché limpiado ({count} entradas eliminadas)",
        "stats": "📊 Estadísticas",
        "cache": "Caché",
        "entries": "entradas",
        "users_authorized": "Usuarios autorizados",
        "environment": "Entorno",
        "configured": "✅ Configurado",
        "not_configured": "❌ No configurado",
        "time": "🕐 Hora",
        "error_sending": "❌ Error al enviar. Inténtalo de nuevo.",
        "error_unexpected": "❌ Error inesperado. Contacta al desarrollador.",
        "tmdb_not_configured": "❌ TMDB_API_KEY no configurada.",
        "anime": "𝗔𝗻𝗶𝗺𝗲",
        "film": "𝗣𝗲𝗹í𝗰𝘂𝗹𝗮",
        "format": "𝗙𝗼𝗿𝗺𝗮𝘁𝗼",
        "status": "𝗘𝘀𝘁𝗮𝗱𝗼",
        "genres": "𝗚é𝗻𝗲𝗿𝗼𝘀",
        "year": "𝗔ñ𝗼",
        "start": "𝗜𝗻𝗶𝗰𝗶𝗼",
        "end": "𝗙𝗶𝗻",
        "studio": "𝗘𝘀𝘁𝘂𝗱𝗶𝗼",
        "episodes": "𝗘𝗽𝗶𝘀𝗼𝗱𝗶𝗼𝘀",
        "duration": "𝗗𝘂𝗿𝗮𝗰𝗶ó𝗻",
        "popularity": "𝗣𝗼𝗽𝘂𝗹𝗮𝗿𝗶𝗱𝗮𝗱",
        "rating": "𝗖𝗮𝗹𝗶𝗳𝗶𝗰𝗮𝗰𝗶ó𝗻",
        "summary": "𝗥𝗲𝘀𝘂𝗺𝗲𝗻",
        "status_finished": "Terminado",
        "status_releasing": "En emisión",
        "status_upcoming": "Próximo",
        "status_cancelled": "Cancelado",
        "status_released": "Estrenado",
        "no_description": "Sin descripción.",
    }
}

# --- DATABASE ---
async def init_db():
    """Initialise la base de données PostgreSQL."""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id BIGINT PRIMARY KEY,
                language VARCHAR(5) DEFAULT 'fr',
                footer TEXT DEFAULT '@WorldZPrime',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS global_stats (
                key VARCHAR(50) PRIMARY KEY,
                value BIGINT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Initialiser les stats globales
        await conn.execute("""
            INSERT INTO global_stats (key, value) 
            VALUES ('total_searches', 0)
            ON CONFLICT (key) DO NOTHING
        """)
    
    logger.info("✅ Base de données PostgreSQL initialisée")

async def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Récupère les paramètres d'un utilisateur."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT language, footer FROM user_settings WHERE user_id = $1",
            user_id
        )
        if row:
            return {"language": row["language"], "footer": row["footer"]}
        
        # Créer les paramètres par défaut
        await conn.execute(
            "INSERT INTO user_settings (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )
        return {"language": "fr", "footer": "@WorldZPrime"}

async def update_user_language(user_id: int, language: str):
    """Met à jour la langue d'un utilisateur."""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, language, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id) 
            DO UPDATE SET language = $2, updated_at = NOW()
        """, user_id, language)

async def update_user_footer(user_id: int, footer: str):
    """Met à jour le footer d'un utilisateur."""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, footer, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id) 
            DO UPDATE SET footer = $2, updated_at = NOW()
        """, user_id, footer)

async def increment_stat(key: str):
    """Incrémente une statistique globale."""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO global_stats (key, value, updated_at)
            VALUES ($1, 1, NOW())
            ON CONFLICT (key) 
            DO UPDATE SET value = global_stats.value + 1, updated_at = NOW()
        """, key)

async def get_global_stats() -> Dict[str, int]:
    """Récupère toutes les statistiques globales."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM global_stats")
        return {row["key"]: row["value"] for row in rows}

# --- UTILITAIRES ---
def t(key: str, lang: str = "fr", **kwargs) -> str:
    """Traduit une clé dans la langue spécifiée."""
    text = TRANSLATIONS.get(lang, TRANSLATIONS["fr"]).get(key, key)
    return text.format(**kwargs) if kwargs else text

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

def month_name(m: int, lang: str = "fr") -> str:
    """Retourne le nom du mois."""
    months = {
        "fr": ["", "janvier", "février", "mars", "avril", "mai", "juin",
               "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
        "en": ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"],
        "es": ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    }
    return months.get(lang, months["fr"])[m] if 1 <= m <= 12 else "?"

def is_owner(user_id: int) -> bool:
    """Vérifie si l'utilisateur est autorisé."""
    return user_id in AUTHORIZED_USER_IDS

def sanitize_text(text: str, max_length: int = 480) -> str:
    """Nettoie et tronque le texte."""
    text = re.sub(r'<[^>]+>', '', html.unescape(text)).strip()
    return (text[:max_length] + "...") if len(text) > max_length else (text or "")

# --- API ---
async def search_anime(title: str) -> Optional[List[Dict[str, Any]]]:
    """Recherche plusieurs animes."""
    cache_key = f"anime_search:{title.lower()}"
    if cache_key in _cache:
        logger.info(f"Cache hit pour: {title}")
        return _cache[cache_key]

    query = """
    query ($search: String) {
      Page(page: 1, perPage: 5) {
        media(search: $search, type: ANIME) {
          id title { romaji english native } format status genres
          startDate { year month day } endDate { year month day }
          studios(isMain: true) { nodes { name } } episodes duration
          popularity averageScore description(asHtml: false)
          coverImage { large } countryOfOrigin
        }
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
            results = r.json().get("data", {}).get("Page", {}).get("media", [])
            if results:
                _cache[cache_key] = results
                logger.info(f"✅ {len(results)} anime(s) trouvé(s)")
            return results
    except Exception as e:
        logger.error(f"❌ Erreur recherche anime: {e}")
    return None

async def search_movie(title: str) -> Optional[List[Dict[str, Any]]]:
    """Recherche plusieurs films."""
    if not TMDB_API_KEY:
        return None
    
    cache_key = f"movie_search:{title.lower()}"
    if cache_key in _cache:
        logger.info(f"Cache hit pour: {title}")
        return _cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            search = await client.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title.strip(), "language": "fr-FR"}
            )
            search.raise_for_status()
            results = search.json().get("results", [])[:5]
            
            if results:
                _cache[cache_key] = results
                logger.info(f"✅ {len(results)} film(s) trouvé(s)")
            return results
            
    except Exception as e:
        logger.error(f"❌ Erreur recherche film: {e}")
    return None

async def get_movie_details(movie_id: int) -> Optional[Dict[str, Any]]:
    """Récupère les détails d'un film."""
    cache_key = f"movie_details:{movie_id}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            details = await client.get(
                f"https://api.themoviedb.org/3/movie/{movie_id}",
                params={"api_key": TMDB_API_KEY, "language": "fr-FR"}
            )
            details.raise_for_status()
            data = details.json()
            _cache[cache_key] = data
            return data
    except Exception as e:
        logger.error(f"❌ Erreur détails film: {e}")
    return None

# --- FORMATTAGE ---
def format_anime(data: Dict[str, Any], lang: str, footer: str) -> str:
    """Formate les données d'un anime."""
    flag = get_flag(data.get("countryOfOrigin", "JP"))
    titles = data["title"]
    main = titles.get("romaji") or titles.get("english") or "???"
    alts = list(dict.fromkeys(filter(None, [titles.get("english"), titles.get("native")])))
    alt_str = " / ".join(alts[:2]) if alts else ""

    fmt = data.get("format", "?").replace("_", " ").title()
    status_map = {
        "FINISHED": t("status_finished", lang),
        "RELEASING": t("status_releasing", lang),
        "NOT_YET_RELEASED": t("status_upcoming", lang),
        "CANCELLED": t("status_cancelled", lang)
    }
    status = status_map.get(data.get("status", "?"), data.get("status", "?"))
    genres = " / ".join(f"{get_genre_emoji(g)} {g}" for g in data.get("genres", [])[:4]) or "?"

    start = data.get("startDate", {})
    end = data.get("endDate", {})
    start_str = f"{start.get('day', '?')} {month_name(start.get('month') or 0, lang)} {start.get('year', '?')}" if start.get('year') else "?"
    end_str = f"{end.get('day', '?')} {month_name(end.get('month') or 0, lang)} {end.get('year', '?')}" if end.get('year') else "?"

    studio = data["studios"]["nodes"][0]["name"] if data.get("studios", {}).get("nodes") else "?"
    episodes = data.get("episodes", "?")
    duration = f"{data.get('duration', '?')} min/ép"
    popularity = f"#{data.get('popularity', '?')}"
    score = data.get("averageScore")
    rating = "★" * (score // 20) + "☆" * (5 - score // 20) if score else "?"

    desc = sanitize_text(data.get("description", "")) or t("no_description", lang)

    return f"""{flag} {bold(t('anime', lang))}: {main}
{alt_str}

☾ {bold(t('format', lang))}: {fmt}
☾ {bold(t('status', lang))}: {status}
☾ {bold(t('genres', lang))}: {genres}

☾ {bold(t('year', lang))}: {start.get('year', '?')}
☾ {bold(t('start', lang))}: {start_str}
☾ {bold(t('end', lang))}: {end_str}
☾ {bold(t('studio', lang))}: {studio}
☾ {bold(t('episodes', lang))}: {episodes}
☾ {bold(t('duration', lang))}: {duration}
☾ {bold(t('popularity', lang))}: {popularity}
☾ {bold(t('rating', lang))}: {rating} ({score}/100)

╔═══『 ✦ 』═══╗
    {footer}
╚═══『 ✦ 』═══╝

{bold(t('summary', lang))}:
{desc}"""

def format_movie(data: Dict[str, Any], lang: str, footer: str) -> str:
    """Formate les données d'un film."""
    release = data.get("release_date", "")
    year = release[:4] if release else "?"
    genres = " / ".join(f"{get_genre_emoji(g['name'])} {g['name']}" for g in data.get("genres", [])[:4]) or "?"
    runtime = f"{data.get('runtime', '?')} min" if data.get("runtime") else "?"
    popularity = f"#{int(data.get('popularity', 0))}" if data.get("popularity") else "?"
    vote = data.get("vote_average", 0)
    rating = "★" * int(vote // 2) + "☆" * (5 - int(vote // 2)) if vote >= 1 else "?"

    desc = sanitize_text(data.get("overview", "")) or t("no_description", lang)

    return f"""🇺🇸 {bold(t('film', lang))}: {data.get('title', '???')}

☾ {bold(t('status', lang))}: {t('status_released', lang)}
☾ {bold(t('genres', lang))}: {genres}

☾ {bold(t('year', lang))}: {year}
☾ {bold(t('duration', lang))}: {runtime}
☾ {bold(t('popularity', lang))}: {popularity}
☾ {bold(t('rating', lang))}: {rating} ({vote}/10)

╔═══『 ✦ 』═══╗
    {footer}
╚═══『 ✦ 』═══╝

{bold(t('summary', lang))}:
{desc}"""

# --- COMMANDES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(t("access_denied"))
        logger.warning(f"❌ Accès refusé - User ID: {update.effective_user.id}")
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    footer = settings["footer"]
    
    welcome = f"""{t('welcome', lang)} !

{t('commands_available', lang)}
/anime <titre> - {t('search_anime', lang)}
/movie <titre> - {t('search_movie', lang)}
/setfooter <texte> - {t('change_footer', lang)}
/setlang <fr|en|es> - {t('change_language', lang)}
/stats - {t('show_stats', lang)}
/clearcache - {t('clear_cache', lang)}
/help - {t('show_help', lang)}

{t('bot_by', lang)} {footer}"""
    
    await update.message.reply_text(welcome)
    logger.info(f"✅ /start - User: {update.effective_user.username or update.effective_user.id}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help."""
    if not is_owner(update.effective_user.id):
        return
    await start(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stats - Affiche les statistiques GLOBALES."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    
    global_stats = await get_global_stats()
    
    stats_text = f"""{t('stats', lang)}

• {t('cache', lang)}: {len(_cache)} {t('entries', lang)}
• {t('users_authorized', lang)}: {len(AUTHORIZED_USER_IDS)}
• {t('environment', lang)}: {ENVIRONMENT}
• TMDB: {t('configured', lang) if TMDB_API_KEY else t('not_configured', lang)}
• Total recherches: {global_stats.get('total_searches', 0)}

{t('time', lang)}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    await update.message.reply_text(stats_text)

async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /clearcache - Vide le cache."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    
    global _cache
    count = len(_cache)
    _cache.clear()
    await update.message.reply_text(t("cache_cleared", lang, count=count))
    logger.info(f"Cache cleared by {update.effective_user.id}")

async def set_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /setfooter - Change le footer de l'utilisateur."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    
    if not context.args:
        await update.message.reply_text(
            f"{t('usage', lang)} /setfooter <nouveau footer>\n\n{t('current_footer', lang)} {settings['footer']}"
        )
        return
    
    new_footer = " ".join(context.args)
    await update_user_footer(update.effective_user.id, new_footer)
    await update.message.reply_text(f"{t('footer_updated', lang)}\n{new_footer}")
    logger.info(f"Footer changed by {update.effective_user.id} to: {new_footer}")

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /setlang - Change la langue de l'utilisateur."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    current_lang = settings["language"]
    
    if not context.args or context.args[0] not in ["fr", "en", "es"]:
        await update.message.reply_text(
            f"{t('usage', current_lang)} /setlang <fr|en|es>\n\n"
            f"{t('current_language', current_lang)} {current_lang}"
        )
        return
    
    new_lang = context.args[0]
    await update_user_language(update.effective_user.id, new_lang)
    
    lang_names = {"fr": "Français", "en": "English", "es": "Español"}
    await update.message.reply_text(
        f"{t('language_updated', new_lang)} {lang_names[new_lang]}"
    )
    logger.info(f"Language changed by {update.effective_user.id} to: {new_lang}")

async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /anime - Recherche un anime avec sélection."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    
    if not context.args:
        await update.message.reply_text(
            f"{t('usage', lang)} /anime <titre>\n\n{t('example', lang)} /anime Naruto"
        )
        return
    
    title = " ".join(context.args)
    msg = await update.message.reply_text(f"{t('searching', lang)} {title}...")
    
    try:
        results = await search_anime(title)
        if not results:
            await msg.edit_text(t("no_results", lang))
            return
        
        await increment_stat("total_searches")
        
        # Si un seul résultat, l'afficher directement
        if len(results) == 1:
            formatted = format_anime(results[0], lang, settings["footer"])
            img = results[0].get("coverImage", {}).get("large")
            
            if img and len(formatted) <= 1024:
                await update.message.reply_photo(img, caption=formatted)
                await msg.delete()
            else:
                if img:
                    await update.message.reply_photo(img)
                await msg.edit_text(formatted)
            return
        
        # Créer les boutons de sélection
        keyboard = []
        for i, result in enumerate(results):
            titles = result["title"]
            main = titles.get("romaji") or titles.get("english") or "???"
            year = result.get("startDate", {}).get("year", "?")
            button_text = f"{main} ({year})"[:60]
            keyboard.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"anime_{i}_{update.effective_user.id}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Stocker les résultats temporairement
        context.user_data[f"anime_results_{update.effective_user.id}"] = {
            "results": results,
            "settings": settings
        }
        
        await msg.edit_text(
            f"{t('select_result', lang)}\n\n" + 
            "\n".join([f"{i+1}. {r['title'].get('romaji', '???')}" for i, r in enumerate(results)]),
            reply_markup=reply_markup
        )
        
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        await msg.edit_text(t("error_sending", lang))
    except Exception as e:
        logger.error(f"Unexpected error in anime command: {e}")
        await msg.edit_text(t("error_unexpected", lang))

async def movie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /movie - Recherche un film avec sélection."""
    if not is_owner(update.effective_user.id):
        return
    
    settings = await get_user_settings(update.effective_user.id)
    lang = settings["language"]
    
    if not context.args:
        await update.message.reply_text(
            f"{t('usage', lang)} /movie <titre>\n\n{t('example', lang)} /movie Inception"
        )
        return
    
    if not TMDB_API_KEY:
        await update.message.reply_text(t("tmdb_not_configured", lang))
        return
    
    title = " ".join(context.args)
    msg = await update.message.reply_text(f"{t('searching', lang)} {title}...")
    
    try:
        results = await search_movie(title)
        if not results:
            await msg.edit_text(t("no_results", lang))
            return
        
        await increment_stat("total_searches")
        
        # Si un seul résultat, l'afficher directement
        if len(results) == 1:
            details = await get_movie_details(results[0]["id"])
            if details:
                formatted = format_movie(details, lang, settings["footer"])
                poster = details.get("poster_path")
                img = f"https://image.tmdb.org/t/p/original{poster}" if poster else None
                
                if img and len(formatted) <= 1024:
                    await update.message.reply_photo(img, caption=formatted)
                    await msg.delete()
                else:
                    if img:
                        await update.message.reply_photo(img)
                    await msg.edit_text(formatted)
            return
        
        # Créer les boutons de sélection
        keyboard = []
        for i, result in enumerate(results):
            title_text = result.get("title", "???")
            year = result.get("release_date", "")[:4] if result.get("release_date") else "?"
            button_text = f"{title_text} ({year})"[:60]
            keyboard.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"movie_{result['id']}_{update.effective_user.id}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Stocker les settings temporairement
        context.user_data[f"movie_settings_{update.effective_user.id}"] = settings
        
        await msg.edit_text(
            f"{t('select_result', lang)}\n\n" + 
            "\n".join([f"{i+1}. {r.get('title', '???')}" for i, r in enumerate(results)]),
            reply_markup=reply_markup
        )
        
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        await msg.edit_text(t("error_sending", lang))
    except Exception as e:
        logger.error(f"Unexpected error in movie command: {e}")
        await msg.edit_text(t("error_unexpected", lang))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les callbacks des boutons inline."""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    media_type = data_parts[0]
    user_id = int(data_parts[-1])
    
    # Vérifier que c'est bien l'utilisateur qui a fait la recherche
    if query.from_user.id != user_id:
        return
    
    try:
        if media_type == "anime":
            index = int(data_parts[1])
            cache_key = f"anime_results_{user_id}"
            
            if cache_key not in context.user_data:
                await query.edit_message_text("❌ Session expirée. Relancez la recherche.")
                return
            
            data = context.user_data[cache_key]
            result = data["results"][index]
            settings = data["settings"]
            
            formatted = format_anime(result, settings["language"], settings["footer"])
            img = result.get("coverImage", {}).get("large")
            
            if img and len(formatted) <= 1024:
                await query.message.reply_photo(img, caption=formatted)
                await query.delete_message()
            else:
                if img:
                    await query.message.reply_photo(img)
                await query.edit_message_text(formatted)
            
            # Nettoyer
            del context.user_data[cache_key]
            
        elif media_type == "movie":
            movie_id = int(data_parts[1])
            settings_key = f"movie_settings_{user_id}"
            
            if settings_key not in context.user_data:
                await query.edit_message_text("❌ Session expirée. Relancez la recherche.")
                return
            
            settings = context.user_data[settings_key]
            
            details = await get_movie_details(movie_id)
            if not details:
                await query.edit_message_text("❌ Erreur lors de la récupération des détails.")
                return
            
            formatted = format_movie(details, settings["language"], settings["footer"])
            poster = details.get("poster_path")
            img = f"https://image.tmdb.org/t/p/original{poster}" if poster else None
            
            if img and len(formatted) <= 1024:
                await query.message.reply_photo(img, caption=formatted)
                await query.delete_message()
            else:
                if img:
                    await query.message.reply_photo(img)
                await query.edit_message_text(formatted)
            
            # Nettoyer
            del context.user_data[settings_key]
            
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        await query.edit_message_text("❌ Erreur inattendue.")

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
    # Initialiser la base de données
    await init_db()
    
    # Définir les commandes du bot
    commands = [
        BotCommand("start", "Démarrer le bot"),
        BotCommand("anime", "Rechercher un anime"),
        BotCommand("movie", "Rechercher un film"),
        BotCommand("setfooter", "Changer le footer"),
        BotCommand("setlang", "Changer la langue"),
        BotCommand("stats", "Voir les statistiques"),
        BotCommand("clearcache", "Vider le cache"),
        BotCommand("help", "Aide"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Commandes du bot configurées")

async def post_shutdown(application: Application):
    """Nettoyage à l'arrêt."""
    if db_pool:
        await db_pool.close()
        logger.info("✅ Pool PostgreSQL fermé")

# --- LANCEMENT ---
def main():
    """Point d'entrée principal."""
    logger.info("🚀 Démarrage du bot...")
    
    # Construction de l'application
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("clearcache", clear_cache))
    app.add_handler(CommandHandler("setfooter", set_footer))
    app.add_handler(CommandHandler("setlang", set_language))
    app.add_handler(CommandHandler("anime", anime_command))
    app.add_handler(CommandHandler("movie", movie_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    # Démarrage
    if ENVIRONMENT == "production" and WEBHOOK_URL:
        logger.info(f"🌐 Mode webhook: {WEBHOOK_URL}/webhook")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="/webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook",
            allowed_updates=Update.ALL_TYPES
        )
    else:
        logger.info("🔄 Mode polling (développement)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()