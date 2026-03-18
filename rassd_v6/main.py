"""
Modern Business v3.0 — Platform Intelligence Marchés Publics Maroc
══════════════════════════════════════════════════════════════════
Architecture: FastAPI + SQLite WAL + AI Agents
Agents:
  - ScraperAgent   : Extraction marchespublics.gov.ma
  - ClassifierAgent: Classification secteur/région (keyword scoring)
  - NotifyAgent    : Email SMTP + Telegram Bot (queue-based)
  - MonitorAgent   : Auto-heal + error detection
  - ChatAgent      : Claude AI assistant
══════════════════════════════════════════════════════════════════
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

# Multi-source scraper
try:
    from multi_scraper import run_all_scrapers, AIClassifier, Tender as MultiTender, SCRAPERS as MULTI_SCRAPERS
    HAS_MULTI = True
except ImportError:
    HAS_MULTI = False

from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

try: from itsdangerous import URLSafeTimedSerializer; HAS_ITS = True
except: HAS_ITS = False
try: import urllib3; urllib3.disable_warnings()
except: pass

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
TELEGRAM_BOT = os.getenv("TELEGRAM_BOT","7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ANTHROPIC_KEY= os.getenv("ANTHROPIC_API_KEY", "")
GA_ID        = os.getenv("GA_ID",           "")   # Google Analytics
GSC_TOKEN    = os.getenv("GSC_TOKEN",        "")   # Search Console
TWILIO_SID   = os.getenv("TWILIO_SID",       "")   # Twilio Account SID
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN",     "")   # Twilio Auth Token
TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP",  "")   # whatsapp:+14155238886
MULTI_SCRAPE = os.getenv("MULTI_SCRAPE",     "true").lower() == "true"   # Google Analytics
GSC_TOKEN    = os.getenv("GSC_TOKEN",        "")   # Search Console verify
RESEND_KEY   = os.getenv("RESEND_API_KEY",  "")
SCRAPE_HOURS   = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "noreply@modern-business.ma")

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("mb3")

COUNTERS: dict = defaultdict(int)
def counter(k): COUNTERS[k] += 1

# ══════════════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════════════
_rl: dict = defaultdict(list)
_rl_lock  = threading.Lock()

def rate_limit(ip: str, key: str, max_c=60, win=60) -> bool:
    k = f"{ip}:{key}"; now = time.time()
    with _rl_lock:
        calls = [t for t in _rl[k] if now - t < win]
        if len(calls) >= max_c: return False
        calls.append(now); _rl[k] = calls
    return True

def get_ip(r: Request) -> str:
    fwd = r.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "127.0.0.1")

def rl(req: Request, key: str, max_c=60, win=60):
    if not rate_limit(get_ip(req), key, max_c, win):
        raise HTTPException(429, "Trop de requêtes — réessayez plus tard")

# ══════════════════════════════════════════════════════
# SECURITY MIDDLEWARE
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
COOKIE_NAME = "mb3_sess"
COOKIE_TTL  = 86400 * 30

def session_create(resp: Response, uid: int):
    if HAS_ITS:
        s = URLSafeTimedSerializer(SECRET_KEY, salt="mb3v")
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
            s = URLSafeTimedSerializer(SECRET_KEY, salt="mb3v")
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
    -- Tenders from all sources
    CREATE TABLE IF NOT EXISTS tenders (
        id               TEXT PRIMARY KEY,
        objet            TEXT NOT NULL DEFAULT '',
        acheteur         TEXT DEFAULT '',
        region           TEXT DEFAULT '',
        domaine          TEXT DEFAULT '',
        type_marche      TEXT DEFAULT '',
        montant          TEXT DEFAULT '',
        date_publication TEXT DEFAULT '',
        date_limite      TEXT DEFAULT '',
        description      TEXT DEFAULT '',
        statut           TEXT DEFAULT 'actif',
        url              TEXT DEFAULT '',
        source           TEXT DEFAULT 'marchespublics.gov.ma',
        contact          TEXT DEFAULT '',
        ai_score         INTEGER DEFAULT 0,
        ai_label         TEXT DEFAULT '',
        ai_reasons       TEXT DEFAULT '',
        date_extraction  TEXT DEFAULT '',
        views            INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_domaine ON tenders(domaine);
    CREATE INDEX IF NOT EXISTS idx_t_region  ON tenders(region);
    CREATE INDEX IF NOT EXISTS idx_t_date    ON tenders(date_extraction DESC);

    -- Members
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
        notif_wa      INTEGER DEFAULT 1,
        whatsapp      TEXT DEFAULT '',
        created_at    TEXT DEFAULT '',
        last_login    TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_m_email ON members(email);

    -- Member notification filters
    CREATE TABLE IF NOT EXISTS member_filters (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id  INTEGER NOT NULL REFERENCES members(id),
        type       TEXT NOT NULL,  -- 'secteur' | 'region' | 'keyword'
        value      TEXT NOT NULL,
        created_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_mf_member ON member_filters(member_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mf_uniq ON member_filters(member_id,type,value);

    -- Marketplace
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
    CREATE INDEX IF NOT EXISTS idx_p_type   ON posts(type);

    -- Ratings
    CREATE TABLE IF NOT EXISTS ratings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id    INTEGER NOT NULL REFERENCES members(id),
        to_id      INTEGER NOT NULL REFERENCES members(id),
        score      INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
        comment    TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        UNIQUE(from_id, to_id)
    );

    -- Chat sessions
    CREATE TABLE IF NOT EXISTS chats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_key TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        created_at  TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_ch_session ON chats(session_key);
    CREATE INDEX IF NOT EXISTS idx_ch_date    ON chats(created_at);

    -- Notification queue (Agent-managed)
    CREATE TABLE IF NOT EXISTS notif_queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id   INTEGER REFERENCES members(id),
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

    -- Scrape runs history
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        found        INTEGER DEFAULT 0,
        saved        INTEGER DEFAULT 0,
        errors       INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0,
        started_at   TEXT DEFAULT '',
        finished_at  TEXT DEFAULT ''
    );

    -- Agent error log
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

    # Migrations for existing DBs
    migrations = [
        "ALTER TABLE members ADD COLUMN telegram TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN secteur TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN whatsapp TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_wa INTEGER DEFAULT 1",
        "ALTER TABLE members ADD COLUMN notif_email INTEGER DEFAULT 1",
        "ALTER TABLE members ADD COLUMN notif_tg INTEGER DEFAULT 1",
        "ALTER TABLE members ADD COLUMN rating_avg REAL DEFAULT 0",
        "ALTER TABLE members ADD COLUMN rating_count INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN type_marche TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN views INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics'",
        "ALTER TABLE tenders ADD COLUMN contact TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN budget_min REAL DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN budget_max REAL DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN ai_score INTEGER DEFAULT 50",
        "ALTER TABLE tenders ADD COLUMN ai_category TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN ai_reason TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics.gov.ma'",
        "ALTER TABLE tenders ADD COLUMN contact TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN ai_score INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN ai_label TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN ai_reasons TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try: db.execute(sql)
        except: pass

    # Migrate contractors (v2) → members (v3)
    try:
        existing = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        old_table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contractors'").fetchone()
        if old_table and existing == 0:
            db.execute("""INSERT OR IGNORE INTO members
                (id,nom,entreprise,email,phone,secteur,ville,pw_hash,
                 telegram,plan,actif,verified,rating_avg,rating_count,
                 notif_email,notif_tg,created_at,last_login)
                SELECT id,nom,
                    COALESCE(entreprise,''),
                    email,
                    COALESCE(phone,''),
                    COALESCE(secteur,''),
                    COALESCE(ville,''),
                    COALESCE(password_hash,''),
                    COALESCE(telegram,''),
                    COALESCE(plan,'free'),
                    COALESCE(actif,1),
                    COALESCE(verified,0),
                    COALESCE(rating_avg,0),
                    COALESCE(rating_count,0),
                    1,1,
                    COALESCE(created_at,''),
                    COALESCE(last_login,'')
                FROM contractors WHERE actif=1""")
            migrated = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
            logger.info(f"Migrated {migrated} members from contractors table")
        elif old_table and existing > 0:
            # Update telegram from contractors if missing in members
            try:
                db.execute("""UPDATE members SET telegram=c.telegram
                    FROM contractors c WHERE members.email=c.email
                    AND (members.telegram IS NULL OR members.telegram='')
                    AND c.telegram IS NOT NULL AND c.telegram!=''""")
            except: pass
    except Exception as e:
        logger.warning(f"Migration contractors->members: {e}")

    db.commit(); db.close()
    logger.info("DB initialized")

# Helpers
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
# CLASSIFICATION AGENT
# ══════════════════════════════════════════════════════
REGIONS = {
    "Rabat-Salé-Kénitra":         ["rabat","salé","sale","kénitra","kenitra","témara","témara","skhirat"],
    "Casablanca-Settat":          ["casablanca","settat","mohammedia","berrechid","benslimane","nouaceur"],
    "Marrakech-Safi":             ["marrakech","safi","essaouira","kelaa","youssoufia","chichaoua"],
    "Fès-Meknès":                 ["fès","fez","meknès","meknes","ifrane","taza","sefrou","boulemane"],
    "Tanger-Tétouan-Al Hoceima":  ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache","fahs-anjra"],
    "Oriental":                   ["oujda","nador","berkane","taourirt","jerada","figuig","driouch"],
    "Béni Mellal-Khénifra":      ["béni mellal","beni mellal","khénifra","azilal","fquih ben salah","khouribga"],
    "Souss-Massa":                ["agadir","tiznit","taroudant","inezgane","ait melloul","chtouka"],
    "Drâa-Tafilalet":             ["errachidia","ouarzazate","zagora","midelt","tinghir","boumalne"],
    "Laâyoune-Sakia El Hamra":   ["laayoune","laâyoune","boujdour","tarfaya","smara"],
    "Dakhla-Oued Ed-Dahab":      ["dakhla","oued eddahab","aousserd"],
    "Guelmim-Oued Noun":         ["guelmim","tan-tan","sidi ifni","assa-zag"],
    "Beni Mellal-Khenifra":      ["beni mellal","khenifra"],
}

ORG_REGIONS = {
    "Rabat-Salé-Kénitra":        ["ministère","direction centrale","présidence","parlement","sénat","cour","hcp","ofppt","cnops","bank al-maghrib","bnrm","dgapr","mci","mdn","men","ms "],
    "Casablanca-Settat":         ["lydec","cfca","wilaya casa","préfecture casa","onda casa","onee casa","ram ","aéroport casa"],
    "Fès-Meknès":                ["wilaya fès","cra fès","délégation fès","commune fès"],
    "Marrakech-Safi":            ["wilaya marrakech","cra marrakech"],
    "Souss-Massa":               ["wilaya agadir","cra agadir","aéroport agadir"],
}

# ══════════════════════════════════════════════════════
# CLASSIFICATION OFFICIELLE MARCHÉS PUBLICS MAROC
# Source: Portail marchespublics.gov.ma
# Codes T=Travaux, P=Produits, S=Services
# ══════════════════════════════════════════════════════
SECTEURS = {
    # ── TRAVAUX ──
    "T101 - Constructions & Bâtiments": [
        "bâtiment","construction","maçonnerie","béton","coffrage","fondation",
        "gros oeuvre","dalle","mur","clôture","enseigne","façade","rénovation",
        "aménagement","btp","ouvrages d'art","préfabriqué",
    ],
    "T102 - Terrassements": [
        "terrassement","remblai","déblai","excavation","nivellement","compactage",
        "décapage","stabilisation","emprise",
    ],
    "T103 - Menuiserie & Métallerie": [
        "menuiserie","métallerie","charpente","ferronnerie","portail","porte",
        "fenêtre","rideau","grille","serrurerie","aluminium","acier",
    ],
    "T104 - Plomberie & Climatisation": [
        "plomberie","chauffage","climatisation","ventilation","cvc","sanitaire",
        "robinetterie","tuyauterie","chaudière","vmc","split","frigorigène",
    ],
    "T105 - Peinture & Vitrerie": [
        "peinture","vitrerie","décoration","enduit","lasure","vernis",
        "revêtement mural","toile de verre","vitrage","miroir",
    ],
    "T106 - Étanchéité & Isolation": [
        "étanchéité","isolation","imperméabilisation","toiture","terrasse",
        "membrane","bitume","polystyrène","laine de roche",
    ],
    "T107 - Revêtements de sols": [
        "revêtement","carrelage","parquet","moquette","sol","dallage",
        "marbre","granit","faïence","linoléum",
    ],
    "T108 - Plâtrerie & Faux plafonds": [
        "plâtrerie","faux plafond","cloison","doublage","staff","gyproc",
        "plaque de plâtre","isolation acoustique",
    ],
    "T109 - Ascenseurs & Monte-charge": [
        "ascenseur","monte-charge","élévateur","escalier mécanique",
        "monte-plats","nacelle","plateforme élévatrice",
    ],
    "T110 - Génie Civil": [
        "génie civil","infrastructure","ouvrage d'art","pont","viaduc",
        "tunnel","mur de soutènement","gabion","géotechnique",
    ],
    "T111 - Espaces Verts": [
        "espaces verts","jardinage","plantation","gazon","arbre","arbuste",
        "taille","élagage","reboisement","parc","terrain de sport",
    ],
    "T112 - Aménagements Divers": [
        "aménagement divers","mobilier urbain","signalétique","parking",
        "clôture","portail","borne","voie piétonne",
    ],
    "T201 - Assainissement & Conduites": [
        "assainissement","conduite","égout","collecteur","réseau","step",
        "station d'épuration","canalisation","drain","regard",
    ],
    "T202 - Fondations Spéciales": [
        "fondations spéciales","injection","sondage","forage","pieu",
        "micropieu","palplanche","paroi moulée","consolidation",
    ],
    "T203 - Hydraulique & Eau Potable": [
        "hydraulique","eau potable","adduction","réservoir","château d'eau",
        "barrage","irrigation","pompage","traitement eau","station pompage",
    ],
    "T301 - Travaux Routiers": [
        "route","voie","chaussée","trottoir","voirie","bitume","asphalte",
        "enrobé","bordure","caniveau","signalisation","marquage","autoroute",
    ],
    "T401 - Électricité & Éclairage": [
        "électricité","éclairage","câblage","tableau électrique","armoire",
        "transformateur","groupe électrogène","ups","onduleur","éclairage public",
    ],
    "T402 - Sécurité & Télésurveillance": [
        "sécurité électronique","télésurveillance","alarme","incendie","extincteur",
        "détecteur","caméra","vidéosurveillance","cctv","contrôle accès","badge",
    ],
    "T403 - Télécommunications": [
        "télécommunication","téléphonie","réseau","câblage structuré","fibre optique",
        "switch","routeur","wifi","gsm","antenne","infrastructure réseau",
    ],
    # ── PRODUITS ──
    "P802 - Équipements Électroniques": [
        "électronique","équipements électroniques","composants","circuits",
        "capteur","module","carte électronique",
    ],
    "P805 - Mobilier de Bureau": [
        "mobilier","bureau","chaise","fauteuil","armoire","étagère","table",
        "banquette","chevalet","tableau","rangement","open space",
    ],
    "P813 - Équipements Médicaux": [
        "médical","équipements médicaux","laboratoire","analyse","réactif",
        "chirurgical","dentaire","pharmaceutique","seringue","perfusion",
        "stéthoscope","pétri","microbiologie","méthanol","lcms",
    ],
    "P814 - Climatisation": [
        "climatiseur","split","gainable","vrf","pompe chaleur","réfrigération",
        "chambre froide","frigorigène","froid industriel",
    ],
    "P815 - Matériel de Manutention": [
        "manutention","chariot","grue","nacelle","élévateur","transpalette",
        "chariot élévateur","convoyeur","engin","tracteur",
    ],
    "P816 - Matériel Roulant": [
        "véhicule","voiture","camion","bus","minibus","ambulance","motocycle",
        "remorque","carburant","gasoil","pièce rechange","pneumatique",
    ],
    "P818 - Informatique": [
        "informatique","ordinateur","pc","laptop","serveur","imprimante",
        "scanner","toner","cartouche","écran","onduleur","switch","réseau",
        "logiciel","licence","erp","application","développement","cloud",
    ],
    "P821 - Sécurité & Protection": [
        "sécurité","équipements protection","epi","casque","gilet","gants",
        "chaussure sécurité","harnais","équipements incendie","extincteur",
    ],
    "P825 - Fournitures de Bureau": [
        "fournitures","papier","ramette","chemise","classeur","stylo","agrafe",
        "enveloppe","cahier","registre","tampon","consommables bureau",
    ],
    "P831 - Combustibles": [
        "carburant","gasoil","essence","fuel","lubrifiant","huile","gaz",
        "combustible","fioul","énergie",
    ],
    "P833 - Produits Pharmaceutiques": [
        "médicament","pharmaceutique","produits chimiques","parachimique",
        "réactif laboratoire","consommables médicaux","dmi",
    ],
    "P834 - Alimentation": [
        "alimentation","denrée","produit alimentaire","viande","poisson",
        "légume","boisson","eau minérale","café","lait","restauration",
        "traiteur","cuisine","catering","filet de dinde",
    ],
    "P836 - Imprimerie & Papeterie": [
        "impression","imprimerie","papeterie","brochure","affiche","rapport",
        "reprographie","sérigraphie","emballage","badge","carte visite",
    ],
    "P839 - Matériaux de Construction": [
        "matériaux","ciment","sable","gravier","béton prêt","brique",
        "parpaing","préfabriqué","acier","rond à béton","bois",
    ],
    "P841 - Hygiène & Nettoyage": [
        "hygiène","nettoyage","savon","détergent","désinfectant","produits",
        "balai","serpillière","sac poubelle","papier hygiénique",
    ],
    "P850 - Énergies Renouvelables": [
        "solaire","photovoltaïque","énergie renouvelable","panneau solaire",
        "éolien","biomasse","chauffe eau solaire","pompe chaleur",
    ],
    # ── SERVICES ──
    "S901 - IT & Développement": [
        "développement informatique","tic","système information","logiciel",
        "application mobile","site web","base de données","erp","crm",
        "cybersécurité","cloud","hébergement","intégration",
    ],
    "S902 - Études & Conseil": [
        "étude","conseil","consultant","expertise","audit","diagnostic",
        "assistance technique","accompagnement","mission","tdr","ingénierie",
        "maîtrise oeuvre","bureau études",
    ],
    "S903 - Études BTP": [
        "étude btp","topographie","géotechnique","béton armé","structure",
        "plans","permis construire","dossier technique","métreur",
    ],
    "S906 - Maintenance & Entretien": [
        "maintenance","entretien","réparation","dépannage","contrat maintenance",
        "pmr","pme","curatif","préventif","astreinte",
    ],
    "S907 - Nettoyage": [
        "nettoyage","propreté","hygiène","désinfection","dératisation",
        "désinsectisation","lavage","nettoyage industriel","déchets",
    ],
    "S908 - Gardiennage": [
        "gardiennage","sécurité","surveillance","agent sécurité","ronde",
        "portier","accueil sécurisé","protection","interim",
    ],
    "S910 - Communication & Publicité": [
        "communication","publicité","événementiel","médias","presse",
        "audiovisuel","vidéo","photo","signalétique","relations publiques",
    ],
    "S911 - Restauration & Hébergement": [
        "restauration","repas","traiteur","hébergement","hôtel","séminaire",
        "réception","catering","self","cantine",
    ],
    "S913 - Formation": [
        "formation","coaching","séminaire","atelier","certification",
        "accréditation","programme formation","e-learning","stage",
    ],
    "S915 - Location Véhicules": [
        "location véhicule","transport","taxi","navette","bus",
        "location matériel roulant","flotte","chauffeur",
    ],
    "S918 - Traitement Déchets": [
        "déchets","collecte ordures","recyclage","décharge","compostage",
        "traitement déchets","élimination","valorisation",
    ],
    "S921 - Analyses Laboratoire": [
        "analyse laboratoire","contrôle qualité","essais","tests","certification",
        "accréditation laboratoire","mesures","analyses industrielles",
    ],
}

SECTEURS_LIST = list(SECTEURS.keys())

class ClassifierAgent:
    """Agent de classification automatique des marchés"""

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
        # Geographic keywords
        for region, kws in REGIONS.items():
            if any(k in txt for k in kws): return region
        # Organisation keywords
        for region, kws in ORG_REGIONS.items():
            if any(k in txt for k in kws): return region
        return "Maroc"

    @staticmethod
    def secteur(text: str) -> str:
        txt = text.lower()
        scores: dict = defaultdict(int)
        for sect, kws in SECTEURS.items():
            for kw in kws:
                if kw in txt:
                    scores[sect] += 2 if len(kw) > 9 else 1
        return max(scores, key=scores.get) if scores else "Fournitures de Bureau"

    @staticmethod
    def type_marche(text: str) -> str:
        txt = text.lower()
        if any(k in txt for k in ["travaux","construction","réhabilitation","pose","démolition"]): return "Travaux"
        if any(k in txt for k in ["fourniture","livraison","achat","acquisition","matériel"]): return "Fournitures"
        if any(k in txt for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage"]): return "Services"
        if any(k in txt for k in ["étude","mission","audit","conseil","formation","expertise"]): return "Études & Conseil"
        return "Fournitures"

    @staticmethod
    def is_expired(d: str) -> bool:
        if not d: return False
        for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d.%m.%Y"]:
            try: return datetime.strptime(d.strip(), fmt).date() < datetime.now().date()
            except: pass
        return False

    @staticmethod
    def extract_date(text: str) -> str:
        if not text: return ""
        m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
        return m.group(1) if m else ""

# ══════════════════════════════════════════════════════
# SCRAPER AGENT
# ══════════════════════════════════════════════════════
class ScraperLog:
    entries: list = []
    @classmethod
    def add(cls, msg):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.entries.append(entry)
        logger.info(entry)
        if len(cls.entries) > 600: cls.entries = cls.entries[-500:]
    @classmethod
    def last(cls, n=100): return cls.entries[-n:]

class ScraperState:
    running   = False
    found     = 0
    saved     = 0
    errors    = 0
    started   = ""
    current   = 0
    total     = 0

class ScraperAgent:
    BASE_BDC  = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
    BASE_PMMP = "https://www.marchespublics.gov.ma/pmmp/consultation"
    HEADERS   = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    @staticmethod
    def _session():
        import requests
        s = requests.Session()
        s.verify = False
        s.headers.update(ScraperAgent.HEADERS)
        return s

    @staticmethod
    def _is_listing_page(html: str) -> bool:
        """Returns True if page is just the listing (not a tender detail)"""
        markers = ["Liste des avis d'achat", "Aucune consultation", "Résultats des avis"]
        return any(m in html[:3000] for m in markers) and len(html) < 30000

    @staticmethod
    def _parse(html: str, tid: str, prefix: str = "bdc") -> Optional[dict]:
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)

            def cell_after(label: str) -> str:
                for row in soup.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    for i, c in enumerate(cells):
                        if label.lower() in c.get_text().lower() and i + 1 < len(cells):
                            v = cells[i + 1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""

            # ── OBJET ──
            objet = ""
            for sel in [".consultation-title",".objet",".ao-title","#objet","h1","h2"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    skip_kw = ["accueil","liste des avis","connexion","navigation","portail","bienvenue"]
                    if 8 < len(txt) < 600 and not any(s in txt.lower() for s in skip_kw):
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé","désignation","libellé"]:
                    v = cell_after(lbl)
                    if v and 8 < len(v) < 500: objet = v; break
            if not objet:
                meta = soup.find("meta", {"name": "description"})
                if meta and meta.get("content"):
                    c = meta["content"].strip()
                    if len(c) > 15 and "marchespublics" not in c.lower():
                        objet = c[:400]
            if not objet:
                for tag in soup.find_all(["p","div","td"]):
                    txt = tag.get_text(strip=True)
                    skip = ["accueil","liste des avis","connexion","©","cookie"]
                    kws  = ["travaux","fourniture","service","étude","prestation",
                            "acquisition","appel","consultation","accord","marché"]
                    if 20 < len(txt) < 500 and not any(s in txt.lower() for s in skip):
                        if any(k in txt.lower() for k in kws):
                            objet = txt; break

            # ── ACHETEUR ──
            acheteur = (
                cell_after("maître d'ouvrage") or cell_after("maître d'oeuvre") or
                cell_after("organisme") or cell_after("acheteur") or
                cell_after("pouvoir adjudicateur") or ""
            ).strip()

            # ── DATES ──
            date_pub = ClassifierAgent.extract_date(cell_after("publication") or "")
            date_lim = ClassifierAgent.extract_date(
                cell_after("remise") or cell_after("limite") or
                cell_after("ouverture") or ""
            )

            # ── MONTANT ──
            montant = cell_after("montant") or cell_after("budget") or ""
            if not montant:
                m = re.search(r'(\d[\d\s,.]{2,14})\s*(?:DH|MAD|dirham)', full, re.I)
                if m: montant = m.group(0)[:80]

            # ── CLASSIFY ──
            objet   = ClassifierAgent.clean_objet(objet)
            region  = ClassifierAgent.region(acheteur + " " + full[:600])
            domaine = ClassifierAgent.secteur(objet + " " + full[:400])
            type_m  = ClassifierAgent.type_marche(objet + " " + full[:300])

            statut = (
                "annule" if any(k in full.lower() for k in ["annulé","infructueux","sans suite"])
                else "expire" if ClassifierAgent.is_expired(date_lim)
                else "actif"
            )

            return {
                "id":               f"{prefix}_{tid}",
                "objet":            objet[:400] or f"Marché #{tid}",
                "acheteur":         acheteur[:200],
                "region":           region,
                "domaine":          domaine,
                "type_marche":      type_m,
                "montant":          montant[:80],
                "date_publication": date_pub,
                "date_limite":      date_lim,
                "description":      full[:2000],
                "statut":           statut,
                "url":              f"{ScraperAgent.BASE_BDC}/show/{tid}",
            }
        except Exception as e:
            logger.error(f"[parse #{tid}] {e}")
            return None

    @staticmethod
    def _save(t: dict) -> bool:
        if not t or not t.get("id") or not t.get("objet"): return False
        try:
            import json as _json
            ai = t.get("ai") or {}
            db = get_db()
            db.execute("""INSERT OR IGNORE INTO tenders
                (id,objet,acheteur,region,domaine,type_marche,montant,
                 date_publication,date_limite,description,statut,url,
                 source,contact,ai_score,ai_label,ai_reasons,date_extraction)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                str(t.get("id",""))[:80],
                str(t.get("objet") or t.get("title",""))[:400],
                str(t.get("acheteur",""))[:200],
                str(t.get("region",""))[:100],
                str(t.get("domaine") or t.get("category",""))[:80],
                str(t.get("type_marche",""))[:40],
                str(t.get("montant") or t.get("budget",""))[:80],
                str(t.get("date_publication",""))[:20],
                str(t.get("date_limite") or t.get("deadline",""))[:20],
                str(t.get("description",""))[:2000],
                str(t.get("statut","actif")),
                str(t.get("url",""))[:400],
                str(t.get("source","marchespublics.gov.ma"))[:80],
                str(t.get("contact",""))[:120],
                int(ai.get("score",0)),
                str(ai.get("label",""))[:20],
                _json.dumps(ai.get("reasons",[]))[:200],
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ))
            db.commit()
            changed = db.execute("SELECT changes()").fetchone()[0]
            db.close()
            return changed > 0
        except Exception as e:
            logger.error(f"[save] {e}")
            try: db.close()
            except: pass
            return False

    @classmethod
    def run(cls) -> list:
        import requests as rq
        t_start = time.time()
        new_tenders: list = []
        ScraperState.running  = True
        ScraperState.found    = ScraperState.saved = ScraperState.errors = 0
        ScraperState.started  = datetime.now().strftime("%H:%M:%S")
        ScraperState.current  = ScraperState.total = 0
        ScraperLog.add("═══ ScraperAgent démarré ═══")

        s = cls._session()

        # ── Load known IDs ──
        db = get_db()
        known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
        db.close()

        # ── Phase 1: Crawl listing pages ──
        ScraperLog.add("Phase 1: Listing pages...")
        ids_found: list = []
        for base in [cls.BASE_BDC, cls.BASE_PMMP]:
            prefix = "bdc" if "bdc" in base else "pmmp"
            for page in range(1, 15):
                url = base + "/" if page == 1 else f"{base}/?page={page}"
                try:
                    r = s.get(url, timeout=20)
                    if r.status_code != 200: break
                    page_ids = []
                    for m in re.finditer(r'/show/(\d{3,7})', r.text):
                        tid = m.group(1)
                        full_id = f"{prefix}_{tid}"
                        if full_id not in known and (prefix, tid) not in [(x[0], x[1]) for x in ids_found]:
                            ids_found.append((prefix, tid))
                            page_ids.append(tid)
                    if not page_ids:
                        ScraperLog.add(f"  {prefix} page {page}: fin listing")
                        break
                    ScraperLog.add(f"  {prefix} page {page}: +{len(page_ids)} IDs")
                    time.sleep(random.uniform(1.0, 1.8))
                except Exception as e:
                    ScraperLog.add(f"  {prefix} page {page}: erreur {str(e)[:40]}")
                    ScraperState.errors += 1
                    break
            if ids_found: break  # BDC succeeded, no need for PMMP

        ScraperLog.add(f"IDs trouvés: {len(ids_found)} | Nouveaux: {len(ids_found)}")
        ScraperState.total = len(ids_found)

        # ── Phase 2: Fetch each tender ──
        ScraperLog.add("Phase 2: Extraction des marchés...")
        for i, (prefix, tid) in enumerate(ids_found[:100]):
            ScraperState.current = i + 1
            base = cls.BASE_BDC if prefix == "bdc" else cls.BASE_PMMP
            url  = f"{base}/show/{tid}"
            try:
                r = s.get(url, timeout=15)
                if r.status_code == 200:
                    if cls._is_listing_page(r.text):
                        ScraperState.errors += 1
                        continue
                    t = cls._parse(r.text, tid, prefix)
                    if t:
                        ScraperState.found += 1
                        if cls._save(t):
                            ScraperState.saved += 1
                            label = "✓" if t["statut"] == "actif" else "~"
                            ScraperLog.add(f"  {label} #{tid} [{t['domaine'][:20]}] {t['objet'][:50]}")
                            if t["statut"] == "actif":
                                new_tenders.append(t)
                elif r.status_code == 404:
                    pass
                elif r.status_code == 429:
                    ScraperLog.add("  Rate limited — pause 30s")
                    time.sleep(30)
                else:
                    ScraperState.errors += 1
            except Exception as e:
                ScraperState.errors += 1
                ScraperLog.add(f"  ✗ #{tid}: {str(e)[:50]}")
            time.sleep(random.uniform(0.6, 1.3))

        # ── Phase 3: Mark expired ──
        try:
            db = get_db()
            active = db.execute(
                "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
            ).fetchall()
            expired = [r["id"] for r in active if ClassifierAgent.is_expired(r["date_limite"])]
            if expired:
                placeholders = ",".join("?" * len(expired))
                db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({placeholders})", expired)
                ScraperLog.add(f"  {len(expired)} marchés marqués expirés")
            db.commit(); db.close()
        except Exception as e:
            logger.error(f"[expire] {e}")

        # ── Save run stats ──
        duration = time.time() - t_start
        try:
            db = get_db()
            db.execute(
                "INSERT INTO scrape_runs (found,saved,errors,duration_sec,started_at,finished_at) VALUES (?,?,?,?,?,?)",
                (ScraperState.found, ScraperState.saved, ScraperState.errors,
                 duration, ScraperState.started, datetime.now().strftime("%H:%M:%S"))
            )
            db.commit(); db.close()
        except: pass

        ScraperState.running = False
        ScraperLog.add(
            f"═══ Terminé en {duration:.0f}s | "
            f"{ScraperState.saved} sauvegardés | "
            f"{ScraperState.errors} erreurs ═══"
        )
        counter("scrape_runs")
        return new_tenders

# ══════════════════════════════════════════════════════
# NOTIFICATION AGENT
# ══════════════════════════════════════════════════════
class NotifyAgent:
    """
    Agent de notifications par queue.
    - Enqueue: ajoute à la file d'attente DB
    - Worker:  traite la file en arrière-plan (retry 3x)
    - Canaux:  email SMTP + Telegram Bot API
    """

    # ── Queue management ──
    @staticmethod
    def enqueue(member_id: Optional[int], channel: str, recipient: str,
                subject: str, body: str):
        try:
            db = get_db()
            db.execute("""INSERT INTO notif_queue
                (member_id,channel,recipient,subject,body,status,created_at)
                VALUES (?,?,?,?,?,'pending',?)""",
                (member_id, channel, recipient, subject, body, now_str()))
            db.commit(); db.close()
        except Exception as e:
            logger.error(f"[notif:enqueue] {e}")

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
    def mark(nid: int, status: str, error: str = ""):
        try:
            db = get_db()
            if status == "sent":
                db.execute("UPDATE notif_queue SET status='sent', sent_at=? WHERE id=?",
                           (now_str(), nid))
            else:
                db.execute("""UPDATE notif_queue
                    SET status=?, attempts=attempts+1, error=?
                    WHERE id=?""", (status, error[:200], nid))
            db.commit(); db.close()
        except: pass

    # ── Email: Brevo → Resend → SMTP ──
    @staticmethod
    async def send_email(to: str, subject: str, html: str) -> tuple:
        import httpx

        # Priority 1: Brevo API (HTTP - works on Railway, 300/day free)
        if BREVO_KEY:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        "https://api.brevo.com/v3/smtp/email",
                        headers={"api-key": BREVO_KEY, "Content-Type": "application/json"},
                        json={
                            "sender":      {"name": BRAND, "email": GMAIL_USER},
                            "to":          [{"email": to}],
                            "subject":     subject,
                            "htmlContent": html,
                        }
                    )
                    if r.status_code in [200, 201, 202]:
                        counter("emails_sent")
                        logger.info(f"[email:brevo] ok -> {to}")
                        return True, ""
                    err = r.text[:120]
                    logger.error(f"[email:brevo] {r.status_code}: {err}")
            except Exception as e:
                logger.error(f"[email:brevo] {e}")

        # Priority 2: Resend API (requires verified domain for non-owner emails)
        if RESEND_KEY:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {RESEND_KEY}",
                                 "Content-Type": "application/json"},
                        json={"from": f"{BRAND} <onboarding@resend.dev>",
                              "to": [to], "subject": subject, "html": html}
                    )
                    data = r.json()
                    if r.status_code in [200, 201] and data.get("id"):
                        counter("emails_sent")
                        return True, ""
                    logger.error(f"[email:resend] {data.get('message','')[:100]}")
            except Exception as e:
                logger.error(f"[email:resend] {e}")

        # Priority 3: SMTP (blocked by Railway free plan)
        if GMAIL_PASS:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"{BRAND} <{GMAIL_USER}>"
                msg["To"]      = to
                msg.attach(MIMEText(html, "html", "utf-8"))
                def _smtp():
                    for host,port,ssl in [("smtp.gmail.com",465,True),("smtp.gmail.com",587,False)]:
                        try:
                            srv = smtplib.SMTP_SSL(host,port,timeout=20) if ssl else smtplib.SMTP(host,port,timeout=20)
                            if not ssl: srv.ehlo(); srv.starttls(); srv.ehlo()
                            srv.login(GMAIL_USER, GMAIL_PASS)
                            srv.sendmail(GMAIL_USER,[to],msg.as_string())
                            srv.quit(); return True,""
                        except smtplib.SMTPAuthenticationError:
                            return False,"Gmail App Password requis"
                        except: continue
                    return False,"SMTP bloque par Railway (utiliser BREVO_API_KEY)"
                loop = asyncio.get_event_loop()
                ok, err = await loop.run_in_executor(None, _smtp)
                if ok: counter("emails_sent")
                return ok, err
            except Exception as e:
                return False, str(e)

        return False, "BREVO_API_KEY non configure (recommande)"

    # ── WhatsApp via Twilio ──
    @staticmethod
    async def send_whatsapp(to: str, body: str) -> tuple:
        """Send WhatsApp via Twilio — to must be 'whatsapp:+212XXXXXXXXX'"""
        if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
            return False, "Twilio not configured"
        try:
            import httpx, base64
            creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
            # Truncate for WhatsApp (1600 chars max)
            body_t = body[:1500]
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                    headers={"Authorization": f"Basic {creds}"},
                    data={"From": TWILIO_FROM, "To": to, "Body": body_t}
                )
                data = r.json()
                if r.status_code in [200, 201]:
                    counter("whatsapp_sent")
                    logger.info(f"[whatsapp] ✅ → {to}")
                    return True, ""
                err = data.get("message", str(data))[:100]
                logger.error(f"[whatsapp] ✗ {r.status_code}: {err}")
                return False, err
        except Exception as e:
            logger.error(f"[whatsapp] {e}")
            return False, str(e)

    # ── Telegram ──
    @staticmethod
    async def send_telegram(chat_id: str, text: str) -> tuple:
        try:
            import httpx
            MAX = 3800
            msgs = []
            if len(text) <= MAX:
                msgs = [text]
            else:
                current = ""
                for line in text.split("\n"):
                    if len(current) + len(line) + 1 > MAX:
                        msgs.append(current); current = line
                    else:
                        current += ("\n" if current else "") + line
                if current: msgs.append(current)

            all_ok = True
            async with httpx.AsyncClient(timeout=15) as client:
                for part in msgs:
                    r = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                        json={"chat_id": chat_id, "text": part,
                              "parse_mode": "HTML", "disable_web_page_preview": True}
                    )
                    data = r.json()
                    if not data.get("ok"):
                        all_ok = False
                        err = data.get("description","unknown")
                        logger.error(f"[tg→{chat_id}] {err}")
                        return False, err
                    await asyncio.sleep(0.3)
            if all_ok: counter("tg_sent")
            return all_ok, ""
        except Exception as e:
            return False, str(e)

    # ── Worker loop ──
    @staticmethod
    async def worker():
        """Background worker — processes notification queue every 5s"""
        logger.info("[NotifyAgent] Worker started")
        while True:
            try:
                pending = NotifyAgent.get_pending()
                for n in pending:
                    try:
                        if n["channel"] == "email":
                            ok, err = await NotifyAgent.send_email(
                                n["recipient"], n["subject"], n["body"]
                            )
                        elif n["channel"] == "telegram":
                            ok, err = await NotifyAgent.send_telegram(
                                n["recipient"], n["body"]
                            )
                        elif n["channel"] == "whatsapp":
                            ok, err = await NotifyAgent.send_whatsapp(
                                n["recipient"], n["body"]
                            )
                        else:
                            ok, err = False, f"Unknown channel: {n['channel']}"

                        if ok:
                            NotifyAgent.mark(n["id"], "sent")
                            logger.info(f"[NotifyAgent] ✅ {n['channel']}→{n['recipient'][:20]}")
                        else:
                            # After 2 email failures → mark failed, don't keep retrying
                            status = "failed" if n["attempts"] >= 2 else "pending"
                            NotifyAgent.mark(n["id"], status, err)
                            if "Network is unreachable" in err or "SMTP" in err:
                                # Railway blocks SMTP — auto-fail without retry
                                NotifyAgent.mark(n["id"], "failed", "Railway blocks SMTP — use BREVO_API_KEY")
                            logger.warning(f"[NotifyAgent] ✗ {n['channel']}→{n['recipient'][:20]}: {err[:60]}")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        NotifyAgent.mark(n["id"], "pending", str(e))
            except Exception as e:
                logger.error(f"[NotifyAgent:worker] {e}")
            await asyncio.sleep(5)

    # ── Builders ──
    @staticmethod
    def build_email(tenders: list, title: str) -> str:
        def card(t):
            montant_html = (
                f'<tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">💰 Montant</td>'
                f'<td style="color:#c9a84c;font-size:11px;font-weight:700">{t.get("montant","")}</td></tr>'
                if t.get("montant") else ""
            )
            return f"""
<div style="border:1px solid #2a2a2a;border-radius:8px;padding:16px 18px;margin-bottom:14px;background:#141414">
  <div style="display:inline-block;padding:2px 8px;background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.2);
       border-radius:4px;font-size:10px;font-weight:700;color:#c9a84c;margin-bottom:8px;text-transform:uppercase">
    {t.get("type_marche","") or t.get("domaine","")}
  </div>
  <div style="font-size:14px;font-weight:700;color:#f0ede6;margin-bottom:10px;line-height:1.4">
    {(t.get("objet") or "Marché sans titre")[:100]}
  </div>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">🏢 Acheteur</td>
        <td style="color:#aaa;font-size:11px">{(t.get("acheteur") or "—")[:60]}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">📍 Région</td>
        <td style="color:#aaa;font-size:11px">{t.get("region","—")}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">🏷 Secteur</td>
        <td style="color:#aaa;font-size:11px">{t.get("domaine","—")}</td></tr>
    {montant_html}
    <tr><td style="color:#888;font-size:11px;padding:3px 0">⏰ Date limite</td>
        <td style="color:#e87070;font-size:11px;font-weight:700">{t.get("date_limite","—")}</td></tr>
  </table>
  <a href="{t.get("url") or SITE_URL}"
     style="display:inline-block;margin-top:10px;padding:6px 16px;background:#c9a84c;
            color:#000;border-radius:5px;font-weight:700;text-decoration:none;font-size:12px">
    Voir le marché officiel →
  </a>
</div>"""

        cards = "".join(card(t) for t in tenders[:15])
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px;background:#080808;font-family:Georgia,serif">
<div style="max-width:640px;margin:0 auto;background:#0d0d0d;border-radius:12px;padding:32px">
  <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:22px">
    <div style="font-size:22px;font-weight:700;color:#c9a84c">◆ Modern Business</div>
    <div style="font-size:11px;color:#555;margin-top:4px">
      marchespublics.gov.ma — {datetime.now().strftime("%d/%m/%Y à %H:%M")}
    </div>
  </div>
  <div style="font-size:18px;font-weight:700;color:#f0ede6;margin-bottom:6px">{title}</div>
  <div style="font-size:12px;color:#666;margin-bottom:22px">
    Source officielle: Portail Marocain des Marchés Publics
  </div>
  {cards}
  <div style="border-top:1px solid #222;padding-top:20px;margin-top:8px;text-align:center">
    <a href="{SITE_URL}" style="display:inline-block;padding:11px 28px;background:#c9a84c;
       color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px">
      Accéder à la plateforme →
    </a>
    <div style="font-size:10px;color:#333;margin-top:14px">
      Modern Business · <a href="{SITE_URL}/contact" style="color:#555">Se désinscrire</a>
    </div>
  </div>
</div>
</body></html>"""

    @staticmethod
    def build_telegram(tenders: list, header: str) -> str:
        sep = "━" * 28
        lines = [f"🏛 <b>{header}</b>\n{sep}\n"]
        for t in tenders[:8]:
            block = f"📋 <b>{(t.get('objet') or 'Marché sans titre')[:68]}</b>\n"
            if t.get("acheteur"):   block += f"   🏢 {t['acheteur'][:50]}\n"
            if t.get("region"):     block += f"   📍 {t['region']}\n"
            if t.get("domaine"):    block += f"   🏷 {t['domaine']}\n"
            if t.get("montant"):    block += f"   💰 {t['montant']}\n"
            if t.get("date_limite"):block += f"   ⏰ <b>Limite: {t['date_limite']}</b>\n"
            if t.get("url"):        block += f"   🔗 {t['url']}\n"
            lines.append(block)
        lines.append(f"\n🌐 {SITE_URL}")
        return "\n\n".join(lines)

    # ── Public methods ──
    @staticmethod
    def match_tenders(tenders: list, filters: list) -> list:
        """Filter tenders matching member preferences"""
        if not filters:
            return tenders  # No filters = receive all

        secteurs = [f["value"].lower() for f in filters if f["type"] == "secteur"]
        regions  = [f["value"].lower() for f in filters if f["type"] == "region"]
        keywords = [f["value"].lower() for f in filters if f["type"] == "keyword"]

        matched = []
        for t in tenders:
            t_sect = (t.get("domaine") or "").lower()
            t_reg  = (t.get("region") or "").lower()
            t_obj  = (t.get("objet") or "").lower()
            t_desc = (t.get("description") or "").lower()
            t_full = t_obj + " " + t_desc

            # Match secteur
            sect_match = not secteurs or any(s in t_sect or t_sect in s for s in secteurs)
            # Match region
            reg_match  = not regions  or any(r in t_reg  or t_reg  in r for r in regions)
            # Match keyword (optional bonus)
            kw_match   = not keywords or any(k in t_full for k in keywords)

            if sect_match and reg_match and (not keywords or kw_match):
                matched.append(t)

        return matched

    @staticmethod
    def notify_instant(tenders: list):
        """
        Smart notifications — each member receives only matching tenders.
        Matching based on: secteur + region + keywords preferences.
        """
        if not tenders: return
        db = get_db()
        try:
            subs = [dict(r) for r in db.execute(
                "SELECT id,nom,email,telegram,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
            # Load all filters
            all_filters = [dict(r) for r in db.execute(
                "SELECT member_id,type,value FROM member_filters"
            ).fetchall()]
        finally: db.close()

        if not subs:
            ScraperLog.add("[NotifyAgent] Aucun abonné")
            return

        eq = tq = 0
        for sub in subs:
            # Get this member's filters
            my_filters = [f for f in all_filters if f["member_id"] == sub["id"]]

            # Match tenders to member profile
            matched = NotifyAgent.match_tenders(tenders, my_filters)
            if not matched:
                continue

            n = len(matched)
            subj     = f"🏛 {n} marché(s) correspondant à votre profil — {datetime.now().strftime('%d/%m/%Y')}"
            tg_intro = f"Modern Business — {n} marché(s) pour vous"

            if sub.get("notif_tg", 1) and sub.get("telegram"):
                tg_body = NotifyAgent.build_telegram(matched, tg_intro)
                NotifyAgent.enqueue(sub["id"], "telegram", sub["telegram"], "", tg_body)
                tq += 1

            if sub.get("notif_email", 1) and sub.get("email"):
                email_html = NotifyAgent.build_email(matched, f"🏛 {n} marché(s) correspondant à votre profil")
                NotifyAgent.enqueue(sub["id"], "email", sub["email"], subj, email_html)
                eq += 1

        ScraperLog.add(f"[NotifyAgent] Smart match: {tq} TG + {eq} emails — {len(tenders)} marchés traités")
        counter("notifications_queued")

    @staticmethod
    def notify_digest():
        """Queue daily digest for all subscribers"""
        db = get_db()
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE date_extraction >= ? AND statut='actif' ORDER BY date_extraction DESC",
                (yesterday,)
            ).fetchall()]
            subs = [dict(r) for r in db.execute(
                "SELECT id,email,telegram,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()

        if not tenders:
            logger.info("[NotifyAgent:digest] Aucun marché")
            return
        if not subs:
            logger.info("[NotifyAgent:digest] Aucun abonné")
            return

        n = len(tenders)
        ds = datetime.now().strftime("%d/%m/%Y")
        subj       = f"📋 Résumé marchés {ds} ({n} nouveaux) — Modern Business"
        email_html = NotifyAgent.build_email(tenders, f"Résumé du {ds} — {n} marché(s)")
        tg_body    = NotifyAgent.build_telegram(tenders, f"Résumé du {ds} — {n} marché(s)")

        for sub in subs:
            if sub.get("notif_email", 1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"], "email", sub["email"], subj, email_html)
            if sub.get("notif_tg", 1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"], "telegram", sub["telegram"], "", tg_body)
        logger.info(f"[NotifyAgent:digest] {n} marchés mis en file pour {len(subs)} abonnés")

# ══════════════════════════════════════════════════════
# MONITOR AGENT
# ══════════════════════════════════════════════════════
class MonitorAgent:
    """Auto-monitoring: log errors, trigger cleanup, health checks"""

    @staticmethod
    def log_error(agent: str, route: str, error: str):
        try:
            db = get_db()
            existing = db.execute(
                "SELECT id,count FROM agent_errors WHERE agent=? AND route=? AND resolved=0",
                (agent, route)
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE agent_errors SET count=count+1,last_seen=?,error=? WHERE id=?",
                    (now_str(), error[:300], existing["id"])
                )
            else:
                db.execute(
                    "INSERT INTO agent_errors (agent,route,error,count,first_seen,last_seen) VALUES (?,?,?,1,?,?)",
                    (agent, route, error[:300], now_str(), now_str())
                )
            db.commit(); db.close()
        except: pass

    @staticmethod
    async def run():
        """Periodic health checks + cleanup"""
        logger.info("[MonitorAgent] Started")
        while True:
            try:
                db = get_db()
                # Cleanup old chats (> 7 days)
                db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
                # Cleanup old sent notifications (> 30 days)
                db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
                # Reset failed notifications after 1 hour
                db.execute("""UPDATE notif_queue SET status='pending', attempts=0
                    WHERE status='failed' AND created_at < datetime('now','-1 hour')
                    AND attempts < 3""")
                db.commit(); db.close()
                logger.info("[MonitorAgent] Health check OK")
            except Exception as e:
                logger.error(f"[MonitorAgent] {e}")
            await asyncio.sleep(3600)  # Every hour

    @staticmethod
    def get_stats() -> dict:
        db = get_db()
        try:
            return {
                "tenders_total":   db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
                "tenders_active":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
                "tenders_expire":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
                "members":         db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
                "members_tg":      db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0],
                "posts":           db.execute("SELECT COUNT(*) FROM posts WHERE status='actif'").fetchone()[0],
                "ratings":         db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0],
                "notif_pending":   db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0],
                "notif_sent":      db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0],
                "notif_failed":    db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0],
                "errors":          db.execute("SELECT COUNT(*) FROM agent_errors WHERE resolved=0").fetchone()[0],
                "scrape_runs":     db.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0],
            }
        finally: db.close()

# ══════════════════════════════════════════════════════
# CHAT AGENT
# ══════════════════════════════════════════════════════
CHAT_SYSTEM = f"""Tu es l'assistant intelligent de {BRAND}, plateforme marocaine de veille sur les marchés publics.

Ton rôle:
- Aider les entrepreneurs et PME marocaines à comprendre les appels d'offres
- Expliquer les procédures (Décret n°2-12-349 du 8 joumada I 1434)
- Conseiller sur la qualification et classification des entreprises (BTP, SI, etc.)
- Informer sur les organismes: ONCF, ONEE, OCP, RAM, ONDA, CDG, communes, ministères
- Aider à comprendre les cahiers des charges (CPS, CCAG, CCAP)
- Expliquer les garanties (cautionnement provisoire, définitif)
- Répondre en français ou arabe selon la langue de l'utilisateur

Règles:
- Réponses concises et pratiques (max 300 mots sauf si complexe)
- Toujours encourager à vérifier sur marchespublics.gov.ma
- Ne pas donner de conseils juridiques formels

Plateforme: {SITE_URL}"""

class ChatAgent:
    @staticmethod
    async def respond(messages: list) -> str:
        if not ANTHROPIC_KEY:
            return (
                "🤖 L'assistant IA n'est pas encore configuré.\n\n"
                "Contactez-nous sur le site pour toute question.\n"
                f"🌐 {SITE_URL}/contact"
            )
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 600,
                        "system": CHAT_SYSTEM,
                        "messages": messages[-12:],
                    }
                )
                if r.status_code == 200:
                    data = r.json()
                    return data["content"][0]["text"]
                return f"Erreur API ({r.status_code}). Réessayez."
        except Exception as e:
            logger.error(f"[ChatAgent] {e}")
            return "Service temporairement indisponible."

# ══════════════════════════════════════════════════════
# SCHEDULERS
# ══════════════════════════════════════════════════════
LAST_SCRAPE = 0.0

LAST_MULTI_SCRAPE = 0.0

async def scrape_scheduler():
    await asyncio.sleep(60)
    global LAST_SCRAPE, LAST_MULTI_SCRAPE
    while True:
        try:
            now = time.time()
            # Main scraper (marchespublics.gov.ma) — every SCRAPE_HOURS
            if now - LAST_SCRAPE >= SCRAPE_HOURS * 3600:
                LAST_SCRAPE = now
                loop = asyncio.get_event_loop()
                new = await loop.run_in_executor(None, ScraperAgent.run)
                if new:
                    NotifyAgent.notify_instant(new)

            # Multi-scraper (4 private sites) — every SCRAPE_HOURS*2
            if MULTI_SCRAPE and now - LAST_MULTI_SCRAPE >= SCRAPE_HOURS * 2 * 3600:
                LAST_MULTI_SCRAPE = now
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _run_multi_scraper)

        except Exception as e:
            ScraperState.running = False
            logger.error(f"[scheduler:scrape] {e}")
        await asyncio.sleep(600)

def _run_multi_scraper():
    """Run all external scrapers in thread"""
    try:
        db = get_db()
        known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
        db.close()

        # run_all_scrapers(known, sources, log_fn)
        extra_sources = [s for s in MULTI_SCRAPERS.keys() if s != "marchespublics"]
        tenders = run_all_scrapers(known, extra_sources, ScraperLog.add)

        saved = 0
        notify_list = []
        for t in tenders:
            td = {
                "id":               t.id,
                "objet":            t.objet,
                "acheteur":         t.acheteur,
                "region":           t.region,
                "domaine":          t.domaine,
                "type_marche":      t.type_marche,
                "montant":          t.montant,
                "date_publication": t.date_publication,
                "date_limite":      t.date_limite,
                "description":      t.description,
                "statut":           t.statut,
                "url":              t.source_url,
                "source":           t.source,
                "contact":          t.contact,
                "budget_min":       t.budget_min,
                "budget_max":       t.budget_max,
                "ai_score":         t.ai_score,
                "ai_category":      t.ai_category,
                "ai_reason":        t.ai_reason,
            }
            if ScraperAgent._save(td):
                saved += 1
                if t.statut == "actif":
                    notify_list.append(td)

        ScraperLog.add(f"[MultiScraper] ✅ {saved} sauvegardés / {len(tenders)} trouvés")
        if notify_list:
            NotifyAgent.notify_instant(notify_list)

    except Exception as e:
        logger.error(f"[multi_scraper] {e}")
        ScraperLog.add(f"[MultiScraper] ✗ {str(e)[:100]}")

async def digest_scheduler():
    while True:
        now  = datetime.now()
        next = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= next: next += timedelta(days=1)
        wait = (next - now).total_seconds()
        logger.info(f"[scheduler:digest] next in {wait/3600:.1f}h")
        await asyncio.sleep(wait)
        try:
            NotifyAgent.notify_digest()
        except Exception as e:
            logger.error(f"[scheduler:digest] {e}")

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
    logger.info(f"✅ {BRAND} v3.0 — All agents started")
    yield

app = FastAPI(lifespan=lifespan, title=BRAND, version="3.0", docs_url=None, redoc_url=None)
app.add_middleware(SecureMiddleware)

try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

try:
    os.makedirs("templates", exist_ok=True)
    tpl = Jinja2Templates(directory="templates")
except: tpl = None

def render(req: Request, tmpl: str, ctx: dict = {}):
    if not tpl: return HTMLResponse("<h1>Template error</h1>", 500)
    try:
        return tpl.TemplateResponse(tmpl, {
            "request":      req,
            "BRAND":        BRAND,
            "SITE_URL":     SITE_URL,
            "SECTEURS_LIST":SECTEURS_LIST,
            "member":       get_member(req),
            "now":          datetime.now(),
            "GA_ID":        GA_ID,
            "GSC_TOKEN":    GSC_TOKEN,
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
        stats = MonitorAgent.get_stats()
        lr = db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally: db.close()
    counter("pv:home")
    return render(req, "landing.html", {"stats": stats, "last_run": dict(lr) if lr else {}, "scrape_h": SCRAPE_HOURS})

@app.get("/marketplace", response_class=HTMLResponse)
async def marketplace(req: Request, type_f="", secteur_f="", region_f="", q="", page: int=1):
    per = 16; off = (page-1)*per
    db = get_db()
    try:
        conds = ["p.status='actif'"]; params = []
        if type_f:    conds.append("p.type=?");    params.append(type_f)
        if secteur_f: conds.append("p.secteur=?"); params.append(secteur_f)
        if region_f:  conds.append("p.region=?");  params.append(region_f)
        if q:
            conds.append("(p.titre LIKE ? OR p.description LIKE ?)")
            params += [f"%{q[:80]}%"]*2
        w = " AND ".join(conds)
        total = db.execute(f"SELECT COUNT(*) FROM posts p WHERE {w}", params).fetchone()[0]
        posts = [dict(r) for r in db.execute(
            f"""SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,m.rating_count,m.verified
                FROM posts p JOIN members m ON m.id=p.member_id
                WHERE {w} ORDER BY p.id DESC LIMIT ? OFFSET ?""",
            params + [per, off]).fetchall()]
    finally: db.close()
    counter("pv:marketplace")
    return render(req, "marketplace.html", {
        "posts":posts,"total":total,"page":page,"pages":max(1,(total+per-1)//per),
        "type_f":type_f,"secteur_f":secteur_f,"region_f":region_f,"q":q,
        "REGIONS_LIST":list(REGIONS.keys()),
    })

@app.get("/marketplace/new", response_class=HTMLResponse)
async def mp_new_get(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req, "marketplace_new.html", {"error":""})

@app.post("/marketplace/new")
async def mp_new_post(req: Request, titre:str=Form(""), description:str=Form(""),
    type_p:str=Form("offre"), secteur:str=Form(""), region:str=Form(""),
    budget:str=Form(""), contact:str=Form("")):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    rl(req,"mp_new",5,3600)
    if len(titre.strip()) < 10:
        return render(req, "marketplace_new.html", {"error":"Titre trop court (min 10 caractères)"})
    db = get_db()
    try:
        db.execute("""INSERT INTO posts (member_id,type,titre,description,secteur,region,budget,contact,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (m["id"],type_p,titre.strip()[:200],description.strip()[:3000],
             secteur,region,budget.strip()[:60],contact.strip()[:100],now_str()))
        db.commit()
    finally: db.close()
    return RedirectResponse("/marketplace",302)

@app.get("/marketplace/post/{pid}", response_class=HTMLResponse)
async def mp_detail(req: Request, pid: int):
    db = get_db()
    try:
        row = db.execute("""SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,
                            m.rating_count,m.verified,m.phone,m.email as m_email
                            FROM posts p JOIN members m ON m.id=p.member_id
                            WHERE p.id=? AND p.status='actif'""",(pid,)).fetchone()
        if not row: raise HTTPException(404)
        post = dict(row)
        db.execute("UPDATE posts SET views=COALESCE(views,0)+1 WHERE id=?",(pid,))
        db.commit()
        ratings = [dict(r) for r in db.execute(
            "SELECT r.*,m.nom as from_nom FROM ratings r JOIN members m ON m.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 10",
            (post["member_id"],)).fetchall()]
        cur = get_member(req)
        can_rate = cur and cur["id"] != post["member_id"]
        already  = cur and bool(db.execute("SELECT 1 FROM ratings WHERE from_id=? AND to_id=?",
                                           (cur["id"],post["member_id"])).fetchone())
    finally: db.close()
    return render(req,"marketplace_detail.html",{"post":post,"ratings":ratings,"can_rate":can_rate,"already_rated":already})

@app.post("/marketplace/rate/{mid}")
async def mp_rate(req: Request, mid: int, score:int=Form(5), comment:str=Form("")):
    cur = get_member(req)
    if not cur: return RedirectResponse("/login",302)
    if cur["id"] == mid: raise HTTPException(400)
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO ratings (from_id,to_id,score,comment,created_at) VALUES (?,?,?,?,?)",
                   (cur["id"],mid,max(1,min(5,score)),comment.strip()[:300],now_str()))
        db.commit()
        avg = db.execute("SELECT AVG(score),COUNT(*) FROM ratings WHERE to_id=?",(mid,)).fetchone()
        db.execute("UPDATE members SET rating_avg=?,rating_count=? WHERE id=?",(round(avg[0],1),avg[1],mid))
        db.commit()
    finally: db.close()
    return RedirectResponse(req.headers.get("referer","/marketplace"),302)

@app.get("/annuaire", response_class=HTMLResponse)
async def annuaire(req: Request, secteur_f="", q=""):
    db = get_db()
    try:
        conds = ["actif=1"]; params = []
        if secteur_f: conds.append("secteur=?"); params.append(secteur_f)
        if q: conds.append("(nom LIKE ? OR entreprise LIKE ? OR ville LIKE ?)"); params+=[f"%{q}%"]*3
        members = [dict(r) for r in db.execute(
            f"SELECT * FROM members WHERE {' AND '.join(conds)} ORDER BY rating_avg DESC,id DESC LIMIT 60",
            params).fetchall()]
    finally: db.close()
    return render(req,"annuaire.html",{"members":members,"secteur_f":secteur_f,"q":q})

# ── AUTH ──
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{"error":""})

@app.post("/register")
async def register_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    email:str=Form(""), phone:str=Form(""), secteur:str=Form(""),
    ville:str=Form(""), password:str=Form("")):
    rl(req,"register",8,3600)
    error = ""
    if not all([nom,email,password]): error = "Champs * obligatoires"
    elif len(password) < 8: error = "Mot de passe: minimum 8 caractères"
    elif not re.match(r'^[^@]+@[^@]+\.[^@]+$',email): error = "Email invalide"
    else:
        db = get_db()
        try:
            if db.execute("SELECT 1 FROM members WHERE email=?",(email.lower(),)).fetchone():
                error = "Email déjà utilisé"
            else:
                db.execute("""INSERT INTO members
                    (nom,entreprise,email,phone,secteur,ville,pw_hash,actif,created_at)
                    VALUES (?,?,?,?,?,?,?,1,?)""",
                    (nom.strip(),entreprise.strip(),email.lower().strip(),
                     phone.strip(),secteur,ville.strip(),hash_pw(password),now_str()))
                db.commit()
                uid = db.execute("SELECT id FROM members WHERE email=?",(email.lower(),)).fetchone()[0]
                db.close()
                counter("registrations")
                welcome_html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#080808">
<div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:28px;max-width:500px;margin:0 auto;border-radius:10px">
  <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
  <h2 style="color:#f0ede6;margin-bottom:10px">Bienvenue, {nom}! 🎉</h2>
  <p style="color:#aaa;font-size:13px;margin-bottom:20px">Votre compte est activé. Accédez au marketplace et publiez vos annonces.</p>
  <a href="{SITE_URL}/dashboard" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Accéder à mon espace →</a>
  <p style="color:#555;font-size:11px;margin-top:16px">Modern Business · {SITE_URL}</p>
</div></body></html>'''
                NotifyAgent.enqueue(uid, "email", email, f"Bienvenue sur {BRAND}!", welcome_html)
                resp = RedirectResponse("/dashboard",302)
                session_create(resp,uid)
                return resp
        except Exception as e:
            error = f"Erreur: {e}"
        finally:
            try: db.close()
            except: pass
    return render(req,"register.html",{"error":error})

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"login.html",{"error":""})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), password:str=Form("")):
    rl(req,f"login:{get_ip(req)}",5,300)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
        if not row or not check_pw(password,dict(row).get("pw_hash","")):
            return render(req,"login.html",{"error":"Email ou mot de passe incorrect"})
        m = dict(row)
        db.execute("UPDATE members SET last_login=? WHERE id=?",(now_str(),m["id"]))
        db.commit()
    finally: db.close()
    counter("logins")
    resp = RedirectResponse("/dashboard",302)
    session_create(resp,m["id"])
    return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/",302)
    session_delete(resp)
    return resp

# ── FILTER ROUTES ──
@app.get("/filters", response_class=HTMLResponse)
async def filters_get(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    db = get_db()
    try:
        my_filters = [dict(r) for r in db.execute(
            "SELECT * FROM member_filters WHERE member_id=? ORDER BY type,value",
            (m["id"],)
        ).fetchall()]
    finally: db.close()
    return render(req, "filters.html", {"m":m,"my_filters":my_filters})

@app.post("/filters/add")
async def filters_add(req: Request, ftype:str=Form(""), value:str=Form("")):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    if ftype in ["secteur","region","keyword"] and value.strip():
        db = get_db()
        try:
            db.execute("INSERT OR IGNORE INTO member_filters (member_id,type,value,created_at) VALUES (?,?,?,?)",
                       (m["id"], ftype, value.strip()[:80], now_str()))
            db.commit()
        finally: db.close()
    return RedirectResponse("/filters",302)

@app.post("/filters/delete")
async def filters_delete(req: Request, fid:int=Form(0)):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    db = get_db()
    try:
        db.execute("DELETE FROM member_filters WHERE id=? AND member_id=?",(fid,m["id"]))
        db.commit()
    finally: db.close()
    return RedirectResponse("/filters",302)

@app.get("/api/my_filters")
async def api_my_filters(req: Request):
    m = get_member(req)
    if not m: return JSONResponse({"error":"Non connecté"},401)
    db = get_db()
    try:
        filters = [dict(r) for r in db.execute(
            "SELECT id,type,value FROM member_filters WHERE member_id=?",(m["id"],)
        ).fetchall()]
    finally: db.close()
    return JSONResponse({"filters":filters})

# ── DASHBOARD ──
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    db = get_db()
    try:
        my_posts = [dict(r) for r in db.execute(
            "SELECT * FROM posts WHERE member_id=? ORDER BY id DESC LIMIT 5",(m["id"],)).fetchall()]
        my_ratings = [dict(r) for r in db.execute(
            "SELECT r.*,mem.nom as from_nom FROM ratings r JOIN members mem ON mem.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 5",
            (m["id"],)).fetchall()]
        stats = MonitorAgent.get_stats()
    finally: db.close()
    counter("pv:dashboard")
    return render(req,"dashboard.html",{"m":m,"my_posts":my_posts,"my_ratings":my_ratings,"stats":stats})

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"settings.html",{"m":m,"success":"","error":""})

@app.post("/settings")
async def settings_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    phone:str=Form(""), secteur:str=Form(""), ville:str=Form(""),
    notif_email:str=Form(""), notif_tg:str=Form(""),
    password:str=Form(""), password_new:str=Form("")):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    error = ""
    db = get_db()
    try:
        db.execute("""UPDATE members SET nom=?,entreprise=?,phone=?,secteur=?,ville=?,
            notif_email=?,notif_tg=? WHERE id=?""",
            (nom.strip() or m["nom"],entreprise.strip(),phone.strip(),secteur,ville.strip(),
             1 if notif_email else 0, 1 if notif_tg else 0, m["id"]))
        if password and password_new:
            if not check_pw(password,m.get("pw_hash","")): error = "Mot de passe actuel incorrect"
            elif len(password_new) < 8: error = "Nouveau mot de passe trop court"
            else: db.execute("UPDATE members SET pw_hash=? WHERE id=?",(hash_pw(password_new),m["id"]))
        db.commit()
    finally: db.close()
    m = get_member(req)
    return render(req,"settings.html",{"m":m,"success":"Sauvegardé ✓" if not error else "","error":error})

# ── CONTACT ──
@app.get("/contact", response_class=HTMLResponse)
async def contact(req: Request):
    return render(req,"contact.html",{})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(req: Request):
    return render(req,"privacy.html",{})

# ══════════════════════════════════════════════════════
# API — CHAT
# ══════════════════════════════════════════════════════
@app.post("/api/chat")
async def api_chat(req: Request):
    rl(req,f"chat:{get_ip(req)}",20,60)
    try:
        data = await req.json()
        user_msg = str(data.get("message",""))[:800].strip()
        sess_key = data.get("session_key", get_ip(req))[:50]
        if not user_msg: return JSONResponse({"error":"Message vide"},400)

        db = get_db()
        try:
            rows = db.execute(
                "SELECT role,content FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 16",
                (sess_key,)).fetchall()
            history = [{"role":r["role"],"content":r["content"]} for r in reversed(rows)]
        finally: db.close()

        history.append({"role":"user","content":user_msg})
        response = await ChatAgent.respond(history)

        db = get_db()
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",
                       (sess_key,"user",user_msg,ts))
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",
                       (sess_key,"assistant",response,ts))
            db.execute("DELETE FROM chats WHERE session_key=? AND id NOT IN "
                       "(SELECT id FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 40)",
                       (sess_key,sess_key))
            db.commit()
        finally: db.close()

        counter("chat_messages")
        return JSONResponse({"response":response,"session_key":sess_key})
    except Exception as e:
        logger.error(f"[api:chat] {e}")
        return JSONResponse({"error":"Erreur serveur"},500)

@app.post("/api/consent")
async def api_consent(): return JSONResponse({"ok":True})

@app.get("/api/stats")
async def api_stats():
    return JSONResponse(MonitorAgent.get_stats())

# ── REST API v1 — Public tenders ──
@app.get("/api/v1/tenders")
async def api_tenders(
    q: str = "", category: str = "", region: str = "",
    source: str = "", min_score: int = 0,
    page: int = 1, per_page: int = 20
):
    """Public REST API — all active tenders"""
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page
    db = get_db()
    try:
        conds = ["statut='actif'"]; params = []
        if q:        conds.append("(objet LIKE ? OR description LIKE ?)"); params += [f"%{q}%"]*2
        if category: conds.append("domaine LIKE ?"); params.append(f"%{category}%")
        if region:   conds.append("region LIKE ?");  params.append(f"%{region}%")
        if source:   conds.append("source=?");       params.append(source)
        if min_score > 0: conds.append("ai_score >= ?"); params.append(min_score)
        w = " AND ".join(conds)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
        rows = [dict(r) for r in db.execute(
            f"SELECT id,objet,acheteur,region,domaine,type_marche,montant,"
            f"date_publication,date_limite,statut,url,source,contact,"
            f"ai_score,ai_label,date_extraction FROM tenders WHERE {w} "
            f"ORDER BY date_extraction DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]).fetchall()]
    finally: db.close()
    return JSONResponse({
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, (total+per_page-1)//per_page),
        "tenders": rows
    })

@app.get("/api/v1/tenders/new")
async def api_tenders_new(hours: int = 24):
    """Tenders added in the last N hours"""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    db = get_db()
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT id,objet,region,domaine,montant,date_limite,url,source,ai_score,ai_label "
            "FROM tenders WHERE statut='actif' AND date_extraction >= ? "
            "ORDER BY date_extraction DESC LIMIT 100", (since,)).fetchall()]
    finally: db.close()
    return JSONResponse({"since": since, "count": len(rows), "tenders": rows})

@app.get("/api/v1/tenders/filter")
async def api_tenders_filter(city: str = "", category: str = "", score_min: int = 0):
    """Filter tenders by city + category + AI score"""
    db = get_db()
    try:
        conds = ["statut='actif'"]; params = []
        if city:      conds.append("region LIKE ?");  params.append(f"%{city}%")
        if category:  conds.append("domaine LIKE ?"); params.append(f"%{category}%")
        if score_min: conds.append("ai_score >= ?");  params.append(score_min)
        rows = [dict(r) for r in db.execute(
            f"SELECT id,objet,region,domaine,montant,date_limite,url,source,"
            f"contact,ai_score,ai_label,ai_reasons FROM tenders WHERE "
            f"{' AND '.join(conds)} ORDER BY ai_score DESC,date_extraction DESC LIMIT 50",
            params).fetchall()]
    finally: db.close()
    return JSONResponse({"count": len(rows), "tenders": rows})

@app.get("/api/v1/sources")
async def api_sources():
    """List all sources and their tender counts"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT source, COUNT(*) as count, MAX(date_extraction) as last_update "
            "FROM tenders GROUP BY source ORDER BY count DESC"
        ).fetchall()
    finally: db.close()
    return JSONResponse({"sources": [dict(r) for r in rows]})

# ══════════════════════════════════════════════════════
# TELEGRAM WEBHOOK
# ══════════════════════════════════════════════════════
@app.post("/telegram/webhook")
async def tg_webhook(req: Request):
    try:
        data = await req.json()
        msg = data.get("message") or data.get("edited_message") or {}
        if not msg: return {"ok":True}

        chat_id  = str(msg.get("chat",{}).get("id",""))
        text     = (msg.get("text") or "").strip()
        if not chat_id: return {"ok":True}

        async def reply(txt):
            await NotifyAgent.send_telegram(chat_id, txt)

        # REGISTER shortcut
        if text.lower() in ["/register", "/inscription"]:
            await reply(
                f"📝 Inscrivez-vous ici:\n{SITE_URL}/register\n\n"
                f"Après inscription, revenez et envoyez:\n"
                f"<code>/link votre@email.com</code>"
            )
            return {"ok": True}

        # AUTO-LINK: /link email@...
        if text.lower().startswith("/link ") and "@" in text:
            email = text.split()[1].strip().lower()
            db = get_db()
            try:
                row = db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",(email,)).fetchone()
                if row:
                    db.execute("UPDATE members SET telegram=? WHERE id=?",(chat_id,row["id"]))
                    db.commit()
                    await reply(
                        f"✅ <b>Alertes activées!</b>\n\n"
                        f"Bonjour {row['nom']}! Vous recevrez les notifications "
                        f"des nouveaux marchés dès leur publication.\n\n"
                        f"🌐 {SITE_URL}"
                    )
                else:
                    await reply(
                        f"❌ Email non trouvé.\n\n"
                        f"Inscrivez-vous d'abord sur {SITE_URL}/register\n"
                        f"puis envoyez: /link votre@email.com"
                    )
            finally: db.close()
            return {"ok":True}

        if text in ["/start","start"]:
            await reply(
                f"🏛 <b>Modern Business</b>\n"
                f"Intelligence des Marchés Publics — Maroc\n\n"
                f"<b>Commandes:</b>\n"
                f"/link email@... — Activer les alertes 🔔\n"
                f"/secteur [nom] — Filtrer par secteur 🏷\n"
                f"/region [nom] — Filtrer par région 📍\n"
                f"/mes_filtres — Voir mes filtres ⚙️\n"
                f"/tenders — 5 derniers marchés\n"
                f"/stats — Statistiques\n\n"
                f"💡 Étapes:\n"
                f"1️⃣ /link votre@email.com\n"
                f"2️⃣ /secteur Bâtiment & Construction\n"
                f"3️⃣ Recevez les marchés qui vous correspondent!\n\n"
                f"🌐 {SITE_URL}"
            )
        elif text.startswith("/secteur "):
            # /secteur Bâtiment & Construction
            val = text[9:].strip()
            if val:
                db = get_db()
                try:
                    row = db.execute("SELECT id,nom FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                    if row:
                        db.execute("INSERT OR IGNORE INTO member_filters (member_id,type,value,created_at) VALUES (?,?,?,?)",
                                   (row["id"],"secteur",val,now_str()))
                        db.commit()
                        await tg_send(chat_id,f"✅ Filtre ajouté: <b>{val}</b>\nVous recevrez les marchés de ce secteur.\n\nUtilisez /mes_filtres pour voir tous vos filtres.")
                    else:
                        await tg_send(chat_id,f"❌ Compte non lié. Envoyez d'abord:\n/link votre@email.com")
                except Exception as e:
                    await tg_send(chat_id,f"Erreur: {e}")
                finally: db.close()
            return {"ok":True}

        elif text.startswith("/region "):
            val = text[8:].strip()
            if val:
                db = get_db()
                try:
                    row = db.execute("SELECT id FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                    if row:
                        db.execute("INSERT OR IGNORE INTO member_filters (member_id,type,value,created_at) VALUES (?,?,?,?)",
                                   (row["id"],"region",val,now_str()))
                        db.commit()
                        await tg_send(chat_id,f"✅ Région ajoutée: <b>{val}</b>")
                    else:
                        await tg_send(chat_id,"❌ Compte non lié. Envoyez /link votre@email.com")
                except Exception as e:
                    await tg_send(chat_id,f"Erreur: {e}")
                finally: db.close()
            return {"ok":True}

        elif text == "/mes_filtres":
            db = get_db()
            try:
                row = db.execute("SELECT id FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                if row:
                    filters = db.execute("SELECT type,value FROM member_filters WHERE member_id=?",(row["id"],)).fetchall()
                    if filters:
                        lines = ["⚙️ <b>Vos filtres actifs</b>\n"]
                        for f in filters:
                            icon = "🏷" if f["type"]=="secteur" else ("📍" if f["type"]=="region" else "🔍")
                            lines.append(f"{icon} {f['type']}: <b>{f['value']}</b>")
                        lines.append(f"\n💡 Gérer sur {SITE_URL}/filters")
                        await tg_send(chat_id,"\n".join(lines))
                    else:
                        await tg_send(chat_id,
                            f"Aucun filtre — vous recevez <b>tous</b> les marchés.\n\n"
                            f"Pour filtrer par secteur:\n<code>/secteur Bâtiment & Construction</code>\n\n"
                            f"Pour filtrer par région:\n<code>/region Casablanca-Settat</code>\n\n"
                            f"Gérer sur {SITE_URL}/filters")
                else:
                    await tg_send(chat_id,"❌ Compte non lié. Envoyez /link votre@email.com")
            except Exception as e:
                await tg_send(chat_id,f"Erreur: {e}")
            finally: db.close()
            return {"ok":True}

        elif text == "/tenders":
            db = get_db()
            try:
                rows = db.execute(
                    "SELECT objet,acheteur,region,domaine,date_limite,url FROM tenders "
                    "WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 5"
                ).fetchall()
            finally: db.close()
            if rows:
                lines = [f"🏛 <b>5 derniers marchés actifs</b>\n{'━'*28}"]
                for r in rows:
                    t = dict(r)
                    b = f"\n📋 <b>{t.get('objet','')[:60]}</b>"
                    if t.get("acheteur"):    b += f"\n   🏢 {t['acheteur'][:45]}"
                    if t.get("region"):      b += f"\n   📍 {t['region']}"
                    if t.get("domaine"):     b += f"\n   🏷 {t['domaine']}"
                    if t.get("date_limite"): b += f"\n   ⏰ <b>{t['date_limite']}</b>"
                    if t.get("url"):         b += f"\n   🔗 {t['url']}"
                    lines.append(b)
                lines.append(f"\n🌐 {SITE_URL}")
                await reply("\n".join(lines))
            else:
                await reply(f"Aucun marché actif.\nLancez le scraper depuis l'admin.\n🌐 {SITE_URL}")
        elif text == "/stats":
            st = MonitorAgent.get_stats()
            await reply(
                f"📊 <b>Modern Business — Stats</b>\n\n"
                f"✅ Marchés actifs: <b>{st['tenders_active']}</b>\n"
                f"📦 Total indexés: <b>{st['tenders_total']}</b>\n"
                f"🏢 Membres: <b>{st['members']}</b>\n"
                f"🔔 Abonnés TG: <b>{st['members_tg']}</b>\n"
                f"📬 Notifs en attente: <b>{st['notif_pending']}</b>\n"
                f"✉️ Notifs envoyées: <b>{st['notif_sent']}</b>\n\n"
                f"🌐 {SITE_URL}"
            )
        elif text == "/help":
            await reply(
                f"ℹ️ <b>Modern Business — Aide</b>\n\n"
                f"/start — Menu principal\n"
                f"/link email@... — Activer les alertes\n"
                f"/secteur [nom] — Ajouter filtre secteur\n"
                f"/region [nom] — Ajouter filtre région\n"
                f"/mes_filtres — Voir mes filtres actifs\n"
                f"/tenders — 5 derniers marchés actifs\n"
                f"/stats — Statistiques\n\n"
                f"🏷 Secteurs disponibles:\nBâtiment, Génie Civil, Hydraulique, Informatique,\n"
                f"Santé, Transport, Alimentation, Formation...\n\n"
                f"📩 {SITE_URL}/contact"
            )
        else:
            await reply(f"Envoyez /start pour le menu.\n🌐 {SITE_URL}")
    except Exception as e:
        logger.error(f"[tg:webhook] {e}")
    return {"ok":True}

# ══════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════
def chk(pwd: str):
    if pwd != ADMIN_PASS:
        counter("admin_fail")
        raise HTTPException(403, "Accès refusé")

@app.get("/admin", response_class=HTMLResponse)
async def admin(req: Request, pwd: str=""):
    chk(pwd)
    db = get_db()
    try:
        stats   = MonitorAgent.get_stats()
        tenders = [dict(r) for r in db.execute("SELECT * FROM tenders ORDER BY date_extraction DESC LIMIT 50").fetchall()]
        members = [dict(r) for r in db.execute("SELECT * FROM members ORDER BY id DESC LIMIT 20").fetchall()]
        hist    = [dict(r) for r in db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 8").fetchall()]
        errors  = [dict(r) for r in db.execute("SELECT * FROM agent_errors WHERE resolved=0 ORDER BY last_seen DESC LIMIT 10").fetchall()]
        notifs  = [dict(r) for r in db.execute("SELECT * FROM notif_queue ORDER BY id DESC LIMIT 30").fetchall()]
    finally: db.close()
    return render(req,"admin.html",{
        "stats":stats,"tenders":tenders,"members":members,
        "hist":hist,"errors":errors,"notifs":notifs,
        "scrape_state":ScraperState,"scrape_log":ScraperLog.last(80),"pwd":pwd,
    })

@app.get("/admin/scrape")
async def admin_scrape(pwd: str=""):
    chk(pwd)
    if ScraperState.running:
        return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    async def _run():
        loop = asyncio.get_event_loop()
        try:
            new = await loop.run_in_executor(None, ScraperAgent.run)
            if new: NotifyAgent.notify_instant(new)
        finally: ScraperState.running = False
    asyncio.create_task(_run())
    return JSONResponse({"ok":True,"msg":"ScraperAgent marchespublics.gov.ma démarré"})

@app.get("/admin/scrape_multi")
async def admin_scrape_multi(pwd: str=""):
    """Launch multi-site scraper (4 private sites)"""
    chk(pwd)
    async def _run():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_multi_scraper)
    asyncio.create_task(_run())
    return JSONResponse({"ok":True,"msg":"MultiScraper démarré: marocao.com, lesoffres.ma, aljady.ma, marchesprives.ma"})

@app.get("/admin/set_whatsapp")
async def admin_set_whatsapp(pwd: str="", email: str="", wa: str=""):
    """Link WhatsApp number to member"""
    chk(pwd)
    if not wa.startswith("+"): wa = "+" + wa
    db = get_db()
    try:
        db.execute("UPDATE members SET whatsapp=? WHERE email=?", (wa, email.lower()))
        db.commit()
        ch = db.execute("SELECT changes()").fetchone()[0]
    finally: db.close()
    return JSONResponse({"ok": bool(ch), "whatsapp": wa})

@app.get("/admin/scrape_stream")
async def scrape_stream(pwd: str=""):
    chk(pwd)
    async def gen():
        last = 0
        while True:
            logs = ScraperLog.entries[last:]
            for log in logs:
                state = {
                    "running":ScraperState.running, "found":ScraperState.found,
                    "saved":ScraperState.saved, "errors":ScraperState.errors,
                    "current":ScraperState.current, "total":ScraperState.total,
                }
                yield f"data: {json.dumps({'log':log,'state':state})}\n\n"
            last = len(ScraperLog.entries)
            if not ScraperState.running and last > 0:
                yield f"data: {json.dumps({'done':True,'state':{'saved':ScraperState.saved}})}\n\n"
                break
            await asyncio.sleep(0.7)
    return StreamingResponse(gen(), media_type="text/event-stream",
                              headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/admin/test_notify")
async def admin_test_notify(pwd: str="", chat_id: str=""):
    chk(pwd)
    try:
        sample = [
            {
                "objet": "Fourniture materiel informatique 20 PC bureau HP EliteDesk",
                "acheteur": "Commune Urbaine de Rabat Direction des Achats",
                "region": "Rabat-Sale-Kenitra",
                "domaine": "Informatique et Telecoms",
                "type_marche": "Fournitures",
                "montant": "280 000 DH",
                "date_publication": datetime.now().strftime("%d/%m/%Y"),
                "date_limite": (datetime.now()+timedelta(days=14)).strftime("%d/%m/%Y"),
                "url": "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/46205",
            },
            {
                "objet": "Travaux entretien voiries Lot 3 Sud",
                "acheteur": "Ministere de l Interieur Direction Regionale Casablanca",
                "region": "Casablanca-Settat",
                "domaine": "Genie Civil Routes",
                "type_marche": "Travaux",
                "montant": "1 200 000 DH",
                "date_publication": datetime.now().strftime("%d/%m/%Y"),
                "date_limite": (datetime.now()+timedelta(days=21)).strftime("%d/%m/%Y"),
                "url": "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/",
            },
        ]

        results = {}

        # Test Telegram direct
        if chat_id:
            try:
                tg_msg = NotifyAgent.build_telegram(sample, "TEST Modern Business Notification Agent")
                ok, err = await NotifyAgent.send_telegram(chat_id, tg_msg)
                results["telegram"] = "ok" if ok else f"error: {err}"
            except Exception as e:
                results["telegram"] = f"exception: {str(e)}"

        # Test email
        try:
            html = NotifyAgent.build_email(sample, "TEST Modern Business Notification Agent")
            ok, err = await NotifyAgent.send_email(
                GMAIL_USER,
                "TEST Notifications Modern Business",
                html
            )
            results["email"] = "ok" if ok else f"error: {err[:100]}"
        except Exception as e:
            results["email"] = f"exception: {str(e)[:100]}"

        # Queue stats
        try:
            db = get_db()
            results["queue_pending"] = db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0]
            results["queue_sent"]    = db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0]
            results["queue_failed"]  = db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0]
            results["members_total"] = db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]
            results["members_tg"]    = db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0]
            db.close()
        except Exception as e:
            results["db_error"] = str(e)

        return JSONResponse({"ok": True, "results": results})

    except Exception as e:
        logger.error(f"[test_notify] {e}\n{traceback.format_exc()}")
        return JSONResponse({"ok": False, "error": str(e)}, 500)

@app.get("/admin/test_digest")
async def admin_test_digest(pwd: str=""):
    chk(pwd)
    NotifyAgent.notify_digest()
    return JSONResponse({"ok":True,"msg":"Digest mis en file"})

@app.get("/admin/set_telegram")
async def admin_set_tg(pwd: str="", email: str="", chat_id: str=""):
    chk(pwd)
    db = get_db()
    try:
        db.execute("UPDATE members SET telegram=? WHERE email=?",(chat_id,email.lower().strip()))
        db.commit()
        ch = db.execute("SELECT changes()").fetchone()[0]
        member = db.execute("SELECT nom FROM members WHERE email=?", (email.lower().strip(),)).fetchone()
    finally: db.close()
    name = dict(member)["nom"] if member else "?"
    # Send confirmation via Telegram
    if ch and chat_id:
        asyncio.create_task(NotifyAgent.send_telegram(chat_id,
            f"✅ <b>Alertes activées, {name}!</b>\n\n"
            f"Vous recevrez désormais les notifications des nouveaux marchés "
            f"dès leur publication sur marchespublics.gov.ma\n\n"
            f"🌐 {SITE_URL}"
        ))
    return JSONResponse({"ok":bool(ch),"updated":ch,"member":name})

@app.get("/admin/broadcast_tg")
async def admin_broadcast_tg(pwd: str="", msg: str=""):
    """Envoyer un message Telegram à tous les abonnés"""
    chk(pwd)
    if not msg: return JSONResponse({"ok":False,"msg":"Paramètre msg requis"})
    db = get_db()
    try:
        subs = [dict(r) for r in db.execute(
            "SELECT id,nom,telegram FROM members WHERE telegram!='' AND actif=1"
        ).fetchall()]
    finally: db.close()
    sent = 0
    for sub in subs:
        ok, _ = await NotifyAgent.send_telegram(sub["telegram"], msg)
        if ok: sent += 1
    return JSONResponse({"ok":True,"sent":sent,"total":len(subs)})

@app.get("/admin/activate")
async def admin_activate(pwd: str="", member_id: int=0, plan: str="pro"):
    chk(pwd)
    db = get_db()
    try:
        db.execute("UPDATE members SET plan=?,verified=1 WHERE id=?",(plan,member_id))
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/delete_tender")
async def admin_del_tender(pwd: str="", tid: str=""):
    chk(pwd)
    db = get_db()
    try: db.execute("DELETE FROM tenders WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/resolve_error")
async def admin_resolve(pwd: str="", eid: int=0):
    chk(pwd)
    db = get_db()
    try: db.execute("UPDATE agent_errors SET resolved=1 WHERE id=?",(eid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/migrate")
async def admin_migrate(pwd: str=""):
    """Force migrate contractors -> members + set known telegrams"""
    chk(pwd)
    db = get_db()
    try:
        migrated = 0
        # Try contractors table
        old_table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='contractors'"
        ).fetchone()
        if old_table:
            db.execute("""INSERT OR IGNORE INTO members
                (id,nom,entreprise,email,phone,secteur,ville,pw_hash,
                 telegram,plan,actif,verified,rating_avg,rating_count,
                 notif_email,notif_tg,created_at,last_login)
                SELECT id,nom,COALESCE(entreprise,''),email,
                    COALESCE(phone,''),COALESCE(secteur,''),COALESCE(ville,''),
                    COALESCE(password_hash,''),COALESCE(telegram,''),
                    COALESCE(plan,'free'),COALESCE(actif,1),COALESCE(verified,0),
                    COALESCE(rating_avg,0),COALESCE(rating_count,0),
                    1,1,COALESCE(created_at,''),COALESCE(last_login,'')
                FROM contractors WHERE actif=1""")
            db.commit()

        # Always ensure known admins exist
        known = [
            ("mohamed el montassir","","mohamedelmontassir439@gmail.com","","","","","6424992854"),
            ("AYOUB","","ayyoubelaarbi@gmail.com","","","","",""),
        ]
        for nom,ent,email,phone,sect,ville,pw,tg in known:
            existing = db.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone()
            if not existing:
                db.execute("""INSERT INTO members
                    (nom,entreprise,email,phone,secteur,ville,pw_hash,
                     telegram,plan,actif,notif_email,notif_tg,created_at)
                    VALUES (?,?,?,?,?,?,?,?,'free',1,1,1,?)""",
                    (nom,ent,email,phone,sect,ville,pw,tg,now_str()))
            else:
                if tg:
                    db.execute("UPDATE members SET telegram=? WHERE email=? AND (telegram IS NULL OR telegram='')",
                               (tg,email))
        db.commit()

        members = [dict(r) for r in db.execute(
            "SELECT id,nom,email,telegram FROM members WHERE actif=1"
        ).fetchall()]
    finally: db.close()
    return JSONResponse({"ok":True,"members":members})

@app.get("/admin/cleanup")
async def admin_cleanup(pwd: str=""):
    chk(pwd)
    db = get_db()
    try:
        db.execute("DELETE FROM tenders WHERE statut IN ('expire','annule') AND date_extraction < date('now','-60 days')")
        db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
        db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
        r = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"tenders_remaining":r})

@app.get("/admin/notify_status")
async def admin_notify_status(pwd: str=""):
    chk(pwd)
    db = get_db()
    try:
        members = [dict(r) for r in db.execute(
            "SELECT id,nom,email,telegram,notif_email,notif_tg FROM members WHERE actif=1"
        ).fetchall()]
        queue = [dict(r) for r in db.execute(
            "SELECT channel,status,recipient,error,attempts,created_at FROM notif_queue ORDER BY id DESC LIMIT 20"
        ).fetchall()]
    finally: db.close()
    return JSONResponse({
        "gmail_configured": bool(GMAIL_PASS and len(GMAIL_PASS) >= 8),
        "telegram_configured": bool(TELEGRAM_BOT),
        "anthropic_configured": bool(ANTHROPIC_KEY),
        "members": [{"nom":m["nom"],"email":m["email"],
                     "telegram":m["telegram"] or "❌ non configuré",
                     "notif_email":bool(m["notif_email"]),"notif_tg":bool(m["notif_tg"])} for m in members],
        "queue_last20": queue,
    })

# ══════════════════════════════════════════════════════
# INFRA
# ══════════════════════════════════════════════════════
# ── PASSWORD RESET ──
RESET_TOKENS: dict = {}  # token -> {email, expires}

@app.get("/forgot", response_class=HTMLResponse)
async def forgot_get(req: Request):
    return render(req, "forgot.html", {"sent": False, "error": ""})

@app.post("/forgot", response_class=HTMLResponse)
async def forgot_post(req: Request, email: str = Form("")):
    rl(req, "forgot", 3, 3600)
    db = get_db()
    try:
        row = db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",
                         (email.lower().strip(),)).fetchone()
    finally: db.close()

    if row:
        token = secrets.token_urlsafe(32)
        RESET_TOKENS[token] = {
            "email":   email.lower().strip(),
            "expires": datetime.now() + timedelta(hours=2)
        }
        reset_url = f"{SITE_URL}/reset?token={token}"
        html = f"""<div style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:28px;border-radius:10px;max-width:500px">
        <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
        <div style="font-size:15px;font-weight:700;margin-bottom:10px">Réinitialisation du mot de passe</div>
        <div style="font-size:13px;color:#aaa;margin-bottom:20px">Bonjour {dict(row)['nom']}, cliquez ci-dessous pour réinitialiser votre mot de passe (valide 2h).</div>
        <a href="{reset_url}" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Réinitialiser →</a>
        <div style="font-size:11px;color:#555;margin-top:16px">Si vous n'avez pas fait cette demande, ignorez cet email.</div>
        </div>"""
        NotifyAgent.enqueue(None, "email", email, "Réinitialisation mot de passe — Modern Business", html)
        # Also send via Telegram if linked
        db = get_db()
        try:
            tg = db.execute("SELECT telegram FROM members WHERE email=?", (email.lower(),)).fetchone()
            if tg and tg["telegram"]:
                asyncio.create_task(NotifyAgent.send_telegram(tg["telegram"],
                    f"🔑 <b>Réinitialisation mot de passe</b>\n\n"
                    f"Cliquez ici (valide 2h):\n{reset_url}"))
        finally: db.close()

    return render(req, "forgot.html", {"sent": True, "error": ""})

@app.get("/reset", response_class=HTMLResponse)
async def reset_get(req: Request, token: str = ""):
    data = RESET_TOKENS.get(token)
    if not data or datetime.now() > data["expires"]:
        return render(req, "forgot.html", {"sent": False, "error": "Lien expiré ou invalide. Recommencez."})
    return render(req, "reset.html", {"token": token, "error": ""})

@app.post("/reset", response_class=HTMLResponse)
async def reset_post(req: Request, token: str = Form(""),
                     password: str = Form(""), password2: str = Form("")):
    data = RESET_TOKENS.get(token)
    if not data or datetime.now() > data["expires"]:
        return render(req, "forgot.html", {"sent": False, "error": "Lien expiré. Recommencez."})
    if len(password) < 8:
        return render(req, "reset.html", {"token": token, "error": "Minimum 8 caractères"})
    if password != password2:
        return render(req, "reset.html", {"token": token, "error": "Mots de passe différents"})
    db = get_db()
    try:
        db.execute("UPDATE members SET pw_hash=? WHERE email=?",
                   (hash_pw(password), data["email"]))
        db.commit()
    finally: db.close()
    del RESET_TOKENS[token]
    return RedirectResponse("/login?reset=1", 302)

# ── TENDERS PUBLIC ──
@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, code_f: str = "", region_f: str = "",
                       source_f: str = "", q: str = "", page: int = 1):
    per = 20; off = (page - 1) * per
    db = get_db()
    try:
        conds = ["statut='actif'"]; params = []
        if code_f:   conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
        if region_f: conds.append("region=?");       params.append(region_f)
        if source_f: conds.append("source=?");       params.append(source_f)
        if q:
            conds.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
            params += [f"%{q[:80]}%"] * 3
        w = " AND ".join(conds)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
        rows  = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {w} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params + [per, off]).fetchall()]
        regions = [r[0] for r in db.execute(
            "SELECT DISTINCT region FROM tenders WHERE region!='' ORDER BY region").fetchall()]
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT substr(domaine,1,4) FROM tenders WHERE domaine LIKE 'T%' OR domaine LIKE 'P%' OR domaine LIKE 'S%' ORDER BY 1 LIMIT 20"
        ).fetchall()]
    finally: db.close()
    counter("pv:tenders")
    return render(req, "tenders.html", {
        "tenders": rows, "total": total, "page": page,
        "pages": max(1, (total + per - 1) // per),
        "code_f": code_f, "region_f": region_f, "source_f": source_f, "q": q,
        "regions": regions, "codes": codes,
    })

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row: raise HTTPException(404)
        t = dict(row)
        db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?", (tid,))
        db.commit()
        related = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE domaine=? AND id!=? AND statut='actif' ORDER BY date_extraction DESC LIMIT 5",
            (t["domaine"], tid)).fetchall()]
    finally: db.close()
    counter("pv:tender_detail")
    return render(req, "tender_detail.html", {"t": t, "related": related})

# ── CLEANUP DUPLICATES ──
@app.get("/admin/cleanup_tenders")
async def admin_cleanup_tenders(pwd: str = ""):
    """Remove tenders with generic/invalid titles"""
    chk(pwd)
    db = get_db()
    try:
        bad_patterns = [
            "Liste des avis d'achat",
            "ConsultationsRésultats",
            "Accueil",
            "Se connecter",
        ]
        deleted = 0
        for p in bad_patterns:
            db.execute("DELETE FROM tenders WHERE objet LIKE ?", (f"%{p}%",))
            deleted += db.execute("SELECT changes()").fetchone()[0]
        # Remove tenders with objet less than 10 chars
        db.execute("DELETE FROM tenders WHERE length(objet) < 10")
        deleted += db.execute("SELECT changes()").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok": True, "deleted": deleted})

# ══════════════════════════════════════════════════════
# REST API — Extended for multi-source
# ══════════════════════════════════════════════════════

@app.get("/api/v1/tenders")
async def api_tenders(
    source: str = "", code: str = "", region: str = "",
    type_m: str = "", q: str = "", min_score: int = 0,
    page: int = 1, per_page: int = 20
):
    """
    GET /api/v1/tenders
    Params: source, code (T/P/S prefix), region, type_m, q, min_score, page, per_page
    """
    per_page = min(per_page, 100)
    off = (page - 1) * per_page
    db = get_db()
    try:
        conds = ["statut='actif'"]; params = []
        if source:    conds.append("source=?");           params.append(source)
        if code:      conds.append("domaine LIKE ?");     params.append(f"{code}%")
        if region:    conds.append("region LIKE ?");      params.append(f"%{region}%")
        if type_m:    conds.append("type_marche=?");      params.append(type_m)
        if min_score: conds.append("ai_score >= ?");      params.append(min_score)
        if q:
            conds.append("(objet LIKE ? OR description LIKE ? OR acheteur LIKE ?)")
            params += [f"%{q}%"]*3
        w = " AND ".join(conds)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
        rows  = [dict(r) for r in db.execute(
            f"SELECT id,objet,acheteur,region,domaine,type_marche,montant,date_limite,"
            f"source,contact,ai_score,ai_category,ai_reason,url,date_extraction "
            f"FROM tenders WHERE {w} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params + [per_page, off]
        ).fetchall()]
    finally: db.close()
    return JSONResponse({
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1,(total+per_page-1)//per_page),
        "tenders": rows,
    })

@app.get("/api/v1/tenders/new")
async def api_tenders_new(hours: int = 24):
    """GET /api/v1/tenders/new?hours=24 — Tenders added in last N hours"""
    db = get_db()
    try:
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        rows = [dict(r) for r in db.execute(
            "SELECT id,objet,acheteur,region,domaine,source,ai_score,date_limite,url "
            "FROM tenders WHERE date_extraction >= ? AND statut='actif' "
            "ORDER BY ai_score DESC, date_extraction DESC LIMIT 50",
            (since,)
        ).fetchall()]
    finally: db.close()
    return JSONResponse({"count": len(rows), "since_hours": hours, "tenders": rows})

@app.get("/api/v1/tenders/{tid}")
async def api_tender_detail(tid: str):
    """GET /api/v1/tenders/{id} — Full tender details"""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row: raise HTTPException(404, "Tender not found")
        t = dict(row)
        db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?", (tid,))
        db.commit()
    finally: db.close()
    return JSONResponse(t)

@app.get("/api/v1/sources")
async def api_sources():
    """GET /api/v1/sources — Stats per source"""
    db = get_db()
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT source, COUNT(*) as total, "
            "SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active, "
            "AVG(ai_score) as avg_score "
            "FROM tenders GROUP BY source ORDER BY total DESC"
        ).fetchall()]
    finally: db.close()
    return JSONResponse({
        "sources": rows,
        "available_scrapers": list(MULTI_SCRAPERS.keys()) if HAS_MULTI else ["marchespublics"],
    })

@app.get("/api/v1/tenders/easy")
async def api_easy_tenders(min_score: int = 70, limit: int = 20):
    """GET /api/v1/tenders/easy — Tenders easy to win (ai_score >= 70)"""
    db = get_db()
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT id,objet,acheteur,region,domaine,source,montant,ai_score,ai_reason,date_limite,url "
            "FROM tenders WHERE statut='actif' AND ai_score >= ? "
            "ORDER BY ai_score DESC LIMIT ?",
            (min_score, limit)
        ).fetchall()]
    finally: db.close()
    return JSONResponse({"count": len(rows), "min_score": min_score, "tenders": rows})

@app.get("/api/v1/stats")
async def api_stats_v1():
    """GET /api/v1/stats — Full platform stats"""
    db = get_db()
    try:
        s = MonitorAgent.get_stats()
        s["sources"] = [dict(r) for r in db.execute(
            "SELECT source,COUNT(*) as total,SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active "
            "FROM tenders GROUP BY source ORDER BY total DESC"
        ).fetchall()]
        s["easy_to_win"] = db.execute(
            "SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score >= 70"
        ).fetchone()[0]
        s["avg_ai_score"] = round(
            db.execute("SELECT AVG(ai_score) FROM tenders WHERE statut='actif'").fetchone()[0] or 50, 1
        )
    finally: db.close()
    return JSONResponse(s)

@app.get("/health")
async def health():
    db = get_db()
    try: active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    finally: db.close()
    return JSONResponse({"status":"ok","version":"3.0","active_tenders":active,"agents":["ScraperAgent","NotifyAgent","MonitorAgent","ChatAgent","ClassifierAgent"]})

@app.get("/metrics")
async def metrics(pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    return JSONResponse({"counters":dict(COUNTERS),"scraper":{"running":ScraperState.running,"saved":ScraperState.saved}})

@app.get("/sitemap.xml")
async def sitemap():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
<url><loc>{SITE_URL}/marketplace</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>
<url><loc>{SITE_URL}/annuaire</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
<url><loc>{SITE_URL}/contact</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
</urlset>"""
    return Response(xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {SITE_URL}/sitemap.xml",
                    media_type="text/plain")
