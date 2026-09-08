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
    # WhatsApp via Twilio — utilisé automatiquement si ces variables sont
    # renseignées, sinon on reste sur le service Baileys existant.
    TWILIO_SID:        str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WA_FROM:    str = os.getenv("TWILIO_WHATSAPP_FROM", "")
    # Abonnement (mise à niveau manuelle via WhatsApp)
    PAYMENT_PHONE: str = os.getenv("PAYMENT_PHONE", "")
    PAYMENT_MSG:   str = os.getenv("PAYMENT_MSG", "Bonjour, je souhaite m'abonner à MAROC ENTREPRENEURIAT")
    # Annuaire d'entreprises — Google Places API (officielle).
    # On n'utilise pas le scraping direct de Google Maps: il viole les
    # conditions d'utilisation de Google, déclenche des CAPTCHA et fait
    # bannir l'IP du serveur. L'API officielle renvoie les mêmes données
    # (nom, adresse, téléphone, site) de façon stable et autorisée.
    GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
    PLACES_MAX_PER_QUERY:  int = int(os.getenv("PLACES_MAX_PER_QUERY", "60"))
    PLACES_DELAY_MS:       int = int(os.getenv("PLACES_DELAY_MS", "400"))
    # Collecte directe Google Maps (navigateur piloté). Rythme lent assumé:
    # une collecte rapide se fait bloquer en quelques minutes.
    MAPS_MAX_PER_QUERY: int = int(os.getenv("MAPS_MAX_PER_QUERY", "20"))
    MAPS_DELAY_MS:      int = int(os.getenv("MAPS_DELAY_MS", "1200"))
    MAPS_HEADLESS:     bool = os.getenv("MAPS_HEADLESS", "true").lower() == "true"
    # Enrichissement email depuis le site web de l'entreprise
    EMAIL_FINDER_ENABLED:  bool = os.getenv("EMAIL_FINDER_ENABLED", "true").lower() == "true"
    EMAIL_FINDER_TIMEOUT:  int = int(os.getenv("EMAIL_FINDER_TIMEOUT", "12"))
    # Identité légale (à renseigner via variables d'environnement Railway —
    # les pages légales affichent un placeholder tant que ces champs sont vides,
    # plutôt que d'inventer de fausses informations d'entreprise)
    COMPANY_NAME:    str = os.getenv("COMPANY_NAME", "")
    COMPANY_FORM:    str = os.getenv("COMPANY_FORM", "")
    COMPANY_ICE:     str = os.getenv("COMPANY_ICE", "")
    COMPANY_ADDRESS: str = os.getenv("COMPANY_ADDRESS", "")
    CONTACT_EMAIL:   str = os.getenv("CONTACT_EMAIL", "contact@marocentrepreneuriat.ma")
    # Essai gratuit (jours) accordé à chaque nouvelle inscription
    TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "7"))
    # Plans (paiement encaissé hors plateforme puis enregistré par l'admin)
    PLANS: dict = field(default_factory=lambda: {
        "free":    {"name":"Inactif", "price":0,   "period":"",      "months":0, "tenders_day":15,"email":True, "telegram":False,"whatsapp":False,"api":False},
        "monthly": {"name":"Mensuel", "price":250, "period":"mois",  "months":1, "tenders_day":0, "email":True, "telegram":True, "whatsapp":True, "api":True},
        "pro":     {"name":"Annuel",  "price":2499,"period":"an",    "months":12,"tenders_day":0, "email":True, "telegram":True, "whatsapp":True, "api":True},
        "business":{"name":"Biennal", "price":4299,"period":"2 ans", "months":24,"tenders_day":0, "email":True, "telegram":True, "whatsapp":True, "api":True},
    })
    SECTEURS: dict = field(default_factory=lambda: SECTORS)
    SECTOR_GROUPS: dict = field(default_factory=lambda: GROUPS)

cfg = Settings()
