from app.core.sectors import SECTORS, GROUPS
import os, secrets
from dataclasses import dataclass, field

@dataclass
class Settings:
    # App
    APP_NAME:    str  = "ATLAS PRO"
    APP_VERSION: str  = "3.3.0"
    SITE_URL:    str  = os.getenv("SITE_URL", "https://atlaspro.up.railway.app")
    SECRET_KEY:  str  = os.getenv("SECRET_KEY", "")
    DEBUG:       bool = os.getenv("DEBUG","false").lower() == "true"

    # Database
    DB_PATH:     str  = os.getenv("DB_PATH", "data/atlas.db")

    # Supabase (optionnel — cloud PostgreSQL)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # Auth
    ADMIN_PASS:      str = os.getenv("ADMIN_PASS", "atlas2026")
    JWT_EXPIRE_DAYS: int = 30

    # Scraping
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "60"))
    SCRAPER_TIMEOUT:   int = 20
    SCRAPER_UA_ROTATE: int = 80

    # Notifications
    TELEGRAM_BOT:  str = os.getenv("TELEGRAM_BOT", "")
    ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
    BREVO_KEY:     str = os.getenv("BREVO_API_KEY", "")
    GMAIL_USER:    str = os.getenv("GMAIL_USER", "")
    GMAIL_PASS:    str = os.getenv("GMAIL_PASS", "")
    FROM_EMAIL:    str = os.getenv("FROM_EMAIL", "alerts@atlaspro.ma")
    FROM_NAME:     str = "ATLAS PRO"

    # WhatsApp
    WA_SERVICE_URL: str = os.getenv("WA_SERVICE_URL", "http://localhost:3001")
    WA_SECRET:      str = os.getenv("WA_SECRET", "atlas_wa_secret_2024")
    WA_ADMIN_PHONE: str = os.getenv("WA_ADMIN_PHONE", "0621728813")

    # AI
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL:     str = "llama-3.1-8b-instant"

    # Paiement WhatsApp
    PAYMENT_PHONE:  str = os.getenv("PAYMENT_PHONE", "212621728813")
    PAYMENT_MSG:    str = os.getenv("PAYMENT_MSG",
        "Bonjour, je souhaite m'abonner à ATLAS PRO.")

    # Plans
    PLANS: dict = field(default_factory=lambda: {
        "free":     {"name":"Gratuit",   "price":0,   "tenders_day":15, "email":True,  "telegram":False, "api":False},
        "pro":      {"name":"Pro",       "price":149, "tenders_day":0,  "email":True,  "telegram":True,  "api":True},
        "business": {"name":"Business",  "price":399, "tenders_day":0,  "email":True,  "telegram":True,  "api":True},
    })
    SECTEURS:      dict = field(default_factory=lambda: SECTORS)
    SECTOR_GROUPS: dict = field(default_factory=lambda: GROUPS)

cfg = Settings()

# Validation au démarrage
import logging
_log = logging.getLogger("atlas.config")
if not cfg.SECRET_KEY:
    _log.warning("⚠️  SECRET_KEY non défini — définissez-le dans Railway Variables!")
if not cfg.TELEGRAM_BOT:
    _log.warning("⚠️  TELEGRAM_BOT non défini — notifications Telegram désactivées")
