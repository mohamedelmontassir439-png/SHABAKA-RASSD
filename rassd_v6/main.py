"""  # v8.0 FINAL 2026-03-27 23:00 2026-03-27 16:12:17 2026-03-25 19:33 2026-03-21 17:53-active-only-20-sources
Modern Business v5.0 — Intelligence Marchés Publics Maroc
══════════════════════════════════════════════════════════
Architecture: FastAPI + SQLite WAL + 5 AI Agents
Agents: Scraper · Classifier · Notify · Monitor · Chat
Sources: 10+ sources gratuites sans inscription
══════════════════════════════════════════════════════════
"""
import os, re, time, json, asyncio, hashlib, secrets, logging
import sqlite3, smtplib, threading, traceback, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict
from contextlib import asynccontextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

try: from itsdangerous import URLSafeTimedSerializer; HAS_ITS = True
except: HAS_ITS = False
try: import urllib3; urllib3.disable_warnings()
except: pass

try:
    from multi_scraper import run_all_scrapers, AIClassifier, Tender as MT, SCRAPERS as MULTI_SRC
    HAS_MULTI = True
except ImportError:
    HAS_MULTI = False

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
BRAND        = "Modern Business"
SITE_URL     = os.getenv("SITE_URL",    "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS   = os.getenv("ADMIN_PASS",  "rassd2026")
SECRET_KEY   = os.getenv("SECRET_KEY",  secrets.token_hex(32))
DB_PATH      = os.getenv("DB_PATH",     "data/mb.db")
GMAIL_USER   = os.getenv("GMAIL_USER",  "mohamedelmontassir439@gmail.com")
GMAIL_PASS   = os.getenv("GMAIL_PASS",  "")
TELEGRAM_BOT  = os.getenv("TELEGRAM_BOT","7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID","6424992854")
ANTHROPIC_KEY= os.getenv("ANTHROPIC_API_KEY", "")
BREVO_KEY    = os.getenv("BREVO_API_KEY", "")
RESEND_KEY   = os.getenv("RESEND_API_KEY", "")
GA_ID        = os.getenv("GA_ID", "")
GSC_TOKEN    = os.getenv("GSC_TOKEN", "")
SCRAPE_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "2"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("mb5")

COUNTERS: dict = defaultdict(int)
def counter(k): COUNTERS[k] += 1

# ══════════════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════════════
_rl: dict = defaultdict(list)
_rl_lock   = threading.Lock()

def rate_limit(ip: str, key: str, max_c=60, win=60) -> bool:
    k = f"{ip}:{key}"; now = time.time()
    with _rl_lock:
        calls = [t for t in _rl[k] if now - t < win]
        if len(calls) >= max_c: return False
        calls.append(now); _rl[k] = calls
    return True

def get_ip(r: Request) -> str:
    fwd = r.headers.get("X-Forwarded-For","")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "127.0.0.1")

def rl(req: Request, key: str, max_c=60, win=60):
    if not rate_limit(get_ip(req), key, max_c, win):
        raise HTTPException(429, "Trop de requêtes — réessayez plus tard")

# ══════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════
class SecureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        })
        return resp

# ══════════════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════════════
COOKIE_NAME = "mb5_s"
COOKIE_TTL  = 86400 * 30

def session_create(resp: Response, uid: int):
    if HAS_ITS:
        s = URLSafeTimedSerializer(SECRET_KEY, salt="mb5")
        token = s.dumps({"id": uid})
    else:
        token = str(uid)
    resp.set_cookie(COOKIE_NAME, token, max_age=COOKIE_TTL,
                    httponly=True, samesite="lax",
                    secure=SITE_URL.startswith("https"))

def session_get(req: Request) -> Optional[int]:
    raw = req.cookies.get(COOKIE_NAME)
    if not raw: return None
    if HAS_ITS:
        try:
            s = URLSafeTimedSerializer(SECRET_KEY, salt="mb5")
            d = s.loads(raw, max_age=COOKIE_TTL)
            return int(d.get("id", 0))
        except: return None
    try: return int(raw)
    except: return None

def session_delete(resp: Response):
    resp.delete_cookie(COOKIE_NAME)

# ══════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════
def get_db() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA cache_size=10000")
    return db

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id               TEXT PRIMARY KEY,
        objet            TEXT NOT NULL DEFAULT '',
        acheteur         TEXT DEFAULT '',
        region           TEXT DEFAULT '',
        domaine          TEXT DEFAULT '',
        type_marche      TEXT DEFAULT '',
        montant          TEXT DEFAULT '',
        budget_min       REAL DEFAULT 0,
        budget_max       REAL DEFAULT 0,
        date_publication TEXT DEFAULT '',
        date_limite      TEXT DEFAULT '',
        description      TEXT DEFAULT '',
        statut           TEXT DEFAULT 'actif',
        url              TEXT DEFAULT '',
        source           TEXT DEFAULT 'marchespublics',
        contact          TEXT DEFAULT '',
        ai_score         INTEGER DEFAULT 50,
        ai_category      TEXT DEFAULT '',
        ai_reason        TEXT DEFAULT '',
        date_extraction  TEXT DEFAULT '',
        views            INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_domaine  ON tenders(domaine);
    CREATE INDEX IF NOT EXISTS idx_t_region   ON tenders(region);
    CREATE INDEX IF NOT EXISTS idx_t_source   ON tenders(source);
    CREATE INDEX IF NOT EXISTS idx_t_score    ON tenders(ai_score DESC);
    CREATE INDEX IF NOT EXISTS idx_t_date     ON tenders(date_extraction DESC);

    CREATE TABLE IF NOT EXISTS members (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nom           TEXT NOT NULL,
        entreprise    TEXT DEFAULT '',
        email         TEXT UNIQUE NOT NULL,
        phone         TEXT DEFAULT '',
        secteur       TEXT DEFAULT '',
        ville         TEXT DEFAULT '',
        pw_hash       TEXT NOT NULL DEFAULT '',
        telegram      TEXT DEFAULT '',
        plan          TEXT DEFAULT 'free',
        actif         INTEGER DEFAULT 1,
        verified      INTEGER DEFAULT 0,
        rating_avg    REAL DEFAULT 0,
        rating_count  INTEGER DEFAULT 0,
        notif_email   INTEGER DEFAULT 1,
        notif_tg      INTEGER DEFAULT 1,
        created_at    TEXT DEFAULT '',
        last_login    TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_m_email ON members(email);

    CREATE TABLE IF NOT EXISTS member_filters (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id  INTEGER NOT NULL REFERENCES members(id),
        type       TEXT NOT NULL,
        value      TEXT NOT NULL,
        created_at TEXT DEFAULT '',
        UNIQUE(member_id, type, value)
    );
    CREATE INDEX IF NOT EXISTS idx_mf_member ON member_filters(member_id);

    CREATE TABLE IF NOT EXISTS posts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id     INTEGER NOT NULL REFERENCES members(id),
        type          TEXT DEFAULT 'offre',
        titre         TEXT NOT NULL DEFAULT '',
        description   TEXT DEFAULT '',
        secteur       TEXT DEFAULT '',
        region        TEXT DEFAULT '',
        budget        TEXT DEFAULT '',
        contact       TEXT DEFAULT '',
        status        TEXT DEFAULT 'actif',
        views         INTEGER DEFAULT 0,
        created_at    TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_p_status ON posts(status);

    CREATE TABLE IF NOT EXISTS ratings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id    INTEGER NOT NULL REFERENCES members(id),
        to_id      INTEGER NOT NULL REFERENCES members(id),
        score      INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
        comment    TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        UNIQUE(from_id, to_id)
    );

    CREATE TABLE IF NOT EXISTS chats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_key TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        created_at  TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_ch_session ON chats(session_key);

    CREATE TABLE IF NOT EXISTS notif_queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id   INTEGER,
        channel     TEXT NOT NULL,
        recipient   TEXT NOT NULL,
        subject     TEXT DEFAULT '',
        body        TEXT NOT NULL,
        status      TEXT DEFAULT 'pending',
        attempts    INTEGER DEFAULT 0,
        error       TEXT DEFAULT '',
        created_at  TEXT DEFAULT '',
        sent_at     TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_nq_status ON notif_queue(status);

    CREATE TABLE IF NOT EXISTS scrape_runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source       TEXT DEFAULT 'all',
        found        INTEGER DEFAULT 0,
        saved        INTEGER DEFAULT 0,
        errors       INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0,
        started_at   TEXT DEFAULT '',
        finished_at  TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS agent_errors (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        agent      TEXT DEFAULT '',
        route      TEXT DEFAULT '',
        error      TEXT DEFAULT '',
        count      INTEGER DEFAULT 1,
        first_seen TEXT DEFAULT '',
        last_seen  TEXT DEFAULT '',
        resolved   INTEGER DEFAULT 0
    );
    """)
    # Migrations
    migrations = [
        "ALTER TABLE members ADD COLUMN telegram TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_email INTEGER DEFAULT 1",
        "ALTER TABLE members ADD COLUMN notif_tg INTEGER DEFAULT 1",
        "ALTER TABLE members ADD COLUMN rating_avg REAL DEFAULT 0",
        "ALTER TABLE members ADD COLUMN rating_count INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN secteur TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN type_marche TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN views INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics'",
        "ALTER TABLE tenders ADD COLUMN contact TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN budget_min REAL DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN budget_max REAL DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN ai_score INTEGER DEFAULT 50",
        "ALTER TABLE tenders ADD COLUMN ai_category TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN ai_reason TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try: db.execute(sql)
        except: pass

    # Auto-migrate from contractors (v1/v2)
    try:
        old = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contractors'").fetchone()
        if old and db.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
            db.execute("""INSERT OR IGNORE INTO members
                (id,nom,entreprise,email,phone,secteur,ville,pw_hash,
                 telegram,plan,actif,verified,notif_email,notif_tg,created_at,last_login)
                SELECT id,nom,COALESCE(entreprise,''),email,COALESCE(phone,''),
                       COALESCE(secteur,''),COALESCE(ville,''),COALESCE(password_hash,''),
                       COALESCE(telegram,''),COALESCE(plan,'free'),COALESCE(actif,1),
                       COALESCE(verified,0),1,1,COALESCE(created_at,''),COALESCE(last_login,'')
                FROM contractors WHERE actif=1""")
            migrated = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
            logger.info(f"Migrated {migrated} members from contractors")
    except Exception as e:
        logger.warning(f"Migration: {e}")

    # Ensure known admin
    try:
        if not db.execute("SELECT 1 FROM members WHERE email=?",("mohamedelmontassir439@gmail.com",)).fetchone():
            db.execute("""INSERT OR IGNORE INTO members
                (nom,email,telegram,plan,actif,notif_email,notif_tg,created_at)
                VALUES (?,?,?,?,1,1,1,?)""",
                ("Admin","mohamedelmontassir439@gmail.com","6424992854","pro",now_str()))
        else:
            db.execute("UPDATE members SET telegram='6424992854' WHERE email=? AND (telegram IS NULL OR telegram='')",
                       ("mohamedelmontassir439@gmail.com",))
    except: pass

    db.commit(); db.close()
    logger.info("DB initialized ✅")

def hash_pw(pw: str) -> str:
    return hashlib.sha256((pw + SECRET_KEY[:16]).encode()).hexdigest()

def check_pw(pw: str, h: str) -> bool:
    return hash_pw(pw) == h

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def get_member(req: Request) -> Optional[dict]:
    uid = session_get(req)
    if not uid: return None
    db = get_db()
    try:
        row = db.execute("SELECT * FROM members WHERE id=? AND actif=1", (uid,)).fetchone()
        return dict(row) if row else None
    finally: db.close()

# ══════════════════════════════════════════════════════
# CLASSIFICATION
# ══════════════════════════════════════════════════════
REGIONS = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","kenitra","témara","khémisset","skhirat"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache"],
    "Oriental":                  ["oujda","nador","berkane","taourirt"],
    "Béni Mellal-Khénifra":     ["béni mellal","khénifra","azilal","khouribga"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt"],
    "Laâyoune":                  ["laayoune","boujdour"],
    "Dakhla":                    ["dakhla"],
    "Guelmim":                   ["guelmim","tan-tan"],
}
REGIONS_LIST = list(REGIONS.keys())

SECTEURS = {
    "T101 - Constructions & Bâtiments": ["bâtiment","construction","maçonnerie","béton","gros oeuvre","btp","rénovation","mur","clôture","façade","toiture","réhabilitation"],
    "T102 - Terrassements":             ["terrassement","remblai","déblai","excavation","nivellement","compactage"],
    "T103 - Menuiserie & Métallerie":   ["menuiserie","métallerie","charpente","ferronnerie","portail","serrurerie"],
    "T104 - Plomberie & Climatisation": ["plomberie","chauffage","climatisation","sanitaire","tuyauterie","cvc"],
    "T105 - Peinture & Vitrerie":       ["peinture","vitrerie","enduit","revêtement"],
    "T106 - Étanchéité & Isolation":    ["étanchéité","isolation","membrane","imperméabilisation"],
    "T107 - Revêtements":               ["carrelage","parquet","revêtement sol","dallage","faïence"],
    "T108 - Plâtrerie & Faux Plafonds": ["plâtrerie","faux plafond","cloison","gyproc"],
    "T110 - Génie Civil":               ["génie civil","pont","infrastructure","ouvrage d'art","géotechnique"],
    "T111 - Espaces Verts":             ["espaces verts","jardinage","plantation","gazon","élagage"],
    "T201 - Assainissement":            ["assainissement","égout","step","collecteur","canalisation"],
    "T203 - Hydraulique & Eau":         ["hydraulique","eau potable","adduction","barrage","forage","irrigation"],
    "T301 - Travaux Routiers":          ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation"],
    "T401 - Électricité & Éclairage":   ["électricité","éclairage","câblage","tableau électrique","transformateur"],
    "T402 - Sécurité Électronique":     ["vidéosurveillance","cctv","alarme incendie","contrôle accès"],
    "T403 - Télécommunications":        ["télécommunication","fibre optique","réseau","switch","wifi"],
    "P813 - Équipements Médicaux":      ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament"],
    "P814 - Climatisation":             ["climatiseur","split","froid industriel","chambre froide"],
    "P816 - Matériel Roulant":          ["véhicule","voiture","camion","bus","carburant","gasoil"],
    "P818 - Informatique":              ["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud","erp"],
    "P825 - Fournitures Bureau":        ["fournitures","papier","ramette","mobilier","bureau","chaise"],
    "P833 - Produits Pharmaceutiques":  ["médicament","pharmaceutique","produits chimiques","réactif labo"],
    "P834 - Alimentation":              ["alimentation","denrée","viande","restauration","traiteur"],
    "P839 - Matériaux Construction":    ["ciment","sable","gravier","béton prêt","brique","acier"],
    "P841 - Hygiène & Nettoyage":       ["nettoyage","propreté","désinfection","savon","détergent"],
    "P850 - Énergies Renouvelables":    ["solaire","photovoltaïque","énergie renouvelable","panneau solaire"],
    "S901 - IT & Développement":        ["développement logiciel","application mobile","site web","cybersécurité"],
    "S902 - Études & Conseil":          ["étude","conseil","consultant","expertise","audit","bureau d'études"],
    "S906 - Maintenance":               ["maintenance","entretien","réparation","dépannage"],
    "S907 - Nettoyage Service":         ["nettoyage service","propreté service","dératisation"],
    "S908 - Gardiennage":               ["gardiennage","sécurité","surveillance","agent de sécurité"],
    "S910 - Communication":             ["communication","publicité","événementiel","impression"],
    "S913 - Formation":                 ["formation","coaching","séminaire","certification"],
    "S915 - Transport":                 ["transport","location véhicule","navette","chauffeur"],
}
SECTEURS_LIST = list(SECTEURS.keys())

PLAN_LIMITS = {
    "free":       {"tenders_per_day": 10, "telegram": False, "api": False, "filters": 2},
    "pro":        {"tenders_per_day": 999, "telegram": True,  "api": True,  "filters": 999},
    "enterprise": {"tenders_per_day": 999, "telegram": True,  "api": True,  "filters": 999},
}

class ClassifierAgent:
    @staticmethod
    def clean_objet(text: str) -> str:
        t = re.sub(r'^#\s*0*\d+\s*', '', text.strip())
        t = re.sub(r'^LOT\s*[N°n°#]?\s*\d+\s*[:\-–]?\s*', '', t, flags=re.I)
        t = re.sub(r'^[\d]+\s*[:\-–]\s*', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t[0].upper() + t[1:] if t and t[0].islower() else t

    @staticmethod
    def region(text: str) -> str:
        txt = text.lower()
        for region, kws in REGIONS.items():
            if any(k in txt for k in kws): return region
        return "Maroc"

    @staticmethod
    def secteur(text: str) -> str:
        txt = text.lower()
        scores: dict = defaultdict(int)
        for sect, kws in SECTEURS.items():
            for kw in kws:
                if kw in txt:
                    scores[sect] += 2 if len(kw) > 10 else 1
        return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

    @staticmethod
    def type_marche(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation"]): return "Travaux"
        if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement"]): return "Fournitures"
        if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage"]): return "Services"
        if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise"]): return "Études & Conseil"
        return "Fournitures"

    @staticmethod
    def is_expired(d: str) -> bool:
        if not d: return False
        d = d.strip()
        if d in ("N/A","—","","-","null","Non précisée","—"): return False
        today = datetime.now().date()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
            try: return datetime.strptime(d, fmt).date() < today
            except: pass
        return False
        return False

    @staticmethod
    def extract_date(text: str) -> str:
        if not text: return ""
        m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
        return m.group(1) if m else ""

# ══════════════════════════════════════════════════════
# SCRAPER AGENT
# ══════════════════════════════════════════════════════
class SLog:
    entries: list = []
    @classmethod
    def add(cls, msg):
        e = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.entries.append(e); logger.info(e)
        if len(cls.entries) > 600: cls.entries = cls.entries[-500:]
    @classmethod
    def last(cls, n=100): return cls.entries[-n:]

class SState:
    running = False; found = 0; saved = 0
    errors = 0; started = ""; current = 0; total = 0

class ScraperAgent:
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @staticmethod
    def _session():
        import requests
        s = requests.Session(); s.verify = False
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        return s

    @staticmethod
    def _save(t: dict) -> bool:
        if not t or not t.get("id") or not t.get("objet"): return False
        try:
            db = get_db()
            db.execute("""INSERT OR IGNORE INTO tenders
                (id,objet,acheteur,region,domaine,type_marche,montant,
                 budget_min,budget_max,date_publication,date_limite,description,
                 statut,url,source,contact,ai_score,ai_category,ai_reason,date_extraction)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                str(t.get("id",""))[:80],         str(t.get("objet",""))[:400],
                str(t.get("acheteur",""))[:200],   str(t.get("region",""))[:100],
                str(t.get("domaine",""))[:80],     str(t.get("type_marche",""))[:40],
                str(t.get("montant",""))[:80],     float(t.get("budget_min",0) or 0),
                float(t.get("budget_max",0) or 0),str(t.get("date_publication",""))[:20],
                str(t.get("date_limite",""))[:20], str(t.get("description",""))[:2000],
                str(t.get("statut","actif")),      str(t.get("url",""))[:400],
                str(t.get("source","marchespublics")),
                str(t.get("contact",""))[:100],
                int(t.get("ai_score",50) or 50),
                str(t.get("ai_category",""))[:80],
                str(t.get("ai_reason",""))[:300],
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ))
            db.commit()
            changed = db.execute("SELECT changes()").fetchone()[0]
            db.close(); return changed > 0
        except Exception as e:
            logger.error(f"[save] {e}")
            try: db.close()
            except: pass
            return False

    @classmethod
    def _parse(cls, html: str, tid: str) -> Optional[dict]:
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)
            def cell(lbl):
                for row in soup.find_all("tr"):
                    cells = row.find_all(["td","th"])
                    for i,c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1 < len(cells):
                            v = cells[i+1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""
            objet = ""
            for sel in [".consultation-title",".objet","h1","h2"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    skip = ["accueil","liste des avis","connexion","portail"]
                    if 8 < len(txt) < 600 and not any(s in txt.lower() for s in skip):
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé"]:
                    v = cell(lbl)
                    if v and len(v) > 8: objet = v; break
            if not objet: return None
            objet = ClassifierAgent.clean_objet(objet)
            acheteur = (cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub = ClassifierAgent.extract_date(cell("publication") or "")
            date_lim = ClassifierAgent.extract_date(cell("remise") or cell("limite") or "")
            mon_raw = cell("montant") or ""
            if not mon_raw:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: mon_raw = m.group(0)[:80]
            return {
                "id":               f"bdc_{tid}",
                "objet":            objet[:400],
                "acheteur":         acheteur[:200],
                "region":           ClassifierAgent.region(acheteur+" "+full[:400]),
                "domaine":          ClassifierAgent.secteur(objet+" "+full[:300]),
                "type_marche":      ClassifierAgent.type_marche(objet),
                "montant":          mon_raw[:80],
                "date_publication": date_pub, "date_limite": date_lim,
                "description":      full[:2000],
                "statut":           "annule" if "annulé" in full.lower() else ("expire" if ClassifierAgent.is_expired(date_lim) else "actif"),
                "url":              f"{cls.BASE}/show/{tid}",
                "source":           "marchespublics",
            }
        except Exception as e:
            logger.error(f"[parse #{tid}] {e}")
            return None

    @classmethod
    @classmethod
    def run(cls) -> list:
        """Scan séquentiel des IDs — contourne le JS du portail"""
        import random as rnd
        t_start = time.time()
        new_tenders: list = []
        SState.running = True
        SState.found = SState.saved = SState.errors = 0
        SState.started = datetime.now().strftime("%H:%M:%S")
        SState.current = SState.total = 0
        SLog.add("═══ ScraperAgent v6 (20260321_143549) — scan séquentiel marchespublics ═══")

        db = get_db()
        known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
        db.close()

        # Trouver le plus grand ID bdc_XXXXX connu
        max_id = 310000
        for k in known:
            if k.startswith("bdc_"):
                try:
                    n = int(k[4:])
                    if n > max_id: max_id = n
                except: pass

        # Scan 50 en arrière + 300 en avant depuis max connu
        start_id = max(310000, max_id - 50)
        end_id   = max_id + 300
        scan_ids = [str(i) for i in range(start_id, end_id + 1)
                    if f"bdc_{i}" not in known]

        SState.total = len(scan_ids)
        SLog.add(f"Max connu: #{max_id} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

        s = cls._session()
        consec_errors = 0

        for idx, tid in enumerate(scan_ids):
            SState.current = idx + 1
            try:
                r = s.get(f"{cls.BASE}/show/{tid}", timeout=15)
                if r.status_code != 200 or len(r.text) < 2000:
                    consec_errors += 1
                    if consec_errors > 30 and SState.saved == 0:
                        SLog.add(f"Trop d'erreurs ({consec_errors}), arrêt")
                        break
                    continue
                consec_errors = 0
                SState.found += 1
                t = cls._parse(r.text, tid)
                if not t:
                    known.add(f"bdc_{tid}"); continue
                if t.get("statut") == "annule":
                    SLog.add(f"  ↳ annulé #{tid} — ignoré")
                    known.add(f"bdc_{tid}"); continue
                if cls._save(t):
                    SState.saved += 1
                    known.add(t["id"])
                    SLog.add(f"✓ #{tid} [{t.get('domaine','')[:18]}] {t.get('objet','')[:52]} [{t.get('statut','?')}]")
                    if t.get("statut") == "actif": new_tenders.append(t)
                else:
                    known.add(f"bdc_{tid}")
                time.sleep(rnd.uniform(0.5, 1.1))
            except Exception as e:
                SState.errors += 1; consec_errors += 1
                SLog.add(f"✗ #{tid}: {str(e)[:55]}")

        # Auto-expire tenders passés
        try:
            db = get_db()
            active = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
            expired = [r["id"] for r in active if ClassifierAgent.is_expired(r["date_limite"])]
            if expired:
                db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join('?'*len(expired))})", expired)
            db.commit(); db.close()
        except: pass

        duration = time.time() - t_start
        try:
            db = get_db()
            db.execute("INSERT INTO scrape_runs (source,found,saved,errors,duration_sec,started_at,finished_at) VALUES (?,?,?,?,?,?,?)",
                       ("marchespublics",SState.found,SState.saved,SState.errors,duration,SState.started,datetime.now().strftime("%H:%M:%S")))
            db.commit(); db.close()
        except: pass
        SState.running = False
        SLog.add(f"═══ Terminé en {duration:.0f}s | {SState.saved} sauvegardés | {SState.errors} erreurs ═══")
        counter("scrape_runs"); return new_tenders
        counter("scrape_runs"); return new_tenders

# ══════════════════════════════════════════════════════
# NOTIFICATION AGENT
# ══════════════════════════════════════════════════════
class NotifyAgent:
    @staticmethod
    def enqueue(member_id, channel, recipient, subject, body):
        try:
            db = get_db()
            db.execute("INSERT INTO notif_queue (member_id,channel,recipient,subject,body,status,created_at) VALUES (?,?,?,?,?,'pending',?)",
                       (member_id,channel,recipient,subject,body,now_str()))
            db.commit(); db.close()
        except Exception as e: logger.error(f"[enqueue] {e}")

    @staticmethod
    def get_pending() -> list:
        try:
            db = get_db()
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM notif_queue WHERE status='pending' AND attempts < 3 ORDER BY id LIMIT 20"
            ).fetchall()]
            db.close(); return rows
        except: return []

    @staticmethod
    def mark(nid: int, status: str, error: str=""):
        try:
            db = get_db()
            if status == "sent":
                db.execute("UPDATE notif_queue SET status='sent',sent_at=? WHERE id=?", (now_str(),nid))
            else:
                db.execute("UPDATE notif_queue SET status=?,attempts=attempts+1,error=? WHERE id=?",
                           (status,error[:200],nid))
            db.commit(); db.close()
        except: pass

    @staticmethod
    async def send_email(to, subject, html) -> tuple:
        # Method 1: Brevo API (HTTP, no SMTP, works on Railway)
        if BREVO_KEY:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post("https://api.brevo.com/v3/smtp/email",
                        headers={"api-key":BREVO_KEY,"Content-Type":"application/json"},
                        json={"sender":{"name":BRAND,"email":GMAIL_USER},
                              "to":[{"email":to}],"subject":subject,"htmlContent":html})
                    if r.status_code in [200,201,202]:
                        counter("emails_sent"); return True, ""
                    logger.error(f"[brevo] {r.status_code}: {r.text[:100]}")
            except Exception as e: logger.error(f"[brevo] {e}")
        # Method 2: Resend
        if RESEND_KEY:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post("https://api.resend.com/emails",
                        headers={"Authorization":f"Bearer {RESEND_KEY}","Content-Type":"application/json"},
                        json={"from":f"{BRAND} <onboarding@resend.dev>","to":[to],"subject":subject,"html":html})
                    if r.status_code in [200,201]:
                        counter("emails_sent"); return True, ""
            except Exception as e: logger.error(f"[resend] {e}")
        # Method 3: SMTP (blocked on Railway free)
        if GMAIL_PASS:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject; msg["From"] = f"{BRAND} <{GMAIL_USER}>"; msg["To"] = to
                msg.attach(MIMEText(html, "html", "utf-8"))
                def _smtp():
                    for host,port,ssl in [("smtp.gmail.com",465,True),("smtp.gmail.com",587,False)]:
                        try:
                            srv = smtplib.SMTP_SSL(host,port,timeout=20) if ssl else smtplib.SMTP(host,port,timeout=20)
                            if not ssl: srv.ehlo(); srv.starttls(); srv.ehlo()
                            srv.login(GMAIL_USER, GMAIL_PASS)
                            srv.sendmail(GMAIL_USER,[to],msg.as_string()); srv.quit(); return True,""
                        except smtplib.SMTPAuthenticationError: return False,"Gmail App Password requis"
                        except: continue
                    return False,"SMTP bloqué (Railway)"
                loop = asyncio.get_event_loop()
                ok, err = await loop.run_in_executor(None, _smtp)
                if ok: counter("emails_sent")
                return ok, err
            except Exception as e: return False, str(e)
        return False, "Aucune méthode email configurée"

    @staticmethod
    async def send_telegram(chat_id, text) -> tuple:
        try:
            import httpx
            MAX = 3800
            parts = [text[i:i+MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
            async with httpx.AsyncClient(timeout=15) as client:
                for part in parts:
                    r = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                        json={"chat_id":chat_id,"text":part,"parse_mode":"HTML","disable_web_page_preview":True}
                    )
                    data = r.json()
                    if not data.get("ok"):
                        return False, data.get("description","error")
                    await asyncio.sleep(0.3)
            counter("tg_sent"); return True, ""
        except Exception as e: return False, str(e)

    @staticmethod
    async def worker():
        logger.info("[NotifyAgent] Worker started")
        while True:
            try:
                for n in NotifyAgent.get_pending():
                    try:
                        if n["channel"] == "email":
                            ok, err = await NotifyAgent.send_email(n["recipient"],n["subject"],n["body"])
                        elif n["channel"] == "telegram":
                            ok, err = await NotifyAgent.send_telegram(n["recipient"],n["body"])
                        else:
                            ok, err = False, f"Unknown: {n['channel']}"
                        if ok:
                            NotifyAgent.mark(n["id"],"sent")
                            logger.info(f"[NotifyAgent] ✅ {n['channel']}→{n['recipient'][:20]}")
                        else:
                            status = "failed" if n["attempts"] >= 2 else "pending"
                            # Fast-fail SMTP network errors
                            if "Network is unreachable" in err or "SMTP bloqué" in err:
                                status = "failed"
                            NotifyAgent.mark(n["id"],status,err)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        NotifyAgent.mark(n["id"],"pending",str(e))
            except Exception as e:
                logger.error(f"[NotifyAgent:worker] {e}")
            await asyncio.sleep(5)

    @staticmethod
    def build_email(tenders: list, title: str) -> str:
        def card(t):
            mon = f'<tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">💰 Montant</td><td style="color:#c9a84c;font-size:11px;font-weight:700">{t.get("montant","")}</td></tr>' if t.get("montant") else ""
            src_label = {"marchespublics":"portail officiel","lematin":"Le Matin","equipement":"Min. Équipement"}.get(t.get("source",""),"") 
            return f"""<div style="border:1px solid #2a2a2a;border-radius:8px;padding:16px;margin-bottom:12px;background:#141414">
  {"<div style='font-size:9px;color:#666;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px'>"+src_label+"</div>" if src_label else ""}
  <div style="font-size:14px;font-weight:700;color:#f0ede6;margin-bottom:10px;line-height:1.35">{(t.get("objet") or "")[:100]}</div>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">🏢 Acheteur</td><td style="color:#aaa;font-size:11px">{(t.get("acheteur") or "—")[:60]}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">📍 Région</td><td style="color:#aaa;font-size:11px">{t.get("region","—")}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">🏷 Secteur</td><td style="color:#aaa;font-size:11px">{t.get("domaine","—")}</td></tr>
    {mon}
    <tr><td style="color:#888;font-size:11px;padding:3px 0">⏰ Limite</td><td style="color:#e87070;font-size:11px;font-weight:700">{t.get("date_limite","—")}</td></tr>
  </table>
  <a href="{t.get("url") or SITE_URL}" style="display:inline-block;margin-top:10px;padding:6px 14px;background:#c9a84c;color:#000;border-radius:5px;font-weight:700;text-decoration:none;font-size:12px">Voir le marché →</a>
</div>"""
        cards = "".join(card(t) for t in tenders[:12])
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#080808;font-family:Georgia,serif">
<div style="max-width:640px;margin:0 auto;background:#0d0d0d;border-radius:12px;padding:32px">
  <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:22px">
    <div style="font-size:20px;font-weight:700;color:#c9a84c">◆ Modern Business</div>
    <div style="font-size:11px;color:#555;margin-top:4px">{datetime.now().strftime("%d/%m/%Y à %H:%M")}</div>
  </div>
  <div style="font-size:17px;font-weight:700;color:#f0ede6;margin-bottom:6px">{title}</div>
  <div style="font-size:12px;color:#666;margin-bottom:22px">marchespublics.gov.ma + sources officielles</div>
  {cards}
  <div style="border-top:1px solid #222;padding-top:18px;margin-top:8px;text-align:center">
    <a href="{SITE_URL}" style="padding:10px 24px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px">Accéder à la plateforme →</a>
    <div style="font-size:10px;color:#333;margin-top:12px">Modern Business · <a href="{SITE_URL}/contact" style="color:#555">Se désinscrire</a></div>
  </div>
</div></body></html>"""

    @staticmethod
    def build_telegram(tenders: list, header: str) -> str:
        lines = [f"🏛 <b>{header}</b>\n{'━'*28}\n"]
        for t in tenders[:8]:
            b = f"📋 <b>{(t.get('objet') or '')[:65]}</b>\n"
            if t.get("acheteur"):    b += f"   🏢 {t['acheteur'][:45]}\n"
            if t.get("region"):      b += f"   📍 {t['region']}\n"
            if t.get("domaine"):     b += f"   🏷 {t['domaine'][:25]}\n"
            if t.get("montant"):     b += f"   💰 {t['montant']}\n"
            if t.get("date_limite"): b += f"   ⏰ <b>Limite: {t['date_limite']}</b>\n"
            if t.get("url"):         b += f"   🔗 {t['url']}\n"
            lines.append(b)
        lines.append(f"\n🌐 {SITE_URL}")
        return "\n\n".join(lines)

    @staticmethod
    def match_tenders(tenders, member_id, secteur=""):
        """
        Filtre les marchés selon les préférences du membre.
        Logique:
          1. Lit les filtres DB (secteur/region/keyword)
          2. Ajoute le secteur du profil membre comme fallback
          3. Si AUCUN filtre → envoie TOUT (membre sans préférences)
          4. Si filtres définis → envoie UNIQUEMENT les marchés correspondants
          5. Jamais de fallback "envoyer quand même" — zéro = zéro
        """
        # ── 1. Charger filtres DB ──
        try:
            db = get_db()
            rows = db.execute(
                "SELECT type,value FROM member_filters WHERE member_id=?", (member_id,)
            ).fetchall()
            db.close()
            filters = [dict(r) for r in rows]
        except:
            filters = []

        sect_f   = {r["value"] for r in filters if r["type"] == "secteur"}
        region_f = {r["value"] for r in filters if r["type"] == "region"}
        kw_f     = {r["value"].lower() for r in filters if r["type"] == "keyword"}

        # ── 2. Fallback: secteur du profil membre ──
        if not sect_f and secteur and secteur.strip():
            sect_f = {secteur.strip()}

        # ── 3. Aucun filtre → reçoit tout ──
        if not sect_f and not region_f and not kw_f:
            return tenders

        # ── 4. Filtrage strict ──
        matched = []
        for t in tenders:
            dom  = (t.get("domaine") or "").lower().strip()
            reg  = (t.get("region")  or "").lower().strip()
            obj  = (t.get("objet")   or "").lower()
            desc = (t.get("description") or "").lower()[:300]
            full = obj + " " + dom + " " + desc

            # Keyword match (OR logic — un seul suffit)
            if kw_f:
                if any(kw in full for kw in kw_f):
                    matched.append(t); continue

            # Region match
            if region_f:
                if any(rf.lower() in reg or reg in rf.lower() for rf in region_f):
                    matched.append(t); continue

            # Secteur match — comparaison précise par code T/P/S
            if sect_f:
                added = False
                for s in sect_f:
                    s_code = s[:4].upper()   # ex: "T101"
                    d_code = dom[:4].upper()  # ex: "t101" → "T101"

                    # Match exact du code
                    if s_code == d_code:
                        matched.append(t); added = True; break

                    # Match partiel: même lettre (T=T, P=P, S=S)
                    if s_code and d_code and s_code[0] == d_code[0]:
                        # Vérifier par mots-clés du secteur
                        if s in SECTEURS:
                            kws = SECTEURS[s]
                            if any(kw in full for kw in kws):
                                matched.append(t); added = True; break
                        # Sinon match sur le code complet
                        elif s_code in d_code or d_code in s_code:
                            matched.append(t); added = True; break

                    if added: break

        # ── 5. Retourner uniquement les matches — jamais de fallback ──
        return matched

    @staticmethod
    def notify_instant(tenders: list):
        if not tenders: return
        db = get_db()
        try:
            subs = [dict(r) for r in db.execute(
                "SELECT id,nom,email,telegram,secteur,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not subs: SLog.add("[NotifyAgent] Aucun abonné"); return
        eq = tq = skipped = 0
        n = len(tenders)
        for sub in subs:
            sect = sub.get("secteur","").strip()
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sect)

            if not matched:
                skipped += 1
                SLog.add(f"[NotifyAgent] {sub['nom']}: 0 match [{sect or 'aucun filtre défini'}]")
                continue

            sect_lbl = sect or "tous secteurs"
            nm = len(matched)
            SLog.add(f"[NotifyAgent] {sub['nom']} [{sect_lbl}]: {nm}/{n} marchés correspondants")

            subj = f"🏛 {nm} marché(s) [{sect_lbl}] — {datetime.now().strftime('%d/%m/%Y')} — Modern Business"
            email_html = NotifyAgent.build_email(matched, f"🏛 {nm} marché(s) — {sect_lbl}")
            tg_body    = NotifyAgent.build_telegram(matched, f"{nm} marché(s) [{sect_lbl}]")

            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,email_html)
                eq += 1
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",tg_body)
                tq += 1

        SLog.add(f"[NotifyAgent] {eq} emails + {tq} TG en file | {skipped} membres sans match")
        counter("notifications_queued")

    @staticmethod
    def notify_digest():
        db = get_db()
        try:
            yesterday = (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE date_extraction>=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC",
                (yesterday,)).fetchall()]
            subs = [dict(r) for r in db.execute(
                "SELECT id,email,telegram,secteur,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not tenders: logger.info("[NotifyAgent:digest] Aucun marché"); return
        ds = datetime.now().strftime("%d/%m/%Y")
        for sub in subs:
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sub.get("secteur",""))
            if not matched: continue
            n = len(matched)
            sl = sub.get("secteur") or "tous secteurs"
            subj = f"📋 Résumé {ds} — {n} marché(s) [{sl}] — Modern Business"
            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,NotifyAgent.build_email(matched,f"Résumé {ds} — {n} marché(s) [{sl}]"))
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",NotifyAgent.build_telegram(matched,f"Résumé {ds} — {n} marché(s) [{sl}]"))
        logger.info(f"[NotifyAgent:digest] {len(subs)} abonnés notifiés")

    @staticmethod
    def notify_weekly_digest():
        """Weekly top 10 easy-to-win tenders every Monday"""
        db = get_db()
        try:
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE statut='actif' AND ai_score>=70 "
                "ORDER BY ai_score DESC LIMIT 10"
            ).fetchall()]
            subs = [dict(r) for r in db.execute(
                "SELECT id,email,telegram,secteur,notif_email,notif_tg,plan FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not tenders: return
        week = datetime.now().strftime("Semaine du %d/%m/%Y")
        for sub in subs:
            # Only pro users get weekly digest
            if sub.get("plan","free") not in ["pro","enterprise"]: continue
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sub.get("secteur",""))
            if not matched: matched = tenders[:5]
            subj = f"📊 Top marchés semaine — {week} — Modern Business"
            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,
                    NotifyAgent.build_email(matched,f"🏆 Top {len(matched)} marchés faciles — {week}"))
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",
                    NotifyAgent.build_telegram(matched,f"Top {len(matched)} marchés — {week}"))
        logger.info(f"[NotifyAgent:weekly] Digest hebdo envoyé")

# ══════════════════════════════════════════════════════
# MONITOR AGENT
# ══════════════════════════════════════════════════════
class MonitorAgent:
    @staticmethod
    def log_error(agent, route, error):
        try:
            db = get_db()
            ex = db.execute("SELECT id FROM agent_errors WHERE agent=? AND route=? AND resolved=0",(agent,route)).fetchone()
            if ex: db.execute("UPDATE agent_errors SET count=count+1,last_seen=?,error=? WHERE id=?",(now_str(),error[:300],ex["id"]))
            else:  db.execute("INSERT INTO agent_errors (agent,route,error,count,first_seen,last_seen) VALUES (?,?,?,1,?,?)",(agent,route,error[:300],now_str(),now_str()))
            db.commit(); db.close()
        except: pass

    @staticmethod
    async def run():
        logger.info("[MonitorAgent] Started")
        while True:
            try:
                db = get_db()
                db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
                db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
                db.execute("UPDATE notif_queue SET status='pending',attempts=0 WHERE status='failed' AND created_at < datetime('now','-1 hour') AND attempts < 3")
                # Auto-expire tenders past deadline
                today_iso = datetime.now().strftime("%Y-%m-%d")
                today_date = datetime.now().date()
                # 1. Expire ISO format
                db.execute(
                    "UPDATE tenders SET statut='expire' WHERE statut='actif' "
                    "AND date_limite!='' AND date_limite NOT LIKE '%/%' "
                    "AND date_limite < date('now') AND date_limite NOT IN ('N/A','—','-')"
                )
                # 2. Expire DD/MM/YYYY format
                rows_ddmm = db.execute(
                    "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite LIKE '%/%'"
                ).fetchall()
                exp_ids = []
                for row in rows_ddmm:
                    dl = (row["date_limite"] or "").strip()
                    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
                        try:
                            if datetime.strptime(dl, fmt).date() < today_date:
                                exp_ids.append(row["id"])
                            break
                        except: pass
                if exp_ids:
                    ph = ",".join(["?"]*len(exp_ids))
                    db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp_ids)
                db.commit(); db.close()
            except Exception as e: logger.error(f"[MonitorAgent] {e}")
            await asyncio.sleep(3600)

    @staticmethod
    def get_stats() -> dict:
        db = get_db()
        try:
            return {
                "tenders_total":  db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
                "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
                "tenders_expire": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
                "easy_to_win":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score>=70").fetchone()[0],
                "members":        db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
                "members_tg":     db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0],
                "posts":          db.execute("SELECT COUNT(*) FROM posts WHERE status='actif'").fetchone()[0],
                "notif_pending":  db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0],
                "notif_sent":     db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0],
                "notif_failed":   db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0],
                "errors":         db.execute("SELECT COUNT(*) FROM agent_errors WHERE resolved=0").fetchone()[0],
            }
        finally: db.close()

# ══════════════════════════════════════════════════════
# CHAT AGENT
# ══════════════════════════════════════════════════════
CHAT_SYS = f"""Tu es l'assistant IA de {BRAND}, plateforme marocaine de veille marchés publics.
Aide les PME sur: procédures AO, Décret 2-22-431, CPS, CCAG, qualification BTP, codes T/P/S.
Réponds en français ou arabe. Max 300 mots sauf si complexe. Renvoie vers marchespublics.gov.ma.
Site: {SITE_URL}"""

class ChatAgent:
    @staticmethod
    async def respond(messages: list) -> str:
        if not ANTHROPIC_KEY:
            return f"🤖 Assistant IA non configuré.\n📞 Contactez-nous: {SITE_URL}/contact"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001","max_tokens":600,
                          "system":CHAT_SYS,"messages":messages[-12:]}
                )
                if r.status_code == 200:
                    return r.json()["content"][0]["text"]
                return f"Erreur API ({r.status_code}). Réessayez."
        except Exception as e:
            logger.error(f"[ChatAgent] {e}")
            return "Service temporairement indisponible."

# ══════════════════════════════════════════════════════
# SCHEDULERS
# ══════════════════════════════════════════════════════
LAST_SCRAPE = 0.0
RESET_TOKENS: dict = {}

async def scrape_scheduler():
    await asyncio.sleep(90)
    global LAST_SCRAPE
    while True:
        try:
            if time.time() - LAST_SCRAPE >= SCRAPE_HOURS * 3600:
                LAST_SCRAPE = time.time()
                loop = asyncio.get_event_loop()
                all_new = []
                # Official scraper
                official = await loop.run_in_executor(None, ScraperAgent.run)
                all_new.extend(official)
                # Multi-source
                if HAS_MULTI:
                    db = get_db()
                    try: known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
                    finally: db.close()
                    extra = [s for s in MULTI_SRC.keys() if s != "marchespublics"]
                    def run_multi(): return run_all_scrapers(known, extra, SLog.add)
                    multi = await loop.run_in_executor(None, run_multi)
                    if multi and ANTHROPIC_KEY:
                        multi = await AIClassifier.batch_classify(multi, ANTHROPIC_KEY, max_b=8)
                    saved = 0
                    for t in multi:
                        td = {"id":t.id,"objet":t.objet,"acheteur":t.acheteur,
                              "region":t.region,"domaine":t.domaine,"type_marche":t.type_marche,
                              "montant":t.montant,"date_publication":t.date_publication,
                              "date_limite":t.date_limite,"description":t.description,
                              "statut":t.statut,"url":t.source_url,"source":t.source,
                              "contact":t.contact,"budget_min":t.budget_min,"budget_max":t.budget_max,
                              "ai_score":t.ai_score,"ai_category":t.ai_category,"ai_reason":t.ai_reason}
                        if ScraperAgent._save(td):
                            saved += 1
                            if t.statut == "actif": all_new.append(td)
                    SLog.add(f"Multi-source: {saved}/{len(multi)} sauvegardés")
                if all_new: NotifyAgent.notify_instant(all_new)
        except Exception as e:
            SState.running = False; logger.error(f"[scheduler:scrape] {e}")
        await asyncio.sleep(600)

async def digest_scheduler():
    while True:
        now_ = datetime.now()
        next_ = now_.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_ >= next_: next_ += timedelta(days=1)
        await asyncio.sleep((next_ - now_).total_seconds())
        try: NotifyAgent.notify_digest()
        except Exception as e: logger.error(f"[scheduler:digest] {e}")

# ══════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app):
    for d in ["static","data","templates"]:
        os.makedirs(d, exist_ok=True)
    try: init_db()
    except Exception as e: logger.error(f"[init_db] {e}")
    asyncio.create_task(NotifyAgent.worker())
    asyncio.create_task(MonitorAgent.run())
    asyncio.create_task(scrape_scheduler())
    asyncio.create_task(digest_scheduler())
    logger.info(f"✅ {BRAND} v5.0 — All agents started")
    yield

app = FastAPI(lifespan=lifespan, title=BRAND, version="5.0", docs_url=None, redoc_url=None)
app.add_middleware(SecureMiddleware)

try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

try:
    os.makedirs("templates", exist_ok=True)
    tpl = Jinja2Templates(directory="templates")
except: tpl = None

def render(req: Request, tmpl: str, ctx: dict={}):
    if not tpl: return HTMLResponse("<h1>Template error</h1>", 500)
    try:
        return tpl.TemplateResponse(tmpl, {
            "request":      req,
            "BRAND":        BRAND,
            "SITE_URL":     SITE_URL,
            "SECTEURS_LIST":SECTEURS_LIST,
            "REGIONS_LIST": REGIONS_LIST,
            "member":       get_member(req),
            "now":          datetime.now(),
            "GA_ID":        GA_ID,
            "GSC_TOKEN":    GSC_TOKEN,
            "flash_msg": req.query_params.get("_flash",""),
            "flash_kind": req.query_params.get("_fk","ok"),
            **ctx
        })
    except Exception as e:
        MonitorAgent.log_error("render", tmpl, str(e))
        logger.error(f"[render:{tmpl}] {e}\n{traceback.format_exc()}")
        raise

# ══════════════════════════════════════════════════════
# ROUTES — PUBLIC
# ══════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders_total":  db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "easy_to_win":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score>=70").fetchone()[0],
            "members":        db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "members_tg":     db.execute("SELECT COUNT(*) FROM members WHERE telegram IS NOT NULL AND telegram!='' AND actif=1").fetchone()[0],
        }
        sources = [dict(r) for r in db.execute(
            "SELECT source, COUNT(*) as active FROM tenders WHERE statut='actif' GROUP BY source ORDER BY active DESC"
        ).fetchall()]
    finally: db.close()
    counter("pv:home")
    return render(req, "landing.html", {"stats":stats,"sources":sources})

# Plan limits

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, code_f="", region_f="", source_f="", type_f="", easy="", q="", page:int=1, sort:str="score"):
    m = get_member(req)
    # Tenders visibles uniquement pour membres Pro/Enterprise
    if not m:
        return render(req, "tenders_locked.html", {"reason": "login", "member": None,
            "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS})
    if m.get("plan","free") == "free":
        return render(req, "tenders_locked.html", {"reason": "upgrade", "member": m,
            "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS})
    per=20; off=(page-1)*per
    db = get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if code_f:    conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
        if region_f:  conds.append("region=?");       params.append(region_f)
        if source_f:  conds.append("source=?");        params.append(source_f)
        if type_f:    conds.append("type_marche=?");   params.append(type_f)
        if easy=="1": conds.append("ai_score >= 70")
        if q:
            conds.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
            params += [f"%{q[:80]}%"]*3
        w = " AND ".join(conds)
        total  = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
        rows   = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {w} ORDER BY " + ("date_extraction DESC" if sort=="date" else ("date_limite ASC" if sort=="deadline" else "ai_score DESC, date_extraction DESC")) + " LIMIT ? OFFSET ?",
            params+[per,off]).fetchall()]
        regions_list = [r[0] for r in db.execute("SELECT DISTINCT region FROM tenders WHERE region!='' ORDER BY region").fetchall()]
        sources_list = [r[0] for r in db.execute("SELECT DISTINCT source FROM tenders WHERE source!='' ORDER BY source").fetchall()]
    finally: db.close()
    counter("pv:tenders")
    return render(req,"tenders.html",{
        "tenders":rows,"total":total,"page":page,"pages":max(1,(total+per-1)//per),"sort":sort,
        "code_f":code_f,"region_f":region_f,"source_f":source_f,"type_f":type_f,
        "easy":easy,"q":q,"regions_list":regions_list,"sources_list":sources_list,
    })

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not row: raise HTTPException(404)
        t = dict(row)
        db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?",(tid,)); db.commit()
        related = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE domaine=? AND id!=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 5",
            (t["domaine"],tid)).fetchall()]
    finally: db.close()
    counter("pv:tender_detail")
    return render(req,"tender_detail.html",{"t":t,"related":related})

@app.get("/marketplace", response_class=HTMLResponse)
async def marketplace(req: Request, type_f="", secteur_f="", region_f="", q="", page:int=1):
    per=16; off=(page-1)*per
    db=get_db()
    try:
        conds=["p.status='actif'"]; params=[]
        if type_f:    conds.append("p.type=?");    params.append(type_f)
        if secteur_f: conds.append("p.secteur=?"); params.append(secteur_f)
        if region_f:  conds.append("p.region=?");  params.append(region_f)
        if q:
            conds.append("(p.titre LIKE ? OR p.description LIKE ?)")
            params+=[f"%{q[:80]}%"]*2
        w=" AND ".join(conds)
        total  = db.execute(f"SELECT COUNT(*) FROM posts p WHERE {w}",params).fetchone()[0]
        posts  = [dict(r) for r in db.execute(
            f"""SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,m.rating_count,m.verified
                FROM posts p JOIN members m ON m.id=p.member_id WHERE {w}
                ORDER BY p.id DESC LIMIT ? OFFSET ?""",
            params+[per,off]).fetchall()]
    finally: db.close()
    counter("pv:marketplace")
    return render(req,"marketplace.html",{
        "posts":posts,"total":total,"page":page,"pages":max(1,(total+per-1)//per),
        "type_f":type_f,"secteur_f":secteur_f,"region_f":region_f,"q":q,
    })

@app.get("/marketplace/new", response_class=HTMLResponse)
async def mp_new_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"marketplace_new.html",{"error":""})

@app.post("/marketplace/new")
async def mp_new_post(req: Request, titre:str=Form(""), description:str=Form(""),
    type_p:str=Form("offre"), secteur:str=Form(""), region:str=Form(""),
    budget:str=Form(""), contact:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    rl(req,"mp_new",5,3600)
    if len(titre.strip())<10: return render(req,"marketplace_new.html",{"error":"Titre trop court (min 10 chars)"})
    db=get_db()
    try:
        db.execute("INSERT INTO posts (member_id,type,titre,description,secteur,region,budget,contact,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (m["id"],type_p,titre.strip()[:200],description.strip()[:3000],secteur,region,budget.strip()[:60],contact.strip()[:100],now_str()))
        db.commit()
    finally: db.close()
    return RedirectResponse("/marketplace",302)

@app.get("/marketplace/post/{pid}", response_class=HTMLResponse)
async def mp_detail(req: Request, pid:int):
    db=get_db()
    try:
        row=db.execute("SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,m.rating_count,m.verified,m.phone,m.email as m_email FROM posts p JOIN members m ON m.id=p.member_id WHERE p.id=? AND p.status='actif'",(pid,)).fetchone()
        if not row: raise HTTPException(404)
        post=dict(row)
        db.execute("UPDATE posts SET views=COALESCE(views,0)+1 WHERE id=?",(pid,)); db.commit()
        ratings=[dict(r) for r in db.execute("SELECT r.*,m.nom as from_nom FROM ratings r JOIN members m ON m.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 10",(post["member_id"],)).fetchall()]
        cur=get_member(req)
        can_rate=cur and cur["id"]!=post["member_id"]
        already=cur and bool(db.execute("SELECT 1 FROM ratings WHERE from_id=? AND to_id=?",(cur["id"],post["member_id"])).fetchone())
    finally: db.close()
    return render(req,"marketplace_detail.html",{"post":post,"ratings":ratings,"can_rate":can_rate,"already_rated":already})

@app.post("/marketplace/rate/{mid}")
async def mp_rate(req: Request, mid:int, score:int=Form(5), comment:str=Form("")):
    cur=get_member(req)
    if not cur: return RedirectResponse("/login",302)
    if cur["id"]==mid: raise HTTPException(400)
    db=get_db()
    try:
        db.execute("INSERT OR IGNORE INTO ratings (from_id,to_id,score,comment,created_at) VALUES (?,?,?,?,?)",(cur["id"],mid,max(1,min(5,score)),comment.strip()[:300],now_str()))
        db.commit()
        avg=db.execute("SELECT AVG(score),COUNT(*) FROM ratings WHERE to_id=?",(mid,)).fetchone()
        db.execute("UPDATE members SET rating_avg=?,rating_count=? WHERE id=?",(round(avg[0],1),avg[1],mid))
        db.commit()
    finally: db.close()
    return RedirectResponse(req.headers.get("referer","/marketplace"),302)

@app.get("/annuaire", response_class=HTMLResponse)
async def annuaire(req: Request, secteur_f="", q=""):
    db=get_db()
    try:
        conds=["actif=1"]; params=[]
        if secteur_f: conds.append("secteur=?"); params.append(secteur_f)
        if q: conds.append("(nom LIKE ? OR entreprise LIKE ? OR ville LIKE ?)"); params+=[f"%{q}%"]*3
        members=[dict(r) for r in db.execute(f"SELECT * FROM members WHERE {' AND '.join(conds)} ORDER BY rating_avg DESC,id DESC LIMIT 60",params).fetchall()]
    finally: db.close()
    return render(req,"annuaire.html",{"members":members,"secteur_f":secteur_f,"q":q})

@app.get("/filters", response_class=HTMLResponse)
async def filters_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try: my_filters=[dict(r) for r in db.execute("SELECT * FROM member_filters WHERE member_id=? ORDER BY type,value",(m["id"],)).fetchall()]
    finally: db.close()
    return render(req,"filters.html",{"m":m,"my_filters":my_filters})

@app.post("/filters/add")
async def filters_add(req: Request, ftype:str=Form(""), value:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    if ftype in ["secteur","region","keyword"] and value.strip():
        db=get_db()
        try:
            db.execute("INSERT OR IGNORE INTO member_filters (member_id,type,value,created_at) VALUES (?,?,?,?)",(m["id"],ftype,value.strip()[:80],now_str()))
            db.commit()
        finally: db.close()
    return RedirectResponse("/filters",302)

@app.post("/filters/delete")
async def filters_delete(req: Request, fid:int=Form(0)):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try: db.execute("DELETE FROM member_filters WHERE id=? AND member_id=?",(fid,m["id"])); db.commit()
    finally: db.close()
    return RedirectResponse("/filters",302)

# ── AUTH ──
@app.get("/register", response_class=HTMLResponse)
async def reg_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{"error":""})

@app.post("/register")
async def reg_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    email:str=Form(""), phone:str=Form(""), secteur:str=Form(""),
    ville:str=Form(""), password:str=Form("")):
    rl(req,"register",8,3600)
    error=""
    if not all([nom,email,password]): error="Champs * obligatoires"
    elif len(password)<8: error="Mot de passe: minimum 8 caractères"
    elif not re.match(r'^[^@]+@[^@]+\.[^@]+$',email): error="Email invalide"
    else:
        db=get_db()
        try:
            if db.execute("SELECT 1 FROM members WHERE email=?",(email.lower(),)).fetchone():
                error="Email déjà utilisé"
            else:
                db.execute("INSERT INTO members (nom,entreprise,email,phone,secteur,ville,pw_hash,actif,notif_email,notif_tg,created_at) VALUES (?,?,?,?,?,?,?,1,1,1,?)",
                           (nom.strip(),entreprise.strip(),email.lower().strip(),phone.strip(),secteur,ville.strip(),hash_pw(password),now_str()))
                db.commit()
                uid=db.execute("SELECT id FROM members WHERE email=?",(email.lower(),)).fetchone()[0]
                db.close()
                counter("registrations")
                # Send verification email
                send_verify_email(uid, email, nom.strip())
                # Welcome email
                welcome_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:#080808;padding:20px">
<div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:28px;max-width:500px;margin:0 auto;border-radius:10px">
  <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
  <h2 style="margin-bottom:10px">Bienvenue, {nom}! 🎉</h2>
  <p style="color:#aaa;font-size:13px;margin-bottom:20px">Votre compte est activé. Recevez les marchés de votre secteur sur Telegram dès publication.</p>
  <a href="{SITE_URL}/dashboard" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Accéder →</a>
  <p style="color:#555;font-size:11px;margin-top:16px">Pour activer Telegram: envoyez /link {email.lower()} à @MarchesMarocBot</p>
</div></body></html>"""
                NotifyAgent.enqueue(uid,"email",email,f"Bienvenue sur {BRAND}!",welcome_html)
                resp=RedirectResponse("/dashboard",302)
                session_create(resp,uid); return resp
        except Exception as e: error=f"Erreur: {e}"
        finally:
            try: db.close()
            except: pass
    return render(req,"register.html",{"error":error})

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"login.html",{"error":"","reset":req.query_params.get("reset","")})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), password:str=Form("")):
    rl(req,f"login:{get_ip(req)}",5,300)
    db=get_db()
    try:
        row=db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
        if not row or not check_pw(password,dict(row).get("pw_hash","")):
            return render(req,"login.html",{"error":"Email ou mot de passe incorrect","reset":""})
        m=dict(row)
        db.execute("UPDATE members SET last_login=? WHERE id=?",(now_str(),m["id"])); db.commit()
    finally: db.close()
    counter("logins")
    resp=RedirectResponse("/dashboard",302)
    session_create(resp,m["id"]); return resp

@app.get("/logout")
async def logout():
    resp=RedirectResponse("/",302)
    session_delete(resp); return resp

@app.get("/forgot", response_class=HTMLResponse)
async def forgot_get(req: Request):
    return render(req,"forgot.html",{"sent":False,"error":""})

@app.post("/forgot")
async def forgot_post(req: Request, email:str=Form("")):
    rl(req,"forgot",3,3600)
    db=get_db()
    try: row=db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
    finally: db.close()
    if row:
        token=secrets.token_urlsafe(32)
        RESET_TOKENS[token]={"email":email.lower().strip(),"expires":datetime.now()+timedelta(hours=2)}
        reset_url=f"{SITE_URL}/reset?token={token}"
        NotifyAgent.enqueue(None,"email",email,f"Réinitialisation mot de passe — {BRAND}",
            f'<div style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:28px;border-radius:10px"><div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div><p>Cliquez pour réinitialiser votre mot de passe (valide 2h):</p><a href="{reset_url}" style="display:inline-block;margin-top:14px;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Réinitialiser →</a></div>')
        db=get_db()
        try:
            tg=db.execute("SELECT telegram FROM members WHERE email=?",(email.lower(),)).fetchone()
            if tg and tg["telegram"]:
                NotifyAgent.enqueue(None,"telegram",tg["telegram"],"",
                    f"🔑 <b>Réinitialisation mot de passe</b>\n\nLien (2h):\n{reset_url}")
        finally: db.close()
    return render(req,"forgot.html",{"sent":True,"error":""})

@app.get("/reset", response_class=HTMLResponse)
async def reset_get(req: Request, token:str=""):
    data=RESET_TOKENS.get(token)
    if not data or datetime.now()>data["expires"]:
        return render(req,"forgot.html",{"sent":False,"error":"Lien expiré ou invalide. Recommencez."})
    return render(req,"reset.html",{"token":token,"error":""})

@app.post("/reset")
async def reset_post(req: Request, token:str=Form(""), password:str=Form(""), password2:str=Form("")):
    data=RESET_TOKENS.get(token)
    if not data or datetime.now()>data["expires"]:
        return render(req,"forgot.html",{"sent":False,"error":"Lien expiré. Recommencez."})
    if len(password)<8: return render(req,"reset.html",{"token":token,"error":"Minimum 8 caractères"})
    if password!=password2: return render(req,"reset.html",{"token":token,"error":"Mots de passe différents"})
    db=get_db()
    try: db.execute("UPDATE members SET pw_hash=? WHERE email=?",(hash_pw(password),data["email"])); db.commit()
    finally: db.close()
    del RESET_TOKENS[token]
    return RedirectResponse("/login?reset=1",302)

# ── DASHBOARD ──
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try:
        my_posts=[dict(r) for r in db.execute("SELECT * FROM posts WHERE member_id=? ORDER BY id DESC LIMIT 5",(m["id"],)).fetchall()]
        my_ratings=[dict(r) for r in db.execute("SELECT r.*,mem.nom as from_nom FROM ratings r JOIN members mem ON mem.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 5",(m["id"],)).fetchall()]
        stats=MonitorAgent.get_stats()
    finally: db.close()
    counter("pv:dashboard")
    return render(req,"dashboard.html",{"m":m,"my_posts":my_posts,"my_ratings":my_ratings,"stats":stats})

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"settings.html",{"m":m,"success":"","error":""})

@app.post("/settings")
async def settings_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    phone:str=Form(""), secteur:str=Form(""), ville:str=Form(""),
    notif_email:str=Form(""), notif_tg:str=Form(""),
    password:str=Form(""), password_new:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    error=""
    db=get_db()
    try:
        db.execute("UPDATE members SET nom=?,entreprise=?,phone=?,secteur=?,ville=?,notif_email=?,notif_tg=? WHERE id=?",
                   (nom.strip() or m["nom"],entreprise.strip(),phone.strip(),secteur,ville.strip(),
                    1 if notif_email else 0,1 if notif_tg else 0,m["id"]))
        if password and password_new:
            if not check_pw(password,m.get("pw_hash","")): error="Mot de passe actuel incorrect"
            elif len(password_new)<8: error="Nouveau mot de passe trop court"
            else: db.execute("UPDATE members SET pw_hash=? WHERE id=?",(hash_pw(password_new),m["id"]))
        db.commit()
    finally: db.close()
    m=get_member(req)
    return render(req,"settings.html",{"m":m,"success":"Sauvegardé ✓" if not error else "","error":error})

@app.get("/contact", response_class=HTMLResponse)
async def contact(req: Request): return render(req,"contact.html",{})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(req: Request): return render(req,"privacy.html",{})

@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request):
    db = get_db()
    try:
        stats = MonitorAgent.get_stats()
    finally: db.close()
    return render(req, "tarifs.html", {"stats": stats})

@app.get("/a-propos", response_class=HTMLResponse)
async def a_propos(req: Request):
    return render(req, "a_propos.html", {})

@app.get("/conditions", response_class=HTMLResponse)
async def conditions(req: Request):
    return render(req, "conditions.html", {})

# ── EMAIL VERIFICATION ──
VERIFY_TOKENS: dict = {}  # token -> {uid, expires}

def send_verify_email(uid: int, email: str, nom: str):
    """Queue verification email"""
    token = secrets.token_urlsafe(32)
    VERIFY_TOKENS[token] = {"uid": uid, "expires": datetime.now() + timedelta(hours=24)}
    url = f"{SITE_URL}/verify?token={token}"
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:#080808;padding:20px">
<div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:28px;max-width:500px;margin:0 auto;border-radius:10px">
  <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
  <h2 style="margin-bottom:10px">Confirmez votre email</h2>
  <p style="color:#aaa;font-size:13px;margin-bottom:20px">Bonjour {nom}, cliquez pour activer votre compte:</p>
  <a href="{url}" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Activer mon compte →</a>
  <p style="color:#555;font-size:11px;margin-top:16px">Lien valide 24h. Ignorez si vous n'avez pas créé de compte.</p>
</div></body></html>"""
    NotifyAgent.enqueue(uid, "email", email, f"Activez votre compte {BRAND}", html)

@app.get("/verify", response_class=HTMLResponse)
async def verify_email(req: Request, token: str = ""):
    data = VERIFY_TOKENS.get(token)
    if not data or datetime.now() > data["expires"]:
        return render(req, "login.html", {"error": "Lien expiré. Connectez-vous pour en recevoir un nouveau.", "reset": ""})
    db = get_db()
    try:
        db.execute("UPDATE members SET verified=1 WHERE id=?", (data["uid"],))
        db.commit()
    finally: db.close()
    try: del VERIFY_TOKENS[token]
    except: pass
    return RedirectResponse("/dashboard?verified=1", 302)

@app.get("/resend-verify")
async def resend_verify(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    if m.get("verified"): return RedirectResponse("/dashboard", 302)
    send_verify_email(m["id"], m["email"], m["nom"])
    return RedirectResponse("/dashboard?verify_sent=1", 302)

# ── ADMIN PLAN MANAGEMENT ──
@app.get("/admin/set_plan")
async def admin_set_plan(pwd: str="", member_id: int=0, plan: str="free"):
    chk(pwd)
    db = get_db()
    try:
        db.execute("UPDATE members SET plan=?,verified=1 WHERE id=?", (plan, member_id))
        db.commit()
        row = db.execute("SELECT email,nom,telegram FROM members WHERE id=?", (member_id,)).fetchone()
    finally: db.close()
    if row and dict(row).get("telegram"):
        plan_names = {"free":"Gratuit","pro":"Pro 99 DH/mois","enterprise":"Entreprise"}
        asyncio.create_task(NotifyAgent.send_telegram(
            dict(row)["telegram"],
            f"🎉 <b>Votre abonnement a été activé!</b>\n\n"
            f"Plan: <b>{plan_names.get(plan, plan)}</b>\n"
            f"Accédez à votre espace: {SITE_URL}/dashboard"
        ))
    return JSONResponse({"ok": True, "plan": plan, "member_id": member_id})

# ══════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════
@app.post("/api/chat")
async def api_chat(req: Request):
    rl(req,f"chat:{get_ip(req)}",20,60)
    try:
        data=await req.json()
        user_msg=str(data.get("message",""))[:800].strip()
        sess=data.get("session_key",get_ip(req))[:50]
        if not user_msg: return JSONResponse({"error":"Message vide"},400)
        db=get_db()
        try:
            rows=db.execute("SELECT role,content FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 16",(sess,)).fetchall()
            history=[{"role":r["role"],"content":r["content"]} for r in reversed(rows)]
        finally: db.close()
        history.append({"role":"user","content":user_msg})
        response=await ChatAgent.respond(history)
        db=get_db()
        try:
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",(sess,"user",user_msg,ts))
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",(sess,"assistant",response,ts))
            db.execute("DELETE FROM chats WHERE session_key=? AND id NOT IN (SELECT id FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 40)",(sess,sess))
            db.commit()
        finally: db.close()
        counter("chat_messages")
        return JSONResponse({"response":response,"session_key":sess})
    except Exception as e:
        logger.error(f"[api:chat] {e}")
        return JSONResponse({"error":"Erreur serveur"},500)

@app.post("/api/consent")
async def api_consent(): return JSONResponse({"ok":True})

@app.get("/api/stats")
async def api_stats(): return JSONResponse(MonitorAgent.get_stats())

@app.get("/api/v1/tenders")
async def api_v1_tenders(req: Request, source:str="", code:str="", region:str="", type_m:str="",
    q:str="", min_score:int=0, easy:str="", page:int=1, per_page:int=20):
    per_page=min(per_page,100); off=(page-1)*per_page
    db=get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if source:     conds.append("source=?");        params.append(source)
        if code:       conds.append("domaine LIKE ?");  params.append(f"{code}%")
        if region:     conds.append("region LIKE ?");   params.append(f"%{region}%")
        if type_m:     conds.append("type_marche=?");   params.append(type_m)
        if min_score:  conds.append("ai_score >= ?");   params.append(min_score)
        if easy=="1":  conds.append("ai_score >= 70")
        if q:
            conds.append("(objet LIKE ? OR description LIKE ? OR acheteur LIKE ?)")
            params+=[f"%{q}%"]*3
        w=" AND ".join(conds)
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}",params).fetchone()[0]
        rows=[dict(r) for r in db.execute(
            f"SELECT id,objet,acheteur,region,domaine,type_marche,montant,date_limite,source,contact,ai_score,ai_category,ai_reason,url,date_extraction FROM tenders WHERE {w} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params+[per_page,off]).fetchall()]
    finally: db.close()
    return JSONResponse({"total":total,"page":page,"per_page":per_page,"pages":max(1,(total+per_page-1)//per_page),"tenders":rows})

@app.get("/api/v1/tenders/new")
async def api_v1_new(hours:int=24):
    db=get_db()
    try:
        since=(datetime.now()-timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        rows=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,source,ai_score,date_limite,url FROM tenders WHERE date_extraction>=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 50",(since,)).fetchall()]
    finally: db.close()
    return JSONResponse({"count":len(rows),"since_hours":hours,"tenders":rows})

@app.get("/api/v1/tenders/easy")
async def api_v1_easy(min_score:int=70, limit:int=20):
    db=get_db()
    try:
        rows=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,source,montant,ai_score,ai_reason,date_limite,url FROM tenders WHERE statut='actif' AND ai_score>=? ORDER BY ai_score DESC LIMIT ?",(min_score,limit)).fetchall()]
    finally: db.close()
    return JSONResponse({"count":len(rows),"min_score":min_score,"tenders":rows})

@app.get("/api/v1/tenders/{tid}")
async def api_v1_detail(tid:str):
    db=get_db()
    try:
        row=db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not row: raise HTTPException(404,"Not found")
        t=dict(row); db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return JSONResponse(t)

@app.get("/api/v1/sources")
async def api_v1_sources():
    db=get_db()
    try:
        rows=[dict(r) for r in db.execute("SELECT source,COUNT(*) as total,SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active,AVG(ai_score) as avg_score FROM tenders GROUP BY source ORDER BY total DESC").fetchall()]
    finally: db.close()
    return JSONResponse({"sources":rows,"multi_available":HAS_MULTI})

@app.get("/api/v1/stats")
async def api_v1_stats():
    s=MonitorAgent.get_stats()
    db=get_db()
    try:
        s["sources"]=[dict(r) for r in db.execute("SELECT source,COUNT(*) as total,SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active FROM tenders GROUP BY source ORDER BY total DESC").fetchall()]
        s["avg_score"]=round(db.execute("SELECT AVG(ai_score) FROM tenders WHERE statut='actif'").fetchone()[0] or 50,1)
    finally: db.close()
    return JSONResponse(s)

@app.get("/api/my_filters")
async def api_my_filters(req: Request):
    m=get_member(req)
    if not m: return JSONResponse({"error":"Non connecté"},401)
    db=get_db()
    try: filters=[dict(r) for r in db.execute("SELECT id,type,value FROM member_filters WHERE member_id=?",(m["id"],)).fetchall()]
    finally: db.close()
    return JSONResponse({"filters":filters})

# ══════════════════════════════════════════════════════
# TELEGRAM WEBHOOK
# ══════════════════════════════════════════════════════
@app.post("/telegram/webhook")
async def tg_webhook(req: Request):
    try:
        data=await req.json()
        msg=data.get("message") or data.get("edited_message") or {}
        if not msg: return {"ok":True}
        chat_id=str(msg.get("chat",{}).get("id",""))
        text=(msg.get("text") or "").strip()
        if not chat_id: return {"ok":True}
        async def reply(txt): await NotifyAgent.send_telegram(chat_id,txt)
        # /register shortcut
        if text.lower() in ["/register","/inscription"]:
            await reply(f"📝 Inscrivez-vous:\n{SITE_URL}/register\n\nEnsuite: /link votre@email.com")
            return {"ok":True}
        # /link email
        if text.lower().startswith("/link ") and "@" in text:
            email=text.split()[1].strip().lower()
            db=get_db()
            try:
                row=db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",(email,)).fetchone()
                if row:
                    db.execute("UPDATE members SET telegram=? WHERE id=?",(chat_id,row["id"])); db.commit()
                    await reply(f"✅ <b>Alertes activées, {row['nom']}!</b>\n\nVous recevrez les marchés de votre secteur.\n\n/secteur — Choisir votre secteur\n🌐 {SITE_URL}")
                else:
                    await reply(f"❌ Email non trouvé.\nInscrivez-vous: {SITE_URL}/register\nPuis: /link votre@email.com")
            finally: db.close()
            return {"ok":True}
        # /secteur
        if text.lower().startswith("/secteur"):
            parts=text.split(None,1)
            if len(parts)>1:
                new_s=parts[1].strip()
                db=get_db()
                try:
                    row=db.execute("SELECT id,nom FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                    if row:
                        matched=next((s for s in SECTEURS.keys() if new_s.lower() in s.lower() or s[:4].lower()==new_s[:4].lower()),None)
                        if matched:
                            db.execute("UPDATE members SET secteur=? WHERE id=?",(matched,row["id"])); db.commit()
                            await reply(f"✅ Secteur: <b>{matched}</b>\nVous recevrez uniquement ces marchés.")
                        else:
                            sl="\n".join(f"• {s}" for s in list(SECTEURS.keys())[:12])
                            await reply(f"Secteur non reconnu.\n\nExemples:\n{sl}\n\nEx: /secteur T101")
                    else:
                        await reply(f"Liez d'abord votre compte: /link votre@email.com")
                finally: db.close()
            else:
                db=get_db()
                try: row=db.execute("SELECT nom,secteur FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                finally: db.close()
                if row:
                    await reply(f"Votre secteur: <b>{dict(row).get('secteur') or 'Non défini'}</b>\n\nChanger: /secteur [code]\nEx: /secteur T101\n\nSecteurs:\n"+"\n".join(f"• {s}" for s in list(SECTEURS.keys())[:15]))
                else:
                    await reply(f"Liez d'abord: /link votre@email.com")
            return {"ok":True}
        if text in ["/start","start"]:
            db=get_db()
            try: row=db.execute("SELECT nom,secteur FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
            finally: db.close()
            if row:
                m2=dict(row)
                await reply(f"👋 Bonjour <b>{m2['nom']}</b>!\n\n✅ Compte lié\n🏷 Secteur: <b>{m2['secteur'] or 'Non défini'}</b>\n\n/secteur — Changer secteur\n/tenders — Derniers marchés\n/stats — Statistiques\n\n🌐 {SITE_URL}")
            else:
                await reply(f"🏛 <b>Modern Business</b>\nIntelligence des Marchés Publics Maroc\n\n📱 <b>2 étapes:</b>\n1️⃣ Inscrivez-vous: {SITE_URL}/register\n2️⃣ <code>/link votre@email.com</code>\n\n✅ Recevez les marchés de votre secteur!\n\n🌐 {SITE_URL}")
        elif text=="/tenders":
            db=get_db()
            try: rows=db.execute("SELECT objet,acheteur,region,domaine,date_limite,url FROM tenders WHERE statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 5").fetchall()
            finally: db.close()
            if rows:
                lines=[f"🏛 <b>5 derniers marchés actifs</b>\n{'━'*28}"]
                for r in rows:
                    b=f"\n📋 <b>{r['objet'][:60]}</b>"
                    if r['acheteur']: b+=f"\n   🏢 {r['acheteur'][:45]}"
                    if r['region']:   b+=f"\n   📍 {r['region']}"
                    if r['domaine']:  b+=f"\n   🏷 {r['domaine'][:25]}"
                    if r['date_limite']: b+=f"\n   ⏰ <b>{r['date_limite']}</b>"
                    if r['url']:      b+=f"\n   🔗 {r['url']}"
                    lines.append(b)
                lines.append(f"\n🌐 {SITE_URL}")
                await reply("\n".join(lines))
            else:
                await reply(f"Aucun marché actif.\n🌐 {SITE_URL}")
        elif text=="/stats":
            st=MonitorAgent.get_stats()
            await reply(f"📊 <b>Modern Business — Stats</b>\n\n✅ Actifs: <b>{st['tenders_active']}</b>\n🏆 Faciles: <b>{st['easy_to_win']}</b>\n📦 Total: <b>{st['tenders_total']}</b>\n🏢 Membres: <b>{st['members']}</b>\n🔔 Abonnés TG: <b>{st['members_tg']}</b>\n\n🌐 {SITE_URL}")
        elif text=="/help":
            await reply(f"ℹ️ <b>Modern Business — Aide</b>\n\n/start — Menu\n/link email — Activer alertes\n/secteur — Choisir secteur\n/tenders — Derniers marchés\n/stats — Statistiques\n\n📩 {SITE_URL}/contact")
        else:
            await reply(f"Envoyez /start pour le menu.\n🌐 {SITE_URL}")
    except Exception as e: logger.error(f"[tg:webhook] {e}")
    return {"ok":True}

# ══════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════
def chk(pwd:str, req=None):
    """Check admin auth: cookie session OR URL pwd"""
    if pwd == ADMIN_PASS: return True
    if req:
        cookie = req.cookies.get("admin_session","")
        if cookie == ADMIN_PASS: return True
    raise HTTPException(403, "Accès refusé")

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(req: Request):
    # If already authenticated via cookie, redirect
    session = req.cookies.get("admin_session","")
    if session == ADMIN_PASS:
        return RedirectResponse("/admin", 302)
    return HTMLResponse("""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Modern Business</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#030303;color:#f3eee7;font-family:'DM Sans',system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center}
.box{width:320px;padding:40px 32px;background:#0f0f0f;border:1px solid #222;border-radius:10px;
  box-shadow:0 16px 64px rgba(0,0,0,.8)}
.gem{width:24px;height:24px;background:linear-gradient(135deg,#e8c97a,#a07830);
  clip-path:polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%);margin:0 auto 16px}
h1{font-family:'Playfair Display',Georgia,serif;font-size:22px;font-weight:900;
  text-align:center;margin-bottom:4px;font-style:italic}
p{font-size:11px;color:#655f58;text-align:center;margin-bottom:28px}
label{display:block;font-size:9px;font-weight:700;color:#3c3730;text-transform:uppercase;
  letter-spacing:1.2px;margin-bottom:5px}
input{width:100%;padding:10px 14px;background:#151515;border:1px solid #2c2c2c;
  border-radius:4px;font-size:14px;color:#f3eee7;outline:none;margin-bottom:16px}
input:focus{border-color:#a07830;box-shadow:0 0 0 3px rgba(201,168,76,.07)}
button{width:100%;padding:11px;background:linear-gradient(135deg,#e8c97a,#a07830);
  color:#030303;font-weight:700;font-size:12px;letter-spacing:.07em;text-transform:uppercase;
  border:none;border-radius:4px;cursor:pointer;transition:.15s}
button:hover{filter:brightness(1.1)}
.err{background:rgba(158,74,74,.1);border:1px solid rgba(158,74,74,.2);border-radius:4px;
  padding:9px 13px;font-size:12px;color:#c46060;margin-bottom:14px;text-align:center}
</style></head><body>
<div class="box">
  <div class="gem"></div>
  <h1>Administration</h1>
  <p>Modern Business — Accès sécurisé</p>
  <div id="err" class="err" style="display:none">Mot de passe incorrect</div>
  <form method="post" action="/admin/login">
    <label>Mot de passe admin</label>
    <input type="password" name="pwd" placeholder="••••••••••" autofocus required>
    <button type="submit">Accéder →</button>
  </form>
</div>
<script>
const p=new URLSearchParams(location.search);
if(p.get('err'))document.getElementById('err').style.display='block';
</script>
</body></html>""")


@app.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    if pwd == ADMIN_PASS:
        resp = RedirectResponse("/admin", 302)
        resp.set_cookie("admin_session", ADMIN_PASS, max_age=86400*7,
                        httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/admin/login?err=1", 302)


@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/admin/login", 302)
    resp.delete_cookie("admin_session")
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin(req: Request, pwd:str=""):
    # Redirect to login if not authenticated
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login", 302)
    db=get_db()
    try:
        stats  =MonitorAgent.get_stats()
        tenders=[dict(r) for r in db.execute("SELECT * FROM tenders ORDER BY date_extraction DESC LIMIT 50").fetchall()]
        members=[dict(r) for r in db.execute("SELECT * FROM members ORDER BY id DESC LIMIT 20").fetchall()]
        hist   =[dict(r) for r in db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 8").fetchall()]
        errors =[dict(r) for r in db.execute("SELECT * FROM agent_errors WHERE resolved=0 ORDER BY last_seen DESC LIMIT 10").fetchall()]
        notifs =[dict(r) for r in db.execute("SELECT * FROM notif_queue ORDER BY id DESC LIMIT 30").fetchall()]
    finally: db.close()
    return render(req,"admin.html",{
        "stats":stats,"tenders":tenders,"members":members,
        "hist":hist,"errors":errors,"notifs":notifs,
        "scrape_state":SState,"scrape_log":SLog.last(80),"pwd":pwd,
        "multi_available":HAS_MULTI,
        "multi_sources":list(MULTI_SRC.keys()) if HAS_MULTI else [],
    })

@app.get("/admin/scrape")
async def admin_scrape(pwd:str="", sources:str="all"):
    chk(pwd)
    if SState.running: return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    src_list=None if sources=="all" else [s.strip() for s in sources.split(",") if s.strip()]
    async def _run():
        all_new=[]
        try:
            if src_list is None or "marchespublics" in src_list:
                loop=asyncio.get_event_loop()
                new=await loop.run_in_executor(None, ScraperAgent.run)
                all_new.extend(new)
            if HAS_MULTI:
                extra=[s for s in (src_list or list(MULTI_SRC.keys())) if s!="marchespublics"]
                if extra:
                    db=get_db()
                    try: known=set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
                    finally: db.close()
                    def run_m(): return run_all_scrapers(known,extra,SLog.add)
                    loop=asyncio.get_event_loop()
                    multi=await loop.run_in_executor(None,run_m)
                    if multi and ANTHROPIC_KEY:
                        multi=await AIClassifier.batch_classify(multi,ANTHROPIC_KEY,max_b=8)
                    saved=0
                    for t in multi:
                        td={"id":t.id,"objet":t.objet,"acheteur":t.acheteur,"region":t.region,"domaine":t.domaine,"type_marche":t.type_marche,"montant":t.montant,"date_publication":t.date_publication,"date_limite":t.date_limite,"description":t.description,"statut":t.statut,"url":t.source_url,"source":t.source,"contact":t.contact,"budget_min":t.budget_min,"budget_max":t.budget_max,"ai_score":t.ai_score,"ai_category":t.ai_category,"ai_reason":t.ai_reason}
                        if ScraperAgent._save(td): saved+=1; all_new.append(td) if t.statut=="actif" else None
                    SLog.add(f"Multi-source: {saved}/{len(multi)} sauvegardés")
            if all_new: NotifyAgent.notify_instant(all_new)
        finally: SState.running=False
    asyncio.create_task(_run())
    return JSONResponse({"ok":True,"msg":f"Scraper démarré — {sources}","multi":HAS_MULTI})

@app.get("/admin/scrape_stream")
async def scrape_stream(pwd:str=""):
    chk(pwd)
    async def gen():
        last=0
        while True:
            logs=SLog.entries[last:]
            for log in logs:
                state={"running":SState.running,"found":SState.found,"saved":SState.saved,"errors":SState.errors,"current":SState.current,"total":SState.total}
                yield f"data: {json.dumps({'log':log,'state':state})}\n\n"
            last=len(SLog.entries)
            if not SState.running and last>0:
                yield f"data: {json.dumps({'done':True,'state':{'saved':SState.saved}})}\n\n"; break
            await asyncio.sleep(0.7)
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/admin/test_notify")
async def admin_test(pwd:str="", chat_id:str=""):
    chk(pwd)
    sample=[
        {"objet":"Fourniture matériel informatique — 20 PC HP EliteDesk","acheteur":"Commune Urbaine de Rabat","region":"Rabat-Salé-Kénitra","domaine":"P818 - Informatique","type_marche":"Fournitures","montant":"280 000 DH","date_publication":datetime.now().strftime("%d/%m/%Y"),"date_limite":(datetime.now()+timedelta(days=14)).strftime("%d/%m/%Y"),"url":"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/46205","source":"marchespublics","ai_score":78},
        {"objet":"Travaux entretien voiries — Lot 3 Sud","acheteur":"Ministère de l'Intérieur","region":"Casablanca-Settat","domaine":"T301 - Travaux Routiers","type_marche":"Travaux","montant":"1 200 000 DH","date_publication":datetime.now().strftime("%d/%m/%Y"),"date_limite":(datetime.now()+timedelta(days=21)).strftime("%d/%m/%Y"),"url":"https://www.marchespublics.gov.ma/","source":"marchespublics","ai_score":55},
    ]
    results={}
    html=NotifyAgent.build_email(sample,"🧪 TEST Modern Business Notification Agent")
    ok,err=await NotifyAgent.send_email(GMAIL_USER,"🧪 TEST — Modern Business",html)
    results["email"]=f"✅ envoyé" if ok else f"❌ {err[:100]}"
    if chat_id:
        tg=NotifyAgent.build_telegram(sample,"🧪 TEST Modern Business Notification Agent")
        ok,err=await NotifyAgent.send_telegram(chat_id,tg)
        results["telegram"]=f"✅ envoyé" if ok else f"❌ {err[:80]}"
    db=get_db()
    try:
        results["queue"]={"pending":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0],"sent":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0],"failed":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0]}
        results["members"]={"total":db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],"with_tg":db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0]}
    finally: db.close()
    return JSONResponse({"ok":True,"results":results})


@app.get("/admin/set_telegram")
async def admin_set_tg(pwd:str="", email:str="", chat_id:str=""):
    chk(pwd)
    db=get_db()
    try:
        db.execute("UPDATE members SET telegram=? WHERE email=?",(chat_id,email.lower().strip())); db.commit()
        ch=db.execute("SELECT changes()").fetchone()[0]
    finally: db.close()
    if ch and chat_id:
        asyncio.create_task(NotifyAgent.send_telegram(chat_id,f"✅ <b>Alertes Telegram activées!</b>\n\nCompte lié: {email}\n🌐 {SITE_URL}"))
    return JSONResponse({"ok":bool(ch),"updated":ch})

@app.get("/admin/activate")
async def admin_activate(pwd:str="", member_id:int=0, plan:str="pro"):
    chk(pwd); db=get_db()
    try: db.execute("UPDATE members SET plan=?,verified=1 WHERE id=?",(plan,member_id)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/delete_tender")
async def admin_del(pwd:str="", tid:str=""):
    chk(pwd); db=get_db()
    try: db.execute("DELETE FROM tenders WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})


@app.get("/admin/expire_now")
async def admin_expire_now(request: Request, pwd: str = ""):
    if pwd != ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    db = get_db()
    try:
        from datetime import date, datetime as _dt
        today = date.today()
        rows = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
        exp = []
        for r in rows:
            dl = (r["date_limite"] or "").strip()
            if not dl or dl in ("N/A","—","-","null"): continue
            for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%d.%m.%Y"):
                try:
                    if _dt.strptime(dl, fmt).date() < today:
                        exp.append(r["id"]); break
                except: pass
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({chr(44).join([chr(63)]*len(exp))})", exp)
        db.execute("UPDATE tenders SET statut='expire' WHERE statut='actif' AND date_limite NOT LIKE '%/%' AND date_limite < date('now') AND date_limite!='' AND date_limite!='N/A'")
        db.commit()
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        db.close()
        return JSONResponse({"ok":True,"expired_python":len(exp),"active_remaining":active})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error":str(e)},500)

@app.get("/admin/cleanup")
async def admin_cleanup(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        db.execute("DELETE FROM tenders WHERE statut IN ('expire','annule') AND date_extraction < date('now','-60 days')")
        db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
        db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
        db.execute("DELETE FROM tenders WHERE length(objet) < 10")
        r=db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"remaining":r})

@app.get("/admin/cleanup_tenders")
async def admin_cleanup_tenders(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        bad=["Liste des avis d'achat","ConsultationsRésultats","Accueil","Se connecter"]
        deleted=0
        for p in bad:
            db.execute("DELETE FROM tenders WHERE objet LIKE ?",(f"%{p}%",))
            deleted+=db.execute("SELECT changes()").fetchone()[0]
        db.execute("DELETE FROM tenders WHERE length(objet) < 10")
        deleted+=db.execute("SELECT changes()").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"deleted":deleted})

@app.get("/admin/resolve_error")
async def admin_resolve(pwd:str="", eid:int=0):
    chk(pwd); db=get_db()
    try: db.execute("UPDATE agent_errors SET resolved=1 WHERE id=?",(eid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/notify_status")
async def admin_notify_status(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        members=[dict(r) for r in db.execute("SELECT id,nom,email,telegram,notif_email,notif_tg,secteur FROM members WHERE actif=1").fetchall()]
        queue  =[dict(r) for r in db.execute("SELECT channel,status,recipient,error,attempts,created_at FROM notif_queue ORDER BY id DESC LIMIT 20").fetchall()]
    finally: db.close()
    return JSONResponse({
        "brevo":      "✅" if BREVO_KEY else "❌ non configuré (recommandé)",
        "resend":     "✅" if RESEND_KEY else "❌",
        "gmail":      "✅" if GMAIL_PASS else "❌",
        "telegram":   "✅" if TELEGRAM_BOT else "❌",
        "anthropic":  "✅" if ANTHROPIC_KEY else "❌",
        "members":    [{"nom":m["nom"],"email":m["email"],"telegram":m["telegram"] or "❌","secteur":m["secteur"] or "—","notif_email":bool(m["notif_email"]),"notif_tg":bool(m["notif_tg"])} for m in members],
        "queue_last": queue,
    })

@app.get("/admin/test_digest")
async def admin_test_digest(pwd:str=""):
    chk(pwd); NotifyAgent.notify_digest()
    return JSONResponse({"ok":True,"msg":"Digest mis en file"})

# ══════════════════════════════════════════════════════
# INFRA
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# ROUTES ARABES /ar/*
# ══════════════════════════════════════════════════════

@app.get("/ar")
@app.get("/ar/")
async def ar_home(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders_total":  db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "easy_to_win":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score>=70").fetchone()[0],
            "members":        db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "members_tg":     db.execute("SELECT COUNT(*) FROM members WHERE telegram IS NOT NULL AND telegram!=''").fetchone()[0],
        }
        tenders = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 6"
        ).fetchall()]
        sources = [dict(r) for r in db.execute(
            "SELECT source, COUNT(*) as active FROM tenders WHERE statut='actif' GROUP BY source ORDER BY active DESC"
        ).fetchall()]
    finally:
        db.close()
    return render(req, "landing_ar.html", {
         "stats": stats, "tenders": tenders,
        "sources": sources, "member": get_member(req),
        "SECTEURS_LIST": SECTEURS_LIST,
    })


@app.get("/ar/tenders")
async def ar_tenders(req: Request, q: str = "", code_f: str = "", easy: str = "",
                     region: str = "", page: int = 1):
    db = get_db(); per = 18
    conds = ["statut='actif'"]; params: list = []
    if q:
        conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    if code_f:
        conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
    if easy == "1":
        conds.append("ai_score >= 70")
    where = " AND ".join(conds)
    try:
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {where}", params).fetchone()[0]
        tenders = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {where} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params + [per, (page-1)*per]
        ).fetchall()]
    finally:
        db.close()
    return render(req, "tenders_ar.html", {
         "tenders": tenders, "total": total,
        "page": page, "pages": max(1, (total+per-1)//per),
        "q": q, "code_f": code_f, "easy": easy,
        "member": get_member(req), "SECTEURS_LIST": SECTEURS_LIST,
    })


@app.get("/ar/register")
async def ar_register_get(req: Request):
    if get_member(req):
        return RedirectResponse("/dashboard", 302)
    return render(req, "register_ar.html", {
         "error": None,
        "member": None, "SECTEURS_LIST": SECTEURS_LIST,
    })


@app.post("/ar/register")
async def ar_register_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    email:str=Form(""), phone:str=Form(""), secteur:str=Form(""),
    ville:str=Form(""), password:str=Form("")):
    return await reg_post(req, nom, entreprise, email, phone, secteur, ville, password)


@app.get("/ar/login")
async def ar_login_get(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        }
    finally:
        db.close()
    return render(req, "login.html", {
         "error": None, "reset": False,
        "member": None, "stats": stats,
    })



@app.post("/api/v1/ingest")
async def api_ingest(req: Request):
    """Reçoit les marchés du scraper local (IP Maroc) et les sauvegarde"""
    try:
        body = await req.json()
        if body.get("pwd") != ADMIN_PASS:
            return JSONResponse({"error":"unauthorized"}, 401)
        tenders = body.get("tenders", [])
        if not tenders:
            return JSONResponse({"ok":True,"saved":0})
        db = get_db(); saved = 0
        for t in tenders:
            if not t.get("id") or not t.get("objet"): continue
            # Skip already expired tenders
            dl = str(t.get("date_limite","")).strip()
            if dl and ClassifierAgent.is_expired(dl): continue
            # Classify with AI
            domaine = ClassifierAgent.secteur((t.get("objet","") + " " + t.get("description",""))[:300])
            region  = ClassifierAgent.region((t.get("acheteur","") + " " + t.get("objet",""))[:300])
            score   = 50
            try:
                changed = db.execute("""INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,region,domaine,type_marche,montant,
                     date_publication,date_limite,description,statut,url,source,
                     ai_score,date_extraction)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    str(t.get("id",""))[:80],
                    str(t.get("objet",""))[:400],
                    str(t.get("acheteur",""))[:200],
                    str(region or t.get("region","Maroc"))[:100],
                    str(domaine or t.get("domaine",""))[:80],
                    str(ClassifierAgent.type_marche(t.get("objet","")))[:40],
                    str(t.get("montant",""))[:80],
                    datetime.now().strftime("%d/%m/%Y"),
                    str(t.get("date_limite",""))[:20],
                    str(t.get("description",""))[:2000],
                    str(t.get("statut","actif")),
                    str(t.get("source_url",""))[:400],
                    str(t.get("source","local"))[:40],
                    score,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                )).rowcount
                if changed: saved += 1
            except Exception as e:
                logger.error(f"[ingest] {e}")
        db.commit(); db.close()
        SLog.add(f"[Ingest] +{saved}/{len(tenders)} depuis scraper local")
        return JSONResponse({"ok":True,"saved":saved,"total":len(tenders)})
    except Exception as e:
        return JSONResponse({"error":str(e)},500)



# ═══════════════════════════════════════════════════
# EXPORT CSV
# ═══════════════════════════════════════════════════
@app.get("/tenders/export")
async def export_csv(req: Request, q:str="", code_f:str="", region:str="", easy:str=""):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)
    db = get_db()
    conds = ["statut='actif'"]; params = []
    if q:
        conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%",f"%{q}%"]
    if code_f:
        conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
    if region:
        conds.append("region LIKE ?"); params.append(f"%{region}%")
    if easy == "1":
        conds.append("ai_score >= 70")
    where = " AND ".join(conds)
    rows = db.execute(
        f"SELECT objet,acheteur,region,domaine,montant,date_publication,date_limite,source,ai_score,url FROM tenders WHERE {where} ORDER BY ai_score DESC LIMIT 2000",
        params
    ).fetchall()
    db.close()
    import io, csv as csv_mod
    buf = io.StringIO()
    w = csv_mod.writer(buf)
    w.writerow(["Objet","Acheteur","Région","Domaine","Montant","Publication","Limite","Source","Score","URL"])
    for r in rows:
        w.writerow([r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9]])
    buf.seek(0)
    from fastapi.responses import StreamingResponse
    fname = f"marches_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter(['﻿' + buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )


# ═══════════════════════════════════════════════════
# FAVORIS
# ═══════════════════════════════════════════════════
@app.post("/tenders/{tid}/fav")
async def toggle_fav(req: Request, tid: str):
    m = get_member(req)
    if not m:
        return JSONResponse({"error": "login required"}, 401)
    db = get_db()
    try:
        ex = db.execute(
            "SELECT id FROM favoris WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone()
        if ex:
            db.execute("DELETE FROM favoris WHERE member_id=? AND tender_id=?", (m["id"], tid))
            db.commit(); db.close()
            return JSONResponse({"fav": False})
        db.execute(
            "INSERT OR IGNORE INTO favoris(member_id,tender_id,created_at) VALUES(?,?,?)",
            (m["id"], tid, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        db.commit(); db.close()
        return JSONResponse({"fav": True})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error": str(e)}, 500)


@app.get("/favoris", response_class=HTMLResponse)
async def favoris_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login?next=/favoris", 302)
    db = get_db()
    try:
        fav_rows = db.execute(
            "SELECT tender_id FROM favoris WHERE member_id=? ORDER BY created_at DESC",
            (m["id"],)
        ).fetchall()
        fav_ids = [r["tender_id"] for r in fav_rows]
        tenders = []
        if fav_ids:
            ph = ",".join(["?"]*len(fav_ids))
            tenders = [dict(r) for r in db.execute(
                f"SELECT * FROM tenders WHERE id IN ({ph}) ORDER BY ai_score DESC",
                fav_ids
            ).fetchall()]
    finally:
        db.close()
    return render(req, "tenders.html", {
        "tenders": tenders, "total": len(tenders), "page": 1, "pages": 1,
        "q": "", "code_f": "", "region": "", "easy": "", "source_f": "",
        "member": m, "page_title": "★ Mes Favoris",
        "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS,
    })


# ═══════════════════════════════════════════════════
# CONTACT POST
# ═══════════════════════════════════════════════════
@app.post("/contact", response_class=HTMLResponse)
async def contact_post_handler(req: Request, nom:str=Form(""), email:str=Form(""),
                                sujet:str=Form(""), message:str=Form("")):
    m = get_member(req)
    if not nom or not email or not message:
        return render(req, "contact.html", {"error": "Tous les champs sont requis", "member": m})
    try:
        if TELEGRAM_BOT and ADMIN_CHAT_ID:
            import requests as _r
            _r.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID,
                      "text": f"📩 Contact\n<b>{nom}</b> ({email})\n<b>{sujet}</b>\n{message[:500]}",
                      "parse_mode": "HTML"},
                timeout=5
            )
    except Exception as e:
        logger.error(f"[contact] {e}")
    return render(req, "contact.html", {"ok": "Message envoyé. Réponse sous 24h ✓", "member": m})


# ═══════════════════════════════════════════════════
# BACKUP DB
# ═══════════════════════════════════════════════════
@app.get("/admin/backup")
async def admin_backup(req: Request, pwd: str = ""):
    cookie = req.cookies.get("admin_session", "")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login", 302)
    import shutil
    bp = DB_PATH.replace(".db", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
    shutil.copy2(DB_PATH, bp)
    from fastapi.responses import FileResponse
    return FileResponse(bp, filename=os.path.basename(bp), media_type="application/octet-stream")



# ══════════════════════════════════════════════════════
# ROUTES ARABES /ar/*
# ══════════════════════════════════════════════════════

@app.get("/health")
async def health():
    db=get_db()
    try: active=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    finally: db.close()
    return JSONResponse({"status":"ok","version":"5.0","brand":BRAND,"active_tenders":active,
        "agents":["ScraperAgent","ClassifierAgent","NotifyAgent","MonitorAgent","ChatAgent"],
        "multi_source":HAS_MULTI})

@app.get("/metrics")
async def metrics(pwd:str=""):
    if pwd!=ADMIN_PASS: raise HTTPException(403)
    return JSONResponse({"counters":dict(COUNTERS),"scraper":{"running":SState.running,"saved":SState.saved}})

@app.get("/sitemap.xml")
async def sitemap():
    xml=f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
<url><loc>{SITE_URL}/tenders</loc><changefreq>hourly</changefreq><priority>0.95</priority></url>
<url><loc>{SITE_URL}/marketplace</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>
<url><loc>{SITE_URL}/annuaire</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
<url><loc>{SITE_URL}/contact</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
<url><loc>{SITE_URL}/ar</loc><changefreq>daily</changefreq><priority>0.9</priority></url>
  <url><loc>{SITE_URL}/ar/tenders</loc><changefreq>hourly</changefreq><priority>0.8</priority></url>
  <url><loc>{SITE_URL}/tarifs</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
<url><loc>{SITE_URL}/a-propos</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
<url><loc>{SITE_URL}/conditions</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>
</urlset>"""
    return Response(xml,media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml",media_type="text/plain")