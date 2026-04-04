"""
RASSD Scraper — marchespublics.gov.ma
Real-time detection with auto max-ID discovery
"""
import re, ssl, time, random, logging
from datetime import datetime, date
from typing import Optional
import requests, urllib3
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter

urllib3.disable_warnings()
logger = logging.getLogger("rassd.scraper")

BASE     = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
LIST_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/list"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
]

DATE_RE  = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})')
DATE_FMT = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"]

OBJET_LABELS = [
    "objet du marché","objet de la consultation","objet de l'appel d'offres",
    "objet","intitulé","désignation","nature des travaux",
    "nature des fournitures","nature des prestations",
]
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres","date limite de remise des devis",
    "date limite de réception des offres","date limite de réception des devis",
    "date de remise des offres","date de clôture","heure limite","date limite",
]
ACHETEUR_LABELS = ["maître d'ouvrage","maître d ouvrage","organisme acheteur","administration","organisme"]
SKIP_H2 = ["accueil","connexion","liste des avis","résultats","invité","retour à","se connecter","consultations"]


class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", TLSAdapter())
    s.verify = False
    s.headers.update({
        "User-Agent":      random.choice(UA_POOL),
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
        "Referer":         "https://www.marchespublics.gov.ma/",
    })
    return s


def _parse_date(s: str) -> Optional[date]:
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def _extract_date(text: str) -> str:
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _is_expired(text: str) -> bool:
    if not text or str(text).strip() in ("","N/A","—","-"): return False
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _cell(soup, *labels) -> str:
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 2: continue
        lbl = cells[0].get_text(strip=True).lower()
        for label in labels:
            if label.lower() in lbl:
                val = " ".join(c.get_text(strip=True) for c in cells[1:]).strip()
                if val and len(val) > 1: return val[:500]
    return ""

def _detect_secteur(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","route","béton","maçonnerie"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","système","réseau","serveur","cloud","it ","digital","cybersécurité"]): return "IT & Télécoms"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire","pharmacie","chirurgie"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport","bus","flotte"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","gardiennage","sécurité","hygiène"]): return "Services Généraux"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie","architecture","bureau d'études"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","éducation","stage","séminaire","atelier"]): return "Formation"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas","traiteur","buffet"]): return "Restauration"
    if any(k in t for k in ["communication","publicité","impression","média","événement","audiovisuel"]): return "Communication"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque","solaire","générateur"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau potable","assainissement","irrigation","barrage"]): return "Hydraulique"
    if any(k in t for k in ["papeterie","cartouche","toner","fournitures de bureau","imprimante","photocopieur"]): return "Fournitures Bureau"
    if any(k in t for k in ["mobilier","meuble","aménagement","bureau","chaise","armoire"]): return "Mobilier"
    if any(k in t for k in ["agriculture","semence","engrais","irrigation","élevage","vétérinaire"]): return "Agriculture"
    if any(k in t for k in ["environnement","déchets","recyclage","pollution","écologie"]): return "Environnement"
    return "Autres"

def _detect_region(text: str) -> str:
    t = text.lower()
    regions = {
        "Casablanca-Settat":          ["casablanca","settat","mohammedia","berrechid","benslimane"],
        "Rabat-Salé-Kénitra":         ["rabat","salé","kénitra","skhirat","temara"],
        "Fès-Meknès":                 ["fès","meknès","ifrane","boulemane","sefrou","taounate"],
        "Tanger-Tétouan-Al Hoceïma":  ["tanger","tétouan","al hoceïma","chefchaouen","larache"],
        "Marrakech-Safi":             ["marrakech","safi","essaouira","el kelaa","chichaoua"],
        "Souss-Massa":                ["agadir","tiznit","taroudant","ouarzazate","zagora"],
        "Oriental":                   ["oujda","nador","berkane","taourirt","jerada"],
        "Béni Mellal-Khénifra":       ["beni mellal","khénifra","khouribga","azilal","fquih"],
        "Drâa-Tafilalet":             ["errachidia","ouarzazate","zagora","tinghir"],
        "Guelmim-Oued Noun":          ["guelmim","tan-tan","sidi ifni","assa"],
        "Laâyoune-Sakia El Hamra":    ["laâyoune","boujdour","tarfaya","smara"],
        "Dakhla-Oued Ed-Dahab":       ["dakhla","aousserd"],
    }
    for region, keys in regions.items():
        if any(k in t for k in keys): return region
    return ""


def find_max_id(s: requests.Session, log_fn=print) -> int:
    try:
        r = s.get(LIST_URL, timeout=20)
        if r.status_code == 200:
            ids = re.findall(r'/show/(\d{5,6})', r.text)
            if ids:
                max_id = max(int(i) for i in ids)
                log_fn(f"🎯 Max ID depuis listing: #{max_id}")
                return max_id
    except Exception as e:
        log_fn(f"⚠ Listing: {e}")
    # Binary search fallback
    log_fn("🔍 Recherche binaire du Max ID...")
    low, high, best = 310000, 330000, 320000
    for _ in range(12):
        mid = (low + high) // 2
        try:
            r = s.get(f"{BASE}/show/{mid}", timeout=12)
            if r.status_code == 200 and len(r.text) > 2000:
                best = mid; low = mid + 1
            else:
                high = mid - 1
        except:
            high = mid - 1
    log_fn(f"🎯 Max ID trouvé: #{best}")
    return best


def parse_page(html: str, tid: str) -> Optional[dict]:
    try:
        soup = BS(html, "html.parser")
        full = soup.get_text(" ", strip=True)

        # ── OBJET ──
        objet = _cell(soup, *OBJET_LABELS)
        if not objet:
            for tag in soup.find_all(["h1","h2","h3"])[:10]:
                t = tag.get_text(strip=True)
                if len(t) < 8 or len(t) > 500: continue
                if any(s in t.lower() for s in SKIP_H2): continue
                objet = t; break
        if not objet:
            parts = full.split("avis d'achat")
            if len(parts) > 1:
                after = re.sub(r'^\s*#?[\w/\.\-]+\s*', "", parts[-1], count=1).strip()
                for stop in ["Accueil","Se connecter","Retour","Invité","Si vous","Liste"]:
                    if stop in after: after = after[:after.index(stop)].strip()
                if len(after) > 8: objet = after[:200]

        if not objet or objet.lower().startswith("détails de") or len(objet) < 5:
            return None
        objet = re.sub(r'\s+', ' ', objet).strip()

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
            for ds in DATE_RE.findall(full):
                d = _parse_date(ds)
                if d and d >= date.today():
                    date_lim = d.strftime("%d/%m/%Y"); break

        if date_lim and _is_expired(date_lim): return None
        if any(w in full.lower() for w in ["annulé","annulée","sans suite","infructueux"]): return None

        acheteur = _cell(soup, *ACHETEUR_LABELS).strip()
        montant  = _cell(soup,"montant estimé","montant","budget") or ""
        if not montant:
            m2 = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD|dirhams?)', full, re.I)
            if m2: montant = m2.group(0)[:80]
        date_pub = _extract_date(_cell(soup,"date de publication","publication"))
        region   = _detect_region(acheteur + " " + objet)

        return {
            "id":               f"bdc_{tid}",
            "objet":            objet[:400],
            "acheteur":         acheteur[:200],
            "secteur":          _detect_secteur(objet + " " + full[:400]),
            "region":           region,
            "montant":          montant[:80],
            "date_publication": date_pub,
            "date_limite":      date_lim,
            "description":      full[:3000],
            "url":              f"{BASE}/show/{tid}",
            "statut":           "actif",
            "scraped_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"[parse #{tid}] {e}")
        return None


def run(known_ids: set, log_fn=print) -> list:
    t0 = time.time()
    s  = _session()

    log_fn("═" * 48)
    log_fn(f"  RASSD Real-Time Scraper")
    log_fn(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log_fn("═" * 48)

    max_id = find_max_id(s, log_fn)
    db_max = max((int(k[4:]) for k in known_ids if k.startswith("bdc_") and k[4:].isdigit()), default=0)
    if db_max > max_id: max_id = db_max

    start_id = max(max_id - 50, 310000)
    end_id   = max_id + 200
    scan_ids = [str(i) for i in range(start_id, end_id+1) if f"bdc_{i}" not in known_ids]

    log_fn(f"📊 Plage: #{start_id} → #{end_id} ({len(scan_ids)} IDs)")

    results=[]; errors=0

    for i, tid in enumerate(scan_ids):
        if i % 80 == 0 and i > 0:
            s.headers["User-Agent"] = random.choice(UA_POOL)
        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=20)
            if r.status_code == 404: continue
            if r.status_code != 200 or len(r.text) < 1500: continue
            t = parse_page(r.text, tid)
            if not t: continue
            results.append(t)
            log_fn(f"✓ #{tid} │ {t['secteur'][:16]:16} │ {t['objet'][:44]} │ ⏰{t['date_limite'] or '?'}")
            time.sleep(0.25)
        except Exception as e:
            errors += 1
            if errors <= 2: log_fn(f"⚠ #{tid}: {str(e)[:50]}")

    dur = time.time() - t0
    log_fn(f"═" * 48)
    log_fn(f"  ✅ {len(results)} marchés actifs | {errors} erreurs | {dur:.0f}s")
    log_fn(f"═" * 48)
    return results
