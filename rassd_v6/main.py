"""
╔══════════════════════════════════════════════════════════════════╗
║  RASSD — Plateforme Intelligence Marchés Publics Maroc           ║
║  Version 3.0 — Production Ready                                  ║
║  Architecture: FastAPI + SQLite WAL + FTS5                       ║
║  Sources: Marchés Publics · ONEE · OCP · RAM · ONCF + plus      ║
║  Agents: Scraper · Classifier · Notifier · Monitor · Scheduler   ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ── Stdlib ────────────────────────────────────────────────────────
import os, re, time, json, asyncio, hashlib, secrets, logging, hmac
import sqlite3, threading, traceback, random, csv, io, uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date
from functools import wraps
from pathlib import Path
from typing import Any, Optional

# ── Optional third-party ──────────────────────────────────────────
try:
    from bs4 import BeautifulSoup as BS
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from itsdangerous import URLSafeTimedSerializer
    HAS_ITS = True
except ImportError:
    HAS_ITS = False

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

# ── FastAPI ───────────────────────────────────────────────────────
from fastapi import FastAPI, Request, Form, HTTPException, Response, Query
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse,
    StreamingResponse, PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
BRAND         = "RASSD"
TAGLINE       = "Intelligence des Marchés Publics"
VERSION       = "3.0"
SITE_URL      = os.getenv("SITE_URL",           "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS    = os.getenv("ADMIN_PASS",          "rassd2026")
SECRET_KEY    = os.getenv("SECRET_KEY",          secrets.token_hex(32))
DB_PATH       = os.getenv("DB_PATH",             "data/rassd.db")
TG_BOT        = os.getenv("TELEGRAM_BOT",        "7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_TG      = os.getenv("ADMIN_CHAT_ID",       "6424992854")
BREVO_KEY     = os.getenv("BREVO_API_KEY",       "")
FROM_EMAIL    = os.getenv("FROM_EMAIL",          "noreply@rassd.ma")
FROM_NAME     = os.getenv("FROM_NAME",           "RASSD Alertes")
SCRAPE_HRS    = int(os.getenv("SCRAPE_INTERVAL_HOURS", "2"))
MIN_BDC_ID    = int(os.getenv("SCRAPE_MIN_ID",   "311500"))
MAX_SCAN_FWD  = int(os.getenv("SCRAPE_SCAN_FWD", "600"))
FREE_DAILY    = int(os.getenv("FREE_DAILY_ALERTS","10"))
DEMO_MODE     = os.getenv("DEMO_MODE", "0") == "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rassd")

# ═══════════════════════════════════════════════════════════════════
# SECURITY MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════
class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req: Request, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Frame-Options":           "DENY",
            "X-Content-Type-Options":    "nosniff",
            "Referrer-Policy":           "strict-origin-when-cross-origin",
            "Permissions-Policy":        "geolocation=()",
            "X-XSS-Protection":          "1; mode=block",
            "X-Powered-By":              "RASSD",
        })
        return resp

# ═══════════════════════════════════════════════════════════════════
# RATE LIMITER — token bucket per IP
# ═══════════════════════════════════════════════════════════════════
_rl_store: dict[str, list[float]] = {}
_rl_lock  = threading.Lock()

def _rate_limit(ip: str, key: str, max_calls: int, window: int) -> bool:
    k   = f"{ip}:{key}"
    now = time.time()
    with _rl_lock:
        bucket = [t for t in _rl_store.get(k, []) if now - t < window]
        if len(bucket) >= max_calls:
            return False
        bucket.append(now)
        _rl_store[k] = bucket
    return True

def get_ip(req: Request) -> str:
    fwd = req.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() or (
        req.client.host if req.client else "127.0.0.1"
    )

def rate_guard(req: Request, key: str, max_calls: int = 10, window: int = 60):
    if not _rate_limit(get_ip(req), key, max_calls, window):
        raise HTTPException(429, "Trop de requêtes. Réessayez dans quelques instants.")

# ═══════════════════════════════════════════════════════════════════
# SESSION — HMAC signed cookie
# ═══════════════════════════════════════════════════════════════════
_SESS_COOKIE = "rssd_s"
_ADM_COOKIE  = "rssd_a"
_SESS_TTL    = 86400 * 30   # 30 jours

def _mac(data: str) -> str:
    return hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()

def session_create(resp: Response, uid: int):
    if HAS_ITS:
        ser   = URLSafeTimedSerializer(SECRET_KEY, salt="rassd-session-v3")
        token = ser.dumps({"id": uid, "v": 3})
    else:
        payload = f"{uid}:3"
        token   = f"{payload}.{_mac(payload)}"
    resp.set_cookie(
        _SESS_COOKIE, token,
        max_age  = _SESS_TTL,
        httponly = True,
        samesite = "lax",
        secure   = SITE_URL.startswith("https"),
    )

def session_get(req: Request) -> Optional[int]:
    raw = req.cookies.get(_SESS_COOKIE)
    if not raw:
        return None
    if HAS_ITS:
        try:
            ser = URLSafeTimedSerializer(SECRET_KEY, salt="rassd-session-v3")
            d   = ser.loads(raw, max_age=_SESS_TTL)
            return int(d["id"])
        except Exception:
            return None
    try:
        payload, sig = raw.rsplit(".", 1)
        if hmac.compare_digest(_mac(payload), sig):
            return int(payload.split(":")[0])
    except Exception:
        pass
    return None

def session_destroy(resp: Response):
    resp.delete_cookie(_SESS_COOKIE)

def _adm_token() -> str:
    return hmac.new(SECRET_KEY.encode(), b"rassd-admin-v3-2026", hashlib.sha256).hexdigest()

def admin_ok(req: Request) -> bool:
    return hmac.compare_digest(req.cookies.get(_ADM_COOKIE, ""), _adm_token())

def admin_guard(req: Request):
    if not admin_ok(req):
        raise HTTPException(302, headers={"Location": "/admin/login"})

# ═══════════════════════════════════════════════════════════════════
# CRYPTO
# ═══════════════════════════════════════════════════════════════════
def pw_hash(pwd: str) -> str:
    salt = (SECRET_KEY[:16] + "rassd").encode()
    return hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, 310_000).hex()

def pw_verify(pwd: str, hashed: str) -> bool:
    return hmac.compare_digest(pw_hash(pwd), hashed)

def gen_token() -> str:
    return secrets.token_urlsafe(32)

# ═══════════════════════════════════════════════════════════════════
# DATABASE — SQLite WAL + FTS5
# ═══════════════════════════════════════════════════════════════════
_db_lock = threading.Lock()

def db() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA synchronous  = NORMAL")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA cache_size   = 20000")
    c.execute("PRAGMA temp_store   = MEMORY")
    return c

SCHEMA = """
-- ─── Appels d'offres ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenders (
    id               TEXT PRIMARY KEY,
    objet            TEXT NOT NULL DEFAULT '',
    acheteur         TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    domaine          TEXT DEFAULT '',
    domaine_code     TEXT DEFAULT '',
    type_marche      TEXT DEFAULT '',
    date_publication TEXT DEFAULT '',
    date_limite      TEXT DEFAULT '',
    days_left        INTEGER DEFAULT NULL,
    urgence          INTEGER DEFAULT 0,
    statut           TEXT DEFAULT 'actif'
                          CHECK(statut IN ('actif','expire','annule','brouillon')),
    source           TEXT DEFAULT 'marchespublics',
    source_type      TEXT DEFAULT 'public'
                          CHECK(source_type IN ('public','semi-public','parastatal','prive','journal')),
    url              TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    montant_estime   TEXT DEFAULT '',
    date_extraction  TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_domaine  ON tenders(domaine_code);
CREATE INDEX IF NOT EXISTS idx_t_region   ON tenders(region);
CREATE INDEX IF NOT EXISTS idx_t_date     ON tenders(date_extraction DESC);
CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_t_urgence  ON tenders(urgence);
CREATE INDEX IF NOT EXISTS idx_t_source   ON tenders(source_type);
CREATE INDEX IF NOT EXISTS idx_t_created  ON tenders(created_at DESC);

-- FTS5 full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS tenders_fts USING fts5(
    id UNINDEXED,
    objet, acheteur, description,
    content='tenders',
    content_rowid='rowid'
);

-- ─── Membres ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT UNIQUE NOT NULL DEFAULT '',
    nom             TEXT NOT NULL DEFAULT '',
    email           TEXT UNIQUE NOT NULL,
    phone           TEXT DEFAULT '',
    telegram        TEXT DEFAULT '',
    secteurs        TEXT DEFAULT '',
    regions_pref    TEXT DEFAULT '',
    types_pref      TEXT DEFAULT '',
    pw_hash         TEXT NOT NULL DEFAULT '',
    plan            TEXT DEFAULT 'free'
                         CHECK(plan IN ('free','pro','enterprise')),
    actif           INTEGER DEFAULT 1,
    verified        INTEGER DEFAULT 0,
    notif_tg        INTEGER DEFAULT 1,
    notif_email     INTEGER DEFAULT 1,
    notif_urgence   INTEGER DEFAULT 1,
    api_token       TEXT UNIQUE DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    last_login      TEXT DEFAULT '',
    alert_count     INTEGER DEFAULT 0,
    daily_sent      INTEGER DEFAULT 0,
    daily_reset     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_m_email ON members(email);
CREATE INDEX IF NOT EXISTS idx_m_uid   ON members(uid);
CREATE INDEX IF NOT EXISTS idx_m_token ON members(api_token);

-- ─── Bookmarks ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bookmarks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    tender_id TEXT NOT NULL,
    note      TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(member_id, tender_id)
);

-- ─── Alertes envoyées ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts_sent (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    tender_id TEXT NOT NULL,
    channel   TEXT NOT NULL CHECK(channel IN ('telegram','email','webhook')),
    sent_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(member_id, tender_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_as_member ON alerts_sent(member_id);
CREATE INDEX IF NOT EXISTS idx_as_date   ON alerts_sent(sent_at DESC);

-- ─── Webhooks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhooks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    url       TEXT NOT NULL,
    secret    TEXT NOT NULL DEFAULT '',
    actif     INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ─── Scrape runs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT DEFAULT 'marchespublics',
    found       INTEGER DEFAULT 0,
    saved       INTEGER DEFAULT 0,
    expired_cnt INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    duration_s  REAL DEFAULT 0,
    started_at  TEXT DEFAULT '',
    finished_at TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ─── Erreurs agent ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    context    TEXT DEFAULT '',
    error      TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
"""

def db_init():
    conn = db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    log.info("✅ Database initialized")

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

# ═══════════════════════════════════════════════════════════════════
# CLASSIFICATION ENGINE — 47 secteurs · 12 régions
# ═══════════════════════════════════════════════════════════════════

REGIONS: dict[str, list[str]] = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","sale","kénitra","kenitra","témara","khémisset","skhirat"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane","bouskoura","médiouna"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia","chichaoua","rehamna"],
    "Fès-Meknès":                ["fès","fes","meknès","meknes","ifrane","taza","sefrou","boulemane","moulay yaacoub"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","tetouan","al hoceima","hoceima","chefchaouen","larache","fnideq","mdiq","fahs"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","jerada","driouch","figuig","guercif"],
    "Béni Mellal-Khénifra":     ["béni mellal","beni mellal","khénifra","khenifra","azilal","khouribga","fquih ben salah"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane","aït melloul","biougra","chtouka","tata"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt","tinghir","boumalne","goulmima"],
    "Laâyoune-Sakia El Hamra":  ["laayoune","laâyoune","boujdour","tarfaya","smara"],
    "Dakhla-Oued Ed-Dahab":     ["dakhla","aousserd"],
    "Guelmim-Oued Noun":         ["guelmim","tan-tan","sidi ifni","assa","zag","bouizakarne"],
}

SECTORS: dict[str, dict] = {
    # ─── TRAVAUX (T) ──────────────────────────────────────────────
    "T101": {
        "label": "Constructions & Bâtiments",
        "keywords": ["bâtiment","construction","maçonnerie","béton","gros œuvre","gros oeuvre",
                     "réhabilitation","rénovation bâtiment","façade","toiture","ravalement",
                     "mur de clôture","démolition","fondations","structure","immeuble"],
        "type": "T",
    },
    "T102": {
        "label": "Terrassements & VRD",
        "keywords": ["terrassement","remblai","déblai","excavation","nivellement","compactage",
                     "vrd","voirie réseaux divers","assise"],
        "type": "T",
    },
    "T103": {
        "label": "Menuiserie & Métallerie",
        "keywords": ["menuiserie","métallerie","charpente","ferronnerie","portail","portes","fenêtres",
                     "serrurerie","aluminium","stores","persiennes","vérandas"],
        "type": "T",
    },
    "T104": {
        "label": "Plomberie & CVC",
        "keywords": ["plomberie","chauffage","climatisation","sanitaire","tuyauterie","cvc",
                     "hvac","ventilation","pompe de chaleur","chaudière","géothermie"],
        "type": "T",
    },
    "T105": {
        "label": "Peinture & Revêtements",
        "keywords": ["peinture","vitrerie","enduit","revêtement mural","carrelage","parquet",
                     "faïence","dallage","sol","ragréage","papier peint"],
        "type": "T",
    },
    "T106": {
        "label": "Étanchéité & Isolation",
        "keywords": ["étanchéité","isolation","membrane","imperméabilisation","toiture terrasse",
                     "bardage","isolation thermique","isolation phonique"],
        "type": "T",
    },
    "T110": {
        "label": "Génie Civil & Infrastructure",
        "keywords": ["génie civil","pont","viaduc","infrastructure","ouvrage d'art","géotechnique",
                     "sondage","tunnel","barrage","digue","mur de soutènement"],
        "type": "T",
    },
    "T111": {
        "label": "Espaces Verts & Paysage",
        "keywords": ["espace vert","jardinage","plantation","gazon","élagage","parc","jardin",
                     "arboriculture","pelouse","ornementaux","aménagement paysager"],
        "type": "T",
    },
    "T201": {
        "label": "Assainissement & Eaux Usées",
        "keywords": ["assainissement","égout","step","station d'épuration","collecteur",
                     "canalisation","réseau assainissement","lagunage","boues","bassin"],
        "type": "T",
    },
    "T203": {
        "label": "Hydraulique & Eau Potable",
        "keywords": ["hydraulique","eau potable","adduction","forage","irrigation","réseau d'eau",
                     "château d'eau","réservoir","pompage","canalisation eau","aep"],
        "type": "T",
    },
    "T301": {
        "label": "Travaux Routiers",
        "keywords": ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation routière",
                     "marquage","enrobé","couche de roulement","autoroute","déviation"],
        "type": "T",
    },
    "T401": {
        "label": "Électricité & Éclairage",
        "keywords": ["électricité","éclairage","câblage","tableau électrique","transformateur",
                     "éclairage public","basse tension","haute tension","groupe électrogène",
                     "borne de recharge","installation électrique"],
        "type": "T",
    },
    "T402": {
        "label": "Sécurité Électronique & Vidéosurveillance",
        "keywords": ["vidéosurveillance","cctv","alarme incendie","contrôle d'accès","intrusion",
                     "détection","sécurité électronique","sssi","ssai","système anti-intrusion"],
        "type": "T",
    },
    "T403": {
        "label": "Télécommunications & Réseaux",
        "keywords": ["télécommunication","fibre optique","réseau","switch","wifi","lan","wan",
                     "infrastructure réseau","câblage réseau","dépôt","nœud","backbone"],
        "type": "T",
    },
    "T501": {
        "label": "Réhabilitation & Restauration Patrimoine",
        "keywords": ["restauration","réhabilitation patrimoine","médina","monument","site historique",
                     "sauvegarde","mise en valeur","patrimoine","ancienne médina"],
        "type": "T",
    },
    # ─── PRODUITS / FOURNITURES (P) ───────────────────────────────
    "P813": {
        "label": "Équipements Médicaux & Pharmaceutiques",
        "keywords": ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique",
                     "médicament","scanner","irm","bloc opératoire","stérilisation","endoscopie"],
        "type": "P",
    },
    "P814": {
        "label": "Équipements Froid & Climatisation",
        "keywords": ["climatiseur","split","froid industriel","chambre froide","groupe froid",
                     "réfrigération","congélateur","armoire réfrigérée"],
        "type": "P",
    },
    "P815": {
        "label": "Matériel Électrique & Électronique",
        "keywords": ["onduleur","ups","batterie","générateur","armoire électrique","disjoncteur",
                     "câbles électriques","luminaires","led","éclairage led"],
        "type": "P",
    },
    "P816": {
        "label": "Véhicules & Matériel Roulant",
        "keywords": ["véhicule","voiture","camion","bus","minibus","ambulance","carburant",
                     "gasoil","flotte","engin","tracteur","poids lourd"],
        "type": "P",
    },
    "P818": {
        "label": "Informatique & Matériel Numérique",
        "keywords": ["informatique","ordinateur","pc","serveur","imprimante","scanner","copieur",
                     "logiciel","cloud","erp","datacenter","tablette","écran","laptop"],
        "type": "P",
    },
    "P825": {
        "label": "Mobilier & Fournitures de Bureau",
        "keywords": ["fournitures bureau","papier","ramette","mobilier","bureau","chaise","armoire",
                     "tableau blanc","cartouche","classeur","reliure","consommables"],
        "type": "P",
    },
    "P830": {
        "label": "Équipements Sportifs & Culturels",
        "keywords": ["équipement sportif","terrain de sport","gymnase","salle de sport",
                     "équipement culturel","musée","bibliothèque","livre","publication"],
        "type": "P",
    },
    "P833": {
        "label": "Produits Pharmaceutiques & Parapharmaceutiques",
        "keywords": ["médicament","pharmacie","produits chimiques","réactif laboratoire",
                     "consommable médical","dispositif médical","seringue","gants"],
        "type": "P",
    },
    "P834": {
        "label": "Alimentation & Denrées",
        "keywords": ["alimentation","denrée","viande","restauration fournitures","repas",
                     "cafétéria","cantine","épicerie","boissons","lait","huile","farine"],
        "type": "P",
    },
    "P839": {
        "label": "Matériaux de Construction",
        "keywords": ["ciment","sable","gravier","béton prêt","brique","acier","fer à béton",
                     "matériaux construction","bois","tuile","ardoise","marbre"],
        "type": "P",
    },
    "P840": {
        "label": "Outillage & Équipements Industriels",
        "keywords": ["outillage","outil","machine","pièce de rechange","pompe industrielle",
                     "compresseur","perceuse","engin travaux","nacelle","chariot élévateur"],
        "type": "P",
    },
    "P841": {
        "label": "Hygiène & Produits d'Entretien",
        "keywords": ["nettoyage produits","produits d'entretien","désinfection","savon",
                     "détergent","consommable hygiène","masque","gel hydroalcoolique"],
        "type": "P",
    },
    "P850": {
        "label": "Énergies Renouvelables & Équipements Verts",
        "keywords": ["solaire","photovoltaïque","énergie renouvelable","panneau solaire",
                     "éolien","biomasse","chauffe-eau solaire","pompe solaire","batterie solaire"],
        "type": "P",
    },
    "P860": {
        "label": "Équipements Didactiques & Pédagogiques",
        "keywords": ["équipement pédagogique","scolaire","didactique","tableau interactif",
                     "matériel scolaire","banc d'école","fourniture scolaire","université"],
        "type": "P",
    },
    # ─── SERVICES (S) ─────────────────────────────────────────────
    "S901": {
        "label": "IT, Développement & Cloud",
        "keywords": ["développement logiciel","application mobile","site web","cybersécurité",
                     "infogérance","maintenance informatique","cloud computing","saas","paas",
                     "développement web","erp implémentation","migration cloud","devops"],
        "type": "S",
    },
    "S902": {
        "label": "Études, Ingénierie & Conseil",
        "keywords": ["étude","ingénierie","conseil","consultant","expertise","audit technique",
                     "bureau d'études","maîtrise d'œuvre","assistance technique","amc","ami"],
        "type": "S",
    },
    "S903": {
        "label": "Audit, Expertise Comptable & Juridique",
        "keywords": ["audit financier","expertise comptable","commissaire aux comptes","juridique",
                     "notaire","avocat","due diligence","certification iso","conformité"],
        "type": "S",
    },
    "S906": {
        "label": "Maintenance & Entretien",
        "keywords": ["maintenance","entretien","réparation","dépannage","préventive","corrective",
                     "contrat maintenance","mco","mcsi","garantie maintien opérationnel"],
        "type": "S",
    },
    "S907": {
        "label": "Nettoyage & Propreté",
        "keywords": ["nettoyage","propreté","nettoyage industriel","nettoyage bâtiment",
                     "dératisation","désinsectisation","hygiène locaux","décontamination"],
        "type": "S",
    },
    "S908": {
        "label": "Gardiennage & Sécurité",
        "keywords": ["gardiennage","agent de sécurité","surveillance","sécurité humaine",
                     "rondier","rondes","faction","accueil sécurité","télésurveillance"],
        "type": "S",
    },
    "S909": {
        "label": "Assurance & Mutuelles",
        "keywords": ["assurance","mutuelle","garantie décennale","responsabilité civile",
                     "couverture médicale","prévoyance","contrat assurance"],
        "type": "S",
    },
    "S910": {
        "label": "Communication, Marketing & Événements",
        "keywords": ["communication","publicité","événementiel","impression","sérigraphie",
                     "signalétique","organisation manifestation","salon","exposition",
                     "branding","identité visuelle","médias"],
        "type": "S",
    },
    "S911": {
        "label": "Études & Sondages",
        "keywords": ["étude de marché","sondage","enquête","statistiques","collecte données",
                     "focus group","panel","recherche","analyse"],
        "type": "S",
    },
    "S912": {
        "label": "Restauration & Hôtellerie",
        "keywords": ["hôtel","hébergement","restauration service","traiteur","réception",
                     "accueil","séminaire hôtel","gestion cafétéria","catering"],
        "type": "S",
    },
    "S913": {
        "label": "Formation, Coaching & Certification",
        "keywords": ["formation","coaching","séminaire formation","certification",
                     "e-learning","programme de formation","ingénierie pédagogique",
                     "recyclage","perfectionne","renforcement capacités"],
        "type": "S",
    },
    "S914": {
        "label": "Recrutement & Ressources Humaines",
        "keywords": ["recrutement","placement","intérim","ressources humaines","externalisation rh",
                     "bilan compétences","chasseur têtes","cabinet recrutement"],
        "type": "S",
    },
    "S915": {
        "label": "Transport, Location & Logistique",
        "keywords": ["transport","location véhicule","navette","chauffeur","déménagement",
                     "logistique","affrètement","fret","messagerie","coursier","location cars"],
        "type": "S",
    },
    "S916": {
        "label": "Impression & Reprographie",
        "keywords": ["impression","imprimerie","reprographie","édition","livret","flyer",
                     "brochure","catalogue","affiche","rapport annuel","imprimé"],
        "type": "S",
    },
    "S917": {
        "label": "Environnement & Développement Durable",
        "keywords": ["environnement","déchets","tri sélectif","recyclage","développement durable",
                     "étude d'impact environnement","eie","évaluation environnementale",
                     "biodiversité","empreinte carbone","bilan carbone"],
        "type": "S",
    },
}

# Flat lookup helpers
SECTORS_LIST      = list(SECTORS.keys())
SECTORS_BY_TYPE   = {
    "T": {k: v for k, v in SECTORS.items() if v["type"] == "T"},
    "P": {k: v for k, v in SECTORS.items() if v["type"] == "P"},
    "S": {k: v for k, v in SECTORS.items() if v["type"] == "S"},
}
REGIONS_LIST      = list(REGIONS.keys())
MARKET_TYPES      = ["Travaux", "Fournitures", "Services", "Études & Ingénierie", "Autre"]
SOURCE_TYPES      = ["public", "semi-public", "parastatal", "prive", "journal"]

PORTAL_JUNK = {
    "accueil", "liste des avis", "connexion", "portail marocain",
    "marchés publics maroc", "espace entreprise", "se connecter",
    "liste des", "avis d'achat", "tableau de bord", "recherche",
    "inscription", "bienvenue", "login", "home", "dashboard",
    "portail", "marchés publics", "appels d'offres","résultats",
}

AO_KEYWORDS = [
    "fourniture","travaux","prestation","acquisition","maintenance",
    "réhabilitation","construction","étude","mission","location",
    "nettoyage","gardiennage","transport","formation","audit",
    "aménagement","installation","extension","livraison","réparation",
    "entretien","rénovation","pose","démolition","achat","service",
    "marché","appel d'offres","consultation","lot n°","lot n",
]

def is_junk(text: str) -> bool:
    tl = text.lower().strip()
    if len(tl) < 8:
        return True
    return any(tl == j or tl.startswith(j) for j in PORTAL_JUNK)

def classify_region(text: str) -> str:
    t = text.lower()
    for region, kws in REGIONS.items():
        if any(k in t for k in kws):
            return region
    return "Maroc"

def classify_sector(text: str) -> tuple[str, str]:
    """Return (code, label) — weighted scoring"""
    t      = text.lower()
    scores: dict[str, int] = defaultdict(int)
    for code, info in SECTORS.items():
        for kw in info["keywords"]:
            if kw in t:
                scores[code] += 3 if len(kw) > 12 else (2 if len(kw) > 7 else 1)
    if not scores:
        return "P825", SECTORS["P825"]["label"]
    best = max(scores, key=scores.get)
    return best, SECTORS[best]["label"]

def classify_market_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","rénovation","terrassement",
                              "pose","démolition","voirie","aménagement","chaussée","bitume"]):
        return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel",
                              "équipement","produits","articles","articles"]):
        return "Fournitures"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie","maîtrise"]):
        return "Études & Ingénierie"
    if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage",
                              "nettoyage","transport","formation","restauration"]):
        return "Services"
    return "Autre"

def clean_objet(text: str) -> str:
    t = re.sub(r"^#\s*0*\d+\s*",              "", text.strip())
    t = re.sub(r"^LOT\s*[N°n°#]?\s*\d+\s*[:\-–]?\s*", "", t, flags=re.I)
    t = re.sub(r"^\d+\s*[:\-–]\s*",           "", t)
    t = re.sub(r"\s+",                         " ", t).strip()
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t

def parse_date(raw: str) -> str:
    if not raw:
        return ""
    for pat, fmt in [
        (r"(\d{1,2}/\d{2}/\d{4})", "%d/%m/%Y"),
        (r"(\d{4}-\d{2}-\d{2})",   "%Y-%m-%d"),
        (r"(\d{1,2}-\d{2}-\d{4})", "%d-%m-%Y"),
    ]:
        m = re.search(pat, str(raw))
        if m:
            return m.group(1)
    return ""

def days_until(raw: str) -> Optional[int]:
    if not raw:
        return None
    dt = None
    for pat, fmt in [
        (r"(\d{1,2}/\d{2}/\d{4})", "%d/%m/%Y"),
        (r"(\d{4}-\d{2}-\d{2})",   "%Y-%m-%d"),
        (r"(\d{1,2}-\d{2}-\d{4})", "%d-%m-%Y"),
    ]:
        m = re.search(pat, str(raw))
        if m:
            try:
                dt = datetime.strptime(m.group(1), fmt).date()
                break
            except ValueError:
                pass
    if dt is None:
        return None
    return (dt - date.today()).days

def is_expired(raw: str) -> bool:
    d = days_until(raw)
    return d is not None and d < 0

# ═══════════════════════════════════════════════════════════════════
# HTML PARSER — marchespublics.gov.ma card layout
# ═══════════════════════════════════════════════════════════════════
_LABEL_RE = re.compile(
    r"label|titre|key|head|caption|field|info.label|card.label|field.label", re.I
)

def _card_val(soup: Any, keywords: list[str]) -> str:
    """Extract card field value — 3-level strategy."""
    kw_low    = [k.lower() for k in keywords]
    full_text = soup.get_text(" ", strip=True)

    # Level 1: class ~label → next sibling
    for el in soup.find_all(True, class_=_LABEL_RE):
        txt = el.get_text(strip=True)
        if not any(k in txt.lower() for k in kw_low):
            continue
        nxt = el.find_next_sibling()
        if nxt:
            v = nxt.get_text(strip=True)
            if 2 < len(v) < 300:
                return v
        if el.parent:
            ps = el.parent.find_next_sibling()
            if ps:
                v = ps.get_text(strip=True)
                if 2 < len(v) < 300:
                    return v

    # Level 2: short element containing keyword
    for el in soup.find_all(True):
        txt = el.get_text(strip=True)
        if len(txt) > 120 or len(txt) < 4:
            continue
        if not any(k in txt.lower() for k in kw_low):
            continue
        nxt = el.find_next_sibling()
        if nxt:
            v = nxt.get_text(strip=True)
            if 2 < len(v) < 300:
                return v

    # Level 3: regex in full text
    for kw in kw_low:
        idx = full_text.lower().find(kw)
        if idx >= 0:
            after = full_text[idx + len(kw): idx + len(kw) + 250].strip()
            lines = [ln.strip() for ln in after.split("\n") if ln.strip()]
            if lines:
                return lines[0][:250]

    return ""


def parse_marchespublics(html: str, tid: str) -> Optional[dict]:
    """Parse a marchespublics.gov.ma consultation page."""
    if not HAS_BS4:
        return None
    try:
        soup      = BS(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # Early rejection: annulé
        if any(k in full_text.lower() for k in [
            "marché annulé","consultation annulée","a été annulée",
            "appel d'offres annulé","marché infructueux",
        ]):
            return None

        # ── Objet ─────────────────────────────────────────────────
        objet = ""

        # a) <title> tag
        title_el = soup.find("title")
        if title_el:
            t = title_el.get_text(strip=True)
            t = re.sub(r"\s*[|–\-]\s*.*marchés publics.*", "", t, flags=re.I).strip()
            t = re.sub(r"\s*[|–\-]\s*.*portail.*",         "", t, flags=re.I).strip()
            if 10 < len(t) < 400 and not is_junk(t):
                objet = t

        # b) CSS selectors
        if not objet:
            for sel in [".consultation-title",".objet-marche",".title-consultation",
                        ".card-title",".page-title","h1","h2","h3"]:
                for el in soup.select(sel):
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600 and not is_junk(t):
                        objet = t
                        break
                if objet:
                    break

        # c) card_val
        if not objet:
            objet = _card_val(soup, [
                "objet du marché","objet de la consultation",
                "intitulé du marché","intitulé","objet",
            ])

        # d) Nature de prestation
        if not objet or len(objet) < 8:
            nat = _card_val(soup, ["nature de prestation","nature"])
            cat = _card_val(soup, ["catégorie principale","catégorie"])
            if nat and len(nat) > 8:
                objet = nat
            elif cat and len(cat) > 4:
                objet = f"Prestation — {cat}"

        # e) First paragraph with AO keyword
        if not objet or len(objet) < 8:
            _junk_els = {"nav","footer","header","aside","script","style"}
            for el in soup.find_all(["p","div","span","li","td"]):
                t  = el.get_text(strip=True)
                tl = t.lower()
                if 15 < len(t) < 400 and not is_junk(t):
                    parents = {p.name for p in el.parents}
                    if parents & _junk_els:
                        continue
                    if any(k in tl for k in AO_KEYWORDS):
                        objet = t
                        break

        if not objet or len(objet) < 8:
            return None
        objet = clean_objet(objet)

        # ── Date limite ───────────────────────────────────────────
        dl_raw = _card_val(soup, [
            "date limite de réception des devis",
            "date limite de réception des offres",
            "date limite","date de remise des offres",
            "remise des offres","remise des plis",
            "date de clôture","réception des devis","délai de remise",
        ])
        if not dl_raw:
            m2 = re.search(
                r"(?:date limite|réception des (?:offres|devis)|"
                r"remise des (?:offres|plis)|clôture)"
                r".{0,100}?(\d{1,2}/\d{2}/\d{4})",
                full_text, re.I | re.S,
            )
            if m2:
                dl_raw = m2.group(1)

        date_lim = parse_date(dl_raw)

        if date_lim and is_expired(date_lim):
            return None

        # ── Other fields ──────────────────────────────────────────
        acheteur    = _card_val(soup, ["acheteur public","maître d'ouvrage",
                                       "organisme acheteur","pouvoir adjudicateur","organisme"])
        cat_off     = _card_val(soup, ["catégorie principale","catégorie"])
        nature      = _card_val(soup, ["nature de prestation","nature"])
        lieu        = _card_val(soup, ["lieu d'exécution","lieu d execution","lieu de livraison"])
        dp_raw      = _card_val(soup, ["date mise en ligne","date de publication","date de parution"])
        date_pub    = parse_date(dp_raw)
        montant_raw = _card_val(soup, ["montant estimé","montant","budget estimatif"])

        # ── Classification ────────────────────────────────────────
        corpus = f"{cat_off} {nature} {objet} {acheteur}"
        code, dom_label = classify_sector(corpus)

        cat_l = cat_off.lower()
        if   "travaux"      in cat_l: type_m = "Travaux"
        elif "fournitures"  in cat_l: type_m = "Fournitures"
        elif "services"     in cat_l: type_m = "Services"
        elif "études"       in cat_l: type_m = "Études & Ingénierie"
        else:                         type_m = classify_market_type(f"{objet} {nature}")

        region = classify_region(f"{lieu} {acheteur} {full_text[:500]}")
        deft   = days_until(date_lim)
        urgence = 1 if (deft is not None and 0 <= deft <= 7) else 0

        return {
            "id":               f"bdc_{tid}",
            "objet":            objet[:400],
            "acheteur":         acheteur[:200],
            "region":           region,
            "domaine":          f"{code} · {dom_label}",
            "domaine_code":     code,
            "type_marche":      type_m,
            "date_publication": date_pub,
            "date_limite":      date_lim,
            "days_left":        deft,
            "urgence":          urgence,
            "statut":           "actif",
            "source":           "marchespublics",
            "source_type":      "public",
            "url":              f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
            "montant_estime":   montant_raw[:100] if montant_raw else "",
        }
    except Exception as exc:
        log.warning(f"[parse bdc_{tid}] {exc}")
        return None

# ═══════════════════════════════════════════════════════════════════
# ONEE PARSER — onee.ma appels d'offres
# ═══════════════════════════════════════════════════════════════════
def scrape_onee_page(html: str, base_url: str) -> list[dict]:
    """Parse ONEE appels d'offres listing."""
    if not HAS_BS4:
        return []
    results = []
    try:
        soup = BS(html, "html.parser")
        # ONEE typically uses a table or list layout
        rows = soup.select("table.views-table tbody tr") or soup.select(".view-content .views-row")
        for row in rows[:30]:
            txt = row.get_text(" ", strip=True)
            if len(txt) < 20:
                continue
            # Extract title
            title_el = row.select_one("a, h3, h2, .field-content")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if len(title) < 10 or is_junk(title):
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.onee.ma" + href
            # Extract date
            dl = ""
            date_el = row.select_one(".field--name-field-date-limite, .date-limite, .field-date")
            if date_el:
                dl = parse_date(date_el.get_text(strip=True))
            if dl and is_expired(dl):
                continue
            code, dom_label = classify_sector(title)
            deft   = days_until(dl)
            results.append({
                "id":           f"onee_{abs(hash(href + title)) % 999999:06d}",
                "objet":        clean_objet(title)[:400],
                "acheteur":     "ONEE — Office National de l'Électricité et de l'Eau Potable",
                "region":       "Maroc",
                "domaine":      f"{code} · {dom_label}",
                "domaine_code": code,
                "type_marche":  classify_market_type(title),
                "date_limite":  dl,
                "days_left":    deft,
                "urgence":      1 if (deft is not None and 0 <= deft <= 7) else 0,
                "statut":       "actif",
                "source":       "onee",
                "source_type":  "parastatal",
                "url":          href or "https://www.onee.ma/fr/appels-offres",
                "montant_estime": "",
            })
    except Exception as exc:
        log.warning(f"[onee] {exc}")
    return results

# ═══════════════════════════════════════════════════════════════════
# SAVE TENDER — idempotent upsert + FTS sync
# ═══════════════════════════════════════════════════════════════════
def tender_save(t: dict) -> bool:
    if not t or not t.get("id") or not t.get("objet"):
        return False
    try:
        conn = db()
        cur  = conn.execute(
            """INSERT OR IGNORE INTO tenders
               (id, objet, acheteur, region, domaine, domaine_code,
                type_marche, date_publication, date_limite, days_left,
                urgence, statut, source, source_type, url,
                description, montant_estime, date_extraction)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(t["id"])[:80],
                str(t.get("objet",""))[:400],
                str(t.get("acheteur",""))[:200],
                str(t.get("region",""))[:100],
                str(t.get("domaine",""))[:100],
                str(t.get("domaine_code",""))[:10],
                str(t.get("type_marche",""))[:50],
                str(t.get("date_publication",""))[:20],
                str(t.get("date_limite",""))[:20],
                t.get("days_left"),
                int(t.get("urgence", 0)),
                "actif",
                str(t.get("source","marchespublics"))[:40],
                str(t.get("source_type","public"))[:20],
                str(t.get("url",""))[:400],
                str(t.get("description",""))[:2000],
                str(t.get("montant_estime",""))[:100],
                now_str(),
            ),
        )
        changed = cur.rowcount
        if changed:
            # Sync FTS
            row = conn.execute(
                "SELECT rowid FROM tenders WHERE id=?", (str(t["id"])[:80],)
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT INTO tenders_fts(rowid, id, objet, acheteur, description) VALUES (?,?,?,?,?)",
                    (row["rowid"], str(t["id"])[:80],
                     str(t.get("objet",""))[:400],
                     str(t.get("acheteur",""))[:200],
                     str(t.get("description",""))[:2000]),
                )
        conn.commit()
        conn.close()
        return changed > 0
    except Exception as exc:
        log.error(f"[save {t.get('id')}] {exc}")
        try:
            conn.close()
        except Exception:
            pass
        return False

# ═══════════════════════════════════════════════════════════════════
# EXPIRE ENGINE
# ═══════════════════════════════════════════════════════════════════
def expire_tenders(conn: sqlite3.Connection) -> int:
    today = date.today()
    exp_ids: list[str] = []

    # ISO dates — SQLite handles directly
    conn.execute(
        "UPDATE tenders SET statut='expire' "
        "WHERE statut='actif' AND date_limite != '' "
        "AND date_limite NOT LIKE '%/%' "
        "AND date_limite < date('now') "
        "AND date_limite NOT IN ('N/A','—','-','null','')"
    )

    # DD/MM/YYYY dates — Python loop
    rows = conn.execute(
        "SELECT id, date_limite FROM tenders "
        "WHERE statut='actif' AND date_limite LIKE '%/%'"
    ).fetchall()
    for row in rows:
        raw = (row["date_limite"] or "").strip()
        m   = re.search(r"(\d{1,2}/\d{2}/\d{4})", raw)
        if m:
            try:
                if datetime.strptime(m.group(1), "%d/%m/%Y").date() < today:
                    exp_ids.append(row["id"])
            except ValueError:
                pass

    if exp_ids:
        ph = ",".join(["?"] * len(exp_ids))
        conn.execute(
            f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp_ids
        )

    conn.commit()
    return len(exp_ids)

# ═══════════════════════════════════════════════════════════════════
# SCRAPER LOG & STATE
# ═══════════════════════════════════════════════════════════════════
class SLog:
    _entries: list[str] = []
    _lock = threading.Lock()

    @classmethod
    def add(cls, msg: str):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        with cls._lock:
            cls._entries.append(entry)
            if len(cls._entries) > 800:
                cls._entries = cls._entries[-600:]
        log.info(msg)

    @classmethod
    def tail(cls, n: int = 120) -> list[str]:
        with cls._lock:
            return list(cls._entries[-n:])

class SS:
    running:    bool = False
    source:     str  = ""
    found:      int  = 0
    saved:      int  = 0
    errors:     int  = 0
    current:    int  = 0
    total:      int  = 0
    started_at: str  = ""

# ═══════════════════════════════════════════════════════════════════
# SCRAPER — marchespublics.gov.ma
# ═══════════════════════════════════════════════════════════════════
def run_scraper_marchespublics() -> list[dict]:
    import requests as _req

    t0         = time.time()
    SS.running = True
    SS.source  = "marchespublics"
    SS.found = SS.saved = SS.errors = SS.current = SS.total = 0
    SS.started_at = datetime.now().strftime("%H:%M:%S")

    SLog.add("═" * 60)
    SLog.add(f"ScraperAgent · marchespublics.gov.ma · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    SLog.add("═" * 60)

    # Load known IDs
    conn = db()
    known: set[str] = {r[0] for r in conn.execute("SELECT id FROM tenders").fetchall()}
    conn.close()

    max_known = MIN_BDC_ID
    for k in known:
        if k.startswith("bdc_"):
            try:
                n = int(k[4:])
                if n > max_known:
                    max_known = n
            except ValueError:
                pass

    start_id  = max(MIN_BDC_ID, max_known - 30)
    end_id    = max_known + MAX_SCAN_FWD
    scan_ids  = [str(i) for i in range(start_id, end_id + 1) if f"bdc_{i}" not in known]

    SS.total = len(scan_ids)
    SLog.add(f"Plage: bdc_{start_id} → bdc_{end_id} ({len(scan_ids)} IDs à vérifier)")

    session = _req.Session()
    session.verify = False
    session.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.5",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Connection":      "keep-alive",
    })

    new_tenders: list[dict] = []
    consec_empty = 0

    for idx, tid in enumerate(scan_ids):
        SS.current = idx + 1
        try:
            r = session.get(
                f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
                timeout=15,
            )
            if r.status_code != 200 or len(r.text) < 2500:
                consec_empty += 1
                if consec_empty > 60 and SS.saved == 0:
                    SLog.add(f"⚠ {consec_empty} pages invalides consécutives — arrêt")
                    break
                continue

            consec_empty = 0
            SS.found += 1

            tender = parse_marchespublics(r.text, tid)
            if not tender:
                known.add(f"bdc_{tid}")
                continue

            if tender_save(tender):
                SS.saved += 1
                known.add(tender["id"])
                dl   = tender.get("date_limite") or "?"
                dlft = tender.get("days_left")
                urg  = "🔴" if tender.get("urgence") else ""
                SLog.add(
                    f"✓ {urg}bdc_{tid:>6} │ {tender['domaine_code']:>4} │ "
                    f"{tender['objet'][:50]:50} │ ⏰{dl}"
                )
                new_tenders.append(tender)
            else:
                known.add(f"bdc_{tid}")

            time.sleep(random.uniform(0.4, 0.9))

        except Exception as exc:
            SS.errors += 1
            consec_empty += 1
            SLog.add(f"✗ bdc_{tid}: {str(exc)[:70]}")

    # Auto-expire + record run
    conn = db()
    try:
        expired_cnt = expire_tenders(conn)
        duration    = time.time() - t0
        conn.execute(
            "INSERT INTO scrape_runs "
            "(source, found, saved, expired_cnt, errors, duration_s, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("marchespublics", SS.found, SS.saved, expired_cnt,
             SS.errors, round(duration, 1), SS.started_at,
             datetime.now().strftime("%H:%M:%S")),
        )
        conn.commit()
    except Exception as exc:
        SLog.add(f"⚠ [expire/log] {exc}")
    finally:
        conn.close()

    dur = time.time() - t0
    SLog.add("═" * 60)
    SLog.add(
        f"Terminé en {dur:.0f}s │ {SS.saved} nouveaux │ "
        f"{SS.errors} erreurs"
    )
    SLog.add("═" * 60)
    SS.running = False
    return new_tenders

# ═══════════════════════════════════════════════════════════════════
# SCRAPER — ONEE
# ═══════════════════════════════════════════════════════════════════
def run_scraper_onee() -> list[dict]:
    import requests as _req

    SLog.add("─── Source: ONEE (onee.ma) ───")
    session = _req.Session()
    session.verify = False
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; RASSD-Bot/3.0)"

    new_tenders: list[dict] = []
    conn = db()
    known: set[str] = {r[0] for r in conn.execute(
        "SELECT id FROM tenders WHERE source='onee'"
    ).fetchall()}
    conn.close()

    urls = [
        "https://www.onee.ma/fr/appels-offres",
        "https://www.onee.ma/fr/appels-d-offres",
    ]
    for url in urls:
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            items = scrape_onee_page(r.text, url)
            for t in items:
                if t["id"] not in known and tender_save(t):
                    new_tenders.append(t)
                    known.add(t["id"])
                    SLog.add(f"✓ [ONEE] {t['objet'][:55]}")
            break
        except Exception as exc:
            SLog.add(f"✗ [ONEE] {exc}")

    SLog.add(f"[ONEE] {len(new_tenders)} nouveaux marchés")
    return new_tenders

# ═══════════════════════════════════════════════════════════════════
# ORCHESTRATOR — runs all scrapers
# ═══════════════════════════════════════════════════════════════════
def run_all_scrapers() -> list[dict]:
    if SS.running:
        return []
    SS.running = True

    all_new: list[dict] = []
    try:
        # Primary source
        new = run_scraper_marchespublics()
        all_new.extend(new)

        # Secondary sources
        try:
            onee = run_scraper_onee()
            all_new.extend(onee)
        except Exception as exc:
            SLog.add(f"⚠ [ONEE] {exc}")

    finally:
        SS.running = False

    return all_new

# ═══════════════════════════════════════════════════════════════════
# NOTIFICATION AGENT
# ═══════════════════════════════════════════════════════════════════
async def tg_send(chat_id: str, text: str) -> bool:
    if not TG_BOT or not chat_id:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
                json={
                    "chat_id":                  chat_id,
                    "text":                     text,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return r.status_code == 200
    except Exception as exc:
        log.warning(f"[TG] {exc}")
        return False


async def email_brevo(to: str, subject: str, html: str) -> bool:
    if not BREVO_KEY:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": BREVO_KEY, "content-type": "application/json"},
                json={
                    "sender":      {"name": FROM_NAME, "email": FROM_EMAIL},
                    "to":          [{"email": to}],
                    "subject":     subject,
                    "htmlContent": html,
                },
            )
            return r.status_code in (200, 201, 202)
    except Exception as exc:
        log.warning(f"[Email] {exc}")
        return False


async def webhook_send(url: str, secret: str, payload: dict) -> bool:
    try:
        import httpx
        body    = json.dumps(payload, ensure_ascii=False)
        sig     = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                url,
                content  = body.encode(),
                headers  = {
                    "Content-Type":          "application/json",
                    "X-RASSD-Signature":     f"sha256={sig}",
                    "X-RASSD-Version":       VERSION,
                },
            )
            return r.status_code < 300
    except Exception as exc:
        log.warning(f"[Webhook] {exc}")
        return False


def _match_member(m: dict, tenders: list[dict]) -> list[dict]:
    """Filter tenders based on member's preferences."""
    secteurs = [s.strip() for s in (m.get("secteurs") or "").split(",") if s.strip()]
    regions  = [r.strip() for r in (m.get("regions_pref") or "").split(",") if r.strip()]
    types_p  = [t.strip() for t in (m.get("types_pref") or "").split(",") if t.strip()]

    # No filters = receive all
    if not secteurs and not regions and not types_p:
        return tenders

    matched: list[dict] = []
    for t in tenders:
        dom   = (t.get("domaine_code") or "")
        obj   = (t.get("objet") or "").lower()
        reg   = (t.get("region") or "")
        typ   = (t.get("type_marche") or "")

        # Region filter
        if regions and not any(reg == r or r in reg for r in regions):
            continue

        # Type filter
        if types_p and typ not in types_p:
            continue

        # Sector filter
        if secteurs:
            match = False
            for s in secteurs:
                if s[:4] == dom[:4]:
                    match = True
                    break
                info = SECTORS.get(s)
                if info and any(kw in obj for kw in info["keywords"]):
                    match = True
                    break
            if not match:
                continue

        matched.append(t)
    return matched


def _tg_msg(tenders: list[dict], nom: str) -> str:
    n  = len(tenders)
    pl = "x" if n > 1 else ""
    lines = [
        f"🏛 <b>{BRAND}</b> — {n} nouveau{pl} marché{pl}",
        f"Bonjour <b>{nom}</b> 👋\n",
    ]
    for t in tenders[:5]:
        dl  = t.get("date_limite") or "?"
        urg = " 🔴" if t.get("urgence") else ""
        lines.append(
            f"▸ <b>{t['objet'][:80]}</b>{urg}\n"
            f"  🏷 {t.get('domaine','')[:30]} · {t.get('type_marche','')}\n"
            f"  🏢 {t.get('acheteur','')[:55]}\n"
            f"  📍 {t.get('region','Maroc')} · ⏰ {dl}\n"
            f"  🔗 <a href='{t.get('url','')}'>Voir la consultation</a>\n"
        )
    if n > 5:
        lines.append(f"<i>+ {n-5} autre(s) — <a href='{SITE_URL}/tenders'>Voir tout</a></i>")
    return "\n".join(lines)


def _email_html(tenders: list[dict], nom: str) -> str:
    cards = ""
    for t in tenders[:8]:
        dl  = t.get("date_limite") or "Non précisée"
        src = t.get("source_type","public")
        urg = " ⚡ URGENT" if t.get("urgence") else ""
        tc  = (t.get("domaine_code") or "P")[:1]
        clr = {"T": "#5B9CF6", "P": "#2DCDA0", "S": "#E9A420"}.get(tc, "#888")
        cards += f"""
        <div style="margin-bottom:20px;padding:22px;background:#0A0F16;
                    border:1px solid #141C28;border-left:3px solid {clr};
                    border-radius:10px">
          <div style="font-size:10px;color:{clr};font-weight:700;letter-spacing:1px;
                      text-transform:uppercase;margin-bottom:10px">
            {t.get('domaine','')[:45]} · {src.upper()}
          </div>
          <h3 style="margin:0 0 12px;font-size:16px;color:#EEF0F2;line-height:1.4;font-family:'Helvetica Neue',sans-serif">
            {t['objet'][:110]}{urg}
          </h3>
          <table style="width:100%;font-size:13px;border-collapse:collapse">
            <tr><td style="padding:3px 0;color:#8A8490">🏢</td>
                <td style="padding:3px 0;color:#A8A29E">{t.get('acheteur','')[:70]}</td></tr>
            <tr><td style="padding:3px 0;color:#8A8490">📍</td>
                <td style="padding:3px 0;color:#A8A29E">{t.get('region','Maroc')} · {t.get('type_marche','')}</td></tr>
            <tr><td style="padding:3px 0;color:#8A8490">⏰</td>
                <td style="padding:3px 0;color:#2DCDA0;font-weight:700">Limite: {dl}</td></tr>
          </table>
          <a href="{t.get('url','')}" style="display:inline-block;margin-top:16px;
             padding:10px 20px;background:#E9A420;color:#000;border-radius:8px;
             font-weight:700;font-size:13px;text-decoration:none;font-family:'Helvetica Neue',sans-serif">
            Voir la consultation →
          </a>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BRAND} — Alertes Marchés</title></head>
<body style="background:#04080F;font-family:'Helvetica Neue',Arial,sans-serif;color:#EEF0F2;
             padding:0;margin:0">
<div style="max-width:620px;margin:0 auto;padding:40px 24px">
  <div style="margin-bottom:36px;padding-bottom:24px;border-bottom:1px solid #141C28;
              display:flex;align-items:center;justify-content:space-between">
    <div>
      <span style="font-size:24px;font-weight:900;color:#E9A420;letter-spacing:2px">{BRAND}</span>
      <div style="font-size:11px;color:#52524E;letter-spacing:.5px;text-transform:uppercase;margin-top:2px">
        Intelligence des Marchés Publics
      </div>
    </div>
    <span style="padding:4px 12px;background:rgba(45,205,160,.1);color:#2DCDA0;
                 border-radius:100px;font-size:11px;font-weight:700;border:1px solid rgba(45,205,160,.2)">
      {len(tenders)} nouveau(x)
    </span>
  </div>
  <h2 style="font-size:20px;font-weight:700;margin:0 0 6px;color:#EEF0F2">
    Nouveaux marchés · {nom}
  </h2>
  <p style="color:#52524E;font-size:13px;margin:0 0 30px">
    Correspondant à vos secteurs d'activité — {datetime.now().strftime('%d/%m/%Y')}
  </p>
  {cards}
  <div style="margin-top:40px;padding-top:24px;border-top:1px solid #141C28;
              text-align:center;font-size:12px;color:#52524E">
    <a href="{SITE_URL}/tenders" style="color:#E9A420">Voir tous les marchés</a>
    &nbsp;·&nbsp;
    <a href="{SITE_URL}/settings" style="color:#52524E">Gérer mes préférences</a>
  </div>
</div>
</body></html>"""


def _record_alerts(member_id: int, tenders: list[dict], channel: str):
    try:
        conn = db()
        for t in tenders:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO alerts_sent "
                    "(member_id, tender_id, channel, sent_at) VALUES (?,?,?,?)",
                    (member_id, t["id"], channel, now_str()),
                )
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning(f"[record_alerts] {exc}")


async def notify_members(new_tenders: list[dict]):
    """Dispatch notifications to all active members."""
    if not new_tenders:
        return

    conn = db()
    try:
        members = [
            dict(r) for r in conn.execute(
                "SELECT id,nom,email,telegram,secteurs,regions_pref,types_pref,"
                "notif_tg,notif_email,plan,daily_sent,daily_reset "
                "FROM members WHERE actif=1"
            ).fetchall()
        ]
    finally:
        conn.close()

    total_tg = total_em = 0

    for m in members:
        matched = _match_member(m, new_tenders)
        if not matched:
            continue

        nom  = m.get("nom") or "Utilisateur"
        plan = m.get("plan", "free")

        # Free plan daily cap
        if plan == "free":
            today_s = today_str()
            if m.get("daily_reset") != today_s:
                conn = db()
                conn.execute(
                    "UPDATE members SET daily_sent=0, daily_reset=? WHERE id=?",
                    (today_s, m["id"]),
                )
                conn.commit()
                conn.close()
                m["daily_sent"] = 0
            remaining = FREE_DAILY - (m.get("daily_sent") or 0)
            if remaining <= 0:
                continue
            matched = matched[:remaining]

        SLog.add(f"[Notify] {nom} ({plan}) → {len(matched)} marché(s)")

        # Telegram
        if m.get("notif_tg") and m.get("telegram"):
            ok = await tg_send(m["telegram"], _tg_msg(matched, nom))
            if ok:
                total_tg += 1
                _record_alerts(m["id"], matched, "telegram")

        # Email
        if m.get("notif_email") and m.get("email"):
            subj = f"🏛 {len(matched)} marché(s) — {BRAND}"
            ok   = await email_brevo(m["email"], subj, _email_html(matched, nom))
            if ok:
                total_em += 1
                _record_alerts(m["id"], matched, "email")

        # Update counters
        conn = db()
        conn.execute(
            "UPDATE members SET alert_count=alert_count+?, daily_sent=daily_sent+? WHERE id=?",
            (len(matched), len(matched), m["id"]),
        )
        conn.commit()
        conn.close()

    if total_tg or total_em:
        SLog.add(f"[Notify] ✅ {total_tg} TG · {total_em} Email")
        await tg_send(
            ADMIN_TG,
            f"📊 <b>{BRAND}</b>\n"
            f"✓ {SS.saved} nouveaux · {total_tg} TG · {total_em} Email",
        )

# ═══════════════════════════════════════════════════════════════════
# MONITOR AGENT — hourly expire + cleanup
# ═══════════════════════════════════════════════════════════════════
async def monitor_agent():
    while True:
        await asyncio.sleep(3600)
        try:
            conn = db()
            expire_tenders(conn)
            conn.execute("DELETE FROM alerts_sent WHERE sent_at < date('now','-90 days')")
            conn.execute("DELETE FROM agent_errors WHERE created_at < date('now','-7 days')")
            conn.execute("DELETE FROM scrape_runs WHERE created_at < date('now','-30 days')")
            conn.commit()
            conn.close()
            SLog.add("[Monitor] ✓ Nettoyage horaire effectué")
        except Exception as exc:
            log.warning(f"[Monitor] {exc}")

# ═══════════════════════════════════════════════════════════════════
# SCHEDULER
# ═══════════════════════════════════════════════════════════════════
_last_scrape: float = 0.0

async def scheduler():
    await asyncio.sleep(120)
    global _last_scrape
    while True:
        try:
            if time.time() - _last_scrape >= SCRAPE_HRS * 3600:
                _last_scrape = time.time()
                loop     = asyncio.get_event_loop()
                new_list = await loop.run_in_executor(None, run_all_scrapers)
                if new_list:
                    await notify_members(new_list)
        except Exception as exc:
            SS.running = False
            SLog.add(f"[Scheduler] ❌ {exc}")
            log.error(f"[Scheduler] {traceback.format_exc()}")
        await asyncio.sleep(300)

# ═══════════════════════════════════════════════════════════════════
# APP INIT
# ═══════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in ["static", "data", "templates"]:
        os.makedirs(d, exist_ok=True)
    db_init()
    asyncio.create_task(scheduler())
    asyncio.create_task(monitor_agent())
    log.info(f"✅ {BRAND} v{VERSION} — {TAGLINE}")
    yield

app = FastAPI(
    lifespan  = lifespan,
    title     = BRAND,
    version   = VERSION,
    docs_url  = None,
    redoc_url = None,
)
app.add_middleware(SecureHeadersMiddleware)
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass

try:
    tpl = Jinja2Templates(directory="templates")
except Exception:
    tpl = None   # type: ignore

# ─── Jinja2 custom filters ────────────────────────────────────────
def _fmt_num(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

def _sector_color(code: str) -> str:
    t = (code or "")[:1]
    return {"T": "blue", "P": "green", "S": "amber"}.get(t, "gray")

if tpl:
    tpl.env.filters["fmt_num"] = _fmt_num
    tpl.env.filters["sec_color"] = _sector_color

# ─── Template renderer ────────────────────────────────────────────
def render(req: Request, tmpl: str, ctx: dict | None = None) -> HTMLResponse:
    if tpl is None:
        return HTMLResponse("<h1>Template engine unavailable</h1>", 500)
    uid = session_get(req)
    m   = None
    if uid:
        conn = db()
        row  = conn.execute(
            "SELECT * FROM members WHERE id=? AND actif=1", (uid,)
        ).fetchone()
        conn.close()
        m = dict(row) if row else None

    base: dict = {
        "request":       req,
        "BRAND":         BRAND,
        "TAGLINE":       TAGLINE,
        "VERSION":       VERSION,
        "SITE_URL":      SITE_URL,
        "SECTORS":       SECTORS,
        "SECTORS_LIST":  SECTORS_LIST,
        "SECTORS_BY_TYPE": SECTORS_BY_TYPE,
        "REGIONS_LIST":  REGIONS_LIST,
        "MARKET_TYPES":  MARKET_TYPES,
        "SOURCE_TYPES":  SOURCE_TYPES,
        "member":        m,
        "now":           datetime.now(),
        "_flash":        req.query_params.get("_f", ""),
        "_fk":           req.query_params.get("_fk", "ok"),
    }
    if ctx:
        base.update(ctx)
    try:
        return tpl.TemplateResponse(tmpl, base)
    except Exception as exc:
        log.error(f"[render:{tmpl}] {exc}\n{traceback.format_exc()}")
        return HTMLResponse(f"<pre>Template error: {exc}</pre>", 500)

def redirect_flash(url: str, msg: str, kind: str = "ok") -> RedirectResponse:
    return RedirectResponse(
        f"{url}?_f={msg}&_fk={kind}", status_code=302
    )

def require_login(req: Request) -> Optional[dict]:
    uid = session_get(req)
    if not uid:
        return None
    conn = db()
    row  = conn.execute(
        "SELECT * FROM members WHERE id=? AND actif=1", (uid,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ═══════════════════════════════════════════════════════════════════
# ROUTES — LANDING & PUBLIC
# ═══════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    conn = db()
    try:
        stats = {
            "actif":    conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "total":    conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members":  conn.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "urgence":  conn.execute("SELECT COUNT(*) FROM tenders WHERE urgence=1 AND statut='actif'").fetchone()[0],
            "public":   conn.execute("SELECT COUNT(*) FROM tenders WHERE source_type='public' AND statut='actif'").fetchone()[0],
            "para":     conn.execute("SELECT COUNT(*) FROM tenders WHERE source_type='parastatal' AND statut='actif'").fetchone()[0],
        }
        recent = [
            dict(r) for r in conn.execute(
                "SELECT * FROM tenders WHERE statut='actif' "
                "ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
        ]
        runs = [
            dict(r) for r in conn.execute(
                "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1"
            ).fetchall()
        ]
    finally:
        conn.close()
    return render(req, "landing.html", {
        "stats": stats,
        "recent": recent,
        "last_run": runs[0] if runs else {},
    })

# ═══════════════════════════════════════════════════════════════════
# ROUTES — TENDERS
# ═══════════════════════════════════════════════════════════════════
@app.get("/tenders", response_class=HTMLResponse)
async def tenders_list(
    req:       Request,
    q:         str = "",
    code_f:    str = "",
    type_f:    str = "",
    region_f:  str = "",
    source_f:  str = "",
    urgence_f: int = 0,
    sort:      str = "recent",
    page:      int = 1,
):
    m = require_login(req)
    if not m:
        return RedirectResponse(f"/login?next=/tenders", 302)

    _SORT = {
        "recent":   "created_at DESC",
        "deadline": "CASE WHEN date_limite='' THEN '9999' ELSE date_limite END ASC",
        "urgence":  "urgence DESC, created_at DESC",
        "az":       "objet ASC",
    }
    order = _SORT.get(sort, "created_at DESC")
    PER   = 24
    off   = (page - 1) * PER

    conn = db()
    try:
        conds:  list[str] = ["t.statut='actif'"]
        params: list      = []

        if q:
            # Try FTS first, fallback to LIKE
            try:
                fts_ids = [
                    r[0] for r in conn.execute(
                        "SELECT id FROM tenders_fts WHERE tenders_fts MATCH ? LIMIT 200",
                        (q,),
                    ).fetchall()
                ]
                if fts_ids:
                    ph = ",".join(["?"] * len(fts_ids))
                    conds.append(f"t.id IN ({ph})")
                    params.extend(fts_ids)
                else:
                    qp = f"%{q[:80]}%"
                    conds.append("(t.objet LIKE ? OR t.acheteur LIKE ? OR t.domaine LIKE ?)")
                    params += [qp, qp, qp]
            except Exception:
                qp = f"%{q[:80]}%"
                conds.append("(t.objet LIKE ? OR t.acheteur LIKE ? OR t.domaine LIKE ?)")
                params += [qp, qp, qp]

        if code_f:
            conds.append("t.domaine_code = ?")
            params.append(code_f)
        if type_f:
            conds.append("t.type_marche = ?")
            params.append(type_f)
        if region_f:
            conds.append("t.region = ?")
            params.append(region_f)
        if source_f:
            conds.append("t.source_type = ?")
            params.append(source_f)
        if urgence_f:
            conds.append("t.urgence = 1")

        where = " AND ".join(conds)
        total = conn.execute(
            f"SELECT COUNT(*) FROM tenders t WHERE {where}", params
        ).fetchone()[0]
        rows = [
            dict(r) for r in conn.execute(
                f"SELECT t.* FROM tenders t WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                params + [PER, off],
            ).fetchall()
        ]

        # Sidebar counts for active filters
        domaine_counts = {
            r[0]: r[1] for r in conn.execute(
                "SELECT domaine_code, COUNT(*) FROM tenders WHERE statut='actif' "
                "GROUP BY domaine_code ORDER BY 2 DESC LIMIT 20"
            ).fetchall()
        }
        region_counts = {
            r[0]: r[1] for r in conn.execute(
                "SELECT region, COUNT(*) FROM tenders WHERE statut='actif' "
                "GROUP BY region ORDER BY 2 DESC LIMIT 12"
            ).fetchall()
        }
        source_counts = {
            r[0]: r[1] for r in conn.execute(
                "SELECT source_type, COUNT(*) FROM tenders WHERE statut='actif' "
                "GROUP BY source_type"
            ).fetchall()
        }
    finally:
        conn.close()

    pages = max(1, (total + PER - 1) // PER)
    return render(req, "tenders.html", {
        "tenders":       rows,
        "total":         total,
        "page":          page,
        "pages":         pages,
        "q":             q,
        "code_f":        code_f,
        "type_f":        type_f,
        "region_f":      region_f,
        "source_f":      source_f,
        "urgence_f":     urgence_f,
        "sort":          sort,
        "domaine_counts": domaine_counts,
        "region_counts":  region_counts,
        "source_counts":  source_counts,
    })


@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    m = require_login(req)
    if not m:
        return RedirectResponse(f"/login?next=/tenders/{tid}", 302)
    conn = db()
    t    = conn.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    bm   = conn.execute(
        "SELECT id FROM bookmarks WHERE member_id=? AND tender_id=?",
        (m["id"], tid),
    ).fetchone()
    # Related tenders (same domaine)
    related = [
        dict(r) for r in conn.execute(
            "SELECT * FROM tenders WHERE statut='actif' AND domaine_code=? "
            "AND id != ? ORDER BY created_at DESC LIMIT 4",
            ((dict(t)["domaine_code"] if t else ""), tid),
        ).fetchall()
    ]
    conn.close()
    if not t:
        raise HTTPException(404, "Marché introuvable")
    return render(req, "tender_detail.html", {
        "t":          dict(t),
        "bookmarked": bool(bm),
        "related":    related,
    })


@app.post("/tenders/{tid}/bookmark")
async def toggle_bookmark(req: Request, tid: str, note: str = Form("")):
    m = require_login(req)
    if not m:
        return JSONResponse({"error": "auth"}, 401)
    conn = db()
    bm   = conn.execute(
        "SELECT id FROM bookmarks WHERE member_id=? AND tender_id=?",
        (m["id"], tid),
    ).fetchone()
    if bm:
        conn.execute("DELETE FROM bookmarks WHERE id=?", (bm["id"],))
        added = False
    else:
        conn.execute(
            "INSERT OR IGNORE INTO bookmarks (member_id, tender_id, note) VALUES (?,?,?)",
            (m["id"], tid, note[:500]),
        )
        added = True
    conn.commit()
    conn.close()
    return JSONResponse({"bookmarked": added})

# ═══════════════════════════════════════════════════════════════════
# ROUTES — AUTH
# ═══════════════════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def reg_get(req: Request):
    if require_login(req):
        return RedirectResponse("/tenders", 302)
    return render(req, "register.html", {})


@app.post("/register")
async def reg_post(
    req:       Request,
    nom:       str = Form(""),
    email:     str = Form(""),
    phone:     str = Form(""),
    telegram:  str = Form(""),
    secteurs:  str = Form(""),
    regions_p: str = Form(""),
    types_p:   str = Form(""),
    password:  str = Form(""),
    password2: str = Form(""),
):
    rate_guard(req, "register", 5, 3600)

    form_data = {"nom": nom, "email": email, "phone": phone,
                 "telegram": telegram, "secteurs": secteurs}

    def err(msg: str):
        return render(req, "register.html", {"error": msg, "fd": form_data})

    if not nom.strip() or not email.strip() or not password:
        return err("Nom, email et mot de passe sont obligatoires.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
        return err("Adresse email invalide.")
    if password != password2:
        return err("Les mots de passe ne correspondent pas.")
    if len(password) < 8:
        return err("Le mot de passe doit contenir au moins 8 caractères.")

    email_c = email.strip().lower()[:200]

    conn = db()
    try:
        if conn.execute("SELECT 1 FROM members WHERE email=?", (email_c,)).fetchone():
            conn.close()
            return err("Cette adresse email est déjà associée à un compte.")
        uid = str(uuid.uuid4())[:8]
        conn.execute(
            "INSERT INTO members "
            "(uid, nom, email, phone, telegram, secteurs, regions_pref, types_pref, "
            "pw_hash, plan, actif, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
            (
                uid,
                nom.strip()[:100],
                email_c,
                phone.strip()[:30],
                telegram.strip()[:80],
                secteurs[:800],
                regions_p[:300],
                types_p[:200],
                pw_hash(password),
                "free",
                now_str(),
            ),
        )
        conn.commit()
        new_id = conn.execute(
            "SELECT id FROM members WHERE email=?", (email_c,)
        ).fetchone()[0]
        conn.close()
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return err(f"Erreur : {exc}")

    resp = RedirectResponse("/tenders?_f=Bienvenue+sur+RASSD+✓&_fk=ok", 302)
    session_create(resp, new_id)
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    if require_login(req):
        return RedirectResponse("/tenders", 302)
    return render(req, "login.html", {"next": req.query_params.get("next", "/tenders")})


@app.post("/login")
async def login_post(
    req:      Request,
    email:    str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/tenders"),
):
    rate_guard(req, f"login:{get_ip(req)}", 5, 300)
    conn = db()
    row  = conn.execute(
        "SELECT * FROM members WHERE email=? AND actif=1",
        (email.strip().lower(),),
    ).fetchone()
    conn.close()

    if not row or not pw_verify(password, row["pw_hash"]):
        return render(req, "login.html", {
            "error": "Email ou mot de passe incorrect.",
            "next":  next_url,
        })

    conn = db()
    conn.execute("UPDATE members SET last_login=? WHERE id=?", (now_str(), row["id"]))
    conn.commit()
    conn.close()

    safe = next_url if next_url.startswith("/") else "/tenders"
    resp = RedirectResponse(safe, 302)
    session_create(resp, row["id"])
    return resp


@app.get("/logout")
async def logout(req: Request):
    resp = RedirectResponse("/", 302)
    session_destroy(resp)
    return resp

# ═══════════════════════════════════════════════════════════════════
# ROUTES — SETTINGS & DASHBOARD
# ═══════════════════════════════════════════════════════════════════
@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = require_login(req)
    if not m:
        return RedirectResponse("/login?next=/settings", 302)
    conn = db()
    bookmarks = [
        dict(r) for r in conn.execute(
            "SELECT b.*, t.objet, t.date_limite, t.domaine, t.source_type "
            "FROM bookmarks b JOIN tenders t ON t.id=b.tender_id "
            "WHERE b.member_id=? ORDER BY b.created_at DESC LIMIT 20",
            (m["id"],),
        ).fetchall()
    ]
    webhook_rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM webhooks WHERE member_id=?", (m["id"],)
        ).fetchall()
    ]
    alert_stats = conn.execute(
        "SELECT channel, COUNT(*) as cnt FROM alerts_sent WHERE member_id=? "
        "GROUP BY channel", (m["id"],)
    ).fetchall()
    conn.close()
    sel_sect = [s.strip() for s in (m.get("secteurs") or "").split(",") if s.strip()]
    sel_reg  = [r.strip() for r in (m.get("regions_pref") or "").split(",") if r.strip()]
    sel_typ  = [t.strip() for t in (m.get("types_pref") or "").split(",") if t.strip()]
    return render(req, "settings.html", {
        "sel_sect":    sel_sect,
        "sel_reg":     sel_reg,
        "sel_typ":     sel_typ,
        "bookmarks":   bookmarks,
        "webhooks":    webhook_rows,
        "alert_stats": {r["channel"]: r["cnt"] for r in alert_stats},
    })


@app.post("/settings")
async def settings_post(
    req:          Request,
    nom:          str = Form(""),
    phone:        str = Form(""),
    telegram:     str = Form(""),
    secteurs:     str = Form(""),
    regions_pref: str = Form(""),
    types_pref:   str = Form(""),
    notif_tg:     str = Form("0"),
    notif_email:  str = Form("0"),
    notif_urgence: str = Form("0"),
    password:     str = Form(""),
    password2:    str = Form(""),
):
    m = require_login(req)
    if not m:
        return RedirectResponse("/login", 302)

    if password:
        if password != password2:
            return render(req, "settings.html", {
                "error": "Les mots de passe ne correspondent pas.",
                "sel_sect": [], "sel_reg": [], "sel_typ": [],
                "bookmarks": [], "webhooks": [], "alert_stats": {},
            })
        if len(password) < 8:
            return render(req, "settings.html", {
                "error": "Mot de passe trop court.",
                "sel_sect": [], "sel_reg": [], "sel_typ": [],
                "bookmarks": [], "webhooks": [], "alert_stats": {},
            })

    upd: dict = {
        "nom":          (nom.strip() or m["nom"])[:100],
        "phone":        phone.strip()[:30],
        "telegram":     telegram.strip()[:80],
        "secteurs":     secteurs[:800],
        "regions_pref": regions_pref[:400],
        "types_pref":   types_pref[:200],
        "notif_tg":     1 if notif_tg    == "1" else 0,
        "notif_email":  1 if notif_email  == "1" else 0,
        "notif_urgence": 1 if notif_urgence == "1" else 0,
    }
    if password:
        upd["pw_hash"] = pw_hash(password)

    conn = db()
    fields = ", ".join(f"{k}=?" for k in upd)
    conn.execute(
        f"UPDATE members SET {fields} WHERE id=?",
        [*upd.values(), m["id"]],
    )
    conn.commit()
    conn.close()
    return redirect_flash("/settings", "Paramètres sauvegardés ✓")


@app.post("/settings/webhook")
async def add_webhook(
    req:    Request,
    url:    str = Form(""),
    secret: str = Form(""),
):
    m = require_login(req)
    if not m:
        return RedirectResponse("/login", 302)
    if m.get("plan") == "free":
        return redirect_flash("/settings", "Webhooks disponibles en plan Pro", "err")
    if not url.startswith("http"):
        return redirect_flash("/settings", "URL webhook invalide", "err")
    conn = db()
    conn.execute(
        "INSERT INTO webhooks (member_id, url, secret, actif) VALUES (?,?,?,1)",
        (m["id"], url[:400], secret[:100] or gen_token()),
    )
    conn.commit()
    conn.close()
    return redirect_flash("/settings", "Webhook ajouté ✓")


@app.post("/settings/api_token")
async def gen_api_token(req: Request):
    m = require_login(req)
    if not m:
        return JSONResponse({"error": "auth"}, 401)
    token = gen_token()
    conn  = db()
    conn.execute("UPDATE members SET api_token=? WHERE id=?", (token, m["id"]))
    conn.commit()
    conn.close()
    return JSONResponse({"token": token})

# ═══════════════════════════════════════════════════════════════════
# ROUTES — ADMIN
# ═══════════════════════════════════════════════════════════════════
@app.get("/admin/login", response_class=HTMLResponse)
async def adm_login_get(req: Request):
    if admin_ok(req):
        return RedirectResponse("/admin", 302)
    return HTMLResponse(_adm_login_page(""))


@app.post("/admin/login")
async def adm_login_post(req: Request, pwd: str = Form("")):
    rate_guard(req, "admin_login", 5, 300)
    if pwd != ADMIN_PASS:
        return HTMLResponse(_adm_login_page("Mot de passe incorrect"))
    resp = RedirectResponse("/admin", 302)
    resp.set_cookie(
        _ADM_COOKIE, _adm_token(),
        max_age=86400, httponly=True, samesite="lax",
        secure=SITE_URL.startswith("https"),
    )
    return resp


@app.get("/admin/logout")
async def adm_logout():
    resp = RedirectResponse("/", 302)
    resp.delete_cookie(_ADM_COOKIE)
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(req: Request):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    conn = db()
    try:
        stats = {
            "actif":    conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "expire":   conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "total":    conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members":  conn.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "alerts":   conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0],
            "urgence":  conn.execute("SELECT COUNT(*) FROM tenders WHERE urgence=1 AND statut='actif'").fetchone()[0],
        }
        members = [
            dict(r) for r in conn.execute(
                "SELECT id,nom,email,telegram,plan,secteurs,notif_tg,notif_email,"
                "created_at,last_login,alert_count,actif "
                "FROM members ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ]
        recent = [
            dict(r) for r in conn.execute(
                "SELECT * FROM tenders WHERE statut='actif' "
                "ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        ]
        runs = [
            dict(r) for r in conn.execute(
                "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 15"
            ).fetchall()
        ]
        # Source breakdown
        src_breakdown = {
            r[0]: r[1] for r in conn.execute(
                "SELECT source_type, COUNT(*) FROM tenders WHERE statut='actif' "
                "GROUP BY source_type"
            ).fetchall()
        }
        # Daily activity (last 7d)
        daily = [
            dict(r) for r in conn.execute(
                "SELECT DATE(created_at) as d, COUNT(*) as cnt "
                "FROM tenders WHERE created_at >= date('now','-7 days') "
                "GROUP BY d ORDER BY d"
            ).fetchall()
        ]
    finally:
        conn.close()
    return render(req, "admin.html", {
        "stats":         stats,
        "members":       members,
        "recent":        recent,
        "runs":          runs,
        "src_breakdown": src_breakdown,
        "daily":         daily,
        "slog":          SLog.tail(80),
        "ss":            SS,
    })


@app.get("/admin/scrape")
async def adm_scrape(req: Request):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    if SS.running:
        return JSONResponse({"error": "Scraping déjà en cours"}, 409)

    async def _bg():
        loop = asyncio.get_event_loop()
        new  = await loop.run_in_executor(None, run_all_scrapers)
        if new:
            await notify_members(new)

    asyncio.create_task(_bg())
    return redirect_flash("/admin", "Scraping lancé ▶")


@app.get("/admin/scrape_stream")
async def adm_scrape_stream(req: Request):
    if not admin_ok(req):
        return JSONResponse({"error": "Non autorisé"}, 401)
    prev = [0]

    async def gen():
        while True:
            entries = SLog.tail(400)
            new     = entries[prev[0]:]
            for e in new:
                data = json.dumps({
                    "log":   e,
                    "state": {
                        "running": SS.running,
                        "found":   SS.found,
                        "saved":   SS.saved,
                        "errors":  SS.errors,
                        "current": SS.current,
                        "total":   SS.total,
                        "source":  SS.source,
                    },
                })
                yield f"data: {data}\n\n"
            prev[0] = len(entries)
            if not SS.running and prev[0] > 0:
                yield f"data: {json.dumps({'done': True, 'saved': SS.saved})}\n\n"
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(
        gen(),
        media_type = "text/event-stream",
        headers    = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/admin/expire_now")
async def adm_expire(req: Request):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    conn = db()
    n    = expire_tenders(conn)
    act  = conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    conn.close()
    return JSONResponse({"expired": n, "active_remaining": act})


@app.get("/admin/clear_tenders")
async def adm_clear(req: Request, confirm: str = ""):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    if confirm != "yes":
        return JSONResponse({"error": "Ajoutez ?confirm=yes"}, 400)
    conn = db()
    n    = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    conn.execute("DELETE FROM tenders")
    conn.execute("DELETE FROM tenders_fts")
    conn.execute("DELETE FROM alerts_sent")
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "deleted": n})


@app.get("/admin/test_notify")
async def adm_test_notify(req: Request, chat_id: str = ""):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    target = chat_id or ADMIN_TG
    ok     = await tg_send(
        target,
        f"✅ <b>{BRAND}</b> v{VERSION} — Test notification OK\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
    )
    return JSONResponse({"ok": ok, "target": target})


@app.post("/admin/member_toggle")
async def adm_member_toggle(req: Request, mid: int = Form(0)):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    conn = db()
    conn.execute(
        "UPDATE members SET actif = CASE WHEN actif=1 THEN 0 ELSE 1 END WHERE id=?",
        (mid,),
    )
    conn.commit()
    conn.close()
    return redirect_flash("/admin", "Membre mis à jour ✓")


@app.post("/admin/member_plan")
async def adm_member_plan(req: Request, mid: int = Form(0), plan: str = Form("free")):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    if plan not in ("free","pro","enterprise"):
        return redirect_flash("/admin", "Plan invalide", "err")
    conn = db()
    conn.execute("UPDATE members SET plan=? WHERE id=?", (plan, mid))
    conn.commit()
    conn.close()
    return redirect_flash("/admin", f"Plan mis à jour → {plan} ✓")


@app.get("/admin/export_csv")
async def adm_export_csv(req: Request, statut: str = "actif"):
    if not admin_ok(req):
        return RedirectResponse("/admin/login", 302)
    conn = db()
    rows = conn.execute(
        "SELECT id,objet,acheteur,region,domaine,type_marche,date_limite,"
        "source,source_type,url,date_extraction "
        "FROM tenders WHERE statut=? ORDER BY created_at DESC",
        (statut,),
    ).fetchall()
    conn.close()

    buf  = io.StringIO()
    wrt  = csv.writer(buf)
    wrt.writerow(["ID","Objet","Acheteur","Région","Domaine","Type","Date limite",
                  "Source","Type source","URL","Extrait le"])
    for r in rows:
        wrt.writerow(list(r))
    buf.seek(0)
    fname = f"rassd_{statut}_{today_str()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type = "text/csv; charset=utf-8",
        headers    = {"Content-Disposition": f"attachment; filename={fname}"},
    )

# ═══════════════════════════════════════════════════════════════════
# ROUTES — PUBLIC API
# ═══════════════════════════════════════════════════════════════════
@app.post("/api/v1/ingest")
async def api_ingest(req: Request):
    rate_guard(req, "api_ingest", 20, 60)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)

    # Auth: Bearer token or pwd
    auth_header = req.headers.get("Authorization", "")
    pwd         = body.get("pwd", "")
    if not auth_header.startswith("Bearer ") and pwd != ADMIN_PASS:
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            conn  = db()
            row   = conn.execute(
                "SELECT id FROM members WHERE api_token=? AND actif=1", (token,)
            ).fetchone()
            conn.close()
            if not row:
                return JSONResponse({"error": "unauthorized"}, 401)
        elif pwd != ADMIN_PASS:
            return JSONResponse({"error": "unauthorized"}, 401)

    tenders = body.get("tenders", [])
    saved   = 0
    new_lst: list[dict] = []

    for t in tenders:
        if not t.get("id") or not t.get("objet"):
            continue
        if is_expired(str(t.get("date_limite", ""))):
            continue
        if tender_save(t):
            saved += 1
            new_lst.append(t)

    if new_lst:
        asyncio.create_task(notify_members(new_lst))

    return JSONResponse({
        "ok":    True,
        "saved": saved,
        "total": len(tenders),
    })


@app.get("/api/v1/tenders")
async def api_tenders(
    req:    Request,
    q:      str = "",
    code:   str = "",
    region: str = "",
    page:   int = 1,
    limit:  int = 20,
):
    # Token auth
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "Unauthorized"}, 401)
    token = auth[7:]
    conn  = db()
    row   = conn.execute(
        "SELECT id FROM members WHERE api_token=? AND actif=1", (token,)
    ).fetchone()
    if not row:
        conn.close()
        return JSONResponse({"error": "Invalid token"}, 401)

    limit  = min(limit, 100)
    off    = (page - 1) * limit
    conds  = ["statut='actif'"]
    params: list = []

    if q:
        conds.append("(objet LIKE ? OR acheteur LIKE ?)")
        qp = f"%{q[:80]}%"
        params += [qp, qp]
    if code:
        conds.append("domaine_code = ?")
        params.append(code)
    if region:
        conds.append("region = ?")
        params.append(region)

    where  = " AND ".join(conds)
    total  = conn.execute(f"SELECT COUNT(*) FROM tenders WHERE {where}", params).fetchone()[0]
    rows   = [
        dict(r) for r in conn.execute(
            f"SELECT id,objet,acheteur,region,domaine,domaine_code,type_marche,"
            f"date_limite,days_left,urgence,source,source_type,url,date_extraction "
            f"FROM tenders WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, off],
        ).fetchall()
    ]
    conn.close()
    return JSONResponse({
        "total": total,
        "page":  page,
        "limit": limit,
        "data":  rows,
    })


@app.get("/api/v1/stats")
async def api_stats():
    conn = db()
    data = {
        "actif":    conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
        "expire":   conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
        "members":  conn.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        "urgence":  conn.execute("SELECT COUNT(*) FROM tenders WHERE urgence=1 AND statut='actif'").fetchone()[0],
        "sources":  {r[0]: r[1] for r in conn.execute(
            "SELECT source_type, COUNT(*) FROM tenders WHERE statut='actif' GROUP BY source_type"
        ).fetchall()},
        "scraper_running": SS.running,
        "last_saved": SS.saved if SS.running else None,
        "version":  VERSION,
    }
    conn.close()
    return JSONResponse(data)

# ═══════════════════════════════════════════════════════════════════
# ROUTES — UTILITY
# ═══════════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    try:
        conn = db()
        n    = conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        conn.close()
        return JSONResponse({
            "status":    "ok",
            "brand":     BRAND,
            "version":   VERSION,
            "actif":     n,
            "running":   SS.running,
            "timestamp": now_str(),
        })
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, 500)

@app.get("/sitemap.xml")
async def sitemap():
    urls = [
        f"{SITE_URL}/",
        f"{SITE_URL}/tenders",
        f"{SITE_URL}/register",
        f"{SITE_URL}/login",
    ]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in urls:
        xml += f"<url><loc>{u}</loc></url>\n"
    xml += "</urlset>"
    return PlainTextResponse(xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return PlainTextResponse(
        "User-agent: *\nDisallow: /admin\nDisallow: /api\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )

# ═══════════════════════════════════════════════════════════════════
# ADMIN LOGIN PAGE — inline HTML
# ═══════════════════════════════════════════════════════════════════
def _adm_login_page(error: str = "") -> str:
    err_html = (
        f'<div style="color:#E85454;background:rgba(232,84,84,.1);border:1px solid rgba(232,84,84,.2);'
        f'padding:11px 16px;border-radius:8px;font-size:13px;margin-bottom:20px">⚠ {error}</div>'
        if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Admin — {BRAND}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#04080F;color:#EEF0F2;font-family:'Outfit',sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh;
      background-image:linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),
                       linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px);
      background-size:60px 60px}}
.box{{background:#070D17;border:1px solid #141C28;border-radius:20px;
      padding:52px 44px;width:380px;box-shadow:0 32px 80px rgba(0,0,0,.8)}}
.logo{{font-size:28px;font-weight:900;color:#E9A420;letter-spacing:2px}}
.sub{{font-size:11px;color:#52524E;letter-spacing:.5px;text-transform:uppercase;margin-bottom:40px;margin-top:4px}}
input{{width:100%;padding:13px 16px;background:#0D1626;border:1px solid #1D2C44;
       border-radius:10px;color:#EEF0F2;font-size:14px;margin-bottom:16px;
       font-family:inherit;transition:border-color .2s;outline:none}}
input:focus{{border-color:#E9A420;box-shadow:0 0 0 3px rgba(233,164,32,.1)}}
button{{width:100%;padding:14px;background:#E9A420;color:#000;border:none;
        border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;
        font-family:inherit;letter-spacing:.3px;transition:opacity .2s}}
button:hover{{opacity:.85}}
</style></head>
<body><div class="box">
<div class="logo">{BRAND}</div>
<div class="sub">Console d'administration</div>
{err_html}
<form method="post" action="/admin/login">
  <input type="password" name="pwd" placeholder="Mot de passe admin" autofocus autocomplete="current-password">
  <button type="submit">Accéder au tableau de bord →</button>
</form>
</div></body></html>"""
