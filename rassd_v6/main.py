"""
RASSD — Intelligence Marchés Publics Maroc
═══════════════════════════════════════════
SaaS Beta v1.0 — 2026
Scraper · Classifier · Alertes temps-réel

Architecture: FastAPI + SQLite WAL
Agents: ScraperAgent · NotifyAgent · MonitorAgent
Source: marchespublics.gov.ma (IDs bdc_XXXXX)
"""
from __future__ import annotations
import os, re, time, json, asyncio, hashlib, secrets, logging, hmac
import sqlite3, threading, traceback, random
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup as BS
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

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

# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════
BRAND        = "RASSD"
TAGLINE      = "Intelligence Marchés Publics"
SITE_URL     = os.getenv("SITE_URL",      "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS   = os.getenv("ADMIN_PASS",    "rassd2026")
SECRET_KEY   = os.getenv("SECRET_KEY",    secrets.token_hex(32))
DB_PATH      = os.getenv("DB_PATH",       "data/rassd.db")
TG_BOT       = os.getenv("TELEGRAM_BOT",  "7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_TG     = os.getenv("ADMIN_CHAT_ID", "6424992854")
BREVO_KEY    = os.getenv("BREVO_API_KEY", "")
SCRAPE_HRS   = int(os.getenv("SCRAPE_INTERVAL_HOURS", "2"))
MIN_ID       = int(os.getenv("SCRAPE_MIN_ID", "311500"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rassd")

# ═══════════════════════════════════════════════════════
# SECURITY MIDDLEWARE
# ═══════════════════════════════════════════════════════
class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req: Request, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Frame-Options":           "DENY",
            "X-Content-Type-Options":    "nosniff",
            "Referrer-Policy":           "strict-origin-when-cross-origin",
            "Permissions-Policy":        "geolocation=()",
            "X-XSS-Protection":          "1; mode=block",
        })
        return resp

# ═══════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════
_rl_store: dict[str, list[float]] = {}
_rl_lock  = threading.Lock()

def _rate_limit(ip: str, key: str, max_calls: int, window: int) -> bool:
    k   = f"{ip}:{key}"
    now = time.time()
    with _rl_lock:
        calls = [t for t in _rl_store.get(k, []) if now - t < window]
        if len(calls) >= max_calls:
            return False
        calls.append(now)
        _rl_store[k] = calls
    return True

def get_client_ip(req: Request) -> str:
    fwd = req.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (
        req.client.host if req.client else "127.0.0.1"
    )

def enforce_rate_limit(req: Request, key: str, max_calls: int = 10, window: int = 60):
    if not _rate_limit(get_client_ip(req), key, max_calls, window):
        raise HTTPException(429, detail="Trop de requêtes. Réessayez plus tard.")

# ═══════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════
_COOKIE  = "rssd_s"
_TTL     = 86400 * 30   # 30 jours

def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()

def session_create(resp: Response, uid: int):
    if HAS_ITS:
        s     = URLSafeTimedSerializer(SECRET_KEY, salt="rassd-session")
        token = s.dumps({"id": uid})
    else:
        token = f"{uid}.{_sign(str(uid))}"
    resp.set_cookie(
        _COOKIE, token,
        max_age  = _TTL,
        httponly = True,
        samesite = "lax",
        secure   = SITE_URL.startswith("https"),
    )

def session_read(req: Request) -> Optional[int]:
    raw = req.cookies.get(_COOKIE)
    if not raw:
        return None
    if HAS_ITS:
        try:
            s = URLSafeTimedSerializer(SECRET_KEY, salt="rassd-session")
            d = s.loads(raw, max_age=_TTL)
            return int(d["id"])
        except Exception:
            return None
    try:
        uid, sig = raw.rsplit(".", 1)
        if hmac.compare_digest(_sign(uid), sig):
            return int(uid)
    except Exception:
        pass
    return None

def session_destroy(resp: Response):
    resp.delete_cookie(_COOKIE)

# ═══════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════
def db_connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA cache_size   = 10000")
    return conn

def db_init():
    conn = db_connect()
    conn.executescript("""
    -- ── Appels d'offres ──────────────────────────────────────
    CREATE TABLE IF NOT EXISTS tenders (
        id               TEXT PRIMARY KEY,
        objet            TEXT NOT NULL DEFAULT '',
        acheteur         TEXT DEFAULT '',
        region           TEXT DEFAULT '',
        domaine          TEXT DEFAULT '',
        type_marche      TEXT DEFAULT '',
        date_publication TEXT DEFAULT '',
        date_limite      TEXT DEFAULT '',
        statut           TEXT DEFAULT 'actif'
                              CHECK(statut IN ('actif','expire','annule')),
        url              TEXT DEFAULT '',
        source           TEXT DEFAULT 'marchespublics',
        date_extraction  TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_domaine  ON tenders(domaine);
    CREATE INDEX IF NOT EXISTS idx_t_region   ON tenders(region);
    CREATE INDEX IF NOT EXISTS idx_t_date     ON tenders(date_extraction DESC);
    CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);

    -- ── Membres ───────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS members (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nom           TEXT    NOT NULL DEFAULT '',
        email         TEXT    UNIQUE NOT NULL,
        phone         TEXT    DEFAULT '',
        telegram      TEXT    DEFAULT '',
        secteurs      TEXT    DEFAULT '',
        pw_hash       TEXT    NOT NULL DEFAULT '',
        actif         INTEGER DEFAULT 1,
        notif_tg      INTEGER DEFAULT 1,
        notif_email   INTEGER DEFAULT 1,
        created_at    TEXT    DEFAULT '',
        last_login    TEXT    DEFAULT '',
        last_notif_at TEXT    DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_m_email ON members(email);

    -- ── Alertes envoyées ──────────────────────────────────────
    CREATE TABLE IF NOT EXISTS alerts_sent (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id),
        tender_id TEXT    NOT NULL,
        channel   TEXT    NOT NULL CHECK(channel IN ('telegram','email')),
        sent_at   TEXT    DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_as_member ON alerts_sent(member_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_as_unique
        ON alerts_sent(member_id, tender_id, channel);

    -- ── Historique scraping ───────────────────────────────────
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        found       INTEGER DEFAULT 0,
        saved       INTEGER DEFAULT 0,
        expired_cnt INTEGER DEFAULT 0,
        errors      INTEGER DEFAULT 0,
        duration_s  REAL    DEFAULT 0,
        started_at  TEXT    DEFAULT '',
        finished_at TEXT    DEFAULT ''
    );

    -- ── Erreurs agent ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS agent_errors (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        context    TEXT DEFAULT '',
        error      TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    );
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized ✓")

# ═══════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════
def pw_hash(password: str) -> str:
    """PBKDF2-HMAC-SHA256 — 260 000 itérations"""
    salt = SECRET_KEY[:16].encode()
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return dk.hex()

def pw_check(password: str, hashed: str) -> bool:
    return hmac.compare_digest(pw_hash(password), hashed)

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def current_member(req: Request) -> Optional[dict]:
    uid = session_read(req)
    if not uid:
        return None
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT * FROM members WHERE id = ? AND actif = 1", (uid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════
# CLASSIFICATION ENGINE
# ═══════════════════════════════════════════════════════
REGIONS: dict[str, list[str]] = {
    "Rabat-Salé-Kénitra":         ["rabat","salé","sale","kénitra","kenitra","témara","temara","khémisset"],
    "Casablanca-Settat":          ["casablanca","settat","mohammedia","berrechid","benslimane","bouskoura"],
    "Marrakech-Safi":             ["marrakech","safi","essaouira","kelaa","youssoufia","chichaoua"],
    "Fès-Meknès":                 ["fès","fes","meknès","meknes","ifrane","taza","sefrou","boulemane"],
    "Tanger-Tétouan-Al Hoceima":  ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache","fnideq"],
    "Oriental":                   ["oujda","nador","berkane","taourirt","jerada","driouch"],
    "Béni Mellal-Khénifra":      ["béni mellal","beni mellal","khénifra","khenifra","azilal","khouribga","fquih"],
    "Souss-Massa":                ["agadir","tiznit","taroudant","inezgane","aït melloul","biougra"],
    "Drâa-Tafilalet":             ["errachidia","ouarzazate","zagora","midelt","tinghir","boumalne"],
    "Laâyoune-Sakia El Hamra":   ["laayoune","boujdour","tarfaya"],
    "Dakhla-Oued Ed-Dahab":      ["dakhla","aousserd"],
    "Guelmim-Oued Noun":          ["guelmim","tan-tan","sidi ifni","assa","zag"],
}

SECTEURS: dict[str, list[str]] = {
    "T101 · Constructions & Bâtiments":  ["bâtiment","construction","maçonnerie","béton","gros œuvre","gros oeuvre","réhabilitation","façade","toiture","ravalement","mur de clôture"],
    "T102 · Terrassements & VRD":        ["terrassement","remblai","déblai","excavation","nivellement","compactage","vrd"],
    "T103 · Menuiserie & Métallerie":    ["menuiserie","métallerie","charpente","ferronnerie","portail","porte","fenêtre","serrurerie","aluminium"],
    "T104 · Plomberie & CVC":            ["plomberie","chauffage","climatisation","sanitaire","tuyauterie","cvc","hvac","ventilation","pompe de chaleur"],
    "T105 · Peinture & Revêtements":     ["peinture","vitrerie","enduit","revêtement mural","carrelage","parquet","faïence","dallage","sol"],
    "T106 · Étanchéité & Isolation":     ["étanchéité","isolation","membrane","imperméabilisation","toiture terrasse"],
    "T110 · Génie Civil & Infrastructure":["génie civil","pont","viaduc","infrastructure","ouvrage d'art","géotechnique","sondage"],
    "T111 · Espaces Verts & Paysage":    ["espace vert","jardinage","plantation","gazon","élagage","parc","jardin"],
    "T201 · Assainissement & Eau Usée":  ["assainissement","égout","step","station d'épuration","collecteur","canalisation","réseau d'assainissement"],
    "T203 · Hydraulique & Eau Potable":  ["hydraulique","eau potable","adduction","barrage","forage","irrigation","réseau d'eau"],
    "T301 · Travaux Routiers":           ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation routière","marquage","enrobé"],
    "T401 · Électricité & Éclairage":    ["électricité","éclairage","câblage","tableau électrique","transformateur","éclairage public","basse tension","haute tension"],
    "T402 · Sécurité & Vidéosurveillance":["vidéosurveillance","cctv","alarme incendie","contrôle d'accès","intrusion","détection","sécurité électronique"],
    "T403 · Télécommunications & Réseaux":["télécommunication","fibre optique","réseau","switch","wifi","lan","wan","infrastructure réseau"],
    "P813 · Équipements Médicaux":       ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament","scanner","irm","bloc opératoire"],
    "P814 · Équipements Froid & Clima":  ["climatiseur","split","froid industriel","chambre froide","groupe froid","réfrigération"],
    "P816 · Véhicules & Matériel Roulant":["véhicule","voiture","camion","bus","minibus","ambulance","carburant","gasoil","flotte"],
    "P818 · Informatique & Matériel":    ["informatique","ordinateur","pc","serveur","imprimante","scanner","copier","logiciel","cloud","erp","datacenter"],
    "P825 · Mobilier & Fournitures Bureau":["fournitures bureau","papier","ramette","mobilier","bureau","chaise","armoire","tableau blanc","cartouche"],
    "P833 · Produits Pharmaceutiques":   ["médicament","pharmacie","produits chimiques","réactif laboratoire","consommable médical"],
    "P834 · Alimentation & Restauration":["alimentation","denrée","viande","restauration","traiteur","repas","cafétéria","cantine"],
    "P839 · Matériaux de Construction":  ["ciment","sable","gravier","béton prêt","brique","acier","fer à béton","matériaux"],
    "P841 · Hygiène & Entretien":        ["nettoyage produits","produits d'entretien","désinfection","savon","détergent","consommable hygiène"],
    "P850 · Énergies Renouvelables":     ["solaire","photovoltaïque","énergie renouvelable","panneau solaire","éolien","biomasse"],
    "S901 · IT & Développement":         ["développement logiciel","application mobile","site web","cybersécurité","infogérance","maintenance informatique","cloud computing"],
    "S902 · Études & Ingénierie":        ["étude","ingénierie","conseil","consultant","expertise","audit","bureau d'études","maîtrise d'œuvre"],
    "S906 · Maintenance & Entretien":    ["maintenance","entretien","réparation","dépannage","préventive","corrective","contrat de maintenance"],
    "S907 · Nettoyage & Propreté":       ["nettoyage","propreté","nettoyage industriel","nettoyage bâtiment","dératisation","désinsectisation"],
    "S908 · Gardiennage & Sécurité":     ["gardiennage","agent de sécurité","surveillance","sécurité humaine","rondier","rondes"],
    "S910 · Communication & Événements": ["communication","publicité","événementiel","impression","sérigraphie","signalétique","organisation"],
    "S913 · Formation & Coaching":       ["formation","coaching","séminaire","certification","e-learning","programme de formation"],
    "S915 · Transport & Logistique":     ["transport","location véhicule","navette","chauffeur","déménagement","logistique","affrètement"],
    "S916 · Restauration & Hôtellerie":  ["hôtel","hébergement","restauration service","traiteur événement","réception","accueil"],
}

SECTEURS_LIST = list(SECTEURS.keys())
REGIONS_LIST  = list(REGIONS.keys())

AO_KEYWORDS = [
    "fourniture","travaux","prestation","acquisition","maintenance",
    "réhabilitation","construction","étude","mission","location",
    "nettoyage","gardiennage","transport","formation","audit",
    "aménagement","installation","extension","livraison","réparation",
    "entretien","rénovation","pose","démolition","achat","service",
]

PORTAL_JUNK = {
    "accueil", "liste des avis", "connexion", "portail marocain",
    "marchés publics maroc", "espace entreprise", "se connecter",
    "liste des", "avis d'achat", "tableau de bord", "recherche",
    "inscription", "bienvenue", "login", "home", "dashboard",
    "portail", "marchés publics",
}

def is_portal_junk(text: str) -> bool:
    tl = text.lower().strip()
    return any(tl == j or tl.startswith(j) for j in PORTAL_JUNK)

def classify_region(text: str) -> str:
    t = text.lower()
    for region, keywords in REGIONS.items():
        if any(k in t for k in keywords):
            return region
    return "Maroc"

def classify_secteur(text: str) -> str:
    t      = text.lower()
    scores: dict[str, int] = defaultdict(int)
    for sect, keywords in SECTEURS.items():
        for kw in keywords:
            if kw in t:
                scores[sect] += 3 if len(kw) > 12 else (2 if len(kw) > 7 else 1)
    return max(scores, key=scores.get) if scores else "P825 · Mobilier & Fournitures Bureau"

def classify_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation","aménagement","terrassement","voirie"]):
        return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement","produits","articles"]):
        return "Fournitures"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie","maîtrise"]):
        return "Études & Ingénierie"
    if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage","transport","formation"]):
        return "Services"
    return "Fournitures"

def clean_objet(text: str) -> str:
    t = re.sub(r"^#\s*0*\d+\s*", "", text.strip())
    t = re.sub(r"^LOT\s*[N°n°#]?\s*\d+\s*[:\-–]?\s*", "", t, flags=re.I)
    t = re.sub(r"^\d+\s*[:\-–]\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return (t[0].upper() + t[1:]) if t and t[0].islower() else t

def extract_date(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    m = re.search(r"(\d{1,2}/\d{2}/\d{4})(?:\s+\d{1,2}:\d{2})?", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return ""

def date_is_expired(raw: str) -> bool:
    if not raw or raw in ("N/A", "—", "-", "", "null", "non définie"):
        return False
    today = datetime.now().date()
    for pat, fmt in [
        (r"(\d{1,2}/\d{2}/\d{4})", "%d/%m/%Y"),
        (r"(\d{4}-\d{2}-\d{2})",   "%Y-%m-%d"),
        (r"(\d{1,2}-\d{2}-\d{4})", "%d-%m-%Y"),
    ]:
        m = re.search(pat, str(raw))
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date() < today
            except ValueError:
                pass
    return False

# ═══════════════════════════════════════════════════════
# HTML PARSER — card layout marchespublics.gov.ma
# ═══════════════════════════════════════════════════════
_LABEL_CLASS_RE = re.compile(
    r"label|titre|key|head|caption|field|info\-label|card\-label", re.I
)

def _card_value(soup, keywords: list[str]) -> str:
    """
    Extrait la valeur d'un champ depuis le layout card de marchespublics.gov.ma.
    Stratégie 3 niveaux : class label → élément court → regex texte complet.
    """
    kw_lower = [k.lower() for k in keywords]
    full_text = soup.get_text(" ", strip=True)

    # ── Niveau 1: élément de class *label* → sibling direct ──
    for el in soup.find_all(True, class_=_LABEL_CLASS_RE):
        txt = el.get_text(strip=True)
        if not any(k in txt.lower() for k in kw_lower):
            continue
        nxt = el.find_next_sibling()
        if nxt:
            v = nxt.get_text(strip=True)
            if 2 < len(v) < 300:
                return v
        # parent → parent sibling
        if el.parent:
            ps = el.parent.find_next_sibling()
            if ps:
                v = ps.get_text(strip=True)
                if 2 < len(v) < 300:
                    return v

    # ── Niveau 2: tout élément court (< 120 chars) contenant keyword ──
    for el in soup.find_all(True):
        txt = el.get_text(strip=True)
        if len(txt) > 120 or len(txt) < 4:
            continue
        if not any(k in txt.lower() for k in kw_lower):
            continue
        nxt = el.find_next_sibling()
        if nxt:
            v = nxt.get_text(strip=True)
            if 2 < len(v) < 300:
                return v

    # ── Niveau 3: regex dans texte complet ──
    for kw in kw_lower:
        idx = full_text.lower().find(kw)
        if idx >= 0:
            after = full_text[idx + len(kw): idx + len(kw) + 250].strip()
            lines = [ln.strip() for ln in after.split("\n") if ln.strip()]
            if lines:
                return lines[0][:250]

    return ""

def parse_consultation(html: str, tid: str) -> Optional[dict]:
    """
    Parse une page marchespublics.gov.ma/bdc/entreprise/consultation/show/XXXXX
    Retourne None si: annulée, expirée, ou sans objet valide.
    """
    if not HAS_BS4:
        return None
    try:
        soup      = BS(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # ── 1. Détection précoce: annulation ──
        annul_kw = ["marché annulé", "consultation annulée", "annulé par",
                    "a été annulée", "appel d'offres annulé"]
        if any(k in full_text.lower() for k in annul_kw):
            return None

        # ── 2. Objet ─────────────────────────────────────────────
        objet = ""

        # a) Balise <title> — souvent "Libellé consultation | Marchés Publics"
        title_tag = soup.find("title")
        if title_tag:
            t = title_tag.get_text(strip=True)
            # Nettoyer suffixe portail
            t = re.sub(r"\s*[|–\-]\s*.*marchés publics.*", "", t, flags=re.I).strip()
            t = re.sub(r"\s*[|–\-]\s*.*portail.*",         "", t, flags=re.I).strip()
            if 10 < len(t) < 400 and not is_portal_junk(t):
                objet = t

        # b) Sélecteurs CSS spécifiques
        if not objet:
            for sel in [".consultation-title", ".objet-marche", ".title-consultation",
                        ".card-title", ".page-title", "h2", "h3"]:
                for el in soup.select(sel):
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600 and not is_portal_junk(t):
                        objet = t
                        break
                if objet:
                    break

        # c) card_value: objet / intitulé
        if not objet:
            objet = _card_value(soup, [
                "objet du marché", "objet de la consultation",
                "intitulé du marché", "intitulé", "objet",
            ])

        # d) Fallback: Nature de prestation
        if not objet or len(objet) < 8:
            nature = _card_value(soup, ["nature de prestation", "nature"])
            cat    = _card_value(soup, ["catégorie principale", "catégorie"])
            if nature and len(nature) > 8:
                objet = nature
            elif cat and len(cat) > 4:
                objet = f"Prestation — {cat}"

        # e) Dernier recours: premier paragraphe avec mot-clé AO
        if not objet or len(objet) < 8:
            _junk_terms = ["voir plus", "télécharger", "fichier", "poids",
                           "ko", "mo", "mb", "articles", "pièces jointes",
                           "tout afficher", "tout réduire", "imprimer"]
            for el in soup.find_all(["p", "div", "span", "li"]):
                t  = el.get_text(strip=True)
                tl = t.lower()
                if 15 < len(t) < 400 and not is_portal_junk(t):
                    if any(k in tl for k in _junk_terms):
                        continue
                    parents = {p.name for p in el.parents}
                    if parents & {"nav", "footer", "header", "aside"}:
                        continue
                    if any(k in tl for k in AO_KEYWORDS):
                        objet = t
                        break

        if not objet or len(objet) < 8:
            return None

        objet = clean_objet(objet)

        # ── 3. Date limite ────────────────────────────────────────
        dl_raw = _card_value(soup, [
            "date limite de réception des devis",
            "date limite de réception des offres",
            "date limite",
            "date de remise des offres",
            "remise des offres",
            "remise des plis",
            "date de clôture",
            "réception des devis",
            "délai de remise",
        ])
        if not dl_raw:
            # Regex embedded: "Date limite...25/04/2026 12:00"
            m2 = re.search(
                r"(?:date limite|réception des (?:offres|devis)|"
                r"remise des (?:offres|plis)|clôture)"
                r".{0,80}?(\d{1,2}/\d{2}/\d{4})",
                full_text, re.I | re.S,
            )
            if m2:
                dl_raw = m2.group(1)

        date_lim = extract_date(dl_raw)

        # Rejeter si expiré
        if date_lim and date_is_expired(date_lim):
            return None

        # ── 4. Autres champs ──────────────────────────────────────
        acheteur = _card_value(soup, [
            "acheteur public", "maître d'ouvrage", "organisme acheteur",
            "pouvoir adjudicateur", "organisme",
        ])
        cat_officielle = _card_value(soup, ["catégorie principale", "catégorie"])
        nature_presta  = _card_value(soup, ["nature de prestation", "nature"])
        lieu           = _card_value(soup, ["lieu d'exécution", "lieu d execution", "lieu de livraison"])
        dp_raw         = _card_value(soup, ["date mise en ligne", "date de publication", "date de parution"])
        date_pub       = extract_date(dp_raw)

        # ── 5. Classification ──────────────────────────────────────
        corpus  = f"{cat_officielle} {nature_presta} {objet} {acheteur}"
        domaine = classify_secteur(corpus)

        cat_l = cat_officielle.lower()
        if   "travaux"      in cat_l: type_m = "Travaux"
        elif "fournitures"  in cat_l: type_m = "Fournitures"
        elif "services"     in cat_l: type_m = "Services"
        elif "études"       in cat_l: type_m = "Études & Ingénierie"
        else:                         type_m = classify_type(f"{objet} {nature_presta}")

        region = classify_region(f"{lieu} {acheteur} {full_text[:400]}")

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
            "url":              f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
            "source":           "marchespublics",
        }

    except Exception as exc:
        log.error(f"[parse #{tid}] {exc}")
        return None

# ═══════════════════════════════════════════════════════
# SCRAPER AGENT
# ═══════════════════════════════════════════════════════
class ScrapeLog:
    _entries: list[str] = []
    _lock = threading.Lock()

    @classmethod
    def add(cls, msg: str):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        with cls._lock:
            cls._entries.append(entry)
            if len(cls._entries) > 600:
                cls._entries = cls._entries[-500:]
        log.info(msg)

    @classmethod
    def tail(cls, n: int = 100) -> list[str]:
        with cls._lock:
            return list(cls._entries[-n:])


class ScrapeState:
    running:    bool = False
    found:      int  = 0
    saved:      int  = 0
    errors:     int  = 0
    current:    int  = 0
    total:      int  = 0
    started_at: str  = ""


def tender_save(t: dict) -> bool:
    if not t or not t.get("id") or not t.get("objet"):
        return False
    try:
        conn = db_connect()
        conn.execute(
            """INSERT OR IGNORE INTO tenders
               (id, objet, acheteur, region, domaine, type_marche,
                date_publication, date_limite, statut, url, source, date_extraction)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(t["id"])[:80],
                str(t["objet"])[:400],
                str(t.get("acheteur", ""))[:200],
                str(t.get("region", ""))[:100],
                str(t.get("domaine", ""))[:80],
                str(t.get("type_marche", ""))[:40],
                str(t.get("date_publication", ""))[:20],
                str(t.get("date_limite", ""))[:20],
                "actif",
                str(t.get("url", ""))[:400],
                str(t.get("source", "marchespublics"))[:40],
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        conn.commit()
        changed = conn.execute("SELECT changes()").fetchone()[0]
        conn.close()
        return changed > 0
    except Exception as exc:
        log.error(f"[save] {exc}")
        try:
            conn.close()
        except Exception:
            pass
        return False


def run_scraper() -> list[dict]:
    """
    Scan séquentiel des IDs bdc_XXXXX sur marchespublics.gov.ma.
    Retourne la liste des nouveaux marchés actifs sauvegardés.
    """
    import requests as _req

    t0 = time.time()
    ScrapeState.running    = True
    ScrapeState.found      = 0
    ScrapeState.saved      = 0
    ScrapeState.errors     = 0
    ScrapeState.current    = 0
    ScrapeState.total      = 0
    ScrapeState.started_at = datetime.now().strftime("%H:%M:%S")

    ScrapeLog.add("═" * 54)
    ScrapeLog.add(f"RASSD ScraperAgent — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    ScrapeLog.add("═" * 54)

    # ── Charger les IDs connus ──
    conn = db_connect()
    known: set[str] = {
        r[0] for r in conn.execute("SELECT id FROM tenders").fetchall()
    }
    conn.close()

    # ── Calculer plage de scan ──
    max_known = MIN_ID
    for k in known:
        if k.startswith("bdc_"):
            try:
                n = int(k[4:])
                if n > max_known:
                    max_known = n
            except ValueError:
                pass

    start_id  = max(MIN_ID, max_known - 20)
    end_id    = max_known + 500
    scan_ids  = [
        str(i) for i in range(start_id, end_id + 1)
        if f"bdc_{i}" not in known
    ]

    ScrapeState.total = len(scan_ids)
    ScrapeLog.add(f"Plage: #{start_id} → #{end_id}  ({len(scan_ids)} IDs à vérifier)")

    # ── Session HTTP ──
    session = _req.Session()
    session.verify = False
    session.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.5",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    })

    new_tenders: list[dict] = []
    consec_empty = 0

    for idx, tid in enumerate(scan_ids):
        ScrapeState.current = idx + 1
        try:
            resp = session.get(
                f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
                timeout=12,
            )
            if resp.status_code != 200 or len(resp.text) < 2000:
                consec_empty += 1
                # Arrêt si trop d'erreurs consécutives sans rien sauvegarder
                if consec_empty > 50 and ScrapeState.saved == 0:
                    ScrapeLog.add(f"⚠ {consec_empty} pages invalides — arrêt anticipé")
                    break
                continue

            consec_empty = 0
            ScrapeState.found += 1

            tender = parse_consultation(resp.text, tid)
            if not tender:
                known.add(f"bdc_{tid}")
                continue

            if tender_save(tender):
                ScrapeState.saved += 1
                known.add(tender["id"])
                dl_str = tender.get("date_limite") or "?"
                ScrapeLog.add(
                    f"✓ #{tid}  {tender['domaine'][:22]:22}  "
                    f"{tender['objet'][:46]:46}  ⏰ {dl_str}"
                )
                new_tenders.append(tender)
            else:
                known.add(f"bdc_{tid}")

            time.sleep(random.uniform(0.5, 1.0))

        except Exception as exc:
            ScrapeState.errors += 1
            consec_empty       += 1
            ScrapeLog.add(f"✗ #{tid}: {str(exc)[:60]}")

    # ── Auto-expire des marchés passés ──
    expired_cnt = 0
    try:
        conn  = db_connect()
        today = datetime.now().date()

        # Format ISO YYYY-MM-DD — via SQLite
        conn.execute(
            "UPDATE tenders SET statut='expire' "
            "WHERE statut='actif' AND date_limite != '' "
            "AND date_limite NOT LIKE '%/%' "
            "AND date_limite < date('now') "
            "AND date_limite NOT IN ('N/A','—','-','null')"
        )

        # Format DD/MM/YYYY — via Python (gère les dates embarquées "25/02/2026 12:00")
        rows = conn.execute(
            "SELECT id, date_limite FROM tenders "
            "WHERE statut='actif' AND date_limite LIKE '%/%'"
        ).fetchall()
        exp_ids: list[str] = []
        for row in rows:
            dl = (row["date_limite"] or "").strip()
            m2 = re.search(r"(\d{1,2}/\d{2}/\d{4})", dl)
            if m2:
                try:
                    if datetime.strptime(m2.group(1), "%d/%m/%Y").date() < today:
                        exp_ids.append(row["id"])
                except ValueError:
                    pass
        if exp_ids:
            ph = ",".join(["?"] * len(exp_ids))
            conn.execute(
                f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})",
                exp_ids,
            )
            expired_cnt = len(exp_ids)

        conn.commit()

        # Enregistrer le run
        duration = time.time() - t0
        conn.execute(
            "INSERT INTO scrape_runs "
            "(found, saved, expired_cnt, errors, duration_s, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                ScrapeState.found, ScrapeState.saved, expired_cnt,
                ScrapeState.errors, round(duration, 1),
                ScrapeState.started_at,
                datetime.now().strftime("%H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()

    except Exception as exc:
        log.warning(f"[expire/log] {exc}")

    duration = time.time() - t0
    ScrapeLog.add("═" * 54)
    ScrapeLog.add(
        f"Terminé en {duration:.0f}s — "
        f"{ScrapeState.saved} nouveaux · {expired_cnt} expirés · {ScrapeState.errors} erreurs"
    )
    ScrapeLog.add("═" * 54)
    ScrapeState.running = False

    return new_tenders

# ═══════════════════════════════════════════════════════
# NOTIFICATION AGENT
# ═══════════════════════════════════════════════════════
async def tg_send(chat_id: str, text: str) -> bool:
    """Envoie un message Telegram."""
    if not TG_BOT or not chat_id:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return r.status_code == 200
    except Exception as exc:
        log.warning(f"[Telegram] {exc}")
        return False


async def email_send(to: str, subject: str, html: str) -> bool:
    """Envoie un email via Brevo API."""
    if not BREVO_KEY:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key":      BREVO_KEY,
                    "content-type": "application/json",
                },
                json={
                    "sender":      {"name": BRAND, "email": "noreply@rassd.ma"},
                    "to":          [{"email": to}],
                    "subject":     subject,
                    "htmlContent": html,
                },
            )
            return r.status_code in (200, 201, 202)
    except Exception as exc:
        log.warning(f"[Email] {exc}")
        return False


def match_tenders_for_member(member: dict, tenders: list[dict]) -> list[dict]:
    """
    Filtre les marchés selon les secteurs du membre.
    Si aucun secteur défini → reçoit tout.
    """
    raw      = (member.get("secteurs") or "").strip()
    secteurs = [s.strip() for s in raw.split(",") if s.strip()]

    if not secteurs:
        return tenders

    matched: list[dict] = []
    for t in tenders:
        dom = (t.get("domaine") or "").lower()
        obj = (t.get("objet")   or "").lower()
        for s in secteurs:
            s_code = s[:4].upper()
            d_code = dom[:4].upper()
            if s_code == d_code:
                matched.append(t)
                break
            if s in SECTEURS and any(kw in dom + " " + obj for kw in SECTEURS[s]):
                matched.append(t)
                break
    return matched


def _tg_body(tenders: list[dict], nom: str) -> str:
    n     = len(tenders)
    lines = [
        f"🏛 <b>{BRAND}</b> — {n} nouveau{'x' if n > 1 else ''} marché{'s' if n > 1 else ''}\n",
        f"Bonjour <b>{nom}</b>, voici vos nouvelles opportunités :\n",
    ]
    for t in tenders[:6]:
        dl  = t.get("date_limite") or "Non précisée"
        dom = t.get("domaine", "")[:28]
        lines.append(
            f"▸ <b>{t['objet'][:80]}</b>\n"
            f"  🏢 {t.get('acheteur','')[:55]}\n"
            f"  🏷 {dom} · {t.get('type_marche','')}\n"
            f"  📍 {t.get('region','Maroc')} · ⏰ {dl}\n"
            f"  🔗 <a href='{t.get('url','')}'>Voir la consultation</a>\n"
        )
    if n > 6:
        lines.append(f"<i>… et {n - 6} autre(s) sur {SITE_URL}/tenders</i>")
    return "\n".join(lines)


def _email_body(tenders: list[dict], nom: str) -> str:
    cards = ""
    for t in tenders[:10]:
        dl  = t.get("date_limite") or "Non précisée"
        dom = t.get("domaine", "")[:45]
        cards += f"""
        <div style="margin-bottom:20px;padding:20px;background:#111;border:1px solid #2a2a2a;
                    border-left:3px solid #E8A020;border-radius:8px">
          <div style="font-size:11px;color:#E8A020;font-weight:700;letter-spacing:.5px;
                      text-transform:uppercase;margin-bottom:10px">{dom}</div>
          <h3 style="margin:0 0 10px;font-size:16px;color:#f3eee7;line-height:1.4">{t['objet'][:110]}</h3>
          <table style="width:100%;font-size:13px;color:#888;border-collapse:collapse">
            <tr><td style="padding:3px 0">🏢 <strong style="color:#aaa">{t.get('acheteur','')[:70]}</strong></td></tr>
            <tr><td style="padding:3px 0">📍 {t.get('region','Maroc')} · {t.get('type_marche','')}</td></tr>
            <tr><td style="padding:3px 0">⏰ <strong style="color:#4CAF7D">Limite: {dl}</strong></td></tr>
          </table>
          <a href="{t.get('url','')}" style="display:inline-block;margin-top:14px;padding:9px 18px;
             background:#E8A020;color:#000;border-radius:6px;font-weight:700;font-size:13px;
             text-decoration:none">Voir la consultation →</a>
        </div>"""
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BRAND}</title></head>
<body style="background:#030303;font-family:'Helvetica Neue',Arial,sans-serif;color:#f3eee7;
             padding:0;margin:0">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px">
    <div style="margin-bottom:32px;padding-bottom:20px;border-bottom:1px solid #1a1a1a">
      <span style="font-size:22px;font-weight:900;color:#E8A020;letter-spacing:1px">{BRAND}</span>
      <span style="font-size:14px;color:#555;margin-left:10px">Intelligence Marchés Publics</span>
    </div>
    <h2 style="font-size:20px;font-weight:700;margin:0 0 8px">{len(tenders)} nouveau(x) marché(s) pour vous</h2>
    <p style="color:#666;font-size:14px;margin:0 0 28px">Bonjour {nom}, voici les opportunités correspondant à vos secteurs :</p>
    {cards}
    <div style="margin-top:32px;padding-top:20px;border-top:1px solid #1a1a1a;
                font-size:12px;color:#444;text-align:center">
      <a href="{SITE_URL}/tenders" style="color:#E8A020">Voir tous les marchés</a>
      · <a href="{SITE_URL}/settings" style="color:#666">Gérer mes alertes</a>
    </div>
  </div>
</body></html>"""


async def notify_members(new_tenders: list[dict]):
    """Alerte tous les membres actifs pour les nouveaux marchés."""
    if not new_tenders:
        return

    conn = db_connect()
    try:
        members = [
            dict(r) for r in conn.execute(
                "SELECT id,nom,email,telegram,secteurs,notif_tg,notif_email "
                "FROM members WHERE actif=1"
            ).fetchall()
        ]
    finally:
        conn.close()

    total_tg = total_em = 0

    for m in members:
        matched = match_tenders_for_member(m, new_tenders)
        if not matched:
            continue

        nom = m.get("nom") or "Utilisateur"
        n   = len(matched)
        ScrapeLog.add(f"[Notify] {nom}: {n} marché(s) correspondant(s)")

        # ── Telegram ──
        if m.get("notif_tg") and m.get("telegram"):
            ok = await tg_send(m["telegram"], _tg_body(matched, nom))
            if ok:
                total_tg += 1
                _record_alerts(m["id"], matched, "telegram")

        # ── Email ──
        if m.get("notif_email") and m.get("email"):
            subj = f"🏛 {n} marché{'s' if n > 1 else ''} — {BRAND}"
            ok   = await email_send(m["email"], subj, _email_body(matched, nom))
            if ok:
                total_em += 1
                _record_alerts(m["id"], matched, "email")

    if total_tg or total_em:
        ScrapeLog.add(
            f"[Notify] ✓ {total_tg} Telegram · {total_em} Email envoyés"
        )
        await tg_send(
            ADMIN_TG,
            f"📊 <b>{BRAND}</b> — Scrape terminé\n"
            f"✓ {ScrapeState.saved} nouveaux marchés\n"
            f"📬 {total_tg} TG · {total_em} Email envoyés",
        )


def _record_alerts(member_id: int, tenders: list[dict], channel: str):
    try:
        conn = db_connect()
        for t in tenders:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO alerts_sent (member_id,tender_id,channel,sent_at) "
                    "VALUES (?,?,?,?)",
                    (member_id, t["id"], channel, now_str()),
                )
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning(f"[record_alerts] {exc}")

# ═══════════════════════════════════════════════════════
# MONITOR AGENT — expire + cleanup toutes les heures
# ═══════════════════════════════════════════════════════
async def monitor_agent():
    while True:
        await asyncio.sleep(3600)
        try:
            conn  = db_connect()
            today = datetime.now().date()

            # ISO dates
            conn.execute(
                "UPDATE tenders SET statut='expire' "
                "WHERE statut='actif' AND date_limite != '' "
                "AND date_limite NOT LIKE '%/%' "
                "AND date_limite < date('now')"
            )

            # DD/MM/YYYY dates
            rows = conn.execute(
                "SELECT id, date_limite FROM tenders "
                "WHERE statut='actif' AND date_limite LIKE '%/%'"
            ).fetchall()
            exp: list[str] = []
            for row in rows:
                dl = (row["date_limite"] or "").strip()
                m2 = re.search(r"(\d{1,2}/\d{2}/\d{4})", dl)
                if m2:
                    try:
                        if datetime.strptime(m2.group(1), "%d/%m/%Y").date() < today:
                            exp.append(row["id"])
                    except ValueError:
                        pass
            if exp:
                ph = ",".join(["?"] * len(exp))
                conn.execute(
                    f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp
                )

            # Purge logs > 60j
            conn.execute(
                "DELETE FROM alerts_sent WHERE sent_at < date('now','-60 days')"
            )
            conn.execute(
                "DELETE FROM agent_errors WHERE created_at < date('now','-7 days')"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log.warning(f"[monitor] {exc}")

# ═══════════════════════════════════════════════════════
# SCRAPE SCHEDULER
# ═══════════════════════════════════════════════════════
_last_scrape: float = 0.0

async def scrape_scheduler():
    """Lance le scraper automatiquement toutes les SCRAPE_HRS heures."""
    await asyncio.sleep(90)   # Laisser l'app démarrer
    global _last_scrape
    while True:
        try:
            if time.time() - _last_scrape >= SCRAPE_HRS * 3600:
                _last_scrape = time.time()
                loop = asyncio.get_event_loop()
                new  = await loop.run_in_executor(None, run_scraper)
                if new:
                    await notify_members(new)
        except Exception as exc:
            ScrapeState.running = False
            log.error(f"[scheduler] {exc}\n{traceback.format_exc()}")
        await asyncio.sleep(300)

# ═══════════════════════════════════════════════════════
# APP LIFECYCLE
# ═══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in ["static", "data", "templates"]:
        os.makedirs(d, exist_ok=True)
    db_init()
    asyncio.create_task(scrape_scheduler())
    asyncio.create_task(monitor_agent())
    log.info(f"✅ {BRAND} — {TAGLINE} — démarré")
    yield

app = FastAPI(
    lifespan  = lifespan,
    title     = BRAND,
    version   = "1.0.0-beta",
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
    tpl = None  # type: ignore

# ── Template helpers ──
def render(req: Request, template: str, ctx: dict | None = None) -> HTMLResponse:
    if tpl is None:
        return HTMLResponse("<h1>Template error</h1>", 500)
    data = {
        "request":      req,
        "BRAND":        BRAND,
        "TAGLINE":      TAGLINE,
        "SITE_URL":     SITE_URL,
        "SECTEURS_LIST": SECTEURS_LIST,
        "SECTEURS":     SECTEURS,
        "REGIONS_LIST": REGIONS_LIST,
        "member":       current_member(req),
        "now":          datetime.now(),
        "flash_msg":    req.query_params.get("_flash", ""),
        "flash_kind":   req.query_params.get("_fk",    "ok"),
    }
    if ctx:
        data.update(ctx)
    try:
        return tpl.TemplateResponse(template, data)
    except Exception as exc:
        log.error(f"[render:{template}] {exc}\n{traceback.format_exc()}")
        raise

def flash_redirect(url: str, msg: str, kind: str = "ok") -> RedirectResponse:
    return RedirectResponse(f"{url}?_flash={msg}&_fk={kind}", 302)

# ═══════════════════════════════════════════════════════
# ROUTES — PUBLIC
# ═══════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    conn = db_connect()
    try:
        stats = {
            "actif":   conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "total":   conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members": conn.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "scrapes": conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0],
        }
        recent = [
            dict(r) for r in conn.execute(
                "SELECT * FROM tenders WHERE statut='actif' "
                "ORDER BY date_extraction DESC LIMIT 8"
            ).fetchall()
        ]
    finally:
        conn.close()
    return render(req, "landing.html", {"stats": stats, "recent": recent})


@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(
    req:      Request,
    code_f:   str = "",
    region_f: str = "",
    type_f:   str = "",
    q:        str = "",
    sort:     str = "date",
    page:     int = 1,
):
    m = current_member(req)
    if not m:
        return RedirectResponse("/login?next=/tenders", 302)

    _SORT = {
        "date":     "date_extraction DESC",
        "deadline": "date_limite ASC",
        "az":       "objet ASC",
    }
    order = _SORT.get(sort, "date_extraction DESC")

    per = 20
    off = (page - 1) * per

    conn = db_connect()
    try:
        conds:  list[str] = ["statut='actif'"]
        params: list      = []

        if code_f:
            conds.append("domaine LIKE ?")
            params.append(f"{code_f}%")
        if region_f:
            conds.append("region = ?")
            params.append(region_f)
        if type_f:
            conds.append("type_marche = ?")
            params.append(type_f)
        if q:
            conds.append("(objet LIKE ? OR acheteur LIKE ? OR domaine LIKE ?)")
            qp = f"%{q[:80]}%"
            params += [qp, qp, qp]

        where = " AND ".join(conds)
        total = conn.execute(
            f"SELECT COUNT(*) FROM tenders WHERE {where}", params
        ).fetchone()[0]

        rows = [
            dict(r) for r in conn.execute(
                f"SELECT * FROM tenders WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                params + [per, off],
            ).fetchall()
        ]
        regions_used = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT region FROM tenders "
                "WHERE statut='actif' AND region != '' ORDER BY region"
            ).fetchall()
        ]
        types_used = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT type_marche FROM tenders "
                "WHERE statut='actif' AND type_marche != '' ORDER BY type_marche"
            ).fetchall()
        ]
    finally:
        conn.close()

    pages = max(1, (total + per - 1) // per)
    return render(req, "tenders.html", {
        "tenders":      rows,
        "total":        total,
        "page":         page,
        "pages":        pages,
        "code_f":       code_f,
        "region_f":     region_f,
        "type_f":       type_f,
        "q":            q,
        "sort":         sort,
        "regions_used": regions_used,
        "types_used":   types_used,
    })


@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    m = current_member(req)
    if not m:
        return RedirectResponse(f"/login?next=/tenders/{tid}", 302)
    conn = db_connect()
    try:
        t = conn.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    finally:
        conn.close()
    if not t:
        raise HTTPException(404, "Marché introuvable")
    return render(req, "tender_detail.html", {"tender": dict(t)})

# ═══════════════════════════════════════════════════════
# ROUTES — AUTH
# ═══════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    if current_member(req):
        return RedirectResponse("/tenders", 302)
    return render(req, "register.html", {})


@app.post("/register")
async def register_post(
    req:       Request,
    nom:       str = Form(""),
    email:     str = Form(""),
    phone:     str = Form(""),
    telegram:  str = Form(""),
    secteurs:  str = Form(""),
    password:  str = Form(""),
    password2: str = Form(""),
):
    enforce_rate_limit(req, "register", 5, 3600)

    def err(msg):
        return render(req, "register.html", {"error": msg, "form": {
            "nom": nom, "email": email, "phone": phone,
            "telegram": telegram, "secteurs": secteurs,
        }})

    if not nom.strip() or not email.strip() or not password:
        return err("Nom, email et mot de passe sont requis.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
        return err("Adresse email invalide.")
    if password != password2:
        return err("Les mots de passe ne correspondent pas.")
    if len(password) < 8:
        return err("Le mot de passe doit contenir au moins 8 caractères.")

    email_clean = email.strip().lower()

    conn = db_connect()
    try:
        if conn.execute("SELECT 1 FROM members WHERE email=?", (email_clean,)).fetchone():
            conn.close()
            return err("Cette adresse email est déjà utilisée.")
        conn.execute(
            "INSERT INTO members "
            "(nom, email, phone, telegram, secteurs, pw_hash, actif, created_at) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (
                nom.strip()[:100],
                email_clean[:200],
                phone.strip()[:30],
                telegram.strip()[:80],
                secteurs[:600],
                pw_hash(password),
                now_str(),
            ),
        )
        conn.commit()
        uid = conn.execute(
            "SELECT id FROM members WHERE email=?", (email_clean,)
        ).fetchone()[0]
        conn.close()
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return err(f"Erreur lors de l'inscription : {exc}")

    resp = RedirectResponse("/tenders", 302)
    session_create(resp, uid)
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    if current_member(req):
        return RedirectResponse("/tenders", 302)
    nxt = req.query_params.get("next", "/tenders")
    return render(req, "login.html", {"next": nxt})


@app.post("/login")
async def login_post(
    req:      Request,
    email:    str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/tenders"),
):
    enforce_rate_limit(req, f"login:{get_client_ip(req)}", 5, 300)

    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT * FROM members WHERE email=? AND actif=1",
            (email.strip().lower(),),
        ).fetchone()
    finally:
        conn.close()

    if not row or not pw_check(password, row["pw_hash"]):
        return render(req, "login.html", {
            "error": "Email ou mot de passe incorrect.",
            "next":  next_url,
        })

    conn = db_connect()
    conn.execute("UPDATE members SET last_login=? WHERE id=?", (now_str(), row["id"]))
    conn.commit()
    conn.close()

    # Valider next_url
    safe_next = next_url if next_url.startswith("/") else "/tenders"
    resp = RedirectResponse(safe_next, 302)
    session_create(resp, row["id"])
    return resp


@app.get("/logout")
async def logout(req: Request):
    resp = RedirectResponse("/", 302)
    session_destroy(resp)
    return resp


@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = current_member(req)
    if not m:
        return RedirectResponse("/login?next=/settings", 302)
    selected = [s.strip() for s in (m.get("secteurs") or "").split(",") if s.strip()]
    return render(req, "settings.html", {"selected_secteurs": selected})


@app.post("/settings")
async def settings_post(
    req:          Request,
    nom:          str = Form(""),
    phone:        str = Form(""),
    telegram:     str = Form(""),
    secteurs:     str = Form(""),
    notif_tg:     str = Form("0"),
    notif_email:  str = Form("0"),
    password:     str = Form(""),
    password2:    str = Form(""),
):
    m = current_member(req)
    if not m:
        return RedirectResponse("/login", 302)

    selected = [s.strip() for s in (secteurs or "").split(",") if s.strip()]

    if password:
        if password != password2:
            return render(req, "settings.html", {
                "error": "Les mots de passe ne correspondent pas.",
                "selected_secteurs": selected,
            })
        if len(password) < 8:
            return render(req, "settings.html", {
                "error": "Mot de passe trop court (min 8 caractères).",
                "selected_secteurs": selected,
            })

    conn = db_connect()
    updates: dict = {
        "nom":         (nom.strip() or m["nom"])[:100],
        "phone":       phone.strip()[:30],
        "telegram":    telegram.strip()[:80],
        "secteurs":    secteurs[:600],
        "notif_tg":    1 if notif_tg  == "1" else 0,
        "notif_email": 1 if notif_email == "1" else 0,
    }
    if password:
        updates["pw_hash"] = pw_hash(password)

    fields = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE members SET {fields} WHERE id=?",
        [*updates.values(), m["id"]],
    )
    conn.commit()
    conn.close()

    return flash_redirect("/settings", "Paramètres sauvegardés ✓")

# ═══════════════════════════════════════════════════════
# ROUTES — ADMIN
# ═══════════════════════════════════════════════════════
_ADMIN_COOKIE = "rassd_adm"

def admin_token() -> str:
    return hmac.new(SECRET_KEY.encode(), b"rassd-admin-2026", hashlib.sha256).hexdigest()

def admin_authed(req: Request) -> bool:
    return hmac.compare_digest(
        req.cookies.get(_ADMIN_COOKIE, ""),
        admin_token(),
    )

def admin_guard(req: Request):
    if not admin_authed(req):
        raise HTTPException(302, headers={"Location": "/admin/login"})


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    if admin_authed(req):
        return RedirectResponse("/admin", 302)
    err = req.query_params.get("err", "")
    return HTMLResponse(_admin_login_html(err))


@app.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    enforce_rate_limit(req, "admin_login", 5, 300)
    if pwd != ADMIN_PASS:
        return RedirectResponse("/admin/login?err=1", 302)
    resp = RedirectResponse("/admin", 302)
    resp.set_cookie(
        _ADMIN_COOKIE, admin_token(),
        max_age=86400, httponly=True, samesite="lax",
        secure=SITE_URL.startswith("https"),
    )
    return resp


@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/", 302)
    resp.delete_cookie(_ADMIN_COOKIE)
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(req: Request):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    conn = db_connect()
    try:
        stats = {
            "actif":   conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "expire":  conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "total":   conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "members": conn.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "alerts":  conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0],
            "runs":    conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0],
        }
        last_run = conn.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        members = [
            dict(r) for r in conn.execute(
                "SELECT id,nom,email,telegram,secteurs,notif_tg,notif_email,created_at,last_login "
                "FROM members WHERE actif=1 ORDER BY id DESC LIMIT 30"
            ).fetchall()
        ]
        recent_tenders = [
            dict(r) for r in conn.execute(
                "SELECT * FROM tenders WHERE statut='actif' "
                "ORDER BY date_extraction DESC LIMIT 15"
            ).fetchall()
        ]
        runs = [
            dict(r) for r in conn.execute(
                "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 10"
            ).fetchall()
        ]
    finally:
        conn.close()
    return render(req, "admin.html", {
        "stats":          stats,
        "last_run":       dict(last_run) if last_run else {},
        "members":        members,
        "recent_tenders": recent_tenders,
        "runs":           runs,
        "slog":           ScrapeLog.tail(50),
        "ss":             ScrapeState,
    })


@app.get("/admin/scrape")
async def admin_trigger_scrape(req: Request):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    if ScrapeState.running:
        return JSONResponse({"error": "Scrape déjà en cours"}, 400)

    async def _run():
        loop = asyncio.get_event_loop()
        new  = await loop.run_in_executor(None, run_scraper)
        if new:
            await notify_members(new)

    asyncio.create_task(_run())
    return RedirectResponse("/admin?_flash=Scraping+lancé&_fk=ok", 302)


@app.get("/admin/scrape_stream")
async def admin_scrape_stream(req: Request):
    """SSE — diffuse le log du scraper en temps réel."""
    if not admin_authed(req):
        return JSONResponse({"error": "Non autorisé"}, 401)

    prev_len = [0]

    async def event_generator():
        while True:
            entries = ScrapeLog.tail(300)
            new     = entries[prev_len[0]:]
            for entry in new:
                data = json.dumps({
                    "log":   entry,
                    "state": {
                        "running": ScrapeState.running,
                        "found":   ScrapeState.found,
                        "saved":   ScrapeState.saved,
                        "errors":  ScrapeState.errors,
                        "current": ScrapeState.current,
                        "total":   ScrapeState.total,
                    },
                })
                yield f"data: {data}\n\n"
            prev_len[0] = len(entries)

            if not ScrapeState.running and prev_len[0] > 0:
                yield f"data: {json.dumps({'done': True, 'saved': ScrapeState.saved})}\n\n"
                break

            await asyncio.sleep(0.7)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/admin/expire_now")
async def admin_expire_now(req: Request):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    conn  = db_connect()
    today = datetime.now().date()
    try:
        conn.execute(
            "UPDATE tenders SET statut='expire' "
            "WHERE statut='actif' AND date_limite != '' "
            "AND date_limite NOT LIKE '%/%' AND date_limite < date('now')"
        )
        rows = conn.execute(
            "SELECT id,date_limite FROM tenders "
            "WHERE statut='actif' AND date_limite LIKE '%/%'"
        ).fetchall()
        exp = []
        for row in rows:
            m2 = re.search(r"(\d{1,2}/\d{2}/\d{4})", row["date_limite"] or "")
            if m2:
                try:
                    if datetime.strptime(m2.group(1), "%d/%m/%Y").date() < today:
                        exp.append(row["id"])
                except ValueError:
                    pass
        if exp:
            ph = ",".join(["?"] * len(exp))
            conn.execute(
                f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp
            )
        conn.commit()
        active = conn.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        conn.close()
        return JSONResponse({"ok": True, "expired": len(exp), "active_remaining": active})
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return JSONResponse({"error": str(exc)}, 500)


@app.get("/admin/clear_db")
async def admin_clear_db(req: Request):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    conn = db_connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        conn.execute("DELETE FROM tenders")
        conn.execute("DELETE FROM alerts_sent")
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "deleted": n})
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return JSONResponse({"error": str(exc)}, 500)


@app.get("/admin/test_notify")
async def admin_test_notify(req: Request, chat_id: str = ""):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    target = chat_id or ADMIN_TG
    ok     = await tg_send(
        target,
        f"✅ <b>{BRAND}</b> — Notification test\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
    )
    return JSONResponse({"ok": ok, "chat_id": target})


@app.post("/admin/member_toggle")
async def admin_member_toggle(req: Request, mid: int = Form(0)):
    if not admin_authed(req):
        return RedirectResponse("/admin/login", 302)
    conn = db_connect()
    conn.execute(
        "UPDATE members SET actif = CASE WHEN actif=1 THEN 0 ELSE 1 END WHERE id=?",
        (mid,),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin?_flash=Membre+mis+à+jour&_fk=ok", 302)

# ═══════════════════════════════════════════════════════
# ROUTES — API (scraper local → ingest)
# ═══════════════════════════════════════════════════════
@app.post("/api/v1/ingest")
async def api_ingest(req: Request):
    enforce_rate_limit(req, "ingest", 10, 60)
    try:
        body = await req.json()
        if body.get("pwd") != ADMIN_PASS:
            return JSONResponse({"error": "unauthorized"}, 401)

        tenders  = body.get("tenders", [])
        saved    = 0
        new_list = []
        for t in tenders:
            if not t.get("id") or not t.get("objet"):
                continue
            dl = str(t.get("date_limite", "")).strip()
            if dl and date_is_expired(dl):
                continue
            if tender_save(t):
                saved    += 1
                new_list.append(t)

        if new_list:
            asyncio.create_task(notify_members(new_list))

        return JSONResponse({"ok": True, "saved": saved, "total": len(tenders)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, 500)

# ═══════════════════════════════════════════════════════
# ROUTES — UTILITAIRES
# ═══════════════════════════════════════════════════════
@app.get("/health")
async def health_check():
    conn = db_connect()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM tenders WHERE statut='actif'"
        ).fetchone()[0]
        conn.close()
        return JSONResponse({
            "status":         "ok",
            "brand":          BRAND,
            "active_tenders": active,
            "scraper_running": ScrapeState.running,
        })
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, 500)


@app.get("/robots.txt")
async def robots():
    return HTMLResponse(
        "User-agent: *\nDisallow: /admin\nDisallow: /api\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )

# ═══════════════════════════════════════════════════════
# ADMIN LOGIN PAGE (HTML inline)
# ═══════════════════════════════════════════════════════
def _admin_login_html(err: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Admin — {BRAND}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#030303;color:#f3eee7;font-family:'Helvetica Neue',sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh}}
.box{{background:#0e0e0e;border:1px solid #1f1f1f;border-radius:16px;padding:48px 40px;
      width:380px;box-shadow:0 24px 80px rgba(0,0,0,.7)}}
.logo{{font-size:26px;font-weight:900;color:#E8A020;letter-spacing:2px;margin-bottom:4px}}
.sub{{font-size:12px;color:#444;letter-spacing:.5px;text-transform:uppercase;margin-bottom:36px}}
input{{width:100%;padding:13px 16px;background:#151515;border:1px solid #2a2a2a;
       border-radius:10px;color:#f3eee7;font-size:14px;margin-bottom:16px;
       transition:border-color .2s}}
input:focus{{outline:none;border-color:#E8A020}}
button{{width:100%;padding:14px;background:#E8A020;color:#000;border:none;
        border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;
        letter-spacing:.5px;transition:opacity .2s}}
button:hover{{opacity:.85}}
.err{{color:#e05555;font-size:13px;margin-bottom:16px;padding:10px 14px;
      background:rgba(224,85,85,.1);border:1px solid rgba(224,85,85,.2);border-radius:8px}}
</style></head>
<body><div class="box">
<div class="logo">{BRAND}</div>
<div class="sub">Administration</div>
{"<div class='err'>⚠ Mot de passe incorrect</div>" if err else ""}
<form method="post" action="/admin/login">
  <input type="password" name="pwd" placeholder="Mot de passe" autofocus autocomplete="current-password">
  <button type="submit">Accéder au panneau →</button>
</form>
</div></body></html>"""
