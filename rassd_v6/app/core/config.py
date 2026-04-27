"""
SOURCE v2.1 — Configuration
============================
✅ All secrets from environment variables
✅ No hardcoded passwords
✅ Type hints
✅ Validation
"""
import os
from typing import Dict, Any

class Config:
    # === App ===
    APP_NAME: str = "SOURCE"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # === Security (MUST be set in production) ===
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "")

    # === Database ===
    DB_PATH: str = os.getenv("DB_PATH", "data/source.db")

    # === Site ===
    SITE_URL: str = os.getenv("SITE_URL", "http://localhost:8000")

    # === Scraping ===
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "30"))

    # === AI (Groq) ===
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "llama-3.1-70b-versatile")

    # === Notifications ===
    TELEGRAM_BOT: str = os.getenv("TELEGRAM_BOT", "")
    TELEGRAM_ADMIN: str = os.getenv("TELEGRAM_ADMIN", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")

    # === Payment ===
    PAYMENT_PHONE: str = os.getenv("PAYMENT_PHONE", "")

    # === Plans ===
    PLANS: Dict[str, Dict[str, Any]] = {
        "free": {"name": "Gratuit", "price": 0, "limits": {"tenders": 10, "pages": 1, "api": False}},
        "essentiel": {"name": "Essentiel", "price": 299, "limits": {"tenders": 50, "pages": 5, "api": False}},
        "pro": {"name": "Pro", "price": 599, "limits": {"tenders": 200, "pages": 20, "api": True}},
        "unlimited": {"name": "Illimité", "price": 999, "limits": {"tenders": 9999, "pages": 999, "api": True}},
    }

    @classmethod
    def validate(cls) -> list:
        """Validate critical config values"""
        errors = []
        if not cls.SECRET_KEY or len(cls.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be at least 32 characters")
        if not cls.ADMIN_PASS or len(cls.ADMIN_PASS) < 12:
            errors.append("ADMIN_PASS must be at least 12 characters")
        if not cls.DEBUG and not cls.SMTP_HOST:
            errors.append("SMTP_HOST required in production")
        return errors

cfg = Config()
