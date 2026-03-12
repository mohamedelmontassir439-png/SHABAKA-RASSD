"""
Modern Business v1.0
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
Intelligence Platform â€” OpportunitÃ©s d'Affaires Maroc
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
Sources: marchespublics.gov.ma + bo.gov.ma + ONCF/ONEE/OCP
       + Le Matin + L'Ã‰conomiste + La Vie Eco
WhatsApp: Meta Cloud API (officiel)
Auth: Signed session cookies
"""

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# IMPORTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
from fastapi import FastAPI, Request, Form, HTTPException, Header, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
import sqlite3, json, re, time, random, os, asyncio
import smtplib, hashlib, secrets, threading, logging, traceback

try:
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    HAS_ITS = True
except ImportError:
    HAS_ITS = False

try:
    import urllib3; urllib3.disable_warnings()
except: pass

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# LOGGING
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class JsonLog(logging.Formatter):
    def format(self, r):
        d = {"ts": datetime.utcnow().isoformat()+"Z", "level": r.levelname, "msg": r.getMessage()}
        if r.exc_info: d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False)

logger = logging.getLogger("mb")
logger.setLevel(logging.INFO)
_h = logging.StreamHandler(); _h.setFormatter(JsonLog())
logger.addHandler(_h)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CONFIG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
BRAND_NAME     = "Modern Business"
BRAND_TAGLINE  = "Intelligence des MarchÃ©s â€” Ø§Ù„Ù…ØºØ±Ø¨"

GMAIL_USER     = os.getenv("GMAIL_USER",   "mohamedelmontassir439@gmail.com")
GMAIL_PASS     = os.getenv("GMAIL_PASS",   "nvzdanptagoovjxr")
MAILGUN_KEY    = os.getenv("MAILGUN_KEY",  "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN","")
TELEGRAM_BOT   = os.getenv("TELEGRAM_BOT", "7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")

# WhatsApp Meta Cloud API
WA_TOKEN       = ""  # WhatsApp disabled       # Meta access token
WA_PHONE_ID    = ""  # WhatsApp disabled    # Phone number ID
WA_VERIFY_TOKEN= os.getenv("WA_VERIFY_TOKEN", "mb2026") # Webhook verify token
WA_BUSINESS_ID = ""  # WhatsApp disabled # Business Account ID

ADMIN_PASS     = os.getenv("ADMIN_PASS",   "mb2026admin")
SECRET_KEY     = os.getenv("SECRET_KEY",   secrets.token_hex(32))
DB_PATH        = os.getenv("DB_PATH",      "data/mb.db")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
SITE_URL       = os.getenv("SITE_URL", "https://web-production-b4ae4.up.railway.app")
SENTRY_DSN     = os.getenv("SENTRY_DSN", "")
SCRAPE_HOURS   = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))

# Sentry
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.05, environment="production")
    except: pass

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PLANS â€” Manual payment (contact sales)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
PLANS = {
    "free":       {"name":"Ù…Ø¬Ø§Ù†ÙŠ",     "name_fr":"Starter",  "price":0,   "limits":{"notifs":10,   "saves":5,    "ai":2,   "export":False}},
    "pro":        {"name":"Ù¾Ø±Ùˆ",       "name_fr":"Pro",      "price":299, "limits":{"notifs":500,  "saves":200,  "ai":100, "export":True}},
    "enterprise": {"name":"Ù…Ø¤Ø³Ø³ÙŠ",    "name_fr":"Enterprise","price":899, "limits":{"notifs":9999,"saves":9999, "ai":9999,"export":True}},
}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER SOURCES â€” 16 sources totales
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
SCRAPER_SOURCES = {
    # PUBLIC
    "marchespublics": {
        "name": "MarchÃ©s Publics Maroc",
        "url":  "https://www.marchespublics.gov.ma",
        "type": "PUBLIC",
        "active": True,
    },
    "bo_maroc": {
        "name": "Bulletin Officiel",
        "url":  "https://www.bo.gov.ma",
        "type": "PUBLIC",
        "active": True,
    },
    # SEMI-PUBLIC
    "oncf": {
        "name": "ONCF",
        "url":  "https://www.oncf.ma/fr/appels-doffres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "onee": {
        "name": "ONEE",
        "url":  "https://www.onee.ma/fr/appels-doffres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "ocp": {
        "name": "OCP Group",
        "url":  "https://www.ocpgroup.ma/fr/appels-doffres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "ram": {
        "name": "Royal Air Maroc",
        "url":  "https://www.royalairmaroc.com/ma-fr/appel-offres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "onda": {
        "name": "ONDA",
        "url":  "https://www.onda.ma/fr/appels-doffres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "cdg": {
        "name": "CDG",
        "url":  "https://www.cdg.ma/fr/appels-doffres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    "lydec": {
        "name": "LYDEC",
        "url":  "https://www.lydec.ma/fr/appels-offres",
        "type": "SEMI_PUBLIC",
        "active": True,
    },
    # PRESS â€” PRIVATE & SEMI-PUBLIC
    "lematin": {
        "name": "Le Matin â€” Appels d'Offres",
        "url":  "https://www.lematin.ma/annonces/appel-offres",
        "type": "PRIVATE",
        "active": True,
    },
    "leconomiste": {
        "name": "L'Ã‰conomiste",
        "url":  "https://www.leconomiste.com/appels-doffres",
        "type": "PRIVATE",
        "active": True,
    },
    "lavieeco": {
        "name": "La Vie Ã‰co",
        "url":  "https://www.lavieeco.com/appels-doffres",
        "type": "PRIVATE",
        "active": True,
    },
}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DATA â€” REGIONS & DOMAINS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
REGIONS = {
    "Rabat-SalÃ©-KÃ©nitra":        ["rabat","salÃ©","kÃ©nitra","sale","kenitra","tÃ©mara","skhirat"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","benslimane","berrechid","el jadida"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","el kelaa","chichaoua"],
    "FÃ¨s-MeknÃ¨s":                ["fÃ¨s","fez","meknÃ¨s","meknes","ifrane","taounate","taza"],
    "Tanger-TÃ©touan-Al Hoceima": ["tanger","tÃ©touan","tetouan","al hoceima","chefchaouen","larache"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","guercif","figuig"],
    "BÃ©ni Mellal-KhÃ©nifra":     ["bÃ©ni mellal","beni mellal","khÃ©nifra","azilal"],
    "DrÃ¢a-Tafilalet":            ["errachidia","ouarzazate","zagora","tinghir","midelt"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","chtouka","inezgane"],
    "Guelmim-Oued Noun":         ["guelmim","tan-tan","sidi ifni","assa"],
    "LaÃ¢youne-Sakia El Hamra":  ["laÃ¢youne","laayoune","boujdour","tarfaya"],
    "Dakhla-Oued Ed-Dahab":     ["dakhla","aousserd"],
}
REGIONS_LIST = list(REGIONS.keys())

DOMAINS_FR = {
    "T101":"BÃ¢timent & Construction",   "T201":"GÃ©nie Civil & Infrastructure",
    "T301":"Travaux Hydrauliques",       "T401":"Voirie & RÃ©seaux Divers",
    "T501":"AmÃ©nagement & Paysage",      "P801":"Fournitures Bureautiques & IT",
    "P811":"MatÃ©riels & Ã‰quipements MÃ©dicaux","P821":"VÃ©hicules & Transport",
    "P831":"Alimentation & Restauration","P841":"MatÃ©riaux de Construction",
    "P851":"Ã‰quipements Industriels",    "S901":"SystÃ¨mes Informatiques & SI",
    "S911":"Ã‰tudes & IngÃ©nierie",        "S921":"Formation & Conseil",
    "S931":"Nettoyage & Maintenance",    "S941":"SÃ©curitÃ© & Gardiennage",
    "S951":"Communication & MÃ©dias",     "S961":"Juridique & Audit",
    "S971":"Environnement & DÃ©veloppement Durable",
}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SESSION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
SESSION_COOKIE = "mb_session"
COOKIE_TTL     = 60*60*24*30  # 30 days

def _signer():
    if not HAS_ITS: return None
    return URLSafeTimedSerializer(SECRET_KEY, salt="mb-v1")

def create_session(response: Response, cid: int):
    s = _signer()
    token = s.dumps({"id": cid, "t": int(time.time())}) if s else str(cid)
    response.set_cookie(SESSION_COOKIE, token, max_age=COOKIE_TTL,
                        httponly=True, samesite="lax", secure=SITE_URL.startswith("https"))

def get_session_id(request: Request) -> Optional[int]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw: return None
    s = _signer()
    if not s:
        try: return int(raw)
        except: return None
    try:
        d = s.loads(raw, max_age=COOKIE_TTL)
        return d.get("id")
    except: return None

def delete_session(response: Response):
    response.delete_cookie(SESSION_COOKIE)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# RATE LIMITER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_rl: dict = defaultdict(list)
_rl_lock = threading.Lock()

def rate_limit(ip: str, key: str, max_c: int = 60, win: int = 60) -> bool:
    k = f"{ip}:{key}"; now = time.time()
    with _rl_lock:
        calls = [t for t in _rl[k] if now-t < win]
        if len(calls) >= max_c: return False
        calls.append(now); _rl[k] = calls
    return True

def get_ip(r: Request) -> str:
    fwd = r.headers.get("X-Forwarded-For","")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "0.0.0.0")

def rl(request: Request, key: str, max_c=60, win=60):
    if not rate_limit(get_ip(request), key, max_c, win):
        raise HTTPException(429, "Too many requests")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SECURITY HEADERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class SecMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Content-Type-Options":  "nosniff",
            "X-Frame-Options":          "DENY",
            "X-XSS-Protection":         "1; mode=block",
            "Referrer-Policy":          "strict-origin-when-cross-origin",
            "Permissions-Policy":       "camera=(), microphone=()",
        })
        if SITE_URL.startswith("https"):
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

METRICS = defaultdict(int)
def metric(k: str, v=1): METRICS[k] += v

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DATABASE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id TEXT PRIMARY KEY,
        objet TEXT NOT NULL DEFAULT '',
        acheteur TEXT DEFAULT '',
        region TEXT DEFAULT '',
        domaine TEXT DEFAULT '',
        montant TEXT DEFAULT '',
        date_publication TEXT DEFAULT '',
        date_limite TEXT DEFAULT '',
        description TEXT DEFAULT '',
        statut TEXT DEFAULT 'actif',
        url TEXT DEFAULT '',
        source_key TEXT DEFAULT '',
        source_name TEXT DEFAULT '',
        type_marche TEXT DEFAULT 'PUBLIC',
        date_extraction TEXT DEFAULT '',
        views INTEGER DEFAULT 0,
        score INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_region  ON tenders(region);
    CREATE INDEX IF NOT EXISTS idx_t_domaine ON tenders(domaine);
    CREATE INDEX IF NOT EXISTS idx_t_type    ON tenders(type_marche);
    CREATE INDEX IF NOT EXISTS idx_t_source  ON tenders(source_key);
    CREATE INDEX IF NOT EXISTS idx_t_date    ON tenders(date_extraction DESC);

    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        entreprise TEXT DEFAULT '',
        email TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '',
        whatsapp TEXT DEFAULT '',
        telegram TEXT DEFAULT '',
        domaines TEXT DEFAULT '[]',
        regions TEXT DEFAULT '[]',
        keywords TEXT DEFAULT '',
        plan TEXT DEFAULT 'free',
        plan_expires TEXT DEFAULT '',
        plan_activated_by TEXT DEFAULT '',
        password_hash TEXT NOT NULL DEFAULT '',
        actif INTEGER DEFAULT 1,
        notifs_sent INTEGER DEFAULT 0,
        saves_count INTEGER DEFAULT 0,
        ai_count INTEGER DEFAULT 0,
        last_login TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        notif_channels TEXT DEFAULT '["email"]',
        type_filters TEXT DEFAULT '["PUBLIC","SEMI_PUBLIC","PRIVATE"]',
        cookie_consent INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_c_email ON contractors(email);

    CREATE TABLE IF NOT EXISTS saved_tenders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        tender_id TEXT NOT NULL,
        saved_at TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        UNIQUE(contractor_id, tender_id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        tender_id TEXT NOT NULL,
        channel TEXT DEFAULT 'email',
        sent_at TEXT DEFAULT '',
        status TEXT DEFAULT 'sent'
    );

    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        key_hash TEXT UNIQUE NOT NULL,
        key_prefix TEXT NOT NULL,
        name TEXT DEFAULT 'Default',
        calls_total INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS wa_sessions (
        phone TEXT PRIMARY KEY,
        contractor_id INTEGER,
        state TEXT DEFAULT 'init',
        last_msg TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        route TEXT DEFAULT '',
        error TEXT DEFAULT '',
        tb TEXT DEFAULT '',
        count INTEGER DEFAULT 1,
        first_seen TEXT DEFAULT '',
        last_seen TEXT DEFAULT '',
        resolved INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_key TEXT DEFAULT '',
        found INTEGER DEFAULT 0,
        saved INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0,
        started_at TEXT DEFAULT '',
        finished_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS contact_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        entreprise TEXT DEFAULT '',
        plan TEXT DEFAULT 'pro',
        message TEXT DEFAULT '',
        status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT ''
    );
    """)
    for sql in [
        "ALTER TABLE contractors ADD COLUMN whatsapp TEXT DEFAULT ''",
        "ALTER TABLE contractors ADD COLUMN type_filters TEXT DEFAULT '[\"PUBLIC\",\"SEMI_PUBLIC\",\"PRIVATE\"]'",
        "ALTER TABLE contractors ADD COLUMN notif_channels TEXT DEFAULT '[\"email\"]'",
        "ALTER TABLE tenders ADD COLUMN score INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN source_key TEXT DEFAULT ''",
    ]:
        try: db.execute(sql)
        except: pass
    db.commit(); db.close()
    logger.info("DB initialized")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# HELPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def hash_pw(pw: str) -> str:
    return hashlib.sha256((pw + SECRET_KEY[:16]).encode()).hexdigest()

def check_pw(pw: str, h: str) -> bool:
    return hash_pw(pw) == h

def is_expired(d: str) -> bool:
    if not d: return False
    for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d.%m.%Y"]:
        try: return datetime.strptime(d.strip(), fmt).date() < datetime.now().date()
        except: pass
    return False

def classify_region(text: str) -> str:
    txt = text.lower()
    for region, kws in REGIONS.items():
        if any(k in txt for k in kws): return region
    return ""

def classify_domain(text: str) -> str:
    txt = text.lower()
    kw_map = {
        "T101":["bÃ¢timent","construction","maÃ§onnerie","bÃ©ton","btp","Ø¨Ù†Ø§Ø¡"],
        "T201":["route","autoroute","pont","gÃ©nie civil","Ø·Ø±ÙŠÙ‚","Ø¬Ø³Ø±"],
        "T301":["hydraulique","eau","assainissement","barrage","Ù…Ø§Ø¡","ØªØ·Ù‡ÙŠØ±"],
        "T401":["rÃ©seau","Ã©lectricitÃ©","Ã©clairage","Ø´Ø¨ÙƒØ©","ÙƒÙ‡Ø±Ø¨Ø§Ø¡"],
        "T501":["amÃ©nagement","jardin","espaces verts","ØªÙ‡ÙŠØ¦Ø©"],
        "P801":["informatique","matÃ©riel","fournitures","bureau","Ù…Ø¹Ù„ÙˆÙ…ÙŠØ§Øª","logiciel"],
        "P811":["mÃ©dical","santÃ©","hÃ´pital","Ã©quipements mÃ©dicaux","Ø·Ø¨ÙŠ"],
        "P821":["vÃ©hicule","voiture","transport","bus","Ø³ÙŠØ§Ø±Ø©"],
        "P831":["alimentation","restaurant","traiteur","ØºØ°Ø§Ø¡","Ù…Ø·Ø¹Ù…"],
        "P841":["matÃ©riaux","ciment","fer","acier","Ù…ÙˆØ§Ø¯ Ø§Ù„Ø¨Ù†Ø§Ø¡"],
        "P851":["industrie","machine","atelier","ØµÙ†Ø§Ø¹Ø©","Ø¢Ù„Ø§Øª"],
        "S901":["systÃ¨me d'information","application","dÃ©veloppement","Ø¨Ø±Ù…Ø¬ÙŠØ§Øª"],
        "S911":["Ã©tude","mission","ingÃ©nierie","bureau d'Ã©tudes","Ø¯Ø±Ø§Ø³Ø©"],
        "S921":["formation","coaching","conseil","consulting","ØªÙƒÙˆÙŠÙ†"],
        "S931":["nettoyage","entretien","maintenance","Ù†Ø¸Ø§ÙØ©","ØµÙŠØ§Ù†Ø©"],
        "S941":["sÃ©curitÃ©","gardiennage","surveillance","Ø­Ø±Ø§Ø³Ø©"],
        "S951":["communication","publicitÃ©","impression","ØªÙˆØ§ØµÙ„","Ø¥Ø¹Ù„Ø§Ù…"],
        "S961":["juridique","audit","comptabilitÃ©","Ù‚Ø§Ù†ÙˆÙ†ÙŠ"],
        "S971":["environnement","dÃ©chets","recyclage","Ø¨ÙŠØ¦Ø©"],
    }
    for code, words in kw_map.items():
        if any(w in txt for w in words): return code
    return ""

def make_id(source_key: str, raw_id: str) -> str:
    return f"{source_key}_{raw_id}"

def extract_date(text: str) -> str:
    m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
    return m.group(1) if m else ""

def log_error(route: str, error: str, tb: str = ""):
    metric("errors"); 
    try:
        db = get_db(); now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ex = db.execute("SELECT id FROM error_log WHERE route=? AND error=? AND resolved=0", (route, str(error)[:200])).fetchone()
        if ex: db.execute("UPDATE error_log SET count=count+1,last_seen=? WHERE id=?", (now, ex[0]))
        else:   db.execute("INSERT INTO error_log (route,error,tb,first_seen,last_seen) VALUES (?,?,?,?,?)", (route, str(error)[:200], tb[:1500], now, now))
        db.commit(); db.close()
    except: pass

def get_contractor(request: Request) -> Optional[dict]:
    cid = get_session_id(request)
    if not cid: return None
    db = get_db()
    try:
        row = db.execute("SELECT * FROM contractors WHERE id=? AND actif=1", (cid,)).fetchone()
        return dict(row) if row else None
    finally: db.close()

def save_tender(t: dict) -> bool:
    if not t.get("id") or not t.get("objet"): return False
    if t.get("date_limite") and is_expired(t.get("date_limite","")): return False
    try:
        db = get_db()
        db.execute("""
            INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,domaine,montant,date_publication,date_limite,
             description,statut,url,source_key,source_name,type_marche,date_extraction,score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            str(t.get("id",""))[:80], str(t.get("objet",""))[:500],
            str(t.get("acheteur",""))[:300], str(t.get("region",""))[:100],
            str(t.get("domaine",""))[:50], str(t.get("montant",""))[:100],
            str(t.get("date_publication",""))[:20], str(t.get("date_limite",""))[:20],
            str(t.get("description",""))[:2000], str(t.get("statut","actif")),
            str(t.get("url",""))[:400], str(t.get("source_key",""))[:50],
            str(t.get("source_name",""))[:100], str(t.get("type_marche","PUBLIC")),
            str(t.get("date_extraction", datetime.now().strftime("%Y-%m-%d %H:%M"))),
            int(t.get("score", 0)),
        ))
        db.commit()
        changed = db.execute("SELECT changes()").fetchone()[0]
        db.close()
        return changed > 0
    except Exception as e:
        logger.error(f"[save_tender] {e}")
        try: db.close()
        except: pass
        return False

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
SCRAPE_LOG   = []
SCRAPE_STATS = {"running":False,"active_source":"","total_found":0,"total_saved":0,"errors":0,"started":"","sources_done":[]}

def slog(msg: str, source=""):
    entry = f"[{datetime.now().strftime('%H:%M:%S')}][{source or 'main'}] {msg}"
    SCRAPE_LOG.append(entry); logger.info(entry)
    if len(SCRAPE_LOG) > 1000: SCRAPE_LOG[:] = SCRAPE_LOG[-800:]

def get_session():
    import requests
    s = requests.Session(); s.verify = False
    s.headers.update({
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        ]),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
    })
    return s

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SOURCE 1 â€” marchespublics.gov.ma (PUBLIC)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def parse_pmmp(html: str, tid: str) -> dict:
    from bs4 import BeautifulSoup as BS
    soup = BS(html, 'html.parser')
    full = soup.get_text(' ', strip=True)

    def in_table(label):
        for row in soup.find_all('tr'):
            cells = row.find_all(['td','th'])
            for i, c in enumerate(cells):
                if label.lower() in c.get_text().lower() and i+1 < len(cells):
                    v = cells[i+1].get_text(strip=True)
                    if v and len(v) > 1: return v[:400]
        return ""

    objet = ""
    for sel in ['h1','h2','.consultation-title','.objet-marche','[class*="objet"]']:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            if 6 < len(txt) < 500: objet = txt; break
    if not objet: objet = in_table("objet") or full[:200]

    acheteur   = in_table("maÃ®tre d") or in_table("organisme") or in_table("acheteur") or ""
    date_pub   = extract_date(in_table("publication") or "")
    date_lim   = extract_date(in_table("remise") or in_table("limite") or "")
    montant    = in_table("montant") or ""
    if not montant:
        m = re.search(r'(\d[\d\s,.]{2,14})\s*(?:DH|MAD|dirham)', full, re.I)
        if m: montant = m.group(0)[:80]

    region  = classify_region(acheteur + " " + full[:600])
    domaine = classify_domain(objet + " " + full[:400])
    statut  = "annule" if any(k in full.lower() for k in ["annulÃ©","infructueux","sans suite"]) else ("expire" if is_expired(date_lim) else "actif")

    return {
        "id": f"pmmp_{tid}", "objet": objet[:400] or f"MarchÃ© #{tid}",
        "acheteur": acheteur[:300], "region": region, "domaine": domaine,
        "montant": montant[:80], "date_publication": date_pub, "date_limite": date_lim,
        "description": full[:2000], "statut": statut,
        "url": f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
        "source_key": "marchespublics", "source_name": "MarchÃ©s Publics Maroc",
        "type_marche": "PUBLIC", "date_extraction": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "score": 90,
    }

def scrape_marchespublics() -> list:
    import requests as rq
    new_tenders = []; s = get_session()
    src = "marchespublics"; slog("â–¶ Starting", src)
    SCRAPE_STATS["active_source"] = src

    SHOW_URLS = [
        "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/",
        "https://www.marchespublics.gov.ma/pmmp/consultation/show/",
    ]
    LIST_URLS = [
        "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/",
        "https://www.marchespublics.gov.ma/pmmp/consultation/",
    ]

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders WHERE source_key='marchespublics'").fetchall())
    row = db.execute("SELECT MAX(CAST(REPLACE(id,'pmmp_','') AS INTEGER)) FROM tenders WHERE source_key='marchespublics'").fetchone()
    max_id = int(row[0]) if (row and row[0]) else 0
    db.close()

    ids_found = set()
    for list_url in LIST_URLS:
        for page in range(1, 6):
            url = f"{list_url}?page={page}" if page > 1 else list_url
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                for pat in [r'/show/(\d{3,7})', r'[?&]id=(\d{3,7})', r'/consultation/(\d{3,7})']:
                    for m in re.finditer(pat, r.text): ids_found.add(m.group(1))
                time.sleep(random.uniform(1, 2))
            except Exception as e: slog(f"List p{page}: {e}", src); break
        if ids_found: break

    # Probe max ID if needed
    if max_id == 0 and not ids_found:
        for probe in [450000,400000,300000,200000,100000,50000]:
            for su in SHOW_URLS:
                try:
                    r = s.get(f"{su}{probe}", timeout=10)
                    if r.status_code == 200 and len(r.text) > 500:
                        max_id = probe; break
                except: pass
            if max_id: break

    # Fetch new from listing
    new_ids = set(ids_found) - set(k.replace("pmmp_","") for k in known)
    slog(f"Listing IDs: {len(ids_found)} | New: {len(new_ids)}", src)
    for tid in sorted(new_ids, reverse=True)[:50]:
        for su in SHOW_URLS:
            try:
                r = s.get(f"{su}{tid}", timeout=15)
                if r.status_code == 200 and len(r.text) > 400:
                    t = parse_pmmp(r.text, tid)
                    SCRAPE_STATS["total_found"] += 1
                    if save_tender(t):
                        SCRAPE_STATS["total_saved"] += 1
                        if t["statut"] == "actif": new_tenders.append(t)
                    break
            except: SCRAPE_STATS["errors"] += 1
        time.sleep(random.uniform(0.5, 1.2))

    # Sequential scan
    if max_id > 0:
        slog(f"Sequential from #{max_id+1}", src)
        miss = 0; cur = max_id + 1
        while miss < 20 and len(new_tenders) < 60:
            if f"pmmp_{cur}" in known: cur += 1; continue
            ok = False
            for su in SHOW_URLS:
                try:
                    r = s.get(f"{su}{cur}", timeout=12)
                    if r.status_code == 200 and len(r.text) > 400:
                        miss = 0; ok = True
                        t = parse_pmmp(r.text, str(cur))
                        SCRAPE_STATS["total_found"] += 1
                        if save_tender(t):
                            SCRAPE_STATS["total_saved"] += 1
                            if t["statut"] == "actif": new_tenders.append(t)
                        break
                    elif r.status_code == 404: miss += 1; ok = True; break
                    elif r.status_code in [429,503]: time.sleep(20); ok = True; break
                except rq.exceptions.ConnectionError: miss += 10; ok = True; break
                except: ok = True; break
            if not ok: miss += 1
            cur += 1; time.sleep(random.uniform(0.3, 0.8))

    slog(f"Done: {SCRAPE_STATS['total_saved']} saved", src)
    return new_tenders

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SOURCE 2 â€” bo.gov.ma (Bulletin Officiel)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def scrape_bo() -> list:
    from bs4 import BeautifulSoup as BS
    import requests as rq
    new_tenders = []; s = get_session()
    src = "bo_maroc"; slog("â–¶ Starting", src)
    SCRAPE_STATS["active_source"] = src

    bo_urls = [
        "https://www.bo.gov.ma/Ar/Archives/",
        "https://www.bo.gov.ma/Fr/Archives/",
        "https://www.bo.gov.ma",
    ]

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders WHERE source_key='bo_maroc'").fetchall())
    db.close()

    for url in bo_urls:
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200: continue
            soup = BS(r.text, 'html.parser')
            full = soup.get_text(' ', strip=True)

            # Look for tender notices (avis d'appel d'offres)
            patterns = [
                r'(?:appel[s]?\s+d[\'\s]offre[s]?|avis[s]?\s+d[\'\s]appel|Ù…Ù†Ø§Ù‚ØµØ©|Ø¥Ø¹Ù„Ø§Ù†|Ø·Ù„Ø¨ Ø¹Ø±ÙˆØ¶)[^\n\.]{10,300}',
            ]
            found_notices = []
            for pat in patterns:
                found_notices += re.findall(pat, full, re.I | re.MULTILINE)

            for i, notice in enumerate(found_notices[:30]):
                notice = notice.strip()
                if len(notice) < 20: continue
                tid = f"bo_{hashlib.md5(notice.encode()).hexdigest()[:12]}"
                if tid in known: continue

                region  = classify_region(notice)
                domaine = classify_domain(notice)
                date_lim = extract_date(notice)

                t = {
                    "id": tid, "objet": notice[:300], "acheteur": "",
                    "region": region, "domaine": domaine, "montant": "",
                    "date_publication": datetime.now().strftime("%d/%m/%Y"),
                    "date_limite": date_lim, "description": notice[:1000],
                    "statut": "expire" if is_expired(date_lim) else "actif",
                    "url": url, "source_key": "bo_maroc",
                    "source_name": "Bulletin Officiel du Maroc",
                    "type_marche": "PUBLIC",
                    "date_extraction": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "score": 85,
                }
                SCRAPE_STATS["total_found"] += 1
                if save_tender(t):
                    SCRAPE_STATS["total_saved"] += 1
                    if t["statut"] == "actif": new_tenders.append(t)
        except Exception as e:
            slog(f"BO error: {e}", src)
            SCRAPE_STATS["errors"] += 1

    slog(f"Done: {len(new_tenders)} new", src)
    return new_tenders

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SOURCE 3 â€” Semi-public (ONCF, ONEE, OCP, RAM, ONDA, CDG, LYDEC)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SEMI_PUBLIC_SOURCES = {
    "oncf":  {"url":"https://www.oncf.ma/fr/appels-doffres",     "name":"ONCF",   "selectors":[".field-item","article",".view-content",".views-row"]},
    "onee":  {"url":"https://www.onee.ma/fr/appels-doffres",     "name":"ONEE",   "selectors":[".node","article",".field-title"]},
    "ocp":   {"url":"https://www.ocpgroup.ma/fr/appels-doffres", "name":"OCP Group","selectors":["article",".tender",".appel-offre"]},
    "ram":   {"url":"https://www.royalairmaroc.com/ma-fr/appel-offres","name":"RAM","selectors":[".appel","article","li"]},
    "onda":  {"url":"https://www.onda.ma/fr/appels-doffres",     "name":"ONDA",   "selectors":[".node","article",".view-row"]},
    "cdg":   {"url":"https://www.cdg.ma/fr/appels-doffres",      "name":"CDG",    "selectors":[".appel","article",".field-content"]},
    "lydec": {"url":"https://www.lydec.ma/fr/appels-offres",     "name":"LYDEC",  "selectors":[".appel","article",".tender"]},
}

def scrape_semi_public_source(key: str, cfg: dict) -> list:
    from bs4 import BeautifulSoup as BS
    import requests as rq
    new_tenders = []; s = get_session()
    slog(f"â–¶ Starting {cfg['name']}", key)

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders WHERE source_key=?", (key,)).fetchall())
    db.close()

    try:
        r = s.get(cfg["url"], timeout=25, allow_redirects=True)
        if r.status_code not in [200, 301, 302]: 
            slog(f"HTTP {r.status_code}", key); return []
        soup = BS(r.text, 'html.parser')
        full_text = soup.get_text(' ', strip=True)

        items = []
        for selector in cfg["selectors"]:
            items = soup.select(selector)
            if items: break
        if not items:
            # Fallback: search for tender keywords in text
            items = soup.find_all(['li','p','div'], string=re.compile(r'appel|offre|tender|marchÃ©|Ù…Ù†Ø§Ù‚ØµØ©', re.I))

        for el in items[:40]:
            txt = el.get_text(' ', strip=True)
            if len(txt) < 30: continue
            if not re.search(r'appel|offre|tender|marchÃ©|Ù…Ù†Ø§Ù‚ØµØ©|adjudication', txt, re.I): continue

            tid = f"{key}_{hashlib.md5(txt[:100].encode()).hexdigest()[:12]}"
            if tid in known: continue

            # Try to find link
            link = el.find('a')
            url = ""
            if link and link.get('href'):
                href = link.get('href','')
                if href.startswith('http'): url = href
                elif href.startswith('/'): url = cfg["url"].split('/fr')[0] + href

            date_lim = extract_date(txt)
            region   = classify_region(txt + " " + cfg["name"])
            domaine  = classify_domain(txt)

            t = {
                "id": tid, "objet": txt[:300].strip(),
                "acheteur": cfg["name"], "region": region, "domaine": domaine,
                "montant": "", "date_publication": datetime.now().strftime("%d/%m/%Y"),
                "date_limite": date_lim, "description": txt[:1500],
                "statut": "expire" if is_expired(date_lim) else "actif",
                "url": url or cfg["url"], "source_key": key, "source_name": cfg["name"],
                "type_marche": "SEMI_PUBLIC",
                "date_extraction": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "score": 80,
            }
            SCRAPE_STATS["total_found"] += 1
            if save_tender(t):
                SCRAPE_STATS["total_saved"] += 1
                if t["statut"] == "actif": new_tenders.append(t)

        slog(f"Done: {len(new_tenders)} new from {cfg['name']}", key)

    except rq.exceptions.SSLError:
        slog(f"SSL error â€” retrying without verify", key)
        try:
            r = rq.get(cfg["url"], timeout=20, verify=False, headers={"User-Agent": random.choice(["Mozilla/5.0"])})
            soup = BS(r.text, 'html.parser')
            full = soup.get_text(' ', strip=True)
            # Extract any tender-like content
            matches = re.findall(r'(?:appel[s]? d[\'\s]offre[s]?|Ù…Ù†Ø§Ù‚ØµØ©)[^\n]{10,200}', full, re.I)
            for m in matches[:10]:
                tid = f"{key}_{hashlib.md5(m.encode()).hexdigest()[:12]}"
                if tid not in known:
                    t = {"id":tid,"objet":m[:300],"acheteur":cfg["name"],"region":classify_region(m),"domaine":classify_domain(m),"montant":"","date_publication":datetime.now().strftime("%d/%m/%Y"),"date_limite":extract_date(m),"description":m,"statut":"actif","url":cfg["url"],"source_key":key,"source_name":cfg["name"],"type_marche":"SEMI_PUBLIC","date_extraction":datetime.now().strftime("%Y-%m-%d %H:%M"),"score":75}
                    if save_tender(t): new_tenders.append(t)
        except Exception as e2:
            slog(f"Retry failed: {e2}", key); SCRAPE_STATS["errors"] += 1
    except Exception as e:
        slog(f"Error: {e}", key); SCRAPE_STATS["errors"] += 1

    return new_tenders

def scrape_all_semi_public() -> list:
    new_tenders = []
    for key, cfg in SEMI_PUBLIC_SOURCES.items():
        try:
            new_tenders += scrape_semi_public_source(key, cfg)
        except Exception as e:
            slog(f"Source {key} crashed: {e}", "semi_public")
        time.sleep(random.uniform(2, 4))
    return new_tenders

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SOURCE 4 â€” Press (Le Matin, L'Ã‰conomiste, La Vie Ã‰co)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PRESS_SOURCES = {
    "lematin": {
        "name": "Le Matin", "type": "PRIVATE",
        "urls": [
            "https://www.lematin.ma/annonces/appel-offres",
            "https://www.lematin.ma/annonces/avis-offres",
            "https://www.lematin.ma/journal/",
        ],
        "selectors": [".article-title","h2 a","h3 a",".title a",".announcement-title",".field-title"],
    },
    "leconomiste": {
        "name": "L'Ã‰conomiste", "type": "PRIVATE",
        "urls": [
            "https://www.leconomiste.com/appels-doffres",
            "https://www.leconomiste.com/categorie/appels-doffres",
        ],
        "selectors": ["h2 a","h3 a",".article-title",".content-title",".field-title"],
    },
    "lavieeco": {
        "name": "La Vie Ã‰co", "type": "PRIVATE",
        "urls": [
            "https://www.lavieeco.com/appels-doffres/",
            "https://www.lavieeco.com/categorie/appels-doffres/",
        ],
        "selectors": ["h2 a","h3 a",".entry-title a",".post-title a"],
    },
}

def scrape_press_source(key: str, cfg: dict) -> list:
    from bs4 import BeautifulSoup as BS
    import requests as rq
    new_tenders = []; s = get_session()
    slog(f"â–¶ Starting {cfg['name']}", key)

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders WHERE source_key=?", (key,)).fetchall())
    db.close()

    tender_kw = re.compile(r'appel|offre|avis|adjudication|consultation|soumission|Ù…Ù†Ø§Ù‚ØµØ©|Ø·Ù„Ø¨ Ø¹Ø±ÙˆØ¶', re.I)

    for page_url in cfg["urls"]:
        try:
            r = s.get(page_url, timeout=20)
            if r.status_code != 200: continue
            soup = BS(r.text, 'html.parser')

            for sel in cfg["selectors"]:
                elements = soup.select(sel)
                if elements:
                    for el in elements[:30]:
                        title_txt = el.get_text(strip=True)
                        if not title_txt or len(title_txt) < 20: continue
                        if not tender_kw.search(title_txt): continue

                        href = el.get('href','')
                        if not href and el.find('a'): href = el.find('a').get('href','')
                        if href and not href.startswith('http'):
                            base = '/'.join(page_url.split('/')[:3])
                            href = base + (href if href.startswith('/') else '/' + href)

                        tid = f"{key}_{hashlib.md5(title_txt[:80].encode()).hexdigest()[:12]}"
                        if tid in known: continue

                        # Try to fetch detail page
                        detail_txt = title_txt; date_lim = extract_date(title_txt)
                        acheteur = ""
                        if href:
                            try:
                                dr = s.get(href, timeout=12)
                                if dr.status_code == 200:
                                    dsoup = BS(dr.text, 'html.parser')
                                    detail_txt = dsoup.get_text(' ', strip=True)[:2000]
                                    if not date_lim: date_lim = extract_date(detail_txt)
                                    # Try to extract acheteur
                                    for m in re.finditer(r'(?:maÃ®tre|organisme|acheteur|sociÃ©tÃ©|groupe|office|direction)[:\s]+([A-Za-zÃ€-Ã¿\s]{5,60})', detail_txt, re.I):
                                        acheteur = m.group(1).strip()[:100]; break
                                time.sleep(0.5)
                            except: pass

                        region  = classify_region(title_txt + " " + detail_txt[:300])
                        domaine = classify_domain(title_txt + " " + detail_txt[:300])

                        t = {
                            "id": tid, "objet": title_txt[:400], "acheteur": acheteur,
                            "region": region, "domaine": domaine, "montant": "",
                            "date_publication": datetime.now().strftime("%d/%m/%Y"),
                            "date_limite": date_lim,
                            "description": detail_txt[:2000],
                            "statut": "expire" if is_expired(date_lim) else "actif",
                            "url": href or page_url, "source_key": key, "source_name": cfg["name"],
                            "type_marche": cfg["type"],
                            "date_extraction": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "score": 70,
                        }
                        SCRAPE_STATS["total_found"] += 1
                        if save_tender(t):
                            SCRAPE_STATS["total_saved"] += 1
                            if t["statut"] == "actif": new_tenders.append(t)
                    break
            time.sleep(random.uniform(1.5, 3))
        except Exception as e:
            slog(f"Error {page_url}: {e}", key)
            SCRAPE_STATS["errors"] += 1

    slog(f"Done: {len(new_tenders)} new from {cfg['name']}", key)
    return new_tenders

def scrape_all_press() -> list:
    new_tenders = []
    for key, cfg in PRESS_SOURCES.items():
        try:
            new_tenders += scrape_press_source(key, cfg)
        except Exception as e:
            slog(f"Press {key} crashed: {e}", "press")
        time.sleep(random.uniform(3, 5))
    return new_tenders

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# MASTER SCRAPER â€” runs all sources
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_all_scrapers() -> list:
    start = time.time()
    all_new = []
    SCRAPE_STATS.update({
        "running": True, "total_found": 0, "total_saved": 0,
        "errors": 0, "started": datetime.now().strftime("%H:%M:%S"),
        "sources_done": [], "active_source": ""
    })
    slog("â•â•â• Master scraper started â•â•â•")

    # 1. marchespublics.gov.ma
    try:
        slog("Phase 1/4 â€” marchespublics.gov.ma")
        new = scrape_marchespublics()
        all_new += new
        SCRAPE_STATS["sources_done"].append(f"marchespublics (+{len(new)})")
    except Exception as e:
        slog(f"marchespublics FAILED: {e}"); SCRAPE_STATS["errors"] += 1

    time.sleep(2)

    # 2. Bulletin Officiel
    try:
        slog("Phase 2/4 â€” Bulletin Officiel")
        new = scrape_bo()
        all_new += new
        SCRAPE_STATS["sources_done"].append(f"bo_maroc (+{len(new)})")
    except Exception as e:
        slog(f"BO FAILED: {e}"); SCRAPE_STATS["errors"] += 1

    time.sleep(2)

    # 3. Semi-public (ONCF, ONEE, OCP, etc.)
    try:
        slog("Phase 3/4 â€” Semi-public sources (7 sources)")
        new = scrape_all_semi_public()
        all_new += new
        SCRAPE_STATS["sources_done"].append(f"semi_public (+{len(new)})")
    except Exception as e:
        slog(f"Semi-public FAILED: {e}"); SCRAPE_STATS["errors"] += 1

    time.sleep(2)

    # 4. Press (Le Matin, L'Ã‰conomiste, La Vie Ã‰co)
    try:
        slog("Phase 4/4 â€” Presse spÃ©cialisÃ©e (3 sources)")
        new = scrape_all_press()
        all_new += new
        SCRAPE_STATS["sources_done"].append(f"press (+{len(new)})")
    except Exception as e:
        slog(f"Press FAILED: {e}"); SCRAPE_STATS["errors"] += 1

    # Auto-classify missing fields
    try:
        db = get_db()
        for row in db.execute("SELECT id,acheteur,objet,description FROM tenders WHERE region='' OR region IS NULL LIMIT 100").fetchall():
            r = classify_region((row["acheteur"] or "") + " " + (row["description"] or "")[:300])
            if r: db.execute("UPDATE tenders SET region=? WHERE id=?", (r, row["id"]))
        for row in db.execute("SELECT id,objet,description FROM tenders WHERE domaine='' OR domaine IS NULL LIMIT 100").fetchall():
            d = classify_domain((row["objet"] or "") + " " + (row["description"] or "")[:300])
            if d: db.execute("UPDATE tenders SET domaine=? WHERE id=?", (d, row["id"]))
        # Mark expired
        active = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
        exp = [r["id"] for r in active if is_expired(r["date_limite"])]
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join('?'*len(exp))})", exp)
        db.commit(); db.close()
    except Exception as e:
        slog(f"Post-process error: {e}")

    # Log run
    duration = time.time() - start
    try:
        db = get_db()
        db.execute("INSERT INTO scrape_runs (source_key,found,saved,errors,duration_sec,started_at,finished_at) VALUES (?,?,?,?,?,?,?)",
                   ("ALL", SCRAPE_STATS["total_found"], SCRAPE_STATS["total_saved"],
                    SCRAPE_STATS["errors"], duration, SCRAPE_STATS["started"],
                    datetime.now().strftime("%H:%M:%S")))
        db.commit(); db.close()
    except: pass

    SCRAPE_STATS["running"] = False
    slog(f"â•â•â• Done in {duration:.0f}s | {SCRAPE_STATS['total_saved']} saved | {SCRAPE_STATS['errors']} errors â•â•â•")
    metric("scrape_runs")
    return all_new

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# WHATSAPP â€” Meta Cloud API (Official)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
WA_API_URL = "https://graph.facebook.com/v19.0"

async def wa_send_text(to_phone: str, message: str) -> bool:
    """WhatsApp disabled â€” returns False"""
    return False
    import httpx
    phone = re.sub(r'\D', '', to_phone)
    if phone.startswith('0'): phone = '212' + phone[1:]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{WA_API_URL}/{WA_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WA_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": phone,
                    "type": "text",
                    "text": {"preview_url": True, "body": message[:4096]},
                }
            )
            if r.status_code == 200:
                logger.info(f"[WhatsApp] Sent to {phone[:6]}***")
                metric("wa_sent"); return True
            else:
                logger.error(f"[WhatsApp] Error {r.status_code}: {r.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"[WhatsApp] {e}"); return False

async def wa_send_template(to_phone: str, template_name: str, params: list = None) -> bool:
    """WhatsApp disabled"""
    return False
    import httpx
    phone = re.sub(r'\D', '', to_phone)
    if phone.startswith('0'): phone = '212' + phone[1:]
    body = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "ar"},
        }
    }
    if params:
        body["template"]["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params]
        }]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{WA_API_URL}/{WA_PHONE_ID}/messages",
                headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
                json=body)
        return r.status_code == 200
    except: return False

async def wa_handle_message(phone: str, message_text: str, msg_type: str = "text"):
    """Handle incoming WhatsApp message â€” conversational bot"""
    text = message_text.strip().lower()
    db = get_db()

    # Get or create session
    session = db.execute("SELECT * FROM wa_sessions WHERE phone=?", (phone,)).fetchone()
    session = dict(session) if session else {"phone": phone, "contractor_id": None, "state": "init"}

    # Find contractor by WhatsApp number
    contractor = None
    if session.get("contractor_id"):
        row = db.execute("SELECT * FROM contractors WHERE id=? AND actif=1", (session["contractor_id"],)).fetchone()
        if row: contractor = dict(row)
    if not contractor:
        row = db.execute("SELECT * FROM contractors WHERE whatsapp=? AND actif=1", (phone,)).fetchone()
        if row: contractor = dict(row)

    db.close()
    response = ""

    # Commands
    if text in ["/start","start","Ù…Ø±Ø­Ø¨Ø§","Ù…Ø±Ø­Ø¨Ø§Ù‹","bonjour","Ø³Ù„Ø§Ù…"]:
        response = (
            f"ðŸ¢ *{BRAND_NAME}*\n"
            f"_Intelligence des MarchÃ©s Maroc_\n\n"
            f"{'â”'*30}\n\n"
            f"ðŸ“‹ */tenders* â€” Ø¢Ø®Ø± Ø§Ù„ØµÙÙ‚Ø§Øª\n"
            f"ðŸ” */search [ÙƒÙ„Ù…Ø©]* â€” Ø¨Ø­Ø«\n"
            f"ðŸ“Š */stats* â€” Ø§Ù„Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª\n"
            f"ðŸ“ */region [Ø¬Ù‡Ø©]* â€” ØµÙÙ‚Ø§Øª Ø§Ù„Ø¬Ù‡Ø©\n"
            f"ðŸ’¼ */type* â€” PUBLIC / SEMI / PRIVATE\n"
            f"â“ */help* â€” Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø£ÙˆØ§Ù…Ø±\n\n"
            f"ðŸŒ {SITE_URL}"
        )
    elif text in ["/help","help","Ù…Ø³Ø§Ø¹Ø¯Ø©"]:
        response = (
            f"*Ø§Ù„Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ù…ØªØ§Ø­Ø©:*\n\n"
            f"â€¢ */tenders* â€” Ø¢Ø®Ø± 5 ØµÙÙ‚Ø§Øª Ù†Ø´ÙŠØ·Ø©\n"
            f"â€¢ */search Ø¨Ù†Ø§Ø¡* â€” Ø¨Ø­Ø« Ø¹Ù† ØµÙÙ‚Ø§Øª Ø§Ù„Ø¨Ù†Ø§Ø¡\n"
            f"â€¢ */public* â€” Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ© ÙÙ‚Ø·\n"
            f"â€¢ */semi* â€” Ø§Ù„Ø´Ø±ÙƒØ§Øª Ø´Ø¨Ù‡ Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ©\n"
            f"â€¢ */private* â€” Ø§Ù„Ù‚Ø·Ø§Ø¹ Ø§Ù„Ø®Ø§Øµ (Ø§Ù„Ø¬Ø±Ø§Ø¦Ø¯)\n"
            f"â€¢ */stats* â€” Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª Ø§Ù„Ù…Ù†ØµØ©\n"
            f"â€¢ */region casablanca* â€” ØµÙÙ‚Ø§Øª Ù…Ù†Ø·Ù‚Ø©\n"
            f"â€¢ */register* â€” Ø¥Ù†Ø´Ø§Ø¡ Ø­Ø³Ø§Ø¨\n\n"
            f"Ø£Ø±Ø³Ù„ Ø£ÙŠ ÙƒÙ„Ù…Ø© Ù„Ù„Ø¨Ø­Ø« Ù…Ø¨Ø§Ø´Ø±Ø©!"
        )
    elif text.startswith("/tenders") or text in ["tenders","ØµÙÙ‚Ø§Øª","Ø¹Ø±ÙˆØ¶"]:
        db = get_db()
        rows = db.execute("SELECT objet,acheteur,date_limite,type_marche,source_name FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 5").fetchall()
        db.close()
        if rows:
            response = f"ðŸ“‹ *Ø¢Ø®Ø± Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ù†Ø´ÙŠØ·Ø©*\n{'â”'*28}\n\n"
            for i, r in enumerate(rows, 1):
                icon = "ðŸ›" if r["type_marche"] == "PUBLIC" else ("ðŸ¢" if r["type_marche"] == "SEMI_PUBLIC" else "ðŸ“°")
                response += f"{i}. {icon} *{r['objet'][:60]}*\n"
                if r["acheteur"]: response += f"   ðŸ› {r['acheteur'][:40]}\n"
                if r["date_limite"]: response += f"   ðŸ“… Limite: _{r['date_limite']}_\n"
                response += f"   ðŸ“¡ _{r['source_name']}_\n\n"
            response += f"ðŸ”— Voir tout: {SITE_URL}/tenders"
        else:
            response = "Aucune opportunitÃ© active pour le moment."

    elif text.startswith("/search ") or text.startswith("search "):
        q = text.replace("/search ","").replace("search ","").strip()
        if q:
            db = get_db()
            rows = db.execute("SELECT objet,acheteur,date_limite FROM tenders WHERE statut='actif' AND (objet LIKE ? OR description LIKE ?) LIMIT 5",
                             (f"%{q}%", f"%{q}%")).fetchall()
            db.close()
            if rows:
                response = f"ðŸ” *Ù†ØªØ§Ø¦Ø¬: {q}*\n{'â”'*28}\n\n"
                for r in rows:
                    response += f"â€¢ *{r['objet'][:70]}*\n  ðŸ“… {r['date_limite'] or 'â€”'}\n\n"
            else:
                response = f"Ù„Ø§ Ù†ØªØ§Ø¦Ø¬ Ù„Ù€ _{q}_. Ø¬Ø±Ø¨ ÙƒÙ„Ù…Ø© Ø£Ø®Ø±Ù‰."
        else:
            response = "Ø§Ø³ØªØ®Ø¯Ù…: /search [ÙƒÙ„Ù…Ø©]\nÙ…Ø«Ø§Ù„: /search Ø¨Ù†Ø§Ø¡"

    elif text in ["/public","public","Ø¹Ù…ÙˆÙ…ÙŠ"]:
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PUBLIC'").fetchone()[0]
        rows  = db.execute("SELECT objet,date_limite FROM tenders WHERE statut='actif' AND type_marche='PUBLIC' ORDER BY date_extraction DESC LIMIT 4").fetchall()
        db.close()
        response = f"ðŸ› *Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ©* ({count} Ù†Ø´ÙŠØ·Ø©)\n{'â”'*28}\n\n"
        for r in rows: response += f"â€¢ {r['objet'][:60]}\n  ðŸ“… {r['date_limite'] or 'â€”'}\n\n"

    elif text in ["/semi","semi","Ø´Ø¨Ù‡ Ø¹Ù…ÙˆÙ…ÙŠ"]:
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='SEMI_PUBLIC'").fetchone()[0]
        rows  = db.execute("SELECT objet,acheteur,date_limite FROM tenders WHERE statut='actif' AND type_marche='SEMI_PUBLIC' ORDER BY date_extraction DESC LIMIT 4").fetchall()
        db.close()
        response = f"ðŸ¢ *Ø´Ø¨Ù‡ Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ©* ({count} Ù†Ø´ÙŠØ·Ø©)\n{'â”'*28}\n\n"
        for r in rows: response += f"â€¢ {r['objet'][:60]}\n  ðŸ¢ {r['acheteur'][:30]}\n  ðŸ“… {r['date_limite'] or 'â€”'}\n\n"

    elif text in ["/private","private","Ø®Ø§Øµ","Ø§Ù„Ø¬Ø±Ø§Ø¦Ø¯"]:
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PRIVATE'").fetchone()[0]
        rows  = db.execute("SELECT objet,source_name,date_limite FROM tenders WHERE statut='actif' AND type_marche='PRIVATE' ORDER BY date_extraction DESC LIMIT 4").fetchall()
        db.close()
        response = f"ðŸ“° *Ø§Ù„Ù‚Ø·Ø§Ø¹ Ø§Ù„Ø®Ø§Øµ* ({count} Ù†Ø´ÙŠØ·Ø©)\n{'â”'*28}\n\n"
        for r in rows: response += f"â€¢ {r['objet'][:60]}\n  ðŸ“° {r['source_name']}\n  ðŸ“… {r['date_limite'] or 'â€”'}\n\n"

    elif text.startswith("/region ") or text.startswith("region "):
        q = text.replace("/region ","").replace("region ","").strip()
        db = get_db()
        matched = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND region LIKE ?", (f"%{q}%",)).fetchone()[0]
        rows = db.execute("SELECT objet,date_limite FROM tenders WHERE statut='actif' AND region LIKE ? LIMIT 4", (f"%{q}%",)).fetchall()
        db.close()
        response = f"ðŸ“ *{q}* â€” {matched} ØµÙÙ‚Ø©\n{'â”'*28}\n\n"
        if rows:
            for r in rows: response += f"â€¢ {r['objet'][:60]}\n  ðŸ“… {r['date_limite'] or 'â€”'}\n\n"
        else:
            response += "Ù„Ø§ ØªÙˆØ¬Ø¯ ØµÙÙ‚Ø§Øª ÙÙŠ Ù‡Ø°Ù‡ Ø§Ù„Ù…Ù†Ø·Ù‚Ø© Ø­Ø§Ù„ÙŠØ§Ù‹."

    elif text in ["/stats","stats","Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª"]:
        db = get_db()
        total   = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        active  = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        public  = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PUBLIC'").fetchone()[0]
        semi    = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='SEMI_PUBLIC'").fetchone()[0]
        private = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PRIVATE'").fetchone()[0]
        db.close()
        response = (
            f"ðŸ“Š *{BRAND_NAME} â€” Statistiques*\n{'â”'*28}\n\n"
            f"âœ… Actives:    *{active}*\n"
            f"ðŸ› Public:     *{public}*\n"
            f"ðŸ¢ Semi-pub:   *{semi}*\n"
            f"ðŸ“° PrivÃ©:      *{private}*\n"
            f"ðŸ“¦ Total:      *{total}*\n\n"
            f"ðŸ”„ 16 sources surveillÃ©es\n"
            f"â° Mise Ã  jour toutes les {SCRAPE_HOURS}h\n\n"
            f"ðŸŒ {SITE_URL}"
        )
    elif text in ["/register","register","ØªØ³Ø¬ÙŠÙ„","inscription"]:
        response = (
            f"ðŸ†“ *CrÃ©er votre compte*\n{'â”'*28}\n\n"
            f"Inscrivez-vous gratuitement sur:\n"
            f"ðŸ‘‰ {SITE_URL}/register\n\n"
            f"âœ… 10 alertes gratuites/mois\n"
            f"âœ… Filtres par rÃ©gion & secteur\n"
            f"âœ… Alertes Email + WhatsApp\n\n"
            f"Pour le plan *Pro* (299 DH/mois):\n"
            f"ðŸ“ž Contactez-nous directement"
        )
    else:
        # Free search for any text
        if len(text) >= 3:
            db = get_db()
            rows = db.execute("SELECT objet,date_limite,type_marche FROM tenders WHERE statut='actif' AND (objet LIKE ? OR description LIKE ?) LIMIT 3",
                             (f"%{text}%", f"%{text}%")).fetchall()
            db.close()
            if rows:
                response = f"ðŸ” *Ù†ØªØ§Ø¦Ø¬: '{text}'*\n\n"
                for r in rows:
                    icon = "ðŸ›" if r["type_marche"]=="PUBLIC" else ("ðŸ¢" if r["type_marche"]=="SEMI_PUBLIC" else "ðŸ“°")
                    response += f"{icon} {r['objet'][:70]}\nðŸ“… {r['date_limite'] or 'â€”'}\n\n"
                response += f"ðŸ”— {SITE_URL}/tenders?q={text}"
            else:
                response = (
                    f"Ù„Ù… Ø£Ø¬Ø¯ Ù†ØªØ§Ø¦Ø¬ Ù„Ù€ _{text}_\n\n"
                    f"Ø£Ø±Ø³Ù„ */help* Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø£ÙˆØ§Ù…Ø±\n"
                    f"Ø£Ùˆ ØªØµÙØ­: {SITE_URL}/tenders"
                )
        else:
            response = f"Ø£Ø±Ø³Ù„ */help* Ù„Ø±Ø¤ÙŠØ© Ø§Ù„Ø£ÙˆØ§Ù…Ø± Ø§Ù„Ù…ØªØ§Ø­Ø©."

    # Update session
    try:
        db = get_db()
        db.execute("INSERT OR REPLACE INTO wa_sessions (phone,contractor_id,state,last_msg,updated_at) VALUES (?,?,?,?,?)",
                   (phone, session.get("contractor_id"), "active", message_text[:100], datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit(); db.close()
    except: pass

    if response:
        await wa_send_text(phone, response)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# NOTIFICATIONS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async def send_email(to: str, subject: str, body: str) -> bool:
    if not to: return False
    if MAILGUN_KEY and MAILGUN_DOMAIN:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                    auth=("api", MAILGUN_KEY),
                    data={"from": f"{BRAND_NAME} <noreply@{MAILGUN_DOMAIN}>", "to": to, "subject": subject, "html": body}
                )
                if r.status_code in [200,202]:
                    metric("email_sent"); return True
        except Exception as e: logger.error(f"[mailgun] {e}")
    if GMAIL_USER and GMAIL_PASS:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject; msg["From"] = f"{BRAND_NAME} <{GMAIL_USER}>"; msg["To"] = to
            msg["List-Unsubscribe"] = f"<{SITE_URL}/unsubscribe?email={to}>"
            msg.attach(MIMEText(body, "html", "utf-8"))
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: (
                lambda srv: [srv.login(GMAIL_USER, GMAIL_PASS), srv.sendmail(GMAIL_USER, to, msg.as_string())]
            )(smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)).__enter__())
            metric("email_sent"); return True
        except Exception as e: logger.error(f"[gmail] {e}")
    return False

async def send_telegram(chat_id: str, text: str) -> bool:
    if not TELEGRAM_BOT or not chat_id: return False
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"})
        if r.status_code == 200: metric("telegram_sent"); return True
    except: pass
    return False

def match_tender(c: dict, t: dict) -> bool:
    if t.get("statut") == "annule": return False
    allowed_types = json.loads(c.get("type_filters") or '["PUBLIC","SEMI_PUBLIC","PRIVATE"]')
    if t.get("type_marche","PUBLIC") not in allowed_types: return False
    domains  = json.loads(c.get("domaines") or "[]")
    regions  = json.loads(c.get("regions") or "[]")
    keywords = [k.strip().lower() for k in (c.get("keywords") or "").split(",") if k.strip()]
    txt = (t.get("objet","") + " " + t.get("description","")).lower()
    if regions and t.get("region") and t["region"] not in regions: return False
    if domains:
        if t.get("domaine","") in domains: return True
        if keywords and any(k in txt for k in keywords): return True
        return False
    return any(k in txt for k in keywords) if keywords else True

async def notify_all(new_tenders: list):
    if not new_tenders: return
    db = get_db()
    contractors = [dict(r) for r in db.execute("SELECT * FROM contractors WHERE actif=1 AND plan!='free'").fetchall()]
    db.close()
    for c in contractors:
        matching = [t for t in new_tenders if match_tender(c, t)][:3]
        if not matching: continue
        limit = PLANS.get(c.get("plan","free"),{}).get("limits",{}).get("notifs",10)
        if c.get("notifs_sent",0) >= limit: continue
        channels = json.loads(c.get("notif_channels") or '["email"]')
        for t in matching:
            objet = t.get("objet","")[:70]
            type_label = {"PUBLIC":"ðŸ› Ø¹Ù…ÙˆÙ…ÙŠ","SEMI_PUBLIC":"ðŸ¢ Ø´Ø¨Ù‡ Ø¹Ù…ÙˆÙ…ÙŠ","PRIVATE":"ðŸ“° Ø®Ø§Øµ"}.get(t.get("type_marche",""),"")
            if "email" in channels and c.get("email"):
                body = f"""<div dir="rtl" style="font-family:Georgia,serif;max-width:600px;margin:0 auto;background:#0d0d0d;color:#fff;border-radius:12px;overflow:hidden">
<div style="background:#1a1a1a;padding:24px;border-bottom:1px solid #2a2a2a">
  <div style="font-size:11px;color:#888;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">MODERN BUSINESS</div>
  <div style="font-size:18px;font-weight:700;color:#f5c842">Nouvelle OpportunitÃ©</div>
</div>
<div style="padding:24px">
  <h2 style="font-size:16px;color:#fff;margin:0 0 16px;line-height:1.4">{objet}</h2>
  <table style="width:100%;font-size:12px;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#888;width:35%">Type</td><td style="color:#f5c842">{type_label}</td></tr>
    <tr><td style="padding:6px 0;color:#888">Organisme</td><td style="color:#fff">{t.get('acheteur','â€”')[:50]}</td></tr>
    <tr><td style="padding:6px 0;color:#888">RÃ©gion</td><td style="color:#fff">{t.get('region','â€”')}</td></tr>
    <tr><td style="padding:6px 0;color:#888">Source</td><td style="color:#888">{t.get('source_name','â€”')}</td></tr>
    <tr><td style="padding:6px 0;color:#888">Date limite</td><td style="color:#ef4444;font-weight:700">{t.get('date_limite','â€”')}</td></tr>
  </table>
  <a href="{SITE_URL}/tender/{t.get('id','')}" style="display:inline-block;margin-top:20px;padding:10px 24px;background:#f5c842;color:#000;border-radius:6px;text-decoration:none;font-size:13px;font-weight:700">Voir l'opportunitÃ© â†’</a>
</div>
<div style="padding:16px 24px;border-top:1px solid #2a2a2a;font-size:10px;color:#555;text-align:center">
  {BRAND_NAME} â€” <a href="{SITE_URL}/unsubscribe?email={c.get('email','')}" style="color:#555">Se dÃ©sabonner</a>
</div></div>"""
                ok = await send_email(c["email"], f"[{BRAND_NAME}] {objet}", body)
                if ok:
                    try:
                        db = get_db()
                        db.execute("INSERT INTO notifications (contractor_id,tender_id,channel,sent_at,status) VALUES (?,?,?,?,?)",
                                   (c["id"],t["id"],"email",datetime.now().strftime("%Y-%m-%d %H:%M"),"sent"))
                        db.execute("UPDATE contractors SET notifs_sent=notifs_sent+1 WHERE id=?", (c["id"],))
                        db.commit(); db.close()
                    except: pass
            if "whatsapp" in channels and c.get("whatsapp"):
                msg = (f"ðŸ¢ *{BRAND_NAME}*\n{type_label}\n\n"
                       f"*{objet}*\n\n"
                       f"ðŸ› {t.get('acheteur','â€”')[:50]}\n"
                       f"ðŸ“ {t.get('region','â€”')}\n"
                       f"ðŸ“° {t.get('source_name','')}\n"
                       f"ðŸ“… Limite: *{t.get('date_limite','â€”')}*\n\n"
                       f"ðŸ”— {SITE_URL}/tender/{t.get('id','')}")
                await wa_send_text(c["whatsapp"], msg)
            if "telegram" in channels and c.get("telegram"):
                msg = (f"ðŸ¢ <b>{BRAND_NAME}</b> | {type_label}\n\n"
                       f"<b>{objet}</b>\n\n"
                       f"ðŸ› {t.get('acheteur','â€”')[:50]}\n"
                       f"ðŸ“ {t.get('region','â€”')}\n"
                       f"ðŸ“… <b>{t.get('date_limite','â€”')}</b>\n\n"
                       f"ðŸ”— {SITE_URL}/tender/{t.get('id','')}")
                await send_telegram(c["telegram"], msg)
            await asyncio.sleep(0.2)

LAST_SCRAPE = 0
async def scheduler_loop():
    global LAST_SCRAPE
    await asyncio.sleep(30)
    while True:
        try:
            if time.time() - LAST_SCRAPE >= SCRAPE_HOURS * 3600:
                LAST_SCRAPE = time.time()
                loop = asyncio.get_event_loop()
                new = await loop.run_in_executor(None, run_all_scrapers)
                if new: await notify_all(new)
        except Exception as e:
            SCRAPE_STATS["running"] = False; logger.error(f"[scheduler] {e}")
        await asyncio.sleep(600)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AI AGENT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async def ai_heal() -> dict:
    fixes = []
    try:
        db = get_db()
        exp = [r["id"] for r in db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall() if is_expired(r["date_limite"])]
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join('?'*len(exp))})", exp)
            db.commit(); fixes.append(f"Expired {len(exp)} tenders")
        gone = db.execute("DELETE FROM tenders WHERE objet='' OR objet IS NULL").rowcount
        if gone: db.commit(); fixes.append(f"Removed {gone} empty tenders")
        no_r = db.execute("SELECT id,acheteur,description FROM tenders WHERE region='' OR region IS NULL LIMIT 100").fetchall()
        fr = 0
        for r in no_r:
            rg = classify_region((r["acheteur"] or "") + " " + (r["description"] or "")[:300])
            if rg: db.execute("UPDATE tenders SET region=? WHERE id=?", (rg,r["id"])); fr+=1
        if fr: db.commit(); fixes.append(f"Classified region for {fr}")
        no_d = db.execute("SELECT id,objet,description FROM tenders WHERE domaine='' OR domaine IS NULL LIMIT 100").fetchall()
        fd = 0
        for r in no_d:
            dm = classify_domain((r["objet"] or "") + " " + (r["description"] or "")[:300])
            if dm: db.execute("UPDATE tenders SET domaine=? WHERE id=?", (dm,r["id"])); fd+=1
        if fd: db.commit(); fixes.append(f"Classified domain for {fd}")
        total  = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        errors = db.execute("SELECT COUNT(*) FROM error_log WHERE resolved=0").fetchone()[0]
        db.close()
        return {"status":"ok","total":total,"active":active,"errors":errors,"fixes":fixes,"ts":datetime.now().isoformat()}
    except Exception as e:
        return {"status":"error","error":str(e)}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FASTAPI APP
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@asynccontextmanager
async def lifespan(app):
    for d in ["static","data","templates"]:
        try: os.makedirs(d, exist_ok=True)
        except: pass
    try: init_db()
    except Exception as e: logger.error(f"[init_db] {e}")
    asyncio.create_task(scheduler_loop())
    logger.info(f"{BRAND_NAME} v1.0 started")
    yield

app = FastAPI(lifespan=lifespan, title=BRAND_NAME, version="1.0", docs_url=None, redoc_url=None)
app.add_middleware(SecMiddleware)

@app.exception_handler(Exception)
async def exc_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    log_error(str(request.url.path), str(exc), tb)
    if SENTRY_DSN:
        try:
            import sentry_sdk; sentry_sdk.capture_exception(exc)
        except: pass
    return HTMLResponse(open("templates/_error.html").read().replace("{{code}}","500").replace("{{msg}}","Erreur serveur") if os.path.exists("templates/_error.html") else
        '<html><body style="background:#0d0d0d;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:Georgia"><div style="text-align:center"><div style="font-size:48px;margin-bottom:16px">âš </div><h2>Erreur serveur</h2><p style="color:#888;margin:12px 0">L\'erreur a Ã©tÃ© enregistrÃ©e automatiquement.</p><a href="/" style="color:#f5c842">Retour â†’</a></div></body></html>',
        status_code=500)

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return HTMLResponse(
        '<html><body style="background:#0d0d0d;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:Georgia"><div style="text-align:center"><div style="font-size:48px;margin-bottom:16px">404</div><h2 style="color:#f5c842">Page introuvable</h2><p style="color:#888;margin:12px 0">Cette page n\'existe pas.</p><a href="/" style="color:#f5c842">Retour â†’</a></div></body></html>',
        status_code=404)

try: os.makedirs("static",exist_ok=True); app.mount("/static",StaticFiles(directory="static"),name="static")
except Exception as e: print(f"[static] {e}")
try: os.makedirs("templates",exist_ok=True); templates=Jinja2Templates(directory="templates")
except Exception as e: print(f"[templates] {e}"); templates=None

def render(req, tpl, ctx={}):
    if not templates: return HTMLResponse("<h1>Templates not loaded</h1>",500)
    try: return templates.TemplateResponse(tpl, {"request":req,"BRAND":BRAND_NAME,"BRAND_TAGLINE":BRAND_TAGLINE,"SITE_URL":SITE_URL,"PLANS":PLANS,"DOMAINS_FR":DOMAINS_FR,"REGIONS_LIST":REGIONS_LIST,**ctx})
    except Exception as e: log_error(f"render:{tpl}",str(e),traceback.format_exc()); raise

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ROUTES â€” PUBLIC
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    db = get_db()
    try:
        stats = {
            "total":       db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "active":      db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "public":      db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='PUBLIC' AND statut='actif'").fetchone()[0],
            "semi":        db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='SEMI_PUBLIC' AND statut='actif'").fetchone()[0],
            "private":     db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='PRIVATE' AND statut='actif'").fetchone()[0],
            "sources":     len(SCRAPER_SOURCES),
            "contractors": db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        }
        recent = [dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,type_marche,date_limite,montant,source_name FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 6").fetchall()]
        by_type = [dict(r) for r in db.execute("SELECT type_marche, COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY type_marche ORDER BY cnt DESC").fetchall()]
        by_source = [dict(r) for r in db.execute("SELECT source_name, COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY source_name ORDER BY cnt DESC LIMIT 8").fetchall()]
    finally: db.close()
    c = get_contractor(request)
    metric("pv:home")
    return render(request, "landing.html", {"stats":stats,"recent":recent,"by_type":by_type,"by_source":by_source,"contractor":c})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_list(request: Request, region:str="", domaine:str="", q:str="", type_filter:str="", source:str="", page:int=1):
    rl(request, "tenders", 120, 60)
    per_page=20; offset=(page-1)*per_page
    db = get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if region:      conds.append("region=?");           params.append(region)
        if domaine:     conds.append("domaine=?");           params.append(domaine)
        if type_filter: conds.append("type_marche=?");       params.append(type_filter.upper())
        if source:      conds.append("source_key=?");        params.append(source)
        if q:
            qc=q[:100]; conds.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
            params+=[f"%{qc}%",f"%{qc}%",f"%{qc}%"]
        w=" AND ".join(conds)
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}",params).fetchone()[0]
        tenders=[dict(r) for r in db.execute(f"SELECT id,objet,acheteur,region,domaine,type_marche,date_limite,montant,source_name,source_key FROM tenders WHERE {w} ORDER BY date_extraction DESC LIMIT ? OFFSET ?",params+[per_page,offset]).fetchall()]
        pages=max(1,(total+per_page-1)//per_page)
        c=get_contractor(request); saved_ids=set()
        if c:
            saved=db.execute("SELECT tender_id FROM saved_tenders WHERE contractor_id=?",(c["id"],)).fetchall()
            saved_ids={r[0] for r in saved}
    finally: db.close()
    metric("pv:tenders")
    return render(request,"tenders.html",{"tenders":tenders,"total":total,"page":page,"pages":pages,"q":q,"region":region,"domaine":domaine,"type_filter":type_filter,"source":source,"contractor":c,"saved_ids":saved_ids,"SCRAPER_SOURCES":SCRAPER_SOURCES})

@app.get("/tender/{tid}", response_class=HTMLResponse)
async def tender_detail(request: Request, tid: str):
    if not re.match(r'^[\w\-]{1,80}$', tid): raise HTTPException(400)
    db=get_db()
    try:
        row=db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not row: raise HTTPException(404)
        tender=dict(row)
        try: db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?",(tid,)); db.commit()
        except: pass
        c=get_contractor(request); is_saved=False
        if c:
            sv=db.execute("SELECT 1 FROM saved_tenders WHERE contractor_id=? AND tender_id=?",(c["id"],tid)).fetchone()
            is_saved=sv is not None
        related=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,date_limite,type_marche,source_name FROM tenders WHERE statut='actif' AND id!=? AND (region=? OR domaine=?) LIMIT 4",(tid,tender.get("region",""),tender.get("domaine",""))).fetchall()]
    finally: db.close()
    metric("pv:tender_detail")
    return render(request,"tender_detail.html",{"tender":tender,"contractor":c,"is_saved":is_saved,"related":related})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    c=get_contractor(request)
    return render(request,"pricing.html",{"contractor":c})

@app.get("/contact", response_class=HTMLResponse)
async def contact_get(request: Request):
    c=get_contractor(request)
    return render(request,"contact.html",{"contractor":c,"success":False,"error":""})

@app.post("/contact", response_class=HTMLResponse)
async def contact_post(request: Request, nom:str=Form(""), email:str=Form(""), phone:str=Form(""), entreprise:str=Form(""), plan:str=Form("pro"), message:str=Form("")):
    rl(request,"contact",5,3600)
    db=get_db()
    try:
        db.execute("INSERT INTO contact_requests (nom,email,phone,entreprise,plan,message,created_at) VALUES (?,?,?,?,?,?,?)",
                   (nom[:100],email[:100],phone[:30],entreprise[:100],plan,message[:1000],datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit()
    finally: db.close()
    # Notify admin
    asyncio.create_task(send_email(GMAIL_USER, f"[{BRAND_NAME}] New Contact: {nom} â€” {plan}",
        f"<b>Nom:</b> {nom}<br><b>Email:</b> {email}<br><b>Phone:</b> {phone}<br><b>Entreprise:</b> {entreprise}<br><b>Plan:</b> {plan}<br><b>Message:</b> {message}"))
    c=get_contractor(request)
    return render(request,"contact.html",{"contractor":c,"success":True,"error":""})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    c=get_contractor(request)
    return render(request,"privacy.html",{"contractor":c})

@app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(request: Request, email:str=""):
    if email:
        db=get_db()
        try: db.execute("UPDATE contractors SET actif=0 WHERE email=?",(email.lower(),)); db.commit()
        finally: db.close()
    return HTMLResponse(f'<html lang="fr"><body style="background:#0d0d0d;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:Georgia;text-align:center"><div><h2 style="color:#f5c842">DÃ©sabonnement effectuÃ©</h2><p style="color:#888;margin:12px 0">Vous ne recevrez plus de messages.</p><a href="/" style="color:#f5c842">Retour â†’</a></div></body></html>')

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AUTH
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.get("/register", response_class=HTMLResponse)
async def reg_get(request: Request):
    return render(request,"register.html",{"error":"","success":""})

@app.post("/register", response_class=HTMLResponse)
async def reg_post(request: Request, nom:str=Form(""), entreprise:str=Form(""), email:str=Form(""), phone:str=Form(""), whatsapp:str=Form(""), password:str=Form(""), domaines:list=Form([]), regions:list=Form([]), type_filters:list=Form(["PUBLIC","SEMI_PUBLIC","PRIVATE"])):
    rl(request,"register",8,3600)
    error=""
    if not nom or not email or not password: error="Tous les champs obligatoires (*) doivent Ãªtre remplis"
    elif len(password)<8: error="Le mot de passe doit contenir au moins 8 caractÃ¨res"
    elif not re.match(r'^[^@]+@[^@]+\.[^@]+$',email): error="Adresse email invalide"
    else:
        db=get_db()
        try:
            ex=db.execute("SELECT id FROM contractors WHERE email=?",(email.lower(),)).fetchone()
            if ex: error="Cette adresse email est dÃ©jÃ  utilisÃ©e"
            else:
                wa_clean = re.sub(r'\D','',whatsapp or "")
                if wa_clean.startswith('0'): wa_clean='212'+wa_clean[1:]
                db.execute("INSERT INTO contractors (nom,entreprise,email,phone,whatsapp,domaines,regions,type_filters,plan,password_hash,actif,notifs_sent,saves_count,ai_count,created_at,notif_channels) VALUES (?,?,?,?,?,?,?,?,?,?,1,0,0,0,?,?)",
                           (nom.strip(),entreprise.strip(),email.lower().strip(),phone.strip(),wa_clean,
                            json.dumps(domaines),json.dumps(regions),json.dumps(type_filters),
                            "free",hash_pw(password),datetime.now().strftime("%Y-%m-%d %H:%M"),
                            json.dumps(["email"] + (["whatsapp"] if wa_clean else []))))
                db.commit()
                cid=db.execute("SELECT id FROM contractors WHERE email=?",(email.lower(),)).fetchone()[0]
                db.close()
                metric("registrations")
                # Welcome email
                asyncio.create_task(send_email(email,f"Bienvenue sur {BRAND_NAME} !",
                    f'<div dir="ltr" style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:32px;border-radius:12px"><h2 style="color:#f5c842">Bienvenue, {nom}!</h2><p style="color:#aaa">Votre compte {BRAND_NAME} est prÃªt.</p><a href="{SITE_URL}/dashboard" style="display:inline-block;margin-top:16px;padding:12px 24px;background:#f5c842;color:#000;border-radius:6px;font-weight:700;text-decoration:none">AccÃ©der â†’</a></div>'))
                # Welcome WhatsApp
                if wa_clean:
                    asyncio.create_task(wa_send_text(wa_clean,f"ðŸ¢ *{BRAND_NAME}*\n\nBienvenue {nom}! Votre compte est activÃ©.\n\nâœ… Envoyez */tenders* pour voir les derniÃ¨res opportunitÃ©s.\nðŸŒ {SITE_URL}"))
                resp=RedirectResponse("/dashboard",status_code=302)
                create_session(resp,cid); return resp
        except Exception as e: error=f"Erreur d'inscription: {e}"
        finally:
            try: db.close()
            except: pass
    return render(request,"register.html",{"error":error,"success":""})

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    c=get_contractor(request)
    if c: return RedirectResponse("/dashboard",status_code=302)
    return render(request,"login.html",{"error":""})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, email:str=Form(""), password:str=Form("")):
    rl(request,f"login:{get_ip(request)}",5,300)
    db=get_db()
    try:
        row=db.execute("SELECT * FROM contractors WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
        if not row or not check_pw(password,dict(row).get("password_hash","")):
            logger.warning(f"[login] failed: {email}")
            return render(request,"login.html",{"error":"Email ou mot de passe incorrect"})
        c=dict(row)
        db.execute("UPDATE contractors SET last_login=? WHERE id=?",(datetime.now().strftime("%Y-%m-%d %H:%M"),c["id"]))
        db.commit()
    finally: db.close()
    metric("logins")
    resp=RedirectResponse("/dashboard",status_code=302)
    create_session(resp,c["id"]); return resp

@app.get("/logout")
async def logout(request: Request):
    resp=RedirectResponse("/",status_code=302)
    delete_session(resp); return resp

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DASHBOARD
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    c=get_contractor(request)
    if not c: return RedirectResponse("/login",status_code=302)
    db=get_db()
    try:
        saved=[dict(r) for r in db.execute("SELECT t.* FROM tenders t JOIN saved_tenders s ON t.id=s.tender_id WHERE s.contractor_id=? ORDER BY s.saved_at DESC LIMIT 5",(c["id"],)).fetchall()]
        notifs_count=db.execute("SELECT COUNT(*) FROM notifications WHERE contractor_id=?",(c["id"],)).fetchone()[0]
        all_active=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,type_marche,date_limite,montant,source_name FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 150").fetchall()]
        matching=[t for t in all_active if match_tender(c,t)][:12]
        plan=PLANS.get(c.get("plan","free"),{})
        stats_by_type=[dict(r) for r in db.execute("SELECT type_marche,COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY type_marche").fetchall()]
    finally: db.close()
    metric("pv:dashboard")
    return render(request,"dashboard.html",{"c":c,"saved":saved,"notifs_count":notifs_count,"matching":matching,"plan":plan,"stats_by_type":stats_by_type})

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request):
    c=get_contractor(request)
    if not c: return RedirectResponse("/login",status_code=302)
    return render(request,"settings.html",{"c":c,"success":"","error":""})

@app.post("/settings", response_class=HTMLResponse)
async def settings_post(request: Request, nom:str=Form(""), entreprise:str=Form(""), phone:str=Form(""), whatsapp:str=Form(""), telegram:str=Form(""), keywords:str=Form(""), domaines:list=Form([]), regions:list=Form([]), type_filters:list=Form(["PUBLIC"]), notif_channels:list=Form(["email"]), password:str=Form(""), password_new:str=Form("")):
    c=get_contractor(request)
    if not c: return RedirectResponse("/login",status_code=302)
    wa_clean=re.sub(r'\D','',whatsapp or "")
    if wa_clean.startswith('0'): wa_clean='212'+wa_clean[1:]
    error=""
    db=get_db()
    try:
        db.execute("UPDATE contractors SET nom=?,entreprise=?,phone=?,whatsapp=?,telegram=?,keywords=?,domaines=?,regions=?,type_filters=?,notif_channels=? WHERE id=?",
                   (nom.strip() or c["nom"],entreprise.strip(),phone.strip(),wa_clean,telegram.strip(),keywords.strip()[:300],
                    json.dumps(domaines),json.dumps(regions),json.dumps(type_filters),json.dumps(notif_channels),c["id"]))
        if password and password_new:
            if not check_pw(password,c.get("password_hash","")): error="Mot de passe actuel incorrect"
            elif len(password_new)<8: error="Le nouveau mot de passe doit contenir 8 caractÃ¨res minimum"
            else: db.execute("UPDATE contractors SET password_hash=? WHERE id=?",(hash_pw(password_new),c["id"]))
        db.commit(); c=get_contractor(request)
    finally: db.close()
    return render(request,"settings.html",{"c":c,"success":"ParamÃ¨tres sauvegardÃ©s âœ“" if not error else "","error":error})

@app.get("/saved", response_class=HTMLResponse)
async def saved_page(request: Request):
    c=get_contractor(request)
    if not c: return RedirectResponse("/login",status_code=302)
    db=get_db()
    try:
        saved=[dict(r) for r in db.execute("SELECT t.*,s.saved_at,s.notes FROM tenders t JOIN saved_tenders s ON t.id=s.tender_id WHERE s.contractor_id=? ORDER BY s.saved_at DESC",(c["id"],)).fetchall()]
    finally: db.close()
    return render(request,"saved.html",{"c":c,"saved":saved})

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.post("/api/save")
async def api_save(request: Request, tender_id:str=Form("")):
    c=get_contractor(request)
    if not c: return JSONResponse({"ok":False,"error":"Login required"},401)
    limit=PLANS.get(c.get("plan","free"),{}).get("limits",{}).get("saves",5)
    if c.get("saves_count",0)>=limit: return JSONResponse({"ok":False,"error":"Limite atteinte â€” upgrade Pro"},403)
    if not re.match(r'^[\w\-]{1,80}$',tender_id): raise HTTPException(400)
    db=get_db()
    try:
        db.execute("INSERT OR IGNORE INTO saved_tenders (contractor_id,tender_id,saved_at) VALUES (?,?,?)",(c["id"],tender_id,datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.execute("UPDATE contractors SET saves_count=saves_count+1 WHERE id=?",(c["id"],))
        db.commit(); changed=db.execute("SELECT changes()").fetchone()[0]
    finally: db.close()
    return JSONResponse({"ok":True,"saved":changed>0})

@app.post("/api/unsave")
async def api_unsave(request: Request, tender_id:str=Form("")):
    c=get_contractor(request)
    if not c: return JSONResponse({"ok":False},401)
    db=get_db()
    try:
        db.execute("DELETE FROM saved_tenders WHERE contractor_id=? AND tender_id=?",(c["id"],tender_id))
        db.execute("UPDATE contractors SET saves_count=MAX(0,saves_count-1) WHERE id=?",(c["id"],))
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/api/v1/tenders")
async def api_v1(q:str="",region:str="",domaine:str="",type_filter:str="",source:str="",page:int=1,limit:int=20,authorization:str=Header(default="")):
    key=authorization.replace("Bearer ","").strip()
    if not key: raise HTTPException(401,"API key required")
    h=hashlib.sha256(key.encode()).hexdigest()
    db=get_db()
    try:
        ak=db.execute("SELECT ak.*,c.plan FROM api_keys ak JOIN contractors c ON c.id=ak.contractor_id WHERE ak.key_hash=? AND ak.active=1",(h,)).fetchone()
        if not ak: raise HTTPException(403,"Invalid key")
        db.execute("UPDATE api_keys SET calls_total=calls_total+1 WHERE id=?",(ak["id"],)); db.commit()
        if limit>200: limit=200
        conds=["statut='actif'"]; params=[]
        if q: conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params+=[f"%{q[:80]}%",f"%{q[:80]}%"]
        if region: conds.append("region=?"); params.append(region)
        if domaine: conds.append("domaine=?"); params.append(domaine)
        if type_filter: conds.append("type_marche=?"); params.append(type_filter.upper())
        if source: conds.append("source_key=?"); params.append(source)
        w=" AND ".join(conds); offset=(page-1)*limit
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}",params).fetchone()[0]
        rows=[dict(r) for r in db.execute(f"SELECT id,objet,acheteur,region,domaine,type_marche,date_publication,date_limite,montant,statut,url,source_name,score FROM tenders WHERE {w} ORDER BY date_extraction DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchall()]
    finally: db.close()
    return JSONResponse({"success":True,"total":total,"page":page,"pages":(total+limit-1)//limit,"data":rows,"sources":len(SCRAPER_SOURCES)})

@app.post("/api/keys/create")
async def create_key(request: Request, name:str=Form("Default")):
    c=get_contractor(request)
    if not c: raise HTTPException(403)
    if c.get("plan","free")=="free": return JSONResponse({"error":"Plan Pro requis"},403)
    raw="mb_"+secrets.token_urlsafe(32)
    h=hashlib.sha256(raw.encode()).hexdigest()
    db=get_db()
    try:
        db.execute("INSERT INTO api_keys (contractor_id,key_hash,key_prefix,name,created_at) VALUES (?,?,?,?,?)",(c["id"],h,raw[:12],name[:50],datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit()
    finally: db.close()
    return JSONResponse({"api_key":raw,"prefix":raw[:12]})

@app.get("/export/csv")
async def export_csv(request: Request, q:str="", region:str="", domaine:str="", type_filter:str="", limit:int=1000):
    import io, csv
    c=get_contractor(request)
    if not c or not PLANS.get(c.get("plan","free"),{}).get("limits",{}).get("export",False):
        return JSONResponse({"error":"Plan Pro requis"},403)
    if limit>5000: limit=5000
    db=get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if q: conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params+=[f"%{q}%",f"%{q}%"]
        if region: conds.append("region=?"); params.append(region)
        if domaine: conds.append("domaine=?"); params.append(domaine)
        if type_filter: conds.append("type_marche=?"); params.append(type_filter.upper())
        rows=[dict(r) for r in db.execute(f"SELECT id,objet,acheteur,region,domaine,type_marche,date_publication,date_limite,montant,statut,url,source_name FROM tenders WHERE {' AND '.join(conds)} ORDER BY date_extraction DESC LIMIT ?",params+[limit]).fetchall()]
    finally: db.close()
    buf=io.StringIO()
    w=csv.DictWriter(buf,fieldnames=["id","objet","acheteur","region","domaine","type_marche","date_publication","date_limite","montant","statut","url","source_name"],extrasaction="ignore")
    w.writeheader()
    for r in rows: w.writerow(r)
    from fastapi.responses import Response
    return Response(content=buf.getvalue().encode("utf-8-sig"),media_type="text/csv",
                    headers={"Content-Disposition":f"attachment; filename=modern_business_{datetime.now().strftime('%Y%m%d')}.csv"})

@app.get("/api/stats")
async def api_stats():
    db=get_db()
    try:
        return JSONResponse({
            "total":    db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "active":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "public":   db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='PUBLIC' AND statut='actif'").fetchone()[0],
            "semi":     db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='SEMI_PUBLIC' AND statut='actif'").fetchone()[0],
            "private":  db.execute("SELECT COUNT(*) FROM tenders WHERE type_marche='PRIVATE' AND statut='actif'").fetchone()[0],
            "sources":  len(SCRAPER_SOURCES),
            "by_source":[dict(r) for r in db.execute("SELECT source_name,COUNT(*) as c FROM tenders WHERE statut='actif' GROUP BY source_name ORDER BY c DESC").fetchall()],
        })
    finally: db.close()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# WHATSAPP WEBHOOK
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.get("/whatsapp/webhook")
async def wa_verify(request: Request):
    """Meta webhook verification"""
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        logger.info("[WhatsApp] Webhook verified âœ“")
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")

@app.post("/whatsapp/webhook")
async def wa_webhook(request: Request):
    """Receive WhatsApp messages via Meta Cloud API"""
    try:
        data = await request.json()
        # Parse message from Meta webhook format
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                val = change.get("value", {})
                messages = val.get("messages", [])
                for msg in messages:
                    phone = msg.get("from","")
                    msg_type = msg.get("type","text")
                    if msg_type == "text":
                        text = msg.get("text",{}).get("body","")
                    elif msg_type == "button":
                        text = msg.get("button",{}).get("payload","")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive",{})
                        if interactive.get("type") == "button_reply":
                            text = interactive.get("button_reply",{}).get("id","")
                        else:
                            text = interactive.get("list_reply",{}).get("id","")
                    else:
                        text = ""
                    if phone and text:
                        asyncio.create_task(wa_handle_message(phone, text, msg_type))
    except Exception as e:
        logger.error(f"[WhatsApp webhook] {e}")
    return JSONResponse({"status": "ok"})

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TELEGRAM WEBHOOK
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.post("/telegram/webhook")
async def tg_webhook(request: Request):
    try:
        data=await request.json()
        msg=data.get("message") or {}
        chat_id=str(msg.get("chat",{}).get("id",""))
        text=msg.get("text","").strip()
        if not chat_id: return {"ok":True}
        if text in ["/start","start"]:
            await send_telegram(chat_id,f"ðŸ¢ <b>{BRAND_NAME}</b>\nIntelligence des MarchÃ©s Maroc\n\n/tenders â€” DerniÃ¨res opportunitÃ©s\n/stats â€” Statistiques\n/public /semi /private\n\nðŸŒ {SITE_URL}")
        elif text=="/tenders":
            db=get_db()
            try: rows=db.execute("SELECT objet,acheteur,date_limite,type_marche FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 5").fetchall()
            finally: db.close()
            resp=f"ðŸ“‹ <b>OpportunitÃ©s â€” {BRAND_NAME}</b>\n\n"
            for r in rows:
                icon="ðŸ›" if r["type_marche"]=="PUBLIC" else ("ðŸ¢" if r["type_marche"]=="SEMI_PUBLIC" else "ðŸ“°")
                resp+=f"{icon} {r['objet'][:60]}\nðŸ“… {r['date_limite'] or 'â€”'}\n\n"
            resp+=f"ðŸ”— {SITE_URL}/tenders"
            await send_telegram(chat_id,resp)
        elif text=="/stats":
            db=get_db()
            try:
                active=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
                pub=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PUBLIC'").fetchone()[0]
                semi=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='SEMI_PUBLIC'").fetchone()[0]
                priv=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PRIVATE'").fetchone()[0]
            finally: db.close()
            await send_telegram(chat_id,f"ðŸ“Š <b>{BRAND_NAME}</b>\n\nðŸ› Public: <b>{pub}</b>\nðŸ¢ Semi-pub: <b>{semi}</b>\nðŸ“° PrivÃ©: <b>{priv}</b>\n\nâœ… Total actif: <b>{active}</b>\nðŸŒ {SITE_URL}")
    except Exception as e: logger.error(f"[telegram] {e}")
    return {"ok":True}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def check_admin(pwd):
    if pwd!=ADMIN_PASS: metric("admin_failed"); raise HTTPException(403)

@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, pwd:str=""):
    check_admin(pwd); rl(request,"admin",30,60)
    db=get_db()
    try:
        stats={
            "tenders":      db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "active":       db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "public":       db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PUBLIC'").fetchone()[0],
            "semi":         db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='SEMI_PUBLIC'").fetchone()[0],
            "private":      db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND type_marche='PRIVATE'").fetchone()[0],
            "contractors":  db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
            "pro_plus":     db.execute("SELECT COUNT(*) FROM contractors WHERE plan!='free'").fetchone()[0],
            "notifs":       db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
            "contacts":     db.execute("SELECT COUNT(*) FROM contact_requests WHERE status='new'").fetchone()[0],
            "errors":       db.execute("SELECT COUNT(*) FROM error_log WHERE resolved=0").fetchone()[0],
            "wa_sessions":  db.execute("SELECT COUNT(*) FROM wa_sessions").fetchone()[0],
        }
        errs=[dict(r) for r in db.execute("SELECT * FROM error_log WHERE resolved=0 ORDER BY last_seen DESC LIMIT 8").fetchall()]
        ctors=[dict(r) for r in db.execute("SELECT id,nom,email,plan,whatsapp,telegram,created_at,notifs_sent FROM contractors ORDER BY id DESC LIMIT 20").fetchall()]
        contacts=[dict(r) for r in db.execute("SELECT * FROM contact_requests ORDER BY id DESC LIMIT 10").fetchall()]
        scrape_hist=[dict(r) for r in db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 5").fetchall()]
        by_source=[dict(r) for r in db.execute("SELECT source_name,source_key,COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY source_key ORDER BY cnt DESC").fetchall()]
    finally: db.close()
    return render(request,"admin.html",{"stats":stats,"errors":errs,"contractors":ctors,"contacts":contacts,"scrape_hist":scrape_hist,"by_source":by_source,"scrape_stats":SCRAPE_STATS,"scrape_log":SCRAPE_LOG[-60:],"pwd":pwd,"SCRAPER_SOURCES":SCRAPER_SOURCES,"METRICS":dict(METRICS)})

@app.get("/admin/scrape")
async def admin_scrape(pwd:str=""):
    check_admin(pwd)
    if SCRAPE_STATS.get("running"): return JSONResponse({"ok":False,"msg":"Already running"})
    async def run():
        loop=asyncio.get_event_loop()
        try: new=await loop.run_in_executor(None,run_all_scrapers); asyncio.create_task(notify_all(new))
        finally: SCRAPE_STATS["running"]=False
    asyncio.create_task(run())
    return JSONResponse({"ok":True,"msg":"All scrapers started (16 sources)"})

@app.get("/admin/scrape_logs")
async def admin_logs(pwd:str=""):
    check_admin(pwd)
    return JSONResponse({"logs":SCRAPE_LOG[-150:],"stats":SCRAPE_STATS,"sources":list(SCRAPER_SOURCES.keys())})

@app.get("/admin/heal")
async def admin_heal(pwd:str=""):
    check_admin(pwd); result=await ai_heal(); return JSONResponse(result)

@app.get("/admin/resolve_error")
async def resolve_error(pwd:str="", error_id:int=0):
    check_admin(pwd)
    db=get_db()
    try: db.execute("UPDATE error_log SET resolved=1 WHERE id=?",(error_id,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/activate")
async def activate(pwd:str="", contractor_id:int=0, plan:str="pro"):
    check_admin(pwd)
    if plan not in PLANS: raise HTTPException(400)
    db=get_db()
    try:
        expires=(datetime.now()+timedelta(days=31)).strftime("%Y-%m-%d")
        db.execute("UPDATE contractors SET plan=?,plan_expires=?,plan_activated_by=? WHERE id=?",(plan,expires,"admin",contractor_id))
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"plan":plan})

@app.post("/admin/broadcast")
async def broadcast(pwd:str=Form(""), message:str=Form(""), channel:str=Form("email")):
    check_admin(pwd)
    db=get_db()
    try: ctors=[dict(r) for r in db.execute("SELECT * FROM contractors WHERE actif=1").fetchall()]
    finally: db.close()
    sent=0
    for c in ctors:
        if channel in ("email","all") and c.get("email"):
            body=f'<div style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:28px;border-radius:12px"><p style="color:#f5c842;font-weight:700">{BRAND_NAME}</p>{message}<hr style="border-color:#2a2a2a;margin:20px 0"><p style="font-size:10px;color:#555"><a href="{SITE_URL}/unsubscribe?email={c["email"]}" style="color:#555">Se dÃ©sabonner</a></p></div>'
            await send_email(c["email"],f"[{BRAND_NAME}] Message",body); sent+=1
        if channel in ("whatsapp","all") and c.get("whatsapp"):
            await wa_send_text(c["whatsapp"],message); sent+=1
        if channel in ("telegram","all") and c.get("telegram"):
            await send_telegram(c["telegram"],message); sent+=1
        await asyncio.sleep(0.2)
    return JSONResponse({"ok":True,"sent":sent})

@app.get("/admin/cleanup")
async def cleanup(pwd:str=""):
    check_admin(pwd)
    db=get_db()
    try:
        db.execute("DELETE FROM tenders WHERE statut IN ('expire','annule') AND date_extraction < date('now','-90 days')")
        db.execute("DELETE FROM error_log WHERE resolved=1 AND last_seen < date('now','-30 days')")
        remaining=db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"remaining":remaining})

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MONITORING & SEO
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.get("/health")
async def health():
    db=get_db()
    try:
        active=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        errors=db.execute("SELECT COUNT(*) FROM error_log WHERE resolved=0").fetchone()[0]
    finally: db.close()
    return JSONResponse({"status":"ok","brand":BRAND_NAME,"version":"1.0","active_tenders":active,"unresolved_errors":errors,"scraper_running":SCRAPE_STATS.get("running",False),"sources":len(SCRAPER_SOURCES),"wa_configured":bool(WA_TOKEN and WA_PHONE_ID)})

@app.get("/metrics")
async def metrics_ep(pwd:str=""):
    if pwd!=ADMIN_PASS: raise HTTPException(403)
    return JSONResponse({"counters":dict(METRICS),"scraper":SCRAPE_STATS})

@app.get("/sitemap.xml")
async def sitemap():
    from fastapi.responses import Response
    db=get_db()
    try: tids=[r[0] for r in db.execute("SELECT id FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 1000").fetchall()]
    finally: db.close()
    urls=[
        f"<url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{SITE_URL}/tenders</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>",
        f"<url><loc>{SITE_URL}/pricing</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>",
        f"<url><loc>{SITE_URL}/contact</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>",
        f"<url><loc>{SITE_URL}/privacy</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>",
    ]
    for tid in tids: urls.append(f"<url><loc>{SITE_URL}/tender/{tid}</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>")
    xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+"\n".join(urls)+"\n</urlset>"
    return Response(content=xml,media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    from fastapi.responses import Response
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /dashboard\nDisallow: /api\nSitemap: {SITE_URL}/sitemap.xml",media_type="text/plain")


# â”€â”€ CONSENT (added) â”€â”€
@app.post("/api/consent")
async def api_consent(request: Request):
    c = get_contractor(request)
    if c:
        db = get_db()
        try: db.execute("UPDATE contractors SET cookie_consent=1 WHERE id=?", (c["id"],)); db.commit()
        finally: db.close()
    return JSONResponse({"ok": True})

