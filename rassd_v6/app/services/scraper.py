"""
RASSD — Real-Time Scraper v1.0
Détecte les nouvelles صفقات dès leur publication.

Stratégie:
1. Trouve le MAX ID actuel depuis la page listing
2. Surveille en boucle les nouveaux IDs
3. Alerte immédiatement à chaque nouvelle صفقة
"""
import re, time, ssl, random, logging, os, requests, urllib3
from datetime import datetime, date
from typing import Optional

urllib3.disable_warnings()
logger = logging.getLogger("rassd.rt")

BASE   = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
LIST_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/list"
HOME_URL = "https://www.marchespublics.gov.ma"

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

DATE_RE  = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DATE_FMT = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"]
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres","date limite de remise des devis",
    "date limite de réception des offres","date limite de réception des devis",
    "date de remise des offres","date de clôture","heure limite","date limite",
]
SKIP_H2 = ["accueil","connexion","liste des avis","résultats","invité",
           "retour à","se connecter","portail national","consultations"]


def _parse_date(s):
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
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

def is_expired(text):
    if not text or str(text).strip() in ("","N/A","—","-"): return False
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _detect_secteur(text):
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","route","béton"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","système","réseau","serveur","cloud"]): return "IT & Télécoms"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","gardiennage"]): return "Services Généraux"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","éducation","stage"]): return "Formation"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas"]): return "Restauration"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau potable","assainissement"]): return "Hydraulique"
    if any(k in t for k in ["papeterie","cartouche","toner"]): return "Fournitures Bureau"
    return "Autres Fournitures"

def _cell(soup, *labels):
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 2: continue
        lbl = cells[0].get_text(strip=True).lower()
        for label in labels:
            if label.lower() in lbl:
                val = " ".join(c.get_text(strip=True) for c in cells[1:]).strip()
                if val and len(val) > 1: return val[:500]
    return ""


def make_session():
    class TLSAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            ctx = ssl.create_default_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw["ssl_context"] = ctx
            return super().init_poolmanager(*a, **kw)
    s = requests.Session()
    s.mount("https://", TLSAdapter())
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(UA),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": HOME_URL,
    })
    return s


def find_max_id(s, log_fn=print) -> int:
    """
    Trouve le MAX ID actuel depuis la page listing.
    Cherche tous les liens /show/NNNNN et prend le plus grand.
    """
    try:
        # Page listing principale
        r = s.get(LIST_URL, timeout=20)
        if r.status_code != 200:
            r = s.get(f"{HOME_URL}/bdc/entreprise/consultation", timeout=20)

        if r.status_code == 200:
            # Chercher tous les IDs dans les liens
            ids = re.findall(r'/show/(\d{5,6})', r.text)
            if ids:
                max_id = max(int(i) for i in ids)
                log_fn(f"Max ID depuis listing: #{max_id}")
                return max_id

        # Fallback: scan binaire pour trouver le dernier ID actif
        log_fn("Listing inaccessible — scan binaire pour trouver max ID...")
        return _find_max_binary(s, 312000, 320000, log_fn)

    except Exception as e:
        log_fn(f"find_max_id error: {e} — fallback 313000")
        return 313000


def _find_max_binary(s, low, high, log_fn) -> int:
    """Recherche binaire du max ID actif"""
    best = low
    while low <= high:
        mid = (low + high) // 2
        try:
            r = s.get(f"{BASE}/show/{mid}", timeout=15)
            if r.status_code == 200 and len(r.text) > 2000:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        except:
            high = mid - 1
    log_fn(f"Max ID trouvé: #{best}")
    return best


def parse_page(html, tid):
    """Parse une page et retourne dict ou None"""
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        full = soup.get_text(" ", strip=True)

        # ── OBJET ──
        objet = _cell(soup, "objet du marché","objet de la consultation",
                      "objet","intitulé","désignation",
                      "nature des travaux","nature des fournitures","nature des prestations")

        if not objet:
            for tag in soup.find_all(["h1","h2","h3"])[:10]:
                t = tag.get_text(strip=True)
                if len(t) < 8 or len(t) > 500: continue
                if any(s in t.lower() for s in SKIP_H2): continue
                objet = t; break

        if not objet:
            # Extraire du texte brut après "avis d'achat"
            m = re.search(r"avis d['\s]achat\s+[#\w/\-\.]+\s+([^\.]{8,200})", full, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                for stop in ["Accueil","Se connecter","Retour","Invité","Si vous","Liste"]:
                    if stop in candidate:
                        candidate = candidate[:candidate.index(stop)].strip()
                if len(candidate) > 8:
                    objet = candidate[:200]

        if not objet or objet.lower().startswith("détails de") or len(objet) < 5:
            return None

        objet = re.sub(r'\s+', ' ', objet).strip()
        # Remove leading markers like #1, #01, N°1, No.1, Ref:, etc.
        objet = re.sub(r'^[#N°n]\s*°?\s*\d+\s*[:\-–—]?\s*', '', objet).strip()
        objet = re.sub(r'^(Ref|Réf|N°|No\.?|Num\.?)\s*[:\-]?\s*[\w\-/]+\s*[:\-–]?\s*', '', objet, flags=re.I).strip()
        objet = re.sub(r'^\d+\s*[:\-–—]\s*', '', objet).strip()  # "123: objet" → "objet"
        # Remove parentheses-only content at start
        objet = re.sub(r'^\([^)]+\)\s*', '', objet).strip()
        # Capitalize first letter
        if objet and len(objet) > 2: objet = objet[0].upper() + objet[1:]

        # ── DATE LIMITE ──
        date_lim = ""
        raw = _cell(soup, *DATE_LABELS)
        if raw: date_lim = _extract_date(raw)

        if not date_lim:
            fl = full.lower()
            for lbl in DATE_LABELS:
                idx = fl.find(lbl)
                if idx >= 0:
                    date_lim = _extract_date(full[idx:idx+200])
                    if date_lim: break

        if not date_lim:
            today = date.today()
            for ds in DATE_RE.findall(full):
                d = _parse_date(ds)
                if d and d >= today:
                    date_lim = d.strftime("%d/%m/%Y"); break

        # Règle absolue
        if date_lim and is_expired(date_lim): return None
        if any(w in full.lower() for w in ["annulé","annulée","sans suite","infructueux"]): return None

        acheteur = _cell(soup, "maître d'ouvrage","maître d ouvrage",
                         "organisme acheteur","administration","organisme").strip()
        montant = _cell(soup, "montant estimé","montant","budget") or ""
        if not montant:
            m2 = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
            if m2: montant = m2.group(0)[:80]

        return {
            "id": f"bdc_{tid}",
            "objet": objet[:400],
            "acheteur": acheteur[:200],
            "date_publication": _extract_date(_cell(soup,"date de publication","publication")),
            "date_limite": date_lim,
            "montant": montant[:80],
            "secteur": _detect_secteur(objet + " " + full[:400]),
            "url": f"{BASE}/show/{tid}",
            "source": "marchespublics",
            "statut": "actif",
            "description": full[:3000],
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"[parse #{tid}] {e}")
        return None


def run(known_ids: set, log_fn=print) -> list:
    """
    Scraper temps réel:
    1. Trouve le max ID actuel
    2. Scanne 50 en arrière + 200 en avant
    3. Retourne uniquement les nouvelles صفقات actives
    """
    s = make_session()
    results = []

    log_fn("═══ Real-Time Scraper ═══")
    log_fn(f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Trouver le max ID actuel
    max_id = find_max_id(s, log_fn)

    # Si DB a des IDs plus récents, les utiliser
    db_max = 0
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > db_max: db_max = n
            except: pass

    if db_max > max_id:
        max_id = db_max
        log_fn(f"Max ID DB plus récent: #{max_id}")

    start_id = max(max_id - 50, 310000)
    end_id   = max_id + 200
    scan_ids = [str(i) for i in range(start_id, end_id+1)
                if f"bdc_{i}" not in known_ids]

    log_fn(f"Scan: #{start_id} → #{end_id} ({len(scan_ids)} IDs)")

    errors = 0
    for i, tid in enumerate(scan_ids):
        if i % 80 == 0 and i > 0:
            s.headers["User-Agent"] = random.choice(UA)
        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=20)
            if r.status_code == 404: continue
            if r.status_code != 200 or len(r.text) < 1500: continue

            t = parse_page(r.text, tid)
            if not t: continue

            results.append(t)
            log_fn(f"✓ #{tid} │ {t['secteur'][:16]:16} │ {t['objet'][:45]} │ ⏰{t['date_limite'] or '?'}")
            time.sleep(0.25)

        except Exception as e:
            errors += 1
            if errors <= 2: log_fn(f"⚠ #{tid}: {str(e)[:60]}")

    log_fn(f"═══ {len(results)} nouveaux │ {errors} erreurs ═══")
    return results
