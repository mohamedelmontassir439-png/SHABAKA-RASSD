"""
Modern Business BETA — Veille Marchés Publics Maroc
════════════════════════════════════════════════════
Objectif: Scraper marchespublics.gov.ma → Classifier → Alertes instantanées

Architecture: FastAPI + SQLite + 3 agents
  · ScraperAgent  — scan IDs bdc_XXXXX, parse card layout
  · NotifyAgent   — Telegram + Email instantané par secteur
  · MonitorAgent  — expire + cleanup toutes les heures
"""
import os, re, time, json, asyncio, hashlib, secrets, logging, hmac
import sqlite3, threading, traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

try:
    from bs4 import BeautifulSoup as BS
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

try: from itsdangerous import URLSafeTimedSerializer; HAS_ITS = True
except: HAS_ITS = False

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
BRAND        = "Modern Business"
SITE_URL     = os.getenv("SITE_URL",    "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS   = os.getenv("ADMIN_PASS",  "rassd2026")
SECRET_KEY   = os.getenv("SECRET_KEY",  secrets.token_hex(32))
DB_PATH      = os.getenv("DB_PATH",     "data/mb.db")
TELEGRAM_BOT = os.getenv("TELEGRAM_BOT","7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_CHAT   = os.getenv("ADMIN_CHAT_ID","6424992854")
BREVO_KEY    = os.getenv("BREVO_API_KEY","")
SCRAPE_HRS   = int(os.getenv("SCRAPE_INTERVAL_HOURS","2"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("mb")

# ══════════════════════════════════════════════
# SECURITY MIDDLEWARE
# ══════════════════════════════════════════════
class SecureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        })
        return resp

# ══════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════
_rl: dict = {}
_rl_lock = threading.Lock()

def rate_limit(ip: str, key: str, max_c=10, win=60) -> bool:
    k = f"{ip}:{key}"; now = time.time()
    with _rl_lock:
        calls = [t for t in _rl.get(k,[]) if now-t < win]
        if len(calls) >= max_c: return False
        calls.append(now); _rl[k] = calls
    return True

def get_ip(r: Request) -> str:
    fwd = r.headers.get("X-Forwarded-For","")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "127.0.0.1")

def rl(req: Request, key: str, max_c=10, win=60):
    if not rate_limit(get_ip(req), key, max_c, win):
        raise HTTPException(429, "Trop de requêtes")

# ══════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════
COOKIE = "mb_s"
TTL    = 86400 * 30

def session_create(resp: Response, uid: int):
    if HAS_ITS:
        s = URLSafeTimedSerializer(SECRET_KEY, salt="mb")
        token = s.dumps({"id": uid})
    else:
        sig = hmac.new(SECRET_KEY.encode(), str(uid).encode(), hashlib.sha256).hexdigest()
        token = f"{uid}.{sig}"
    resp.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="lax",
                    secure=SITE_URL.startswith("https"))

def session_get(req: Request) -> Optional[int]:
    raw = req.cookies.get(COOKIE)
    if not raw: return None
    if HAS_ITS:
        try:
            s = URLSafeTimedSerializer(SECRET_KEY, salt="mb")
            d = s.loads(raw, max_age=TTL)
            return int(d.get("id",0))
        except: return None
    try:
        uid, sig = raw.rsplit(".",1)
        expected = hmac.new(SECRET_KEY.encode(), uid.encode(), hashlib.sha256).hexdigest()
        return int(uid) if hmac.compare_digest(sig, expected) else None
    except: return None

def session_del(resp: Response): resp.delete_cookie(COOKIE)

# ══════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════
def get_db() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=5000")
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id               TEXT PRIMARY KEY,
        objet            TEXT NOT NULL DEFAULT '',
        acheteur         TEXT DEFAULT '',
        region           TEXT DEFAULT '',
        domaine          TEXT DEFAULT '',
        type_marche      TEXT DEFAULT '',
        date_publication TEXT DEFAULT '',
        date_limite      TEXT DEFAULT '',
        statut           TEXT DEFAULT 'actif',
        url              TEXT DEFAULT '',
        source           TEXT DEFAULT 'marchespublics',
        date_extraction  TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_domaine ON tenders(domaine);
    CREATE INDEX IF NOT EXISTS idx_t_date    ON tenders(date_extraction DESC);

    CREATE TABLE IF NOT EXISTS members (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        nom        TEXT NOT NULL DEFAULT '',
        email      TEXT UNIQUE NOT NULL,
        phone      TEXT DEFAULT '',
        telegram   TEXT DEFAULT '',
        secteurs   TEXT DEFAULT '',
        pw_hash    TEXT NOT NULL DEFAULT '',
        actif      INTEGER DEFAULT 1,
        notif_tg   INTEGER DEFAULT 1,
        notif_email INTEGER DEFAULT 1,
        created_at TEXT DEFAULT '',
        last_login TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_m_email ON members(email);

    CREATE TABLE IF NOT EXISTS notif_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        tender_id TEXT,
        channel   TEXT,
        sent_at   TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS scrape_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        found       INTEGER DEFAULT 0,
        saved       INTEGER DEFAULT 0,
        errors      INTEGER DEFAULT 0,
        duration_s  REAL DEFAULT 0,
        started_at  TEXT DEFAULT '',
        finished_at TEXT DEFAULT ''
    );
    """)
    db.commit(); db.close()
    log.info("DB ready ✓")

def hash_pw(pw: str) -> str:
    salt = SECRET_KEY[:16].encode()
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 260_000).hex()

def check_pw(pw: str, h: str) -> bool:
    return hmac.compare_digest(hash_pw(pw), h)

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def get_member(req: Request) -> Optional[dict]:
    uid = session_get(req)
    if not uid: return None
    db = get_db()
    try:
        row = db.execute("SELECT * FROM members WHERE id=? AND actif=1",(uid,)).fetchone()
        return dict(row) if row else None
    finally: db.close()

# ══════════════════════════════════════════════
# CLASSIFICATION
# ══════════════════════════════════════════════
REGIONS = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","kenitra","témara","khémisset"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache"],
    "Oriental":                  ["oujda","nador","berkane","taourirt"],
    "Béni Mellal-Khénifra":     ["béni mellal","khénifra","azilal","khouribga"],
    "Souss-Massa":               ["agadir","tiznit","taroudant"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt"],
    "Laâyoune-Sakia":            ["laayoune","boujdour"],
    "Dakhla-Oued Ed-Dahab":      ["dakhla"],
    "Guelmim-Oued Noun":         ["guelmim","tan-tan"],
}

SECTEURS = {
    "T101 - Constructions & Bâtiments":   ["bâtiment","construction","maçonnerie","béton","gros oeuvre","réhabilitation","façade","toiture"],
    "T102 - Terrassements":               ["terrassement","remblai","déblai","excavation","nivellement"],
    "T103 - Menuiserie & Métallerie":     ["menuiserie","métallerie","charpente","ferronnerie","portail","serrurerie"],
    "T104 - Plomberie & Climatisation":   ["plomberie","chauffage","climatisation","sanitaire","tuyauterie","cvc"],
    "T105 - Peinture & Vitrerie":         ["peinture","vitrerie","enduit","revêtement mur"],
    "T106 - Étanchéité & Isolation":      ["étanchéité","isolation","membrane","imperméabilisation"],
    "T107 - Revêtements de Sol":          ["carrelage","parquet","revêtement sol","dallage","faïence"],
    "T108 - Plâtrerie & Faux Plafonds":   ["plâtrerie","faux plafond","cloison"],
    "T110 - Génie Civil":                 ["génie civil","pont","infrastructure","ouvrage d'art"],
    "T111 - Espaces Verts":               ["espaces verts","jardinage","plantation","gazon","élagage"],
    "T201 - Assainissement":              ["assainissement","égout","step","collecteur","canalisation"],
    "T203 - Hydraulique & Eau":           ["hydraulique","eau potable","adduction","barrage","forage","irrigation"],
    "T301 - Travaux Routiers":            ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation"],
    "T401 - Électricité & Éclairage":     ["électricité","éclairage","câblage","tableau électrique","transformateur"],
    "T402 - Sécurité Électronique":       ["vidéosurveillance","cctv","alarme incendie","contrôle accès"],
    "T403 - Télécommunications":          ["télécommunication","fibre optique","réseau","switch","wifi"],
    "P813 - Équipements Médicaux":        ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament"],
    "P814 - Climatisation":               ["climatiseur","split","froid industriel","chambre froide"],
    "P816 - Matériel Roulant":            ["véhicule","voiture","camion","bus","carburant","gasoil"],
    "P818 - Informatique":                ["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud"],
    "P825 - Fournitures Bureau":          ["fournitures","papier","ramette","mobilier bureau","chaise","bureau"],
    "P833 - Produits Pharmaceutiques":    ["médicament","pharmaceutique","réactif labo"],
    "P834 - Alimentation":                ["alimentation","denrée","viande","restauration","traiteur"],
    "P839 - Matériaux Construction":      ["ciment","sable","gravier","béton prêt","brique","acier"],
    "P841 - Hygiène & Nettoyage":         ["nettoyage produits","propreté produits","désinfection","savon","détergent"],
    "P850 - Énergies Renouvelables":      ["solaire","photovoltaïque","énergie renouvelable","panneau solaire"],
    "S901 - IT & Développement":          ["développement logiciel","application mobile","site web","cybersécurité"],
    "S902 - Études & Conseil":            ["étude","conseil","consultant","expertise","audit","bureau d'études"],
    "S906 - Maintenance":                 ["maintenance","entretien","réparation","dépannage"],
    "S907 - Nettoyage Service":           ["nettoyage service","propreté service","dératisation"],
    "S908 - Gardiennage":                 ["gardiennage","sécurité agent","surveillance","agent de sécurité"],
    "S910 - Communication":               ["communication","publicité","événementiel","impression"],
    "S913 - Formation":                   ["formation","coaching","séminaire","certification"],
    "S915 - Transport & Location":        ["transport","location véhicule","navette","chauffeur","location matériel"],
}
SECTEURS_LIST = list(SECTEURS.keys())
REGIONS_LIST  = list(REGIONS.keys())

def classify_region(text: str) -> str:
    t = text.lower()
    for region, kws in REGIONS.items():
        if any(k in t for k in kws): return region
    return "Maroc"

def classify_secteur(text: str) -> str:
    from collections import defaultdict
    t = text.lower()
    scores: dict = defaultdict(int)
    for sect, kws in SECTEURS.items():
        for kw in kws:
            if kw in t: scores[sect] += 2 if len(kw) > 10 else 1
    return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

def classify_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation","aménagement"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement","produits"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage","transport"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise"]): return "Études"
    return "Fournitures"

def clean_objet(text: str) -> str:
    t = re.sub(r'^#\s*0*\d+\s*','',text.strip())
    t = re.sub(r'^LOT\s*[N°n°#]?\s*\d+\s*[:\-–]?\s*','',t,flags=re.I)
    t = re.sub(r'^\d+\s*[:\-–]\s*','',t)
    t = re.sub(r'\s+',' ',t).strip()
    return t[0].upper()+t[1:] if t and t[0].islower() else t

def extract_date(text: str) -> str:
    if not text: return ""
    m = re.search(r'(\d{1,2}/\d{2}/\d{4})(?:\s+\d{1,2}:\d{2})?',text)
    if m: return m.group(1)
    m = re.search(r'(\d{4}-\d{2}-\d{2})',text)
    if m: return m.group(1)
    return ""

def is_expired(d: str) -> bool:
    if not d or d in ("N/A","—","-","","null"): return False
    m = re.search(r'(\d{1,2}/\d{2}/\d{4})',str(d))
    if m:
        try: return datetime.strptime(m.group(1),"%d/%m/%Y").date() < datetime.now().date()
        except: pass
    m = re.search(r'(\d{4}-\d{2}-\d{2})',str(d))
    if m:
        try: return datetime.strptime(m.group(1),"%Y-%m-%d").date() < datetime.now().date()
        except: pass
    return False

# ══════════════════════════════════════════════
# SCRAPER AGENT
# ══════════════════════════════════════════════
class SLog:
    entries: list = []
    @classmethod
    def add(cls, msg: str):
        e = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.entries.append(e); log.info(e)
        if len(cls.entries) > 500: cls.entries = cls.entries[-400:]
    @classmethod
    def last(cls, n=100): return cls.entries[-n:]

class SState:
    running = False; found = 0; saved = 0
    errors = 0; started = ""; current = 0; total = 0

BASE_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show"

PORTAL_GARBAGE = [
    "accueil","liste des avis","connexion","portail marocain",
    "marchés publics maroc","espace entreprise","se connecter",
    "liste des","avis d'achat","tableau de bord","recherche",
    "inscription","bienvenue","login","home","dashboard"
]

AO_KEYWORDS = [
    "fourniture","travaux","service","prestation","acquisition",
    "maintenance","réhabilitation","construction","étude","mission",
    "location","nettoyage","gardiennage","transport","formation",
    "audit","aménagement","installation","extension","livraison",
    "réparation","entretien","rénovation","pose","démolition"
]

def card_value(soup, keywords: list) -> str:
    """Extrait la valeur d'un champ card sur marchespublics.gov.ma"""
    kw_lower = [k.lower() for k in keywords]
    full = soup.get_text(" ", strip=True)
    import re as _re
    LABEL_CLS = _re.compile(r'label|titre|key|head|caption|field', _re.I)

    # Strat 1: élément de classe label → next sibling
    for el in soup.find_all(True, class_=LABEL_CLS):
        txt = el.get_text(strip=True)
        if not any(k in txt.lower() for k in kw_lower): continue
        sib = el.find_next_sibling()
        if sib:
            v = sib.get_text(strip=True)
            if 2 < len(v) < 300: return v
        if el.parent:
            ps = el.parent.find_next_sibling()
            if ps:
                v = ps.get_text(strip=True)
                if 2 < len(v) < 300: return v

    # Strat 2: tout élément court avec le keyword → next sibling
    for el in soup.find_all(True):
        txt = el.get_text(strip=True)
        if len(txt) > 120 or len(txt) < 4: continue
        if not any(k in txt.lower() for k in kw_lower): continue
        sib = el.find_next_sibling()
        if sib:
            v = sib.get_text(strip=True)
            if 2 < len(v) < 300: return v

    # Strat 3: regex dans texte complet
    for kw in kw_lower:
        idx = full.lower().find(kw)
        if idx >= 0:
            after = full[idx+len(kw):idx+len(kw)+200].strip()
            lines = [l.strip() for l in after.split("\n") if l.strip()]
            if lines: return lines[0][:200]
    return ""

def parse_page(html: str, tid: str) -> Optional[dict]:
    """Parse une page consultation marchespublics.gov.ma"""
    if not HAS_BS4: return None
    try:
        soup = BS(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # Annulation
        if any(k in full_text.lower() for k in
               ["marché annulé","consultation annulée","annulé par","a été annulée"]):
            return None

        def is_garbage(t: str) -> bool:
            tl = t.lower().strip()
            return any(tl == g or tl.startswith(g) for g in PORTAL_GARBAGE)

        # ── Objet ─────────────────────────────────────────
        objet = ""

        # 1. <title> HTML
        title_tag = soup.find("title")
        if title_tag:
            t = title_tag.get_text(strip=True)
            t = re.sub(r'\s*[|\-–].*marchés publics.*','',t,flags=re.I).strip()
            t = re.sub(r'\s*[|\-–].*portail.*','',t,flags=re.I).strip()
            if 10 < len(t) < 400 and not is_garbage(t):
                objet = t

        # 2. h1/h2/h3 (pas le header du site)
        if not objet:
            for sel in [".consultation-title",".objet-marche",".card-title","h2","h3"]:
                for el in soup.select(sel):
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600 and not is_garbage(t):
                        objet = t; break
                if objet: break

        # 3. card_value objet/intitulé
        if not objet:
            objet = card_value(soup, ["objet du marché","objet de la consultation","intitulé","objet"])

        # 4. Nature de prestation comme fallback
        if not objet or len(objet) < 8:
            nature = card_value(soup, ["nature de prestation","nature"])
            cat    = card_value(soup, ["catégorie principale","catégorie"])
            if nature and len(nature) > 8:
                objet = nature
            elif cat and len(cat) > 4:
                objet = f"Prestation — {cat}"

        # 5. Description valide
        if not objet or len(objet) < 8:
            for el in soup.find_all(["p","div","span"]):
                t = el.get_text(strip=True)
                if 15 < len(t) < 400 and not is_garbage(t):
                    if any(k in t.lower() for k in AO_KEYWORDS):
                        objet = t; break

        if not objet or len(objet) < 8:
            return None
        objet = clean_objet(objet)

        # ── Date limite ───────────────────────────────────
        dl_raw = card_value(soup, [
            "date limite de réception des devis",
            "date limite de réception des offres",
            "date limite","date de remise","remise des offres",
            "remise des plis","date de clôture","réception des devis",
        ])
        if not dl_raw:
            m2 = re.search(
                r'(?:date limite|réception des (?:offres|devis)|remise des (?:offres|plis))'
                r'.{0,80}?(\d{1,2}/\d{2}/\d{4})',
                full_text, re.I|re.S)
            if m2: dl_raw = m2.group(1)

        date_lim = extract_date(dl_raw)

        # Filtrer immédiatement si expiré
        if date_lim and is_expired(date_lim):
            return None

        # ── Acheteur ──────────────────────────────────────
        acheteur = card_value(soup, ["acheteur public","maître d'ouvrage","organisme"])

        # ── Catégorie / Type ──────────────────────────────
        cat_off = card_value(soup, ["catégorie principale","catégorie"])
        nature  = card_value(soup, ["nature de prestation","nature"])
        lieu    = card_value(soup, ["lieu d'exécution","localisation"])

        # ── Date publication ──────────────────────────────
        dp_raw  = card_value(soup, ["date mise en ligne","date de publication"])
        date_pub = extract_date(dp_raw)

        # ── Classification ────────────────────────────────
        combined = f"{cat_off} {nature} {objet}"
        domaine  = classify_secteur(combined)

        cat_l = cat_off.lower()
        if "travaux" in cat_l:           type_m = "Travaux"
        elif "fournitures" in cat_l:     type_m = "Fournitures"
        elif "services" in cat_l:        type_m = "Services"
        else:                            type_m = classify_type(f"{objet} {nature}")

        region = classify_region(f"{lieu} {acheteur} {full_text[:300]}")

        return {
            "id":               f"bdc_{tid}",
            "objet":            objet[:400],
            "acheteur":         acheteur[:200],
            "region":           region,
            "domaine":          domaine,
            "type_marche":      type_m,
            "date_publication": date_pub,
            "date_limite":      date_lim,
            "statut":           "actif",
            "url":              f"{BASE_URL}/{tid}",
            "source":           "marchespublics",
        }
    except Exception as e:
        log.error(f"[parse #{tid}] {e}")
        return None

def save_tender(t: dict) -> bool:
    if not t or not t.get("id") or not t.get("objet"): return False
    try:
        db = get_db()
        db.execute("""INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,domaine,type_marche,
             date_publication,date_limite,statut,url,source,date_extraction)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            str(t["id"])[:80],         str(t["objet"])[:400],
            str(t.get("acheteur",""))[:200], str(t.get("region",""))[:100],
            str(t.get("domaine",""))[:80],   str(t.get("type_marche",""))[:40],
            str(t.get("date_publication",""))[:20], str(t.get("date_limite",""))[:20],
            "actif", str(t.get("url",""))[:400], "marchespublics",
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        db.commit()
        changed = db.execute("SELECT changes()").fetchone()[0]
        db.close()
        return changed > 0
    except Exception as e:
        log.error(f"[save] {e}")
        try: db.close()
        except: pass
        return False

def scrape_run() -> list:
    """Scan séquentiel des IDs marchespublics — retourne les nouveaux marchés actifs"""
    import requests, random
    t0 = time.time()
    new_tenders = []
    SState.running = True
    SState.found = SState.saved = SState.errors = 0
    SState.started = datetime.now().strftime("%H:%M:%S")
    SLog.add("═══ ScraperAgent BETA — scan marchespublics.gov.ma ═══")

    db = get_db()
    known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
    db.close()

    max_id = 311500
    for k in known:
        if k.startswith("bdc_"):
            try:
                n = int(k[4:])
                if n > max_id: max_id = n
            except: pass

    start_id = max(311500, max_id - 30)
    end_id   = max_id + 500
    scan_ids = [str(i) for i in range(start_id, end_id+1) if f"bdc_{i}" not in known]

    SState.total = len(scan_ids)
    SLog.add(f"Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs à vérifier)")

    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    consec_empty = 0
    for idx, tid in enumerate(scan_ids):
        SState.current = idx + 1
        try:
            r = s.get(f"{BASE_URL}/{tid}", timeout=12)
            if r.status_code != 200 or len(r.text) < 2000:
                consec_empty += 1
                if consec_empty > 40 and SState.saved == 0:
                    SLog.add(f"Trop de pages vides ({consec_empty}), arrêt")
                    break
                continue
            consec_empty = 0
            SState.found += 1
            t = parse_page(r.text, tid)
            if not t:
                known.add(f"bdc_{tid}"); continue
            if save_tender(t):
                SState.saved += 1
                known.add(t["id"])
                dl = t.get("date_limite","?")
                SLog.add(f"✓ #{tid} [{t['domaine'][:20]}] {t['objet'][:50]} | ⏰ {dl}")
                new_tenders.append(t)
            else:
                known.add(f"bdc_{tid}")
            time.sleep(random.uniform(0.6, 1.2))
        except Exception as e:
            SState.errors += 1; consec_empty += 1
            SLog.add(f"✗ #{tid}: {str(e)[:50]}")

    # Auto-expire
    try:
        db = get_db()
        today = datetime.now().date()
        db.execute(
            "UPDATE tenders SET statut='expire' WHERE statut='actif' "
            "AND date_limite!='' AND date_limite NOT LIKE '%/%' "
            "AND date_limite < date('now') AND date_limite NOT IN ('N/A','—','-')"
        )
        rows = db.execute(
            "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite LIKE '%/%'"
        ).fetchall()
        exp = []
        for r in rows:
            dl = (r["date_limite"] or "").strip()
            m2 = re.search(r'(\d{1,2}/\d{2}/\d{4})', dl)
            if m2:
                try:
                    if datetime.strptime(m2.group(1),"%d/%m/%Y").date() < today:
                        exp.append(r["id"])
                except: pass
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join(['?']*len(exp))})", exp)
            SLog.add(f"[expire] {len(exp)} marchés expirés nettoyés")
        db.commit()

        # Log run
        dur = time.time()-t0
        db.execute("INSERT INTO scrape_runs (found,saved,errors,duration_s,started_at,finished_at) VALUES (?,?,?,?,?,?)",
                   (SState.found,SState.saved,SState.errors,dur,SState.started,datetime.now().strftime("%H:%M:%S")))
        db.commit(); db.close()
    except Exception as e: log.warning(f"[expire] {e}")

    dur = time.time()-t0
    SLog.add(f"═══ Terminé en {dur:.0f}s | {SState.saved} nouveaux | {SState.errors} erreurs ═══")
    SState.running = False
    return new_tenders

# ══════════════════════════════════════════════
# NOTIFICATION AGENT
# ══════════════════════════════════════════════
async def send_telegram(chat_id: str, text: str) -> bool:
    if not TELEGRAM_BOT or not chat_id: return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id":chat_id,"text":text,"parse_mode":"HTML"}
            )
            return r.status_code == 200
    except Exception as e:
        log.warning(f"[TG] {e}"); return False

async def send_email_brevo(to: str, subject: str, html: str) -> bool:
    if not BREVO_KEY: return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key":BREVO_KEY,"content-type":"application/json"},
                json={
                    "sender":{"name":BRAND,"email":"noreply@modernbusiness.ma"},
                    "to":[{"email":to}],
                    "subject":subject,
                    "htmlContent":html
                }
            )
            return r.status_code in (200,201,202)
    except Exception as e:
        log.warning(f"[email] {e}"); return False

def match_member(member: dict, tenders: list) -> list:
    """Retourne les marchés qui correspondent aux secteurs du membre"""
    secteurs = [s.strip() for s in (member.get("secteurs","") or "").split(",") if s.strip()]
    if not secteurs:
        return tenders  # pas de filtre → reçoit tout

    matched = []
    for t in tenders:
        dom = (t.get("domaine","") or "").lower()
        obj = (t.get("objet","") or "").lower()
        full = dom + " " + obj
        for s in secteurs:
            s_code = s[:4].upper()
            d_code = dom[:4].upper()
            if s_code == d_code or s_code in dom.upper():
                matched.append(t); break
            if s in SECTEURS:
                if any(kw in full for kw in SECTEURS[s]):
                    matched.append(t); break
    return matched

def build_tg_message(tenders: list, nom: str) -> str:
    lines = [f"🏛 <b>Modern Business</b> — {len(tenders)} nouveau(x) marché(s) pour vous, {nom}\n"]
    for t in tenders[:5]:
        dl = t.get("date_limite","?") or "non précisée"
        lines.append(
            f"📋 <b>{t['objet'][:80]}</b>\n"
            f"🏢 {t.get('acheteur','')[:60]}\n"
            f"🏷 {t.get('domaine','')[:30]} | {t.get('type_marche','')}\n"
            f"📍 {t.get('region','Maroc')}\n"
            f"⏰ Limite: {dl}\n"
            f"🔗 <a href='{t.get('url','')}'>Voir la consultation</a>\n"
        )
    if len(tenders) > 5:
        lines.append(f"... et {len(tenders)-5} autre(s) sur {SITE_URL}/tenders")
    return "\n".join(lines)

def build_email_html(tenders: list, nom: str) -> str:
    cards = ""
    for t in tenders[:10]:
        dl = t.get("date_limite","Non précisée") or "Non précisée"
        cards += f"""
        <div style="border:1px solid #2a2a2a;border-radius:8px;padding:20px;margin-bottom:16px;background:#111;">
          <h3 style="color:#c9a84c;margin:0 0 8px">{t['objet'][:100]}</h3>
          <p style="color:#999;margin:4px 0">🏢 {t.get('acheteur','')[:80]}</p>
          <p style="color:#999;margin:4px 0">🏷 {t.get('domaine','')[:40]} | {t.get('type_marche','')}</p>
          <p style="color:#999;margin:4px 0">📍 {t.get('region','Maroc')} | ⏰ {dl}</p>
          <a href="{t.get('url','')}" style="display:inline-block;margin-top:10px;padding:8px 16px;background:#c9a84c;color:#000;border-radius:4px;text-decoration:none;font-weight:600">Voir la consultation →</a>
        </div>"""
    return f"""<!DOCTYPE html><html><body style="background:#030303;font-family:sans-serif;color:#f3eee7;padding:32px;max-width:600px;margin:0 auto">
    <h1 style="color:#c9a84c">{BRAND}</h1>
    <p>Bonjour {nom},</p>
    <p>{len(tenders)} nouveau(x) marché(s) correspondant à vos secteurs :</p>
    {cards}
    <p style="color:#666;font-size:12px">Gérez vos alertes sur <a href="{SITE_URL}/settings" style="color:#c9a84c">{SITE_URL}/settings</a></p>
    </body></html>"""

async def notify_new(tenders: list):
    """Alerte instantanée de tous les membres pour les nouveaux marchés"""
    if not tenders: return
    db = get_db()
    try:
        members = [dict(r) for r in db.execute(
            "SELECT id,nom,email,telegram,secteurs,notif_tg,notif_email FROM members WHERE actif=1"
        ).fetchall()]
    finally: db.close()

    sent_tg = sent_em = 0
    for m in members:
        matched = match_member(m, tenders)
        if not matched: continue
        n = len(matched)
        SLog.add(f"[Notify] {m['nom']}: {n} marchés → TG={bool(m.get('notif_tg') and m.get('telegram'))} Email={bool(m.get('notif_email') and m.get('email'))}")

        if m.get("notif_tg") and m.get("telegram"):
            ok = await send_telegram(m["telegram"], build_tg_message(matched, m["nom"]))
            if ok:
                sent_tg += 1
                db = get_db()
                for t in matched:
                    db.execute("INSERT INTO notif_log (member_id,tender_id,channel,sent_at) VALUES (?,?,'telegram',?)",
                               (m["id"],t["id"],now_str()))
                db.commit(); db.close()

        if m.get("notif_email") and m.get("email"):
            subj = f"🏛 {n} marché(s) — Modern Business"
            ok = await send_email_brevo(m["email"], subj, build_email_html(matched, m["nom"]))
            if ok: sent_em += 1

    if sent_tg or sent_em:
        SLog.add(f"[Notify] ✓ {sent_tg} Telegram + {sent_em} Email envoyés")
        await send_telegram(ADMIN_CHAT,
            f"📊 Scrape terminé: {len(tenders)} nouveaux marchés\n"
            f"📬 {sent_tg} TG + {sent_em} Email envoyés")

# ══════════════════════════════════════════════
# SCHEDULERS
# ══════════════════════════════════════════════
LAST_SCRAPE = 0.0

async def scrape_scheduler():
    await asyncio.sleep(60)
    global LAST_SCRAPE
    while True:
        try:
            if time.time() - LAST_SCRAPE >= SCRAPE_HRS * 3600:
                LAST_SCRAPE = time.time()
                loop = asyncio.get_event_loop()
                new = await loop.run_in_executor(None, scrape_run)
                if new:
                    await notify_new(new)
        except Exception as e:
            SState.running = False
            log.error(f"[scheduler] {e}")
        await asyncio.sleep(300)

async def monitor():
    """Nettoie et expire toutes les heures"""
    while True:
        await asyncio.sleep(3600)
        try:
            db = get_db()
            today = datetime.now().date()
            db.execute(
                "UPDATE tenders SET statut='expire' WHERE statut='actif' "
                "AND date_limite!='' AND date_limite NOT LIKE '%/%' AND date_limite < date('now')"
            )
            rows = db.execute(
                "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite LIKE '%/%'"
            ).fetchall()
            exp = []
            for r in rows:
                m2 = re.search(r'(\d{1,2}/\d{2}/\d{4})', r["date_limite"] or "")
                if m2:
                    try:
                        if datetime.strptime(m2.group(1),"%d/%m/%Y").date() < today:
                            exp.append(r["id"])
                    except: pass
            if exp:
                db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join(['?']*len(exp))})", exp)
            db.execute("DELETE FROM notif_log WHERE sent_at < date('now','-30 days')")
            db.commit(); db.close()
        except Exception as e: log.warning(f"[monitor] {e}")

# ══════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app):
    for d in ["static","data","templates"]:
        os.makedirs(d, exist_ok=True)
    init_db()
    asyncio.create_task(scrape_scheduler())
    asyncio.create_task(monitor())
    log.info(f"✅ {BRAND} BETA démarré")
    yield

app = FastAPI(lifespan=lifespan, title=BRAND, docs_url=None, redoc_url=None)
app.add_middleware(SecureMiddleware)

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

try:
    tpl = Jinja2Templates(directory="templates")
except: tpl = None

def render(req: Request, tmpl: str, ctx: dict={}):
    if not tpl: return HTMLResponse("<h1>Template error</h1>",500)
    try:
        return tpl.TemplateResponse(tmpl, {
            "request":req, "BRAND":BRAND, "SITE_URL":SITE_URL,
            "SECTEURS_LIST":SECTEURS_LIST, "REGIONS_LIST":REGIONS_LIST,
            "member":get_member(req),
            "now":datetime.now(),
            **ctx
        })
    except Exception as e:
        log.error(f"[render:{tmpl}] {e}\n{traceback.format_exc()}")
        raise

def flash(url: str, msg: str, kind="ok"):
    return RedirectResponse(f"{url}?_flash={msg}&_fk={kind}",302)

# ══════════════════════════════════════════════
# ROUTES — PUBLIC
# ══════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    try:
        stats = {
            "actif":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "total":    db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members":  db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        }
        recent = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 6"
        ).fetchall()]
    finally: db.close()
    return render(req,"landing.html",{"stats":stats,"recent":recent})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders(req: Request, code_f="", region_f="", type_f="", q="", page:int=1):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    per=20; off=(page-1)*per
    SORT_MAP = {"date":"date_extraction DESC","deadline":"date_limite ASC","score":"date_extraction DESC"}
    sort = req.query_params.get("sort","date")
    order = SORT_MAP.get(sort,"date_extraction DESC")
    db = get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if code_f:   conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
        if region_f: conds.append("region=?");       params.append(region_f)
        if type_f:   conds.append("type_marche=?");  params.append(type_f)
        if q:
            conds.append("(objet LIKE ? OR acheteur LIKE ?)")
            params += [f"%{q[:80]}%"]*2
        w=" AND ".join(conds)
        total  = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}",params).fetchone()[0]
        rows   = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
            params+[per,off]).fetchall()]
        sources= [r[0] for r in db.execute("SELECT DISTINCT source FROM tenders WHERE source!='' ORDER BY source").fetchall()]
    finally: db.close()
    return render(req,"tenders.html",{
        "tenders":rows,"total":total,"page":page,"pages":max(1,(total+per-1)//per),
        "code_f":code_f,"region_f":region_f,"type_f":type_f,"q":q,"sort":sort,
        "sources_list":sources,
    })

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    db = get_db()
    try:
        t = db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not t: raise HTTPException(404,"Marché introuvable")
        db.execute("UPDATE tenders SET statut=statut WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return render(req,"tender_detail.html",{"tender":dict(t)})

# ── Auth ──────────────────────────────────────
@app.get("/register", response_class=HTMLResponse)
async def reg_get(req: Request):
    return render(req,"register.html",{})

@app.post("/register")
async def reg_post(req: Request,
    nom:str=Form(""), email:str=Form(""), phone:str=Form(""),
    telegram:str=Form(""), secteurs:str=Form(""), password:str=Form(""), password2:str=Form("")):
    rl(req,"register",5,3600)
    if not nom or not email or not password:
        return render(req,"register.html",{"error":"Nom, email et mot de passe requis"})
    if password != password2:
        return render(req,"register.html",{"error":"Mots de passe différents"})
    if len(password) < 8:
        return render(req,"register.html",{"error":"Mot de passe trop court (min 8 caractères)"})
    db = get_db()
    try:
        if db.execute("SELECT 1 FROM members WHERE email=?",(email.lower(),)).fetchone():
            db.close()
            return render(req,"register.html",{"error":"Email déjà utilisé"})
        db.execute("""INSERT INTO members (nom,email,phone,telegram,secteurs,pw_hash,actif,created_at)
            VALUES (?,?,?,?,?,?,1,?)""",
            (nom[:100],email.lower()[:200],phone[:30],telegram[:50],
             secteurs[:500],hash_pw(password),now_str()))
        db.commit()
        uid = db.execute("SELECT id FROM members WHERE email=?",(email.lower(),)).fetchone()[0]
        db.close()
    except Exception as e:
        try: db.close()
        except: pass
        return render(req,"register.html",{"error":f"Erreur: {e}"})
    resp = RedirectResponse("/tenders",302)
    session_create(resp, uid)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    m = get_member(req)
    if m: return RedirectResponse("/tenders",302)
    return render(req,"login.html",{})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), password:str=Form("")):
    rl(req,f"login:{get_ip(req)}",5,300)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email.lower(),)).fetchone()
    finally: db.close()
    if not row or not check_pw(password, row["pw_hash"]):
        return render(req,"login.html",{"error":"Email ou mot de passe incorrect"})
    db = get_db()
    db.execute("UPDATE members SET last_login=? WHERE id=?",(now_str(),row["id"]))
    db.commit(); db.close()
    resp = RedirectResponse("/tenders",302)
    session_create(resp, row["id"])
    return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/",302)
    session_del(resp)
    return resp

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"settings.html",{
        "member_secteurs":[s.strip() for s in (m.get("secteurs","") or "").split(",") if s.strip()]
    })

@app.post("/settings")
async def settings_post(req: Request,
    nom:str=Form(""), phone:str=Form(""), telegram:str=Form(""),
    secteurs:str=Form(""), notif_tg:str=Form("0"), notif_email:str=Form("0"),
    password:str=Form(""), password2:str=Form("")):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    db = get_db()
    updates = {
        "nom":nom[:100] or m["nom"],
        "phone":phone[:30],
        "telegram":telegram[:50],
        "secteurs":secteurs[:500],
        "notif_tg":1 if notif_tg=="1" else 0,
        "notif_email":1 if notif_email=="1" else 0,
    }
    if password:
        if password != password2:
            db.close()
            return render(req,"settings.html",{"error":"Mots de passe différents",
                "member_secteurs":[s.strip() for s in (m.get("secteurs","") or "").split(",") if s.strip()]})
        updates["pw_hash"] = hash_pw(password)
    fields = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE members SET {fields} WHERE id=?", list(updates.values())+[m["id"]])
    db.commit(); db.close()
    return flash("/settings","Paramètres sauvegardés ✓")

# ══════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════
def chk(pwd: str):
    if pwd != ADMIN_PASS: raise HTTPException(401,"Non autorisé")

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(req: Request):
    err = req.query_params.get("err","")
    return HTMLResponse(f"""<!DOCTYPE html><html><head><title>Admin — {BRAND}</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{background:#030303;color:#f3eee7;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .box{{background:#111;border:1px solid #222;border-radius:12px;padding:40px;width:360px}}h1{{color:#c9a84c;font-size:22px;margin-bottom:24px}}
    input{{width:100%;padding:12px;background:#1a1a1a;border:1px solid #333;border-radius:6px;color:#f3eee7;font-size:14px;margin-bottom:16px}}
    button{{width:100%;padding:12px;background:#c9a84c;color:#000;border:none;border-radius:6px;font-weight:700;cursor:pointer;font-size:15px}}
    .err{{color:#c46060;margin-bottom:12px;font-size:13px}}</style></head>
    <body><div class="box"><h1>🔐 Admin {BRAND}</h1>
    {"<p class='err'>Mot de passe incorrect</p>" if err else ""}
    <form method="post" action="/admin/login">
    <input type="password" name="pwd" placeholder="Mot de passe admin" autofocus>
    <button type="submit">Connexion</button></form></div></body></html>""")

@app.post("/admin/login")
async def admin_login_post(req: Request, pwd: str=Form("")):
    if pwd != ADMIN_PASS:
        return RedirectResponse("/admin/login?err=1",302)
    resp = RedirectResponse("/admin",302)
    resp.set_cookie("adm_s", hmac.new(SECRET_KEY.encode(), b"admin", hashlib.sha256).hexdigest(),
                    max_age=86400, httponly=True, samesite="lax")
    return resp

def admin_auth(req: Request) -> bool:
    token = req.cookies.get("adm_s","")
    expected = hmac.new(SECRET_KEY.encode(), b"admin", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected)

@app.get("/admin", response_class=HTMLResponse)
async def admin(req: Request):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    db = get_db()
    try:
        stats = {
            "actif":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "expire":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "total":   db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "runs":    db.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0],
        }
        last_run = db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
        members  = [dict(r) for r in db.execute("SELECT id,nom,email,telegram,secteurs,actif,created_at FROM members ORDER BY id DESC LIMIT 20").fetchall()]
        tenders  = [dict(r) for r in db.execute("SELECT * FROM tenders WHERE statut='actif' ORDER BY date_extraction DESC LIMIT 10").fetchall()]
    finally: db.close()
    return render(req,"admin.html",{
        "stats":stats,"last_run":dict(last_run) if last_run else {},
        "members":members,"tenders":tenders,
        "slog":SLog.last(30),"sstate":SState,
    })

@app.get("/admin/scrape")
async def admin_scrape(req: Request):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    if SState.running: return JSONResponse({"error":"Scrape déjà en cours"},400)
    async def run():
        loop = asyncio.get_event_loop()
        new = await loop.run_in_executor(None, scrape_run)
        if new: await notify_new(new)
    asyncio.create_task(run())
    return RedirectResponse("/admin",302)

@app.get("/admin/scrape_stream")
async def scrape_stream(req: Request):
    if not admin_auth(req):
        return JSONResponse({"error":"Non autorisé"},401)
    last_idx = [0]
    async def gen():
        while True:
            entries = SLog.last(200)
            new = entries[last_idx[0]:]
            for e in new:
                data = json.dumps({"log":e,"state":{
                    "running":SState.running,"found":SState.found,
                    "saved":SState.saved,"errors":SState.errors,
                    "current":SState.current,"total":SState.total,
                }})
                yield f"data: {data}\n\n"
            last_idx[0] = len(entries)
            if not SState.running and last_idx[0] > 0:
                yield f"data: {json.dumps({'done':True,'state':{'saved':SState.saved}})}\n\n"
                break
            await asyncio.sleep(0.8)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/admin/expire")
async def admin_expire(req: Request):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    db = get_db()
    try:
        today = datetime.now().date()
        db.execute("UPDATE tenders SET statut='expire' WHERE statut='actif' AND date_limite!='' AND date_limite NOT LIKE '%/%' AND date_limite < date('now')")
        rows = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite LIKE '%/%'").fetchall()
        exp = []
        for r in rows:
            m2 = re.search(r'(\d{1,2}/\d{2}/\d{4})', r["date_limite"] or "")
            if m2:
                try:
                    if datetime.strptime(m2.group(1),"%d/%m/%Y").date() < today: exp.append(r["id"])
                except: pass
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join(['?']*len(exp))})", exp)
        db.commit()
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        db.close()
        return JSONResponse({"expired":len(exp),"active_remaining":active})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error":str(e)},500)

@app.get("/admin/clear_db")
async def clear_db(req: Request):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    db = get_db()
    try:
        n = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.execute("DELETE FROM tenders")
        db.execute("DELETE FROM notif_log")
        db.commit(); db.close()
        return JSONResponse({"ok":True,"deleted":n})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error":str(e)},500)

@app.get("/admin/test_notify")
async def admin_test_notify(req: Request, chat_id:str=""):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    target = chat_id or ADMIN_CHAT
    ok = await send_telegram(target, f"✅ <b>{BRAND}</b> — Test notification OK\n{datetime.now().strftime('%d/%m/%Y %H:%M')}")
    return JSONResponse({"ok":ok,"chat_id":target})

@app.get("/admin/member_delete")
async def admin_del_member(req: Request, mid:int=0):
    if not admin_auth(req): return RedirectResponse("/admin/login",302)
    db = get_db()
    db.execute("UPDATE members SET actif=0 WHERE id=?",(mid,))
    db.commit(); db.close()
    return RedirectResponse("/admin",302)

@app.post("/api/v1/ingest")
async def api_ingest(req: Request):
    rl(req,"ingest",10,60)
    try:
        body = await req.json()
        if body.get("pwd") != ADMIN_PASS:
            return JSONResponse({"error":"unauthorized"},401)
        tenders = body.get("tenders",[])
        saved = 0; new_tenders = []
        for t in tenders:
            if not t.get("id") or not t.get("objet"): continue
            dl = str(t.get("date_limite","")).strip()
            if dl and is_expired(dl): continue
            if save_tender(t):
                saved += 1; new_tenders.append(t)
        if new_tenders:
            asyncio.create_task(notify_new(new_tenders))
        return JSONResponse({"ok":True,"saved":saved,"total":len(tenders)})
    except Exception as e:
        return JSONResponse({"error":str(e)},500)

@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/",302)
    resp.delete_cookie("adm_s")
    return resp

@app.get("/health")
async def health():
    db = get_db()
    try:
        n = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        db.close()
        return JSONResponse({"status":"ok","active_tenders":n,"brand":BRAND})
    except Exception as e:
        return JSONResponse({"status":"error","error":str(e)},500)

@app.get("/robots.txt")
async def robots():
    return HTMLResponse("User-agent: *\nDisallow: /admin\nDisallow: /api\nSitemap: {SITE_URL}/sitemap.xml")
