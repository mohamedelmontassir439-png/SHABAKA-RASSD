from app.core.sectors import SECTORS, GROUPS
import os, secrets
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Charge .env en local (dev). Sans effet sur Railway: les variables y sont
# injectées directement dans l'environnement réel, load_dotenv() ne les
# écrase jamais (override=False par défaut) et ne fait rien si .env est absent.
load_dotenv()

@dataclass
class Settings:
    # App
    APP_NAME:    str  = "MAROC ENTREPRENEURIAT"
    APP_VERSION: str  = "3.0.0"
    SITE_URL:    str  = os.getenv("SITE_URL", "https://web-production-b4ae4.up.railway.app")
    SECRET_KEY:  str  = os.getenv("SECRET_KEY", secrets.token_hex(32))
    DEBUG:       bool = os.getenv("DEBUG","false").lower() == "true"
    # Database
    DB_PATH:     str  = os.getenv("DB_PATH", "data/atlas.db")
    # Auth
    ADMIN_PASS:  str  = os.getenv("ADMIN_PASS", "atlas2026")
    JWT_EXPIRE_DAYS: int = 30
    # Scraping
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "60"))
    SCRAPER_TIMEOUT:   int = 20
    SCRAPER_UA_ROTATE: int = 80
    # Global Marches (appels d'offres privés)
    GM_USERNAME: str = os.getenv("GM_USERNAME", "")
    GM_PASSWORD: str = os.getenv("GM_PASSWORD", "")
    GM_SCAN_INTERVAL_MIN: int = int(os.getenv("GM_SCAN_INTERVAL_MIN", "60"))
    # Notifications
    TELEGRAM_BOT:  str = os.getenv("TELEGRAM_BOT", "")
    ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
    BREVO_KEY:     str = os.getenv("BREVO_API_KEY", "")
    GMAIL_USER:    str = os.getenv("GMAIL_USER", "")
    GMAIL_PASS:    str = os.getenv("GMAIL_PASS", "")
    FROM_EMAIL:    str = os.getenv("FROM_EMAIL", "alerts@atlas.ma")
    FROM_NAME:     str = "MAROC ENTREPRENEURIAT"
    # WhatsApp (service Baileys séparé)
    WA_SERVICE_URL: str = os.getenv("WA_SERVICE_URL", "http://localhost:3001")
    WA_SECRET:      str = os.getenv("WA_SECRET", "atlas_wa_secret_2024")
    # Abonnement (mise à niveau manuelle via WhatsApp)
    PAYMENT_PHONE: str = os.getenv("PAYMENT_PHONE", "")
    PAYMENT_MSG:   str = os.getenv("PAYMENT_MSG", "Bonjour, je souhaite m'abonner à MAROC ENTREPRENEURIAT")
    # Plans (abonnement annuel, paiement manuel via WhatsApp)
    PLANS: dict = field(default_factory=lambda: {
        "free":    {"name":"Inactif", "price":0,   "period":"",      "tenders_day":15,"email":True, "telegram":False,"whatsapp":False,"api":False},
        "pro":     {"name":"Annuel",  "price":3999,"period":"an",    "tenders_day":0, "email":True, "telegram":True, "whatsapp":True, "api":True},
        "business":{"name":"Biennal", "price":6999,"period":"2 ans", "tenders_day":0, "email":True, "telegram":True, "whatsapp":True, "api":True},
    })
    SECTEURS: dict = field(default_factory=lambda: SECTORS)
    SECTOR_GROUPS: dict = field(default_factory=lambda: GROUPS)

cfg = Settings()
