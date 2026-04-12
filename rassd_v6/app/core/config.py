from app.core.sectors import SECTORS, GROUPS
import os, secrets
from dataclasses import dataclass, field

@dataclass
class Settings:
    # App
    APP_NAME:    str  = "ATLAS PRO"
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
    # Notifications
    TELEGRAM_BOT:  str = os.getenv("TELEGRAM_BOT", "")
    ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
    BREVO_KEY:     str = os.getenv("BREVO_API_KEY", "")
    GMAIL_USER:    str = os.getenv("GMAIL_USER", "")
    GMAIL_PASS:    str = os.getenv("GMAIL_PASS", "")
    FROM_EMAIL:    str = os.getenv("FROM_EMAIL", "alerts@atlas.ma")
    # Supabase (cloud sync)
    SUPABASE_URL:  str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY:  str = os.getenv("SUPABASE_KEY", "")
    FROM_NAME:     str = "ATLAS PRO"
    # Supabase (optional cloud sync)
    SUPABASE_URL:  str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY:  str = os.getenv("SUPABASE_KEY", "")
    # Plans
    PLANS: dict = field(default_factory=lambda: {
        "free":    {"name":"Gratuit","price":0,  "tenders_day":15,"email":True, "telegram":False,"api":False},
        "pro":     {"name":"Pro",    "price":99, "tenders_day":0, "email":True, "telegram":True, "api":True},
        "business":{"name":"Business","price":299,"tenders_day":0,"email":True, "telegram":True, "api":True},
    })
    SECTEURS: dict = field(default_factory=lambda: SECTORS)
    SECTOR_GROUPS: dict = field(default_factory=lambda: GROUPS)

cfg = Settings()
