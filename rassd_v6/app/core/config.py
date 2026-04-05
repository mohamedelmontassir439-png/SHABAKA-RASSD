import os, secrets
from dataclasses import dataclass, field

@dataclass
class Settings:
    # App
    APP_NAME:    str  = "RASSD"
    APP_VERSION: str  = "3.0.0"
    SITE_URL:    str  = os.getenv("SITE_URL", "https://web-production-b4ae4.up.railway.app")
    SECRET_KEY:  str  = os.getenv("SECRET_KEY", secrets.token_hex(32))
    DEBUG:       bool = os.getenv("DEBUG","false").lower() == "true"
    # Database
    DB_PATH:     str  = os.getenv("DB_PATH", "data/rassd.db")
    # Auth
    ADMIN_PASS:  str  = os.getenv("ADMIN_PASS", "rassd2026")
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
    FROM_EMAIL:    str = os.getenv("FROM_EMAIL", "alerts@rassd.ma")
    FROM_NAME:     str = "RASSD"
    # Plans
    PLANS: dict = field(default_factory=lambda: {
        "free":    {"name":"Gratuit","price":0,  "tenders_day":15,"email":True, "telegram":False,"api":False},
        "pro":     {"name":"Pro",    "price":99, "tenders_day":0, "email":True, "telegram":True, "api":True},
        "business":{"name":"Business","price":299,"tenders_day":0,"email":True, "telegram":True, "api":True},
    })
    SECTEURS: list = field(default_factory=lambda: [
        "Travaux BTP","IT & Télécoms","Santé & Médical","Transport & Véhicules",
        "Services Généraux","Études & Conseil","Formation","Restauration",
        "Communication","Énergie","Hydraulique","Fournitures Bureau",
        "Mobilier","Agriculture","Environnement","Autres",
    ])
    # AI
    ANTHROPIC_KEY: str = os.getenv("ANTHROPIC_KEY", "")
    # Plan limits
    PLAN_LIMITS: dict = field(default_factory=lambda: {
        "free":       {"tenders_per_day": 10,  "telegram": False, "api": False, "filters": 2},
        "pro":        {"tenders_per_day": 999, "telegram": True,  "api": True,  "filters": 999},
        "business":   {"tenders_per_day": 999, "telegram": True,  "api": True,  "filters": 999},
        "enterprise": {"tenders_per_day": 999, "telegram": True,  "api": True,  "filters": 999},
    })

cfg = Settings()
