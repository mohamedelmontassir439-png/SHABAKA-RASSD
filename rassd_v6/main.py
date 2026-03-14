"""
Modern Business v2.0
══════════════════════════════════════════════════════
- Scraper: marchespublics.gov.ma UNIQUEMENT
- Tenders: Admin seulement
- Landing: Informatif
- Marketplace: Forum contractors
- ChatBot: Claude AI
- PWA: App Store + Play Store ready
══════════════════════════════════════════════════════
"""
from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import sqlite3, json, re, time, random, os, asyncio
import smtplib, hashlib, secrets, threading, logging, traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from itsdangerous import URLSafeTimedSerializer
    HAS_ITS = True
except: HAS_ITS = False

try: import urllib3; urllib3.disable_warnings()
except: pass

# ══════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mb")

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
BRAND        = "Modern Business"
GMAIL_USER   = os.getenv("GMAIL_USER",  "mohamedelmontassir439@gmail.com")
GMAIL_PASS   = os.getenv("GMAIL_PASS",  "nvzdanptagoovjxr")
TELEGRAM_BOT = os.getenv("TELEGRAM_BOT","7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_PASS   = os.getenv("ADMIN_PASS",  "rassd2026")
SECRET_KEY   = os.getenv("SECRET_KEY",  secrets.token_hex(32))
DB_PATH      = os.getenv("DB_PATH",     "data/mb.db")
ANTHROPIC_KEY= os.getenv("ANTHROPIC_API_KEY", "")
SITE_URL     = os.getenv("SITE_URL",    "https://web-production-b4ae4.up.railway.app")
SCRAPE_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))

METRICS = defaultdict(int)
def metric(k): METRICS[k] += 1

# ══════════════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════════════
_rl: dict = defaultdict(list)
_rl_lock = threading.Lock()

def rate_limit(ip, key, max_c=60, win=60):
    k = f"{ip}:{key}"; now = time.time()
    with _rl_lock:
        calls = [t for t in _rl[k] if now-t < win]
        if len(calls) >= max_c: return False
        calls.append(now); _rl[k] = calls
    return True

def get_ip(r: Request):
    fwd = r.headers.get("X-Forwarded-For","")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "0.0.0.0")

def rl(request: Request, key: str, max_c=60, win=60):
    if not rate_limit(get_ip(request), key, max_c, win):
        raise HTTPException(429, "Trop de requêtes")

# ══════════════════════════════════════════════════════
# SECURITY
# ══════════════════════════════════════════════════════
class SecMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

# ══════════════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════════════
SESSION_COOKIE = "mb_sess"
COOKIE_TTL     = 86400 * 30

def create_session(response: Response, cid: int):
    if HAS_ITS:
        s = URLSafeTimedSerializer(SECRET_KEY, salt="mb2")
        token = s.dumps({"id": cid})
    else:
        token = str(cid)
    response.set_cookie(SESSION_COOKIE, token, max_age=COOKIE_TTL,
                        httponly=True, samesite="lax",
                        secure=SITE_URL.startswith("https"))

def get_session_id(request: Request) -> Optional[int]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw: return None
    if HAS_ITS:
        try:
            s = URLSafeTimedSerializer(SECRET_KEY, salt="mb2")
            d = s.loads(raw, max_age=COOKIE_TTL)
            return d.get("id")
        except: return None
    try: return int(raw)
    except: return None

def delete_session(response: Response):
    response.delete_cookie(SESSION_COOKIE)

# ══════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════
def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
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
        date_extraction TEXT DEFAULT '',
        views INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_date   ON tenders(date_extraction DESC);

    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        entreprise TEXT DEFAULT '',
        email TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '',
        secteur TEXT DEFAULT '',
        ville TEXT DEFAULT '',
        password_hash TEXT NOT NULL DEFAULT '',
        plan TEXT DEFAULT 'free',
        actif INTEGER DEFAULT 1,
        verified INTEGER DEFAULT 0,
        rating_avg REAL DEFAULT 0,
        rating_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '',
        last_login TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_c_email ON contractors(email);

    CREATE TABLE IF NOT EXISTS marketplace_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        type TEXT DEFAULT 'offre',
        titre TEXT NOT NULL DEFAULT '',
        description TEXT DEFAULT '',
        secteur TEXT DEFAULT '',
        ville TEXT DEFAULT '',
        budget TEXT DEFAULT '',
        contact TEXT DEFAULT '',
        status TEXT DEFAULT 'actif',
        views INTEGER DEFAULT 0,
        created_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_mp_type   ON marketplace_posts(type);
    CREATE INDEX IF NOT EXISTS idx_mp_status ON marketplace_posts(status);

    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        score INTEGER NOT NULL DEFAULT 5,
        comment TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        UNIQUE(from_id, to_id)
    );

    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_key TEXT DEFAULT '',
        role TEXT DEFAULT 'user',
        content TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_ch_session ON chat_history(session_key);

    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        found INTEGER DEFAULT 0,
        saved INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0,
        started_at TEXT DEFAULT '',
        finished_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        route TEXT DEFAULT '',
        error TEXT DEFAULT '',
        count INTEGER DEFAULT 1,
        first_seen TEXT DEFAULT '',
        last_seen TEXT DEFAULT '',
        resolved INTEGER DEFAULT 0
    );
    """)
    # Migrations
    for sql in [
        "ALTER TABLE contractors ADD COLUMN verified INTEGER DEFAULT 0",
        "ALTER TABLE contractors ADD COLUMN rating_avg REAL DEFAULT 0",
        "ALTER TABLE contractors ADD COLUMN rating_count INTEGER DEFAULT 0",
        "ALTER TABLE contractors ADD COLUMN telegram TEXT DEFAULT ''",
    ]:
        try: db.execute(sql)
        except: pass
    db.commit(); db.close()
    logger.info("DB OK")

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def hash_pw(pw): return hashlib.sha256((pw+SECRET_KEY[:16]).encode()).hexdigest()
def check_pw(pw, h): return hash_pw(pw) == h

REGIONS = {
    "Rabat-Salé-Kénitra":       ["rabat","salé","sale","kénitra","kenitra","témara"],
    "Casablanca-Settat":        ["casablanca","settat","mohammedia","berrechid"],
    "Marrakech-Safi":           ["marrakech","safi","essaouira","kelaa"],
    "Fès-Meknès":               ["fès","fez","meknès","meknes","ifrane","taza"],
    "Tanger-Tétouan-Al Hoceima":["tanger","tétouan","tetouan","al hoceima","chefchaouen"],
    "Oriental":                 ["oujda","nador","berkane","taourirt"],
    "Béni Mellal-Khénifra":    ["béni mellal","beni mellal","khénifra","azilal"],
    "Souss-Massa":              ["agadir","tiznit","taroudant","inezgane"],
    "Drâa-Tafilalet":           ["errachidia","ouarzazate","zagora","midelt"],
    "Laâyoune":                 ["laayoune","laâyoune","boujdour"],
    "Dakhla":                   ["dakhla"],
    "Guelmim":                  ["guelmim","tan-tan"],
}
REGIONS_LIST = list(REGIONS.keys())

SECTEURS = [
    "Bâtiment & Construction", "Génie Civil & Routes", "Hydraulique & Eau",
    "Informatique & SI", "Fournitures & Équipements", "Santé & Médical",
    "Formation & Conseil", "Nettoyage & Maintenance", "Sécurité & Gardiennage",
    "Transport & Logistique", "Alimentation & Restauration", "Environnement",
    "Communication & Médias", "Juridique & Audit", "Autres",
]

def clean_objet(text: str) -> str:
    """Remove noise from tender title: #1, #01, lot numbers, etc."""
    t = text.strip()
    # Remove leading #1, #01, #001, LOT n°, etc.
    t = re.sub(r'^#\d+\s*', '', t)
    t = re.sub(r'^LOT\s+[N°n°\d]+\s*[:\-]?\s*', '', t, flags=re.I)
    t = re.sub(r'^lot\s+\d+\s*[:\-]?\s*', '', t, flags=re.I)
    t = re.sub(r'^\d+\s*[:\-]\s*', '', t)
    # Remove trailing noise
    t = re.sub(r'\s+', ' ', t).strip()
    # Capitalize first letter
    if t and t[0].islower(): t = t[0].upper() + t[1:]
    return t

def classify_region(text: str) -> str:
    """Detect Moroccan region from text"""
    txt = text.lower()
    for region, kws in REGIONS.items():
        if any(k in txt for k in kws): return region
    return "Maroc"

DOMAINES_MAP = {
    "Bâtiment & Construction": [
        "bâtiment","construction","maçonnerie","béton","coffrage","charpente",
        "toiture","carrelage","peinture","enduit","plâtrerie","menuiserie",
        "façade","clôture","mur","dalle","fondation","gros oeuvre","btp",
        "enseigne","rideau","grille","portail","porte","fenêtre","vitrerie",
        "étanchéité","isolation","revêtement","parquet","faux plafond",
    ],
    "Génie Civil & Routes": [
        "route","autoroute","pont","génie civil","chaussée","trottoir",
        "terrassement","voirie","bordure","caniveau","pavage","bitume",
        "asphalte","emprise","infrastructure","ouvrage d'art","plot","borne",
        "poteaux","buse","tube","canalisation","drain","regard",
    ],
    "Hydraulique & Eau": [
        "hydraulique","eau potable","assainissement","barrage","irrigation",
        "réseau d'eau","station d'épuration","forage","pompage","adduction",
        "réservoir","château d'eau","plomberie","robinetterie","cuve",
    ],
    "Informatique & SI": [
        "informatique","logiciel","système d'information","application",
        "réseau","serveur","ordinateur","pc","laptop","imprimante","scanner",
        "toner","cartouche","câblage","switch","routeur","cybersécurité",
        "maintenance informatique","développement","site web","data","cloud",
        "caméra","surveillance","vidéo","sfp","fibre optique","vr","casque",
    ],
    "Fournitures & Équipements": [
        "fournitures de bureau","papier","chemise","classeur","stylo",
        "mobilier","bureau","chaise","fauteuil","armoire","étagère",
        "table","banquette","chevalet","tableau","écran","projecteur",
        "équipements","matériel","rame","agrafe","ramette",
    ],
    "Santé & Médical": [
        "médical","santé","hôpital","clinique","médicament","dispositif médical",
        "laboratoire","analyse","réactif","matériel médical","chirurgical",
        "dentaire","pharmaceutique","infirmier","ambulance","stéthoscope",
        "coloration","antiserum","boîte de pétri","salmonella","microbiologie",
        "ziehl","neelsen","méthanol","lcms",
    ],
    "Nettoyage & Maintenance": [
        "nettoyage","entretien","propreté","désinfection","maintenance",
        "jardinage","espaces verts","déchets","lavage","savon","détergent",
        "balai","mop","hygiène","pest control","dératisation",
    ],
    "Sécurité & Gardiennage": [
        "sécurité","gardiennage","surveillance","agent de sécurité",
        "contrôle d'accès","badge","alarme","incendie","extincteur",
        "poste portatif","radio","talkie","drapeau",
    ],
    "Transport & Logistique": [
        "transport","véhicule","camion","voiture","bus","minibus","taxi",
        "location de véhicule","carburant","gasoil","essence","pneumatique",
        "pièces de rechange","entretien véhicule","flotte","livraison",
    ],
    "Alimentation & Restauration": [
        "alimentation","restauration","repas","traiteur","cuisine",
        "denrée","produit alimentaire","viande","poisson","légume",
        "boisson","eau minérale","café","thé","lait","filet de dinde",
    ],
    "Formation & Conseil": [
        "formation","conseil","consultant","expertise","audit","étude",
        "mission","assistance technique","accompagnement","coaching",
        "séminaire","atelier","programme","évaluation","diagnostic",
        "accréditation","certification","bureau d'études","tdr",
    ],
    "Communication & Médias": [
        "communication","publicité","impression","imprimé","rapport",
        "brochure","affiche","banner","signalétique","image de marque",
        "vidéo","photo","audiovisuel","événementiel","médias",
        "presse","journal","magazine",
    ],
    "Environnement": [
        "environnement","écologie","énergie renouvelable","solaire","éolien",
        "reboisement","plantation","déforestation","pollution","recyclage",
        "décharge","collecte","ordures",
    ],
    "Juridique & Audit": [
        "audit","juridique","notaire","avocat","huissier","contentieux",
        "marché juridique","expertise judiciaire","comptabilité","commissaire",
    ],
}

def classify_domaine(text: str) -> str:
    """Classify tender by sector using comprehensive keyword matching"""
    txt = text.lower()
    scores = {}
    for domaine, kws in DOMAINES_MAP.items():
        score = sum(2 if len(kw) > 8 else 1 for kw in kws if kw in txt)
        if score: scores[domaine] = score
    if scores: return max(scores, key=scores.get)
    return "Fournitures & Équipements"  # default (most common)

ACHETEURS_REGIONS = {
    "Rabat-Salé-Kénitra":        ["rabat","ministère","direction centrale","présidence","parlement","bank al-maghrib","bnrm","hcp","ofppt central","cnops","cnss siège","dgapr"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","inzegane","lydec","cfca","onee casa","ram casa"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa des sraghna","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","boulemane","sefrou"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","al hoceima","chefchaouen","larache","ouazzane"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","jerada","figuig"],
    "Béni Mellal-Khénifra":     ["béni mellal","khénifra","azilal","fquih ben salah","khouribga"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane","aïn chock","ait melloul"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt","tinghir"],
    "Laâyoune":                  ["laayoune","boujdour","tarfaya"],
    "Dakhla":                    ["dakhla","oued eddahab"],
    "Guelmim":                   ["guelmim","tan-tan","sidi ifni","assa-zag"],
}

def classify_region(text: str) -> str:
    txt = text.lower()
    # Check geographical keywords first
    for region, kws in REGIONS.items():
        if any(k in txt for k in kws): return region
    # Then check organisme names
    for region, kws in ACHETEURS_REGIONS.items():
        if any(k in txt for k in kws): return region
    return "Maroc"

def extract_date(text):
    if not text: return ""
    m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
    return m.group(1) if m else ""

def is_expired(d):
    if not d: return False
    for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d.%m.%Y"]:
        try: return datetime.strptime(d.strip(), fmt).date() < datetime.now().date()
        except: pass
    return False

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
    try:
        db = get_db()
        db.execute("""INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,domaine,montant,date_publication,date_limite,
             description,statut,url,date_extraction)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            str(t.get("id",""))[:80], str(t.get("objet",""))[:500],
            str(t.get("acheteur",""))[:200], str(t.get("region",""))[:100],
            str(t.get("domaine",""))[:80], str(t.get("montant",""))[:80],
            str(t.get("date_publication",""))[:20], str(t.get("date_limite",""))[:20],
            str(t.get("description",""))[:2000], str(t.get("statut","actif")),
            str(t.get("url",""))[:400],
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        db.commit()
        ch = db.execute("SELECT changes()").fetchone()[0]
        db.close(); return ch > 0
    except Exception as e:
        logger.error(f"[save_tender] {e}")
        try: db.close()
        except: pass
        return False

# ══════════════════════════════════════════════════════
# SCRAPER — marchespublics.gov.ma UNIQUEMENT
# ══════════════════════════════════════════════════════
SCRAPE_LOG   = []
SCRAPE_STATS = {
    "running": False, "found": 0, "saved": 0,
    "errors": 0, "started": "", "current_id": 0, "max_id": 0,
}

def slog(msg):
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    SCRAPE_LOG.append(entry)
    logger.info(entry)
    if len(SCRAPE_LOG) > 500: SCRAPE_LOG[:] = SCRAPE_LOG[-400:]

def get_req_session():
    import requests
    s = requests.Session(); s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    return s

def parse_pmmp(html: str, tid: str) -> dict:
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, 'html.parser')
        full = soup.get_text(' ', strip=True)

        def in_table(label):
            for row in soup.find_all('tr'):
                cells = row.find_all(['td','th'])
                for i,c in enumerate(cells):
                    if label.lower() in c.get_text().lower() and i+1 < len(cells):
                        v = cells[i+1].get_text(strip=True)
                        if v and len(v) > 1: return v[:300]
            return ""

        def find_objet():
            # Try specific selectors for marchespublics.gov.ma
            for sel in [
                '.consultation-title', '.objet', '#objet',
                'td.objet', '.marche-objet', '.ao-title',
                'h1', 'h2', 'h3',
            ]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    # Skip navigation/header text
                    skip = ['accueil','liste des avis','connexion','menu','navigation','breadcrumb']
                    if 10 < len(txt) < 500 and not any(s in txt.lower() for s in skip):
                        return txt
            # Try table rows
            v = in_table("objet du marché") or in_table("objet") or in_table("intitulé") or in_table("désignation")
            if v and len(v) > 10:
                return v
            # Try meta description
            meta = soup.find('meta', {'name': 'description'})
            if meta and meta.get('content') and len(meta['content']) > 15:
                content = meta['content'].strip()
                skip = ['marchespublics','portail','bienvenue']
                if not any(s in content.lower() for s in skip):
                    return content[:300]
            # Last resort: find meaningful text blocks
            for tag in soup.find_all(['p','div','span','td']):
                txt = tag.get_text(strip=True)
                skip = ['accueil','liste des avis','connexion','menu','©','cookie','javascript']
                if 20 < len(txt) < 400 and not any(s in txt.lower() for s in skip):
                    if any(kw in txt.lower() for kw in ['travaux','fourniture','service','étude','prestation','marché','appel','consultation','accord']):
                        return txt
            return ""

        objet = find_objet()

        acheteur = in_table("maître d") or in_table("organisme") or in_table("acheteur") or ""
        date_pub = extract_date(in_table("publication") or "")
        date_lim = extract_date(in_table("remise") or in_table("limite") or "")
        montant  = in_table("montant") or ""
        if not montant:
            m = re.search(r'(\d[\d\s,.]{2,14})\s*(?:DH|MAD|dirham)', full, re.I)
            if m: montant = m.group(0)[:60]

        region  = classify_region(acheteur + " " + full[:400])
        domaine = classify_domaine(objet + " " + full[:300])
        statut  = "annule" if any(k in full.lower() for k in ["annulé","infructueux","sans suite"]) \
                  else ("expire" if is_expired(date_lim) else "actif")

        # Clean the objet
        objet = clean_objet(objet) if objet else ""

        # Extract acheteur better
        if not acheteur:
            acheteur = (in_table("maître d'ouvrage") or in_table("maître d'oeuvre") or
                       in_table("organisme acheteur") or in_table("pouvoir adjudicateur") or "")
        acheteur = acheteur.strip()

        # Region from acheteur + full text
        region  = classify_region(acheteur + " " + full[:600])
        domaine = classify_domaine(objet + " " + (acheteur or "") + " " + full[:400])

        statut = "annule" if any(k in full.lower() for k in ["annulé","infructueux","sans suite","déclaré infructueux"]) \
                 else ("expire" if is_expired(date_lim) else "actif")

        # Build clean description
        desc_parts = []
        if acheteur: desc_parts.append(f"Acheteur: {acheteur}")
        if domaine:  desc_parts.append(f"Secteur: {domaine}")
        if montant:  desc_parts.append(f"Montant estimé: {montant}")
        desc_parts.append(full[:1500])
        description = " | ".join(desc_parts[:2]) + "\n\n" + full[:1500]

        return {
            "id": f"{prefix}_{tid}",
            "objet": objet[:400] or f"Marché #{tid}",
            "acheteur": acheteur[:200], "region": region, "domaine": domaine,
            "montant": montant[:60], "date_publication": date_pub,
            "date_limite": date_lim, "description": description[:2000],
            "statut": statut,
            "url": f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
        }
    except Exception as e:
        return {"id": f"{prefix}_{tid}", "objet": f"Marché #{tid}", "url": f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}", "statut": "actif",
                "description": "", "acheteur": "", "region": "Maroc", "domaine": "Fournitures & Équipements", "montant": "",
                "date_publication": "", "date_limite": ""}

SHOW_URLS = [
    "https://www.marchespublics.gov.ma/pmmp/consultation/show/",
    "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/",
]
LIST_URLS = [
    "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/",
    "https://www.marchespublics.gov.ma/pmmp/consultation/",
]

def run_scraper() -> list:
    import requests as rq
    start = time.time()
    new_tenders = []
    SCRAPE_STATS.update({"running":True,"found":0,"saved":0,"errors":0,
                          "started":datetime.now().strftime("%H:%M:%S"),
                          "current_id":0,"max_id":0})
    slog("═══ Scraper démarré — marchespublics.gov.ma ═══")
    s = get_req_session()

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
    row = db.execute("SELECT MAX(CAST(REPLACE(id,'pmmp_','') AS INTEGER)) FROM tenders").fetchone()
    max_id = int(row[0]) if row and row[0] else 0
    db.close()

    ids_found = set()
    # Phase 1: Listing pages
    for list_url in LIST_URLS:
        for page in range(1, 8):
            url = f"{list_url}?page={page}" if page > 1 else list_url
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                for pat in [r'/show/(\d{3,7})', r'[?&]id=(\d{3,7})', r'/consultation/(\d{3,7})']:
                    for m in re.finditer(pat, r.text): ids_found.add(m.group(1))
                slog(f"Page {page}: {len(ids_found)} IDs trouvés")
                time.sleep(random.uniform(1, 2))
            except Exception as e: slog(f"Listing p{page}: {e}"); break
        if ids_found: break

    # Phase 2: Probe max ID if needed
    if max_id == 0 and not ids_found:
        slog("Sondage ID maximum...")
        for probe in [500000, 450000, 400000, 350000, 300000, 200000, 100000, 50000, 10000]:
            for su in SHOW_URLS:
                try:
                    r = s.get(f"{su}{probe}", timeout=10)
                    if r.status_code == 200 and len(r.text) > 500:
                        max_id = probe; SCRAPE_STATS["max_id"] = max_id
                        slog(f"Max ID sondé: {max_id}"); break
                except: pass
            if max_id: break

    # Phase 3: Fetch new from listing
    new_ids = set(ids_found) - set(k.replace("pmmp_","") for k in known)
    slog(f"IDs listing: {len(ids_found)} | Nouveaux: {len(new_ids)}")
    for tid in sorted(new_ids, reverse=True)[:60]:
        for su in SHOW_URLS:
            try:
                r = s.get(f"{su}{tid}", timeout=15)
                if r.status_code == 200 and len(r.text) > 400:
                    t = parse_pmmp(r.text, tid)
                    SCRAPE_STATS["found"] += 1; SCRAPE_STATS["current_id"] = int(tid)
                    if save_tender(t):
                        SCRAPE_STATS["saved"] += 1
                        slog(f"✓ #{tid} — {t['objet'][:50]}")
                        if t["statut"] == "actif": new_tenders.append(t)
                    break
            except Exception as e: SCRAPE_STATS["errors"] += 1
        time.sleep(random.uniform(0.5, 1.2))

    # Phase 4: Sequential scan from max
    if max_id > 0:
        slog(f"Scan séquentiel depuis #{max_id+1}...")
        miss = 0; cur = max_id + 1
        while miss < 25 and len(new_tenders) < 80:
            if f"pmmp_{cur}" in known: cur += 1; continue
            SCRAPE_STATS["current_id"] = cur
            ok = False
            for su in SHOW_URLS:
                try:
                    r = s.get(f"{su}{cur}", timeout=12)
                    if r.status_code == 200 and len(r.text) > 400:
                        miss = 0; ok = True
                        t = parse_pmmp(r.text, str(cur))
                        SCRAPE_STATS["found"] += 1
                        if save_tender(t):
                            SCRAPE_STATS["saved"] += 1
                            slog(f"✓ #{cur} — {t['objet'][:50]}")
                            if t["statut"] == "actif": new_tenders.append(t)
                        break
                    elif r.status_code == 404: miss += 1; ok = True; break
                    elif r.status_code in [429,503]: time.sleep(20); ok = True; break
                except rq.exceptions.ConnectionError: miss += 15; ok = True; break
                except: ok = True; break
            if not ok: miss += 1
            cur += 1; time.sleep(random.uniform(0.3, 0.8))

    # Post-process
    try:
        db = get_db()
        active = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
        exp = [r["id"] for r in active if is_expired(r["date_limite"])]
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join('?'*len(exp))})", exp)
        db.commit(); db.close()
    except: pass

    duration = time.time() - start
    try:
        db = get_db()
        db.execute("INSERT INTO scrape_runs (found,saved,errors,duration_sec,started_at,finished_at) VALUES (?,?,?,?,?,?)",
                   (SCRAPE_STATS["found"], SCRAPE_STATS["saved"], SCRAPE_STATS["errors"],
                    duration, SCRAPE_STATS["started"], datetime.now().strftime("%H:%M:%S")))
        db.commit(); db.close()
    except: pass

    SCRAPE_STATS["running"] = False
    slog(f"═══ Terminé en {duration:.0f}s | {SCRAPE_STATS['saved']} sauvegardés ═══")
    metric("scrape_runs")
    return new_tenders

LAST_SCRAPE = 0
# scheduler moved to scheduler_loop_v2

# ══════════════════════════════════════════════════════
# CHATBOT — Claude AI
# ══════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""Tu es l'assistant intelligent de {BRAND}, plateforme marocaine de veille sur les marchés publics.

Ton rôle:
- Aider les entrepreneurs et PME marocaines à comprendre les appels d'offres
- Expliquer les procédures de marchés publics au Maroc (Décret 2-12-349)
- Conseiller sur la qualification et classification des entreprises
- Aider à rédiger des questions sur les cahiers des charges
- Informer sur les organismes: ONCF, ONEE, OCP, communes, ministères
- Répondre en français ou arabe selon la langue de l'utilisateur
- Être concis, professionnel et utile

Tu NE peux PAS:
- Donner de conseils juridiques formels
- Garantir les résultats d'un appel d'offres
- Accéder à des données en temps réel

Plateforme: {SITE_URL}
"""

async def chat_with_claude(messages: list, session_key: str) -> str:
    if not ANTHROPIC_KEY:
        return ("Je suis désolé, le service de chatbot n'est pas encore configuré. "
                "Veuillez contacter l'équipe Modern Business pour plus d'informations. "
                f"📞 Disponible sur {SITE_URL}/contact")
    try:
        import httpx
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 800,
            "system": SYSTEM_PROMPT,
            "messages": messages[-10:],  # last 10 turns only
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json=payload
            )
            if r.status_code == 200:
                data = r.json()
                return data["content"][0]["text"]
            else:
                return "Désolé, une erreur est survenue. Réessayez dans quelques instants."
    except Exception as e:
        logger.error(f"[chatbot] {e}")
        return "Service temporairement indisponible. Réessayez dans quelques instants."

# ══════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════
async def send_email(to, subject, body):
    if not to or not GMAIL_PASS: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject; msg["From"] = f"{BRAND} <{GMAIL_USER}>"; msg["To"] = to
        msg.attach(MIMEText(body, "html", "utf-8"))
        import asyncio
        loop = asyncio.get_event_loop()
        def _send():
            srv = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
            srv.login(GMAIL_USER, GMAIL_PASS)
            srv.sendmail(GMAIL_USER, to, msg.as_string())
            srv.quit()
        await loop.run_in_executor(None, _send)
        metric("emails_sent"); return True
    except Exception as e:
        logger.error(f"[email] {e}"); return False

# ══════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app):
    for d in ["static","data","templates"]:
        try: os.makedirs(d, exist_ok=True)
        except: pass
    try: init_db()
    except Exception as e: logger.error(f"[init_db] {e}")
    asyncio.create_task(scheduler_loop_v2())
    asyncio.create_task(digest_scheduler())
    logger.info(f"{BRAND} v2.0 started")
    yield

app = FastAPI(lifespan=lifespan, title=BRAND, version="2.0", docs_url=None, redoc_url=None)
app.add_middleware(SecMiddleware)

try: os.makedirs("static",exist_ok=True); app.mount("/static",StaticFiles(directory="static"),name="static")
except: pass
try: os.makedirs("templates",exist_ok=True); templates=Jinja2Templates(directory="templates")
except: templates=None

def render(req, tpl, ctx={}):
    if not templates: return HTMLResponse("<h1>Templates error</h1>",500)
    try:
        return templates.TemplateResponse(tpl, {
            "request": req, "BRAND": BRAND, "SITE_URL": SITE_URL,
            "SECTEURS": SECTEURS, "REGIONS_LIST": REGIONS_LIST,
            "contractor": get_contractor(req),
            **ctx
        })
    except Exception as e:
        logger.error(f"[render:{tpl}] {e}\n{traceback.format_exc()}")
        raise

# ══════════════════════════════════════════════════════
# ROUTES — LANDING (Informatif seulement)
# ══════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    db = get_db()
    try:
        stats = {
            "total":   db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "active":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
            "posts":   db.execute("SELECT COUNT(*) FROM marketplace_posts WHERE status='actif'").fetchone()[0],
        }
        last_run = db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
        last_run = dict(last_run) if last_run else {}
    finally: db.close()
    metric("pv:home")
    return render(request, "landing.html", {"stats": stats, "last_run": last_run})

# ══════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def reg_get(request: Request):
    c = get_contractor(request)
    if c: return RedirectResponse("/dashboard", 302)
    return render(request, "register.html", {"error": ""})

@app.post("/register", response_class=HTMLResponse)
async def reg_post(request: Request,
    nom:str=Form(""), entreprise:str=Form(""), email:str=Form(""),
    phone:str=Form(""), secteur:str=Form(""), ville:str=Form(""), password:str=Form("")):
    rl(request, "register", 8, 3600)
    error = ""
    if not nom or not email or not password: error = "Tous les champs * sont requis"
    elif len(password) < 8: error = "Mot de passe: minimum 8 caractères"
    elif not re.match(r'^[^@]+@[^@]+\.[^@]+$', email): error = "Email invalide"
    else:
        db = get_db()
        try:
            if db.execute("SELECT id FROM contractors WHERE email=?", (email.lower(),)).fetchone():
                error = "Cet email est déjà utilisé"
            else:
                db.execute("""INSERT INTO contractors
                    (nom,entreprise,email,phone,secteur,ville,password_hash,actif,created_at)
                    VALUES (?,?,?,?,?,?,?,1,?)""",
                    (nom.strip(), entreprise.strip(), email.lower().strip(),
                     phone.strip(), secteur, ville.strip(),
                     hash_pw(password), datetime.now().strftime("%Y-%m-%d %H:%M")))
                db.commit()
                cid = db.execute("SELECT id FROM contractors WHERE email=?", (email.lower(),)).fetchone()[0]
                db.close()
                metric("registrations")
                asyncio.create_task(send_email(email,
                    f"Bienvenue sur {BRAND}!",
                    f'<div style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:28px;border-radius:10px">'
                    f'<h2 style="color:#c9a84c">Bienvenue, {nom}!</h2>'
                    f'<p style="color:#aaa">Votre compte {BRAND} est activé.</p>'
                    f'<a href="{SITE_URL}/dashboard" style="display:inline-block;margin-top:14px;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Accéder →</a></div>'))
                resp = RedirectResponse("/dashboard", 302)
                create_session(resp, cid); return resp
        except Exception as e: error = f"Erreur: {e}"
        finally:
            try: db.close()
            except: pass
    return render(request, "register.html", {"error": error})

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    c = get_contractor(request)
    if c: return RedirectResponse("/dashboard", 302)
    return render(request, "login.html", {"error": ""})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, email:str=Form(""), password:str=Form("")):
    rl(request, f"login:{get_ip(request)}", 5, 300)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM contractors WHERE email=? AND actif=1", (email.lower().strip(),)).fetchone()
        if not row or not check_pw(password, dict(row).get("password_hash","")):
            return render(request, "login.html", {"error": "Email ou mot de passe incorrect"})
        c = dict(row)
        db.execute("UPDATE contractors SET last_login=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M"), c["id"]))
        db.commit()
    finally: db.close()
    metric("logins")
    resp = RedirectResponse("/dashboard", 302)
    create_session(resp, c["id"]); return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", 302)
    delete_session(resp); return resp

# ══════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    db = get_db()
    try:
        my_posts = [dict(r) for r in db.execute(
            "SELECT * FROM marketplace_posts WHERE contractor_id=? ORDER BY id DESC LIMIT 5", (c["id"],)).fetchall()]
        my_ratings = [dict(r) for r in db.execute(
            "SELECT r.*,c.nom as from_nom FROM ratings r JOIN contractors c ON c.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 5", (c["id"],)).fetchall()]
        stats = {
            "total_tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "my_posts": len(my_posts),
        }
    finally: db.close()
    metric("pv:dashboard")
    return render(request, "dashboard.html", {"c": c, "my_posts": my_posts, "my_ratings": my_ratings, "stats": stats})

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    return render(request, "settings.html", {"c": c, "success": "", "error": ""})

@app.post("/settings", response_class=HTMLResponse)
async def settings_post(request: Request,
    nom:str=Form(""), entreprise:str=Form(""), phone:str=Form(""),
    secteur:str=Form(""), ville:str=Form(""), password:str=Form(""), password_new:str=Form("")):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    error = ""
    db = get_db()
    try:
        db.execute("UPDATE contractors SET nom=?,entreprise=?,phone=?,secteur=?,ville=? WHERE id=?",
                   (nom.strip() or c["nom"], entreprise.strip(), phone.strip(), secteur, ville.strip(), c["id"]))
        if password and password_new:
            if not check_pw(password, c.get("password_hash","")): error = "Mot de passe actuel incorrect"
            elif len(password_new) < 8: error = "Nouveau mot de passe trop court"
            else: db.execute("UPDATE contractors SET password_hash=? WHERE id=?", (hash_pw(password_new), c["id"]))
        db.commit()
    finally: db.close()
    c = get_contractor(request)
    return render(request, "settings.html", {"c": c, "success": "Sauvegardé ✓" if not error else "", "error": error})

# ══════════════════════════════════════════════════════
# MARKETPLACE
# ══════════════════════════════════════════════════════
@app.get("/marketplace", response_class=HTMLResponse)
async def marketplace(request: Request, type_f:str="", secteur_f:str="", q:str="", page:int=1):
    per_page = 15; offset = (page-1)*per_page
    db = get_db()
    try:
        conds = ["mp.status='actif'"]; params = []
        if type_f: conds.append("mp.type=?"); params.append(type_f)
        if secteur_f: conds.append("mp.secteur=?"); params.append(secteur_f)
        if q:
            conds.append("(mp.titre LIKE ? OR mp.description LIKE ?)")
            params += [f"%{q[:80]}%", f"%{q[:80]}%"]
        w = " AND ".join(conds)
        total = db.execute(f"SELECT COUNT(*) FROM marketplace_posts mp WHERE {w}", params).fetchone()[0]
        posts = [dict(r) for r in db.execute(
            f"""SELECT mp.*,c.nom as contractor_nom,c.entreprise,c.secteur as c_secteur,
                c.ville as c_ville,c.rating_avg,c.rating_count,c.verified
                FROM marketplace_posts mp JOIN contractors c ON c.id=mp.contractor_id
                WHERE {w} ORDER BY mp.id DESC LIMIT ? OFFSET ?""",
            params + [per_page, offset]).fetchall()]
        pages = max(1, (total+per_page-1)//per_page)
    finally: db.close()
    metric("pv:marketplace")
    return render(request, "marketplace.html", {
        "posts": posts, "total": total, "page": page, "pages": pages,
        "type_f": type_f, "secteur_f": secteur_f, "q": q
    })

@app.get("/marketplace/new", response_class=HTMLResponse)
async def marketplace_new_get(request: Request):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    return render(request, "marketplace_new.html", {"c": c, "error": ""})

@app.post("/marketplace/new", response_class=HTMLResponse)
async def marketplace_new_post(request: Request,
    type_p:str=Form("offre"), titre:str=Form(""), description:str=Form(""),
    secteur:str=Form(""), ville:str=Form(""), budget:str=Form(""), contact:str=Form("")):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    rl(request, "mp_new", 5, 3600)
    if not titre or len(titre) < 10:
        return render(request, "marketplace_new.html", {"c": c, "error": "Titre trop court (min 10 chars)"})
    db = get_db()
    try:
        db.execute("""INSERT INTO marketplace_posts
            (contractor_id,type,titre,description,secteur,ville,budget,contact,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (c["id"], type_p, titre.strip()[:200], description.strip()[:2000],
             secteur, ville.strip()[:80], budget.strip()[:60],
             contact.strip()[:100], "actif", datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit()
    finally: db.close()
    return RedirectResponse("/marketplace", 302)

@app.get("/marketplace/post/{pid}", response_class=HTMLResponse)
async def marketplace_detail(request: Request, pid: int):
    db = get_db()
    try:
        row = db.execute("""SELECT mp.*,c.nom as contractor_nom,c.entreprise,c.secteur as c_secteur,
                            c.ville as c_ville,c.rating_avg,c.rating_count,c.verified,c.phone,c.email
                            FROM marketplace_posts mp JOIN contractors c ON c.id=mp.contractor_id
                            WHERE mp.id=? AND mp.status='actif'""", (pid,)).fetchone()
        if not row: raise HTTPException(404)
        post = dict(row)
        db.execute("UPDATE marketplace_posts SET views=COALESCE(views,0)+1 WHERE id=?", (pid,))
        db.commit()
        # Ratings for contractor
        ratings = [dict(r) for r in db.execute(
            "SELECT r.*,c.nom as from_nom,c.entreprise as from_ent FROM ratings r JOIN contractors c ON c.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 10",
            (post["contractor_id"],)).fetchall()]
        c = get_contractor(request)
        can_rate = c and c["id"] != post["contractor_id"]
        already_rated = c and bool(db.execute("SELECT 1 FROM ratings WHERE from_id=? AND to_id=?", (c["id"], post["contractor_id"])).fetchone())
    finally: db.close()
    return render(request, "marketplace_detail.html", {"post": post, "ratings": ratings, "can_rate": can_rate, "already_rated": already_rated})

@app.post("/marketplace/rate/{contractor_id}")
async def rate_contractor(request: Request, contractor_id: int,
    score:int=Form(5), comment:str=Form("")):
    c = get_contractor(request)
    if not c: return RedirectResponse("/login", 302)
    if c["id"] == contractor_id: raise HTTPException(400)
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO ratings (from_id,to_id,score,comment,created_at) VALUES (?,?,?,?,?)",
                   (c["id"], contractor_id, max(1,min(5,score)), comment.strip()[:300],
                    datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.commit()
        avg = db.execute("SELECT AVG(score),COUNT(*) FROM ratings WHERE to_id=?", (contractor_id,)).fetchone()
        db.execute("UPDATE contractors SET rating_avg=?,rating_count=? WHERE id=?",
                   (round(avg[0],1), avg[1], contractor_id))
        db.commit()
    finally: db.close()
    return RedirectResponse(request.headers.get("referer", "/marketplace"), 302)

@app.get("/contractors", response_class=HTMLResponse)
async def contractors_list(request: Request, secteur_f:str="", q:str=""):
    db = get_db()
    try:
        conds = ["actif=1"]; params = []
        if secteur_f: conds.append("secteur=?"); params.append(secteur_f)
        if q: conds.append("(nom LIKE ? OR entreprise LIKE ? OR ville LIKE ?)"); params += [f"%{q}%"]*3
        rows = [dict(r) for r in db.execute(
            f"SELECT * FROM contractors WHERE {' AND '.join(conds)} ORDER BY rating_avg DESC, id DESC LIMIT 50",
            params).fetchall()]
    finally: db.close()
    return render(request, "contractors.html", {"contractors_list": rows, "secteur_f": secteur_f, "q": q})

# ══════════════════════════════════════════════════════
# CHATBOT API
# ══════════════════════════════════════════════════════
@app.post("/api/chat")
async def api_chat(request: Request):
    rl(request, f"chat:{get_ip(request)}", 20, 60)
    try:
        data = await request.json()
        user_msg = str(data.get("message", ""))[:1000].strip()
        session_key = data.get("session_key", get_ip(request))
        if not user_msg: return JSONResponse({"error": "Message vide"}, 400)

        # Load history
        db = get_db()
        try:
            rows = db.execute(
                "SELECT role,content FROM chat_history WHERE session_key=? ORDER BY id DESC LIMIT 20",
                (session_key,)).fetchall()
            history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        finally: db.close()

        # Add user message
        history.append({"role": "user", "content": user_msg})

        # Get AI response
        response = await chat_with_claude(history, session_key)

        # Save to DB
        db = get_db()
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO chat_history (session_key,role,content,created_at) VALUES (?,?,?,?)",
                       (session_key, "user", user_msg, now))
            db.execute("INSERT INTO chat_history (session_key,role,content,created_at) VALUES (?,?,?,?)",
                       (session_key, "assistant", response, now))
            # Keep only last 50 messages per session
            db.execute("""DELETE FROM chat_history WHERE session_key=? AND id NOT IN
                (SELECT id FROM chat_history WHERE session_key=? ORDER BY id DESC LIMIT 50)""",
                       (session_key, session_key))
            db.commit()
        finally: db.close()

        metric("chat_messages")
        return JSONResponse({"response": response, "session_key": session_key})
    except Exception as e:
        logger.error(f"[chat] {e}")
        return JSONResponse({"error": "Erreur serveur"}, 500)

@app.post("/api/consent")
async def api_consent():
    return JSONResponse({"ok": True})

# ══════════════════════════════════════════════════════
# ADMIN — Scraper live + Tenders
# ══════════════════════════════════════════════════════
def check_admin(pwd):
    if pwd != ADMIN_PASS: metric("admin_fail"); raise HTTPException(403)

@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, pwd:str=""):
    check_admin(pwd)
    db = get_db()
    try:
        stats = {
            "total":       db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "active":      db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "expire":      db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "contractors": db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
            "posts":       db.execute("SELECT COUNT(*) FROM marketplace_posts WHERE status='actif'").fetchone()[0],
            "ratings":     db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0],
            "chats":       db.execute("SELECT COUNT(DISTINCT session_key) FROM chat_history").fetchone()[0],
            "errors":      db.execute("SELECT COUNT(*) FROM error_log WHERE resolved=0").fetchone()[0],
        }
        tenders = [dict(r) for r in db.execute(
            "SELECT * FROM tenders ORDER BY date_extraction DESC LIMIT 40").fetchall()]
        contractors = [dict(r) for r in db.execute(
            "SELECT * FROM contractors ORDER BY id DESC LIMIT 20").fetchall()]
        scrape_hist = [dict(r) for r in db.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 8").fetchall()]
        errors = [dict(r) for r in db.execute(
            "SELECT * FROM error_log WHERE resolved=0 ORDER BY last_seen DESC LIMIT 10").fetchall()]
    finally: db.close()
    return render(request, "admin.html", {
        "stats": stats, "tenders": tenders, "contractors": contractors,
        "scrape_hist": scrape_hist, "errors": errors,
        "scrape_stats": SCRAPE_STATS, "scrape_log": SCRAPE_LOG[-80:],
        "pwd": pwd
    })

@app.get("/admin/scrape")
async def admin_scrape(pwd:str=""):
    check_admin(pwd)
    if SCRAPE_STATS.get("running"): return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    async def run():
        loop = asyncio.get_event_loop()
        try: await loop.run_in_executor(None, run_scraper)
        finally: SCRAPE_STATS["running"] = False
    asyncio.create_task(run())
    return JSONResponse({"ok":True,"msg":"Scraper démarré — marchespublics.gov.ma"})

@app.get("/admin/scrape_stream")
async def scrape_stream(request: Request, pwd:str=""):
    """SSE — live scraper logs"""
    check_admin(pwd)
    async def generate():
        last = 0
        while True:
            logs = SCRAPE_LOG[last:]
            for log in logs:
                yield f"data: {json.dumps({'log': log, 'stats': SCRAPE_STATS})}\n\n"
            last = len(SCRAPE_LOG)
            if not SCRAPE_STATS.get("running") and last > 0:
                yield f"data: {json.dumps({'done': True, 'stats': SCRAPE_STATS})}\n\n"
                break
            await asyncio.sleep(0.8)
    return StreamingResponse(generate(), media_type="text/event-stream",
                              headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/admin/scrape_logs")
async def scrape_logs(pwd:str=""):
    check_admin(pwd)
    return JSONResponse({"logs": SCRAPE_LOG[-100:], "stats": SCRAPE_STATS})

@app.get("/admin/delete_tender")
async def delete_tender(pwd:str="", tid:str=""):
    check_admin(pwd)
    db = get_db()
    try: db.execute("DELETE FROM tenders WHERE id=?", (tid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok": True})

@app.get("/admin/activate")
async def activate(pwd:str="", contractor_id:int=0, plan:str="pro"):
    check_admin(pwd)
    db = get_db()
    try:
        db.execute("UPDATE contractors SET plan=?,verified=1 WHERE id=?", (plan, contractor_id))
        db.commit()
    finally: db.close()
    return JSONResponse({"ok": True})

@app.get("/admin/cleanup")
async def cleanup(pwd:str=""):
    check_admin(pwd)
    db = get_db()
    try:
        db.execute("DELETE FROM tenders WHERE statut IN ('expire','annule') AND date_extraction < date('now','-60 days')")
        db.execute("DELETE FROM chat_history WHERE created_at < date('now','-7 days')")
        remaining = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok": True, "remaining": remaining})

@app.get("/admin/resolve_error")
async def resolve_error(pwd:str="", error_id:int=0):
    check_admin(pwd)
    db = get_db()
    try: db.execute("UPDATE error_log SET resolved=1 WHERE id=?", (error_id,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok": True})

# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
@app.post("/telegram/webhook")
async def tg_webhook(request: Request):
    try:
        data = await request.json()
        msg = data.get("message") or {}
        chat_id = str(msg.get("chat",{}).get("id",""))
        text = msg.get("text","").strip()
        if not chat_id: return {"ok":True}
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            if text in ["/start","start"]:
                reply = f"🏢 <b>{BRAND}</b>\nPlateforme marocaine des marchés publics\n\n/stats — Statistiques\n/help — Aide\n\n🌐 {SITE_URL}"
            elif text == "/stats":
                db = get_db()
                try:
                    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
                    total  = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
                finally: db.close()
                reply = f"📊 <b>{BRAND}</b>\n✅ Actives: <b>{active}</b>\n📦 Total: <b>{total}</b>\n🌐 {SITE_URL}"
            else:
                reply = f"Envoyez /start pour commencer.\n🌐 {SITE_URL}"
            await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"})
    except Exception as e: logger.error(f"[tg] {e}")
    return {"ok":True}

# ══════════════════════════════════════════════════════
# MONITORING
# ══════════════════════════════════════════════════════
@app.get("/health")
async def health():
    db = get_db()
    try:
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    finally: db.close()
    return JSONResponse({"status":"ok","brand":BRAND,"version":"2.0","active_tenders":active})

@app.get("/api/stats")
async def api_stats():
    db = get_db()
    try:
        return JSONResponse({
            "active":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "total":   db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
            "posts":   db.execute("SELECT COUNT(*) FROM marketplace_posts WHERE status='actif'").fetchone()[0],
        })
    finally: db.close()

@app.get("/metrics")
async def metrics_ep(pwd:str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    return JSONResponse({"counters": dict(METRICS), "scraper": SCRAPE_STATS})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return render(request, "privacy.html", {})

@app.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return render(request, "contact.html", {})

@app.get("/sitemap.xml")
async def sitemap():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
<url><loc>{SITE_URL}/marketplace</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>
<url><loc>{SITE_URL}/contractors</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
<url><loc>{SITE_URL}/contact</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
</urlset>"""
    return Response(content=xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {SITE_URL}/sitemap.xml",
                    media_type="text/plain")


# ══════════════════════════════════════════════════════
# NOTIFICATION SYSTEM
# ══════════════════════════════════════════════════════

async def send_telegram_msg(chat_id: str, text: str):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            )
    except Exception as e:
        logger.error(f"[tg_notif] {e}")

def build_email_html(tenders: list, title: str) -> str:
    """Build professional email HTML for tender notifications"""
    def tender_row(t):
        objet  = t.get("objet","")[:100]
        acheteur = t.get("acheteur","") or "—"
        region   = t.get("region","")  or "—"
        domaine  = t.get("domaine","") or "—"
        montant  = t.get("montant","") or ""
        date_lim = t.get("date_limite","") or "—"
        url      = t.get("url","") or SITE_URL
        montant_html = f'<tr><td style="padding:3px 0;color:#888;min-width:120px;font-size:11px">💰 Montant estimé</td><td style="color:#c9a84c;font-size:11px;font-weight:700">{montant}</td></tr>' if montant else ""
        return f"""
        <div style="border:1px solid #2a2a2a;border-radius:8px;padding:16px 18px;margin-bottom:12px;background:#141414">
          <div style="font-size:14px;font-weight:700;color:#f0ede6;margin-bottom:10px;line-height:1.4">{objet}</div>
          <table style="width:100%;border-collapse:collapse">
            <tr><td style="padding:3px 0;color:#888;min-width:120px;font-size:11px">🏢 Acheteur</td><td style="color:#aaa;font-size:11px">{acheteur[:60]}</td></tr>
            <tr><td style="padding:3px 0;color:#888;font-size:11px">📍 Région</td><td style="color:#aaa;font-size:11px">{region}</td></tr>
            <tr><td style="padding:3px 0;color:#888;font-size:11px">🏷 Secteur</td><td style="color:#aaa;font-size:11px">{domaine}</td></tr>
            {montant_html}
            <tr><td style="padding:3px 0;color:#888;font-size:11px">⏰ Date limite</td><td style="color:#e87070;font-size:11px;font-weight:700">{date_lim}</td></tr>
          </table>
          <a href="{url}" style="display:inline-block;margin-top:10px;padding:6px 14px;background:#c9a84c;color:#000;border-radius:5px;font-weight:700;text-decoration:none;font-size:11px">Voir le marché officiel →</a>
        </div>"""

    cards = "".join(tender_row(t) for t in tenders[:12])
    return f"""
    <div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:32px;max-width:640px;margin:0 auto;border-radius:12px">
      <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:22px">
        <div style="font-size:20px;font-weight:700;color:#c9a84c">◆ Modern Business</div>
        <div style="font-size:12px;color:#666;margin-top:3px">marchespublics.gov.ma — {datetime.now().strftime("%d/%m/%Y %H:%M")}</div>
      </div>
      <div style="font-size:17px;font-weight:700;color:#f0ede6;margin-bottom:4px">{title}</div>
      <div style="font-size:12px;color:#888;margin-bottom:20px">Source officielle: marchespublics.gov.ma</div>
      {cards}
      <div style="border-top:1px solid #222;padding-top:18px;margin-top:6px;text-align:center">
        <a href="{SITE_URL}" style="padding:10px 24px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:12px">Accéder à la plateforme →</a>
        <div style="font-size:10px;color:#333;margin-top:12px">Modern Business · Se désinscrire: {SITE_URL}/contact</div>
      </div>
    </div>"""


def build_tg_message(tenders: list, header: str) -> list:
    """Build Telegram messages (split if >4096 chars)"""
    messages = []
    intro = f"🏛 <b>{header}</b>\n{datetime.now().strftime('%d/%m/%Y')} · marchespublics.gov.ma\n{'━'*28}\n\n"
    current = intro

    for t in tenders[:10]:
        block = (
            f"📋 <b>{t.get('objet','')[:65]}</b>\n"
            f"   🏢 {t.get('acheteur','—')[:45]}\n"
            f"   📍 {t.get('region','—')}  |  🏷 {t.get('domaine','—')[:25]}\n"
        )
        if t.get("montant"):
            block += f"   💰 {t['montant']}\n"
        block += f"   ⏰ Limite: <b>{t.get('date_limite','—')}</b>\n"
        if t.get("url"):
            block += f"   🔗 {t['url']}\n"
        block += "\n"

        if len(current) + len(block) > 3800:
            messages.append(current.strip())
            current = block
        else:
            current += block

    if current.strip() != intro.strip():
        current += f"\n🌐 {SITE_URL}"
        messages.append(current.strip())

    return messages


async def notify_all_members(new_tenders: list):
    """Send instant notifications after scrape"""
    if not new_tenders:
        return
    try:
        db = get_db()
        try:
            members = []
            for r in db.execute("SELECT email, nom FROM contractors WHERE actif=1").fetchall():
                m = dict(r)
                m["telegram"] = ""
                members.append(m)
            # Try to get telegram if column exists
            try:
                for r in db.execute("SELECT email, telegram FROM contractors WHERE actif=1 AND telegram != ''").fetchall():
                    for m in members:
                        if m["email"] == r["email"]:
                            m["telegram"] = r["telegram"] or ""
            except: pass
        finally:
            db.close()

        if not members:
            slog("📢 Aucun membre — pas de notification")
            return

        n = len(new_tenders)
        email_html = build_email_html(new_tenders, f"🏛 {n} nouveau(x) marché(s) public(s)")
        tg_msgs = build_tg_message(new_tenders, f"Modern Business — {n} nouveau(x) marché(s)")

        sent_e = sent_t = 0
        for m in members:
            try:
                await send_email(
                    m["email"],
                    f"🏛 {n} nouveau(x) marché(s) — {datetime.now().strftime('%d/%m/%Y')} — Modern Business",
                    email_html
                )
                sent_e += 1
            except Exception as e:
                logger.error(f"[notify:email:{m['email']}] {e}")

            if m.get("telegram"):
                for msg in tg_msgs:
                    try:
                        await send_telegram_msg(str(m["telegram"]), msg)
                        sent_t += 1
                    except Exception as e:
                        logger.error(f"[notify:tg] {e}")

        slog(f"📢 Notifications envoyées: {sent_e} emails + {sent_t} Telegram ({n} marchés)")
        metric("notifications_sent")
    except Exception as e:
        logger.error(f"[notify_all_members] {e}")
        slog(f"❌ Erreur notification: {e}")



@app.post("/telegram/webhook")
async def tg_webhook_v2(request: Request):
    try:
        data = await request.json()
        msg = data.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()
        user_id = msg.get("from", {}).get("id")
        if not chat_id:
            return {"ok": True}

        import httpx

        if text in ["/start", "start"]:
            reply = (
                f"🏛 <b>Modern Business</b>\n"
                f"Plateforme des marchés publics au Maroc\n\n"
                f"Commandes disponibles:\n"
                f"/tenders — Derniers marchés actifs\n"
                f"/stats — Statistiques\n"
                f"/help — Aide\n\n"
                f"🌐 {SITE_URL}"
            )

        elif text == "/tenders":
            db = get_db()
            try:
                rows = db.execute(
                    "SELECT objet,region,date_limite,url FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 5"
                ).fetchall()
            finally:
                db.close()
            if rows:
                lines = [f"🏛 <b>Derniers marchés actifs</b>\n"]
                for r in rows:
                    lines.append(
                        f"• <b>{r['objet'][:55]}</b>\n"
                        f"  📍 {r['region'] or '—'} | ⏰ {r['date_limite'] or '—'}\n"
                        f"  🔗 {r['url'] or SITE_URL}"
                    )
                reply = "\n\n".join(lines)
            else:
                reply = "Aucun marché actif pour le moment. Revenez bientôt!"

        elif text == "/stats":
            db = get_db()
            try:
                active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
                total  = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
                members= db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0]
            finally:
                db.close()
            reply = (
                f"📊 <b>Modern Business — Statistiques</b>\n\n"
                f"✅ Marchés actifs: <b>{active}</b>\n"
                f"📦 Total indexés: <b>{total}</b>\n"
                f"🏢 Membres: <b>{members}</b>\n\n"
                f"🌐 {SITE_URL}"
            )

        elif text == "/help":
            reply = (
                f"ℹ️ <b>Modern Business — Aide</b>\n\n"
                f"/tenders — Voir les derniers marchés\n"
                f"/stats — Statistiques de la plateforme\n"
                f"/start — Menu principal\n\n"
                f"Pour recevoir les alertes automatiques,\ninscrivez-vous sur {SITE_URL}"
            )

        else:
            reply = f"Commande non reconnue. Envoyez /start pour le menu.\n🌐 {SITE_URL}"

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}
            )
    except Exception as e:
        logger.error(f"[tg] {e}")
    return {"ok": True}


# Add telegram field to contractors
@app.get("/admin/set_telegram")
async def set_member_telegram(pwd: str = "", email: str = "", chat_id: str = ""):
    """Admin: manually link telegram chat_id to a member"""
    check_admin(pwd)
    db = get_db()
    try:
        db.execute("UPDATE contractors SET telegram=? WHERE email=?", (chat_id, email))
        db.commit()
        ch = db.execute("SELECT changes()").fetchone()[0]
    finally:
        db.close()
    return JSONResponse({"ok": True, "updated": ch})


@app.get("/admin/test_notify")
async def test_notify(pwd: str = ""):
    """Test complet: email + telegram"""
    check_admin(pwd)
    try:
        test_tenders = [
            {
                "id": "test_1",
                "objet": "Fourniture de matériel informatique (PC Bureau + Écran)",
                "acheteur": "Commune Urbaine de Rabat — Direction des Achats",
                "region": "Rabat-Salé-Kénitra",
                "domaine": "Informatique & SI",
                "montant": "250 000 DH",
                "date_publication": datetime.now().strftime("%d/%m/%Y"),
                "date_limite": (datetime.now() + timedelta(days=15)).strftime("%d/%m/%Y"),
                "url": "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/46205",
                "description": "Fourniture de 20 PC bureau et écrans pour les services administratifs.",
            },
            {
                "id": "test_2",
                "objet": "Travaux d'entretien et de réparation des voiries communales",
                "acheteur": "Ministère de l'Intérieur — Direction Régionale",
                "region": "Casablanca-Settat",
                "domaine": "Génie Civil & Routes",
                "montant": "1 200 000 DH",
                "date_publication": datetime.now().strftime("%d/%m/%Y"),
                "date_limite": (datetime.now() + timedelta(days=21)).strftime("%d/%m/%Y"),
                "url": "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/",
                "description": "Travaux d'entretien sur 12 km de voirie urbaine.",
            },
        ]
        await notify_all_members(test_tenders)
        return JSONResponse({"ok": True, "msg": f"Test envoyé à tous les membres ({len(test_tenders)} marchés)"})
    except Exception as e:
        logger.error(f"[test_notify] {e}")
        return JSONResponse({"ok": False, "error": str(e)}, 500)


@app.get("/admin/test_digest")
async def test_digest(pwd: str = ""):
    """Test: envoyer le digest maintenant"""
    check_admin(pwd)
    try:
        await send_daily_digest()
        return JSONResponse({"ok": True, "msg": "Digest envoyé"})
    except Exception as e:
        logger.error(f"[test_digest] {e}")
        return JSONResponse({"ok": False, "error": str(e)}, 500)


# ══════════════════════════════════════════════════════
# DAILY DIGEST — كل صباح 08:00
# ══════════════════════════════════════════════════════

async def send_daily_digest():
    """Digest quotidien 08:00 — toutes les nouvelles صفقات"""
    try:
        db = get_db()
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE date_extraction >= ? AND statut='actif' ORDER BY date_extraction DESC",
                (yesterday,)
            ).fetchall()]
            members = []
            for r in db.execute("SELECT email, nom FROM contractors WHERE actif=1").fetchall():
                m = dict(r); m["telegram"] = ""
                members.append(m)
            try:
                for r in db.execute("SELECT email, telegram FROM contractors WHERE actif=1 AND telegram != ''").fetchall():
                    for m in members:
                        if m["email"] == r["email"]:
                            m["telegram"] = r["telegram"] or ""
            except: pass
        finally:
            db.close()

        if not tenders:
            slog("[digest] Aucun nouveau marché — pas d'envoi")
            return
        if not members:
            slog("[digest] Aucun membre — pas d'envoi")
            return

        n = len(tenders)
        date_str = datetime.now().strftime("%d/%m/%Y")
        email_html = build_email_html(tenders, f"Résumé quotidien du {date_str} — {n} marché(s)")
        tg_msgs = build_tg_message(tenders, f"Résumé du {date_str} — {n} marché(s)")

        sent_e = sent_t = 0
        for m in members:
            try:
                await send_email(
                    m["email"],
                    f"📋 Résumé marchés publics du {date_str} ({n} nouveaux) — Modern Business",
                    email_html
                )
                sent_e += 1
            except Exception as e:
                logger.error(f"[digest:email] {e}")

            if m.get("telegram"):
                for msg in tg_msgs:
                    try:
                        await send_telegram_msg(str(m["telegram"]), msg)
                        sent_t += 1
                    except Exception as e:
                        logger.error(f"[digest:tg] {e}")

        slog(f"📰 Digest envoyé: {sent_e} emails + {sent_t} Telegram ({n} marchés)")
        metric("digest_sent")
    except Exception as e:
        logger.error(f"[send_daily_digest] {e}")
        slog(f"❌ Erreur digest: {e}")


async def digest_scheduler():
    """Envoie le digest chaque matin à 08:00"""
    while True:
        now = datetime.now()
        # Calculer le prochain 08:00
        next_run = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait_sec = (next_run - now).total_seconds()
        slog(f"[digest] Prochain envoi dans {wait_sec/3600:.1f}h ({next_run.strftime('%d/%m %H:%M')})")
        await asyncio.sleep(wait_sec)
        try:
            await send_daily_digest()
        except Exception as e:
            logger.error(f"[digest] {e}")


@app.get("/admin/test_digest")
async def test_digest(pwd: str = ""):
    """Test: envoyer le digest maintenant"""
    check_admin(pwd)
    asyncio.create_task(send_daily_digest())
    return JSONResponse({"ok": True, "msg": "Digest envoyé à tous les membres"})


# ══════════════════════════════════════════════════════
# NOTIFICATION AGENT — مستقل + تشخيص كامل
# ══════════════════════════════════════════════════════

async def _tg_send_raw(chat_id: str, text: str) -> dict:
    """Raw telegram send with full error reporting"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"},
                timeout=15
            )
            data = r.json()
            return {"ok": r.status_code == 200 and data.get("ok"), "status": r.status_code, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def _email_send_raw(to: str, subject: str, html: str) -> dict:
    """Raw email send with full error reporting"""
    import asyncio, smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Modern Business <{GMAIL_USER}>"
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))

        def _send():
            s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20)
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to, msg.as_string())
            s.quit()
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send)
        return {"ok": True}
    except smtplib.SMTPAuthenticationError as e:
        return {"ok": False, "error": f"AUTH_ERROR: {e} — Créer App Password sur myaccount.google.com/apppasswords"}
    except smtplib.SMTPException as e:
        return {"ok": False, "error": f"SMTP_ERROR: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/admin/diagnose")
async def diagnose(pwd: str = ""):
    """Full diagnostic — email + telegram + DB"""
    check_admin(pwd)
    results = {}

    # 1. Config check
    results["config"] = {
        "GMAIL_USER": GMAIL_USER or "❌ MANQUANT",
        "GMAIL_PASS": "✅ défini" if GMAIL_PASS else "❌ MANQUANT",
        "TELEGRAM_BOT": "✅ défini" if TELEGRAM_BOT else "❌ MANQUANT",
        "ANTHROPIC_KEY": "✅ défini" if ANTHROPIC_KEY else "⚠️ optionnel",
    }

    # 2. Telegram test
    results["telegram_bot"] = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT}/getMe")
            d = r.json()
            if d.get("ok"):
                results["telegram_bot"] = {"ok": True, "username": d["result"].get("username")}
            else:
                results["telegram_bot"] = {"ok": False, "error": d}
    except Exception as e:
        results["telegram_bot"] = {"ok": False, "error": str(e)}

    # 3. DB check
    db = get_db()
    try:
        members = db.execute("SELECT id, email, nom FROM contractors WHERE actif=1").fetchall()
        tenders_count = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        # Check telegram column
        try:
            tg_members = db.execute("SELECT COUNT(*) FROM contractors WHERE telegram != '' AND telegram IS NOT NULL").fetchone()[0]
        except:
            tg_members = "colonne manquante"
        results["database"] = {
            "members": len(members),
            "members_list": [f"{m['email']}" for m in members[:10]],
            "tenders_active": tenders_count,
            "telegram_linked": tg_members,
        }
    finally:
        db.close()

    # 4. Email test (send to admin email)
    results["email_test"] = await _email_send_raw(
        GMAIL_USER,
        "✅ Test Diagnostic — Modern Business",
        f"""<div style="font-family:Arial;background:#0d0d0d;color:#fff;padding:24px;border-radius:8px">
        <h2 style="color:#c9a84c">✅ Email fonctionne!</h2>
        <p>Diagnostic envoyé le {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        <p>Membres: {results['database']['members']}</p>
        <p>Marchés actifs: {results['database']['tenders_active']}</p>
        </div>"""
    )

    return JSONResponse(results)


@app.get("/admin/notify_agent")
async def notify_agent(pwd: str = "", target_email: str = "", target_tg: str = ""):
    """
    NOTIFICATION AGENT — Envoie les dernières صفقات
    target_email: email direct (optionnel, sinon tous les membres)
    target_tg: chat_id telegram direct (optionnel)
    """
    check_admin(pwd)

    # Get latest active tenders
    db = get_db()
    try:
        tenders = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 10"
        ).fetchall()]
        if target_email:
            members = [{"email": target_email, "nom": "Test", "telegram": target_tg}]
        else:
            members = []
            for r in db.execute("SELECT email, nom FROM contractors WHERE actif=1").fetchall():
                m = dict(r); m["telegram"] = ""
                members.append(m)
            try:
                for r in db.execute("SELECT email, telegram FROM contractors WHERE actif=1").fetchall():
                    for m in members:
                        if m["email"] == r["email"] and r["telegram"]:
                            m["telegram"] = r["telegram"]
            except: pass
    finally:
        db.close()

    if not tenders:
        return JSONResponse({"ok": False, "msg": "Aucun marché actif"})
    if not members:
        return JSONResponse({"ok": False, "msg": "Aucun membre inscrit"})

    report = {"total_members": len(members), "total_tenders": len(tenders), "sent": [], "errors": []}

    email_html = build_email_html(tenders, f"🏛 {len(tenders)} Marchés Publics Actifs")
    tg_messages = build_tg_message(tenders, f"Modern Business — {len(tenders)} Marchés Actifs")

    for m in members:
        member_result = {"email": m["email"], "email_ok": False, "tg_ok": False}

        # Send email
        email_r = await _email_send_raw(
            m["email"],
            f"🏛 {len(tenders)} Marchés Publics — {datetime.now().strftime('%d/%m/%Y')} — Modern Business",
            email_html
        )
        member_result["email_ok"] = email_r["ok"]
        if not email_r["ok"]:
            member_result["email_error"] = email_r.get("error", "")
            report["errors"].append(f"EMAIL {m['email']}: {email_r.get('error','')}")

        # Send Telegram if linked
        if m.get("telegram"):
            for msg in tg_messages:
                tg_r = await _tg_send_raw(str(m["telegram"]), msg)
                member_result["tg_ok"] = tg_r["ok"]
                if not tg_r["ok"]:
                    member_result["tg_error"] = tg_r.get("error") or str(tg_r.get("data",""))
                    report["errors"].append(f"TG {m['telegram']}: {tg_r.get('error','')}")

        report["sent"].append(member_result)

    slog(f"🤖 Agent: {sum(1 for s in report['sent'] if s['email_ok'])} emails + {sum(1 for s in report['sent'] if s['tg_ok'])} TG")
    metric("agent_notif")
    return JSONResponse(report)


@app.get("/admin/link_telegram")
async def link_telegram(pwd: str = "", email: str = "", chat_id: str = ""):
    """Lier un chat_id Telegram à un membre"""
    check_admin(pwd)
    if not email or not chat_id:
        return JSONResponse({"ok": False, "msg": "email et chat_id requis"})
    db = get_db()
    try:
        # Ensure column exists
        try: db.execute("ALTER TABLE contractors ADD COLUMN telegram TEXT DEFAULT ''")
        except: pass
        db.execute("UPDATE contractors SET telegram=? WHERE email=?", (chat_id, email))
        db.commit()
        updated = db.execute("SELECT changes()").fetchone()[0]
    finally:
        db.close()

    if updated:
        # Test immediately
        test_r = await _tg_send_raw(chat_id,
            f"✅ <b>Telegram lié avec succès!</b>\n\nVous recevrez désormais les alertes marchés publics.\n🌐 {SITE_URL}")
        return JSONResponse({"ok": True, "telegram_test": test_r})
    return JSONResponse({"ok": False, "msg": f"Email {email} non trouvé"})


# Override scheduler to use agent
async def scheduler_loop_v2():
    global LAST_SCRAPE
    await asyncio.sleep(60)
    while True:
        try:
            if time.time() - LAST_SCRAPE >= SCRAPE_HOURS * 3600:
                LAST_SCRAPE = time.time()
                loop = asyncio.get_event_loop()
                new_tenders = await loop.run_in_executor(None, run_scraper)
                if new_tenders:
                    await notify_all_members(new_tenders)
        except Exception as e:
            SCRAPE_STATS["running"] = False
            logger.error(f"[scheduler_v2] {e}")
        await asyncio.sleep(600)
