import os
from dataclasses import dataclass, field

@dataclass
class Settings:
    APP_NAME:    str  = "SOURCE"
    APP_VERSION: str  = "2.0.0"
    SITE_URL:    str  = os.getenv("SITE_URL", "https://source.up.railway.app")
    SECRET_KEY:  str  = os.getenv("SECRET_KEY", "")
    DB_PATH:     str  = os.getenv("DB_PATH", "data/source.db")

    # Scraping — toutes les 15 minutes
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "15"))

    # Notifications
    TELEGRAM_BOT:  str = os.getenv("TELEGRAM_BOT", "")
    ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
    BREVO_KEY:     str = os.getenv("BREVO_API_KEY", "")
    GMAIL_USER:    str = os.getenv("GMAIL_USER", "")
    GMAIL_PASS:    str = os.getenv("GMAIL_PASS", "")
    FROM_EMAIL:    str = os.getenv("FROM_EMAIL", "alertes@source.ma")
    FROM_NAME:     str = "SOURCE"

    # WhatsApp
    PAYMENT_PHONE: str = os.getenv("PAYMENT_PHONE", "212621728813")
    PAYMENT_MSG:   str = "Bonjour, je veux activer mon compte SOURCE."

    # AI
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL:     str = "llama-3.1-8b-instant"

    # Admin
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "source2026")

    PLANS: dict = field(default_factory=lambda: {
        "free":     {"name":"Gratuit",   "name_ar":"مجاني",   "price":0,   "limit":10, "telegram":False,"api":False},
        "essentiel":{"name":"Essentiel", "name_ar":"أساسي",   "price":149, "limit":0,  "telegram":True, "api":False},
        "pro":      {"name":"Pro",       "name_ar":"احترافي", "price":399, "limit":0,  "telegram":True, "api":True},
    })

cfg = Settings()

import logging
if not cfg.SECRET_KEY:
    logging.getLogger("source").warning("⚠️  SECRET_KEY manquant — définir dans Railway!")
