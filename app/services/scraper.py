"""
SOURCE — Scraper v1.0
Source UNIQUE: marchespublics.gov.ma
STX10 classification sémantique intégrée.
"""
import re, time, ssl, random, logging, requests, urllib3
from datetime import datetime, date
from bs4 import BeautifulSoup
from app.core.config import cfg
from app.core.stx10 import classify

urllib3.disable_warnings()
logger = logging.getLogger("source.scraper")

BASE     = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
LIST_URL = f"{BASE}/list"
HOME_URL = "https://www.marchespublics.gov.ma"

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

DATE_RE   = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DATE_FMTS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
DL_LABELS = [
    "date et heure limite de remise des offres",
    "date et heure limite de remise des devis",
    "date limite de remise des offres",
    "date limite de réception des offres",
    "date de remise des offres",
    "date limite", "heure limite", "clôture",
]

def _session():
    s = requests.Session()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1)))
    s.headers.update({
        "User-Agent": random.choice(UA),
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": HOME_URL,
    })
    return s

def _parse_date(s):
    s = str(s).strip().split()[0]
    for fmt in DATE_FMTS:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def _extract_date(text):
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _is_expired(text):
    if not text or str(text).strip() in ("","N/A","—","-"): return False
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _cell(soup, *labels):
    """Cherche valeur dans tableau par label"""
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) >= 2:
            label = cells[0].get_text(" ",strip=True).lower()
            for lbl in labels:
                if lbl.lower() in label:
                    return cells[1].get_text(" ",strip=True)
    return ""

def _get_max_id(session) -> int:
    try:
        r = session.get(LIST_URL, timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        ids = []
        for a in soup.find_all("a", href=True):
            m = re.search(r'/consultation/show/(\d+)', a["href"])
            if m: ids.append(int(m.group(1)))
        return max(ids) if ids else 0
    except Exception as e:
        logger.error(f"[max_id] {e}")
        return 0

def _fetch(session, tid: int) -> dict | None:
    url = f"{BASE}/show/{tid}"
    try:
        r = session.get(url, timeout=20)
        if r.status_code in (404, 403): return None
        if r.status_code != 200:
            logger.debug(f"[fetch] {tid} → HTTP {r.status_code}")
            return None

        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ", strip=True)
        if len(text) < 200: return None

        # Skip non-tender pages
        for skip in ["connexion","liste des avis","se connecter","portail national"]:
            if skip in text[:300].lower(): return None

        # Objet (titre du marché)
        objet = ""
        for tag in soup.find_all(["h1","h2","h3"]):
            t = tag.get_text(" ", strip=True)
            if len(t) > 20 and not any(s in t.lower() for s in
               ["accueil","connexion","portail","retour","liste","consultation"]):
                objet = t[:300]; break
        if not objet:
            objet = _cell(soup,"objet","désignation","intitulé","libellé") or ""
        if not objet or len(objet) < 8: return None

        # Acheteur
        acheteur = _cell(soup,
            "acheteur","maître d'ouvrage","entité","organisme",
            "administration","établissement","ministère","commune","wilaya") or ""

        # Date publication
        date_pub = _extract_date(
            _cell(soup,"publication","date de publication","avis de consultation")
        ) or datetime.now().strftime("%d/%m/%Y")

        # Date limite — cherche par labels
        date_limite = ""
        for lbl in DL_LABELS:
            v = _cell(soup, lbl)
            if v:
                date_limite = _extract_date(v)
                if date_limite: break

        # Filtre expiré
        if _is_expired(date_limite): return None

        # Montant
        montant = _cell(soup,"montant","budget","estimation","coût","valeur") or ""
        if len(montant) > 60: montant = ""

        # Région
        region = _cell(soup,"région","wilaya","lieu d'exécution","localisation","ville") or ""
        if len(region) > 80: region = region[:80]

        # STX10 sémantique
        stx10 = classify(f"{objet} {acheteur} {region}")

        return {
            "id":               f"bdc_{tid}",
            "objet":            objet[:300],
            "acheteur":         acheteur[:150],
            "stx10_code":       stx10.get("code","S902"),
            "stx10_label":      stx10.get("label",""),
            "region":           region[:100],
            "montant":          montant[:80],
            "date_publication": date_pub,
            "date_limite":      date_limite,
            "url":              url,
            "statut":           "actif",
            "scraped_at":       datetime.now().isoformat(),
        }
    except Exception as e:
        logger.debug(f"[fetch {tid}] {e}")
        return None

def scrape_new(db, last_max: int = 0) -> list:
    """Scrape nouveaux marchés depuis marchespublics.gov.ma"""
    session = _session()
    found = []
    t0 = time.time()

    current_max = _get_max_id(session)
    if not current_max:
        logger.warning("[scraper] Impossible de trouver max_id")
        return []

    if last_max and last_max < current_max:
        start_id = last_max + 1
        end_id   = current_max + 30
    else:
        start_id = max(1, current_max - 250)
        end_id   = current_max + 30

    logger.info(f"[scraper] Scan IDs {start_id}→{end_id} (max={current_max})")

    for tid in range(end_id, start_id-1, -1):
        if db.execute("SELECT id FROM tenders WHERE id=?", (f"bdc_{tid}",)).fetchone():
            continue
        t = _fetch(session, tid)
        if t:
            try:
                db.execute("""
                    INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,stx10_code,stx10_label,region,montant,
                     date_publication,date_limite,url,statut,scraped_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (t["id"],t["objet"],t["acheteur"],t["stx10_code"],t["stx10_label"],
                      t["region"],t["montant"],t["date_publication"],t["date_limite"],
                      t["url"],t["statut"],t["scraped_at"]))
                db.commit()
                found.append(t)
                logger.info(f"✅ {t['id']} [{t['stx10_code']}] {t['objet'][:60]}")
            except Exception as e:
                logger.error(f"[DB insert] {e}")
        time.sleep(random.uniform(0.8, 1.6))

    # Marquer expirés
    try:
        rows = db.execute(
            "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
        ).fetchall()
        for row in rows:
            if _is_expired(row["date_limite"]):
                db.execute("UPDATE tenders SET statut='expiré' WHERE id=?", (row["id"],))
        db.commit()
    except Exception as e:
        logger.error(f"[expire] {e}")

    dur = round(time.time()-t0, 1)
    try:
        db.execute("INSERT INTO scrape_log(ts,found,duration) VALUES(?,?,?)",
                   (datetime.now().isoformat(), len(found), dur))
        db.commit()
    except: pass

    logger.info(f"[scraper] ✅ {len(found)} nouveaux en {dur}s")
    return found
