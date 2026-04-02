"""
Modern Business — Configuration centrale
Toutes les variables d'environnement en un seul endroit.
"""
import os, secrets
from dataclasses import dataclass, field

@dataclass
class Config:
    # App
    SITE_URL:    str = os.getenv("SITE_URL", "http://localhost:8000")
    SECRET_KEY:  str = os.getenv("SECRET_KEY", secrets.token_hex(32))
    DEBUG:       bool = os.getenv("DEBUG", "false").lower() == "true"

    # DB
    DB_PATH:     str = os.getenv("DB_PATH", "data/mb.db")

    # Auth
    ADMIN_PASS:  str = os.getenv("ADMIN_PASS", "rassd2026")

    # Scraping
    SCRAPE_INTERVAL_HOURS: int = int(os.getenv("SCRAPE_INTERVAL_HOURS", "2"))

    # AI
    ANTHROPIC_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Notifications
    TELEGRAM_BOT:   str = os.getenv("TELEGRAM_BOT", "")
    ADMIN_CHAT_ID:  str = os.getenv("ADMIN_CHAT_ID", "")
    BREVO_API_KEY:  str = os.getenv("BREVO_API_KEY", "")
    GMAIL_USER:     str = os.getenv("GMAIL_USER", "")
    GMAIL_PASS:     str = os.getenv("GMAIL_PASS", "")

    # Plans
    PLAN_LIMITS: dict = field(default_factory=lambda: {
        "free":       {"tenders_per_day": 10, "telegram": False, "api": False},
        "pro":        {"tenders_per_day": 9999, "telegram": True,  "api": True},
        "enterprise": {"tenders_per_day": 9999, "telegram": True,  "api": True},
    })

cfg = Config()
