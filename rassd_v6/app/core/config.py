import os
from dataclasses import dataclass, field

@dataclass
class Settings:
    APP_NAME:    str  = "SOURCE"
    APP_TAGLINE: str  = "Marchés Publics Maroc"
    APP_VERSION: str  = "1.0.0"
    SITE_URL:    str  = os.getenv("SITE_URL", "https://source.up.railway.app")
    SECRET_KEY:  str  = os.getenv("SECRET_KEY", "")
    DEBUG:       bool = os.getenv("DEBUG","false").lower() == "true"
    DB_PATH:     str  = os.getenv("DB_PATH", "data/source.db")

    # Scraping — marchespublics.gov.ma UNIQUEMENT
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "60"))

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
    WA_API_URL:    str = os.getenv("WA_API_URL", "")
    WA_API_KEY:    str = os.getenv("WA_API_KEY", "")

    # AI (Groq)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL:     str = "llama-3.1-8b-instant"

    # Admin
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "source2026")

    PLANS: dict = field(default_factory=lambda: {
        "free":     {"name":"Gratuit",      "name_ar":"مجاني",      "price":0,   "tenders_day":10,  "telegram":False,"api":False},
        "essentiel":{"name":"Essentiel",    "name_ar":"أساسي",      "price":149, "tenders_day":0,   "telegram":True, "api":False},
        "pro":      {"name":"Pro",          "name_ar":"احترافي",    "price":399, "tenders_day":0,   "telegram":True, "api":True},
    })

cfg = Settings()

import logging
if not cfg.SECRET_KEY:
    logging.getLogger("source").warning("⚠️ SECRET_KEY non défini dans Railway Variables!")
