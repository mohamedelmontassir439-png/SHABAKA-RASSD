"""
ATLAS PRO Multi-Source Scraper v1.0
================================
Sources: marchespublics + ONDA + Le Matin + ONEE + ONCF + IAM + SNRT + BCP + Crédit Agricole
"""
import re
import ssl
import time
import random
import hashlib
import logging
from datetime import datetime, date
from typing import Optional

import requests
import urllib3
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter

from app.core.sectors import classify, get_label

urllib3.disable_warnings()
logger = logging.getLogger("atlas.multi")

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
]

# Régions marocaines
REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": ["tanger", "tétouan", "tetouan", "al hoceima"],
    "Oriental": ["oujda", "nador", "berkane"],
    "Fès-Meknès": ["fès", "fes", "meknès", "meknes"],
    "Rabat-Salé-Kénitra": ["rabat", "salé", "sale", "kénitra", "kenitra"],
    "Béni Mellal-Khénifra": ["béni mellal", "beni mellal", "khouribga"],
    "Casablanca-Settat": ["casablanca", "settat", "mohammedia"],
    "Marrakech-Safi": ["marrakech", "safi", "essaouira"],
    "Drâa-Tafilalet": ["errachidia", "ouarzazate", "zagora"],
    "Souss-Massa": ["agadir", "tiznit", "taroudant"],
    "Guelmim-Oued Noun": ["guelmim", "tan-tan"],
    "Laâyoune-Sakia El Hamra": ["laayoune", "laâyoune"],
    "Dakhla-Oued Ed-Dahab": ["dakhla"],
}

DATE_RE  = re.compile(r'(\d{2}[/\-]\d{2}[/\-]20\d{2}|\d{4}-\d{2}-\d{2})')
DATE_FMT = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]

class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        kw["ssl_context"]  = ctx
        return super().init_poolmanager(*a, **kw)

def _session() -> requests.Session:
    retry = urllib3.Retry(
        total=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", TLSAdapter(max_retries=retry))
    s.mount("http://",  TLSAdapter(max_retries=retry))
    s.verify = False
    s.headers.update({
        "User-Agent":      random.choice(UA_POOL),
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
    })
    return s

def _parse_date(s: str) -> Optional[date]:
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None

def _extract_date(text: str) -> str:
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _is_expired(text: str) -> bool:
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _detect_secteur(text: str) -> str:
    code = classify(text)
    return f"{code} \u2013 {get_label(code)}"


def _detect_region(text: str) -> str:
    """Détecte la région marocaine depuis le texte."""
    t = text.lower()
    for region, keywords in REGIONS.items():
        if any(kw in t for kw in keywords):
            return region
    return ""

def _make_id(source: str, ref: str, objet: str) -> str:
    key = f"{source}_{ref or objet[:40]}"
    return f"{source.lower()[:4]}_{hashlib.md5(key.encode()).hexdigest()[:10]}"

# Mots qui indiquent que ce n'est PAS une vraie offre
_NOISE_WORDS = ["accueil","connexion","navigation","retour","login","menu",
               "footer","copyright","contact","aide","home","voir plus",
               "lire plus","en savoir","télécharger","imprimer","partager",
               "facebook","twitter","linkedin","instagram","youtube"]

def _tender(source: str, objet: str, acheteur: str = "", date_limite: str = "",
            url: str = "", ref: str = "", montant: str = "") -> Optional[dict]:
    if not objet: return None
    objet = re.sub(r'\s+', ' ', objet).strip()
    # Quality filters
    if len(objet) < 20: return None              # Too short
    if len(objet.split()) < 3: return None       # Less than 3 words
    if re.match(r'^[\d\s/\-\.]+$', objet): return None  # Only numbers
    if any(w in objet.lower() for w in _NOISE_WORDS): return None  # Navigation noise
    if date_limite and _is_expired(date_limite): return None
    if any(w in objet.lower() for w in ["annulé","sans suite","infructueux","résultat"]): return None
    objet = objet[:400]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id":               _make_id(source, ref, objet),
        "objet":            objet,
        "acheteur":         (acheteur or source)[:200],
        "secteur":          _detect_secteur(objet),
        "region":           _detect_region(f"{acheteur} {objet}"),
        "montant":          montant[:80],
        "date_publication": date.today().strftime("%d/%m/%Y"),
        "date_limite":      date_limite,
        "description":      f"Source: {source}" + (f" | Réf: {ref}" if ref else ""),
        "url":              url,
        "statut":           "actif",
        "scraped_at":       now,
        "updated_at":       now,
        "source":           source,
    }

# ══════════════════════════════════════════════════════════
# SOURCE 1: ONDA — Aéroports du Maroc
# ══════════════════════════════════════════════════════════
def scrape_onda(s: requests.Session, log) -> list:
    url = "https://www.onda.ma/mobile/Je-suis-Professionnel/Appels-d'offres/Appels-d'offres-Achats"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        full = r.text
        # Extract references and dates
        refs   = re.findall(r'N°\s*([\d]+/\d{2}/AOO[^<\s"]{0,20})', full)
        dates  = re.findall(r'(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+20\d{2}|\d{2}/\d{2}/20\d{2})', full, re.I)
        objets = re.findall(r'(?:Objet\s*:?\s*)([A-ZÀÂÉÈÊË][^<\n]{20,200})', full)
        for i, ref in enumerate(refs[:20]):
            objet = objets[i] if i < len(objets) else f"Appel d'offres ONDA N°{ref}"
            dl    = _extract_date(dates[i]) if i < len(dates) else ""
            t = _tender("ONDA", objet, "Office National des Aéroports", dl,
                       f"https://www.onda.ma/Je-suis-Professionnel/Appels-d'offres/Appels-d'offres-Achats", ref)
            if t: results.append(t)
        log(f"✅ ONDA: {len(results)} marchés")
        return results
    except Exception as e:
        log(f"⚠ ONDA: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 2: Le Matin Annonces
# ══════════════════════════════════════════════════════════
def scrape_lematin(s: requests.Session, log) -> list:
    url = "https://annonces.lematin.ma/annonces/appels-offres/"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        for a in soup.find_all("a", href=re.compile(r'/annonce/')):
            title = a.get_text(strip=True)
            if len(title) < 15: continue
            href  = a.get("href","")
            full_url = ("https://annonces.lematin.ma" + href) if href.startswith("/") else href
            # Try to get date from parent
            parent = a.find_parent(["div","li","article"])
            dl = ""
            if parent:
                dl = _extract_date(parent.get_text())
            t = _tender("Le Matin", title, "Annonces Le Matin", dl, full_url)
            if t: results.append(t)
        log(f"✅ Le Matin: {len(results)} marchés")
        return results[:30]
    except Exception as e:
        log(f"⚠ Le Matin: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 3: ONEE — Office National de l'Électricité
# ══════════════════════════════════════════════════════════
def scrape_onee(s: requests.Session, log) -> list:
    url = "https://www.one.org.ma/FR/pages/aoselect.asp?esp=2&id1=7&id2=64&id3=54&t2=1&t3=1"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2: continue
            objet = cells[0].get_text(strip=True)
            dl    = _extract_date(" ".join(c.get_text() for c in cells))
            if len(objet) > 20 and dl:  # ONEE: require date for quality
                t = _tender("ONEE", objet, "Office National de l'Électricité", dl, url)
                if t: results.append(t)
        log(f"✅ ONEE: {len(results)} marchés")
        return results[:30]
    except Exception as e:
        log(f"⚠ ONEE: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 4: ONCF — Train Maroc
# ══════════════════════════════════════════════════════════
def scrape_oncf(s: requests.Session, log) -> list:
    url = "https://www.oncf.ma/fr/Entreprise/Fournisseurs/Appels-d-offres"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all(["tr","div"], class_=re.compile(r'row|item|appel|offre', re.I)):
            t  = row.get_text(" ", strip=True)
            dl = _extract_date(t)
            if len(t) > 25 and t[:40] not in seen:
                seen.add(t[:40])
                td = _tender("ONCF", t[:200], "ONCF", dl, url)
                if td: results.append(td)
        log(f"✅ ONCF: {len(results)} marchés")
        return results[:20]
    except Exception as e:
        log(f"⚠ ONCF: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 5: IAM — Maroc Telecom
# ══════════════════════════════════════════════════════════
def scrape_iam(s: requests.Session, log) -> list:
    url = "https://www.iam.ma/groupe-maroc-telecom/appels-d-offres"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all(["tr","div","article","li"]):
            t   = row.get_text(" ", strip=True)
            ref = re.search(r'N°\s*([\d/\w]+/(?:ACHATS|MAR|DRM|ADM|DAF)\S*)', t)
            dl  = _extract_date(t)
            if ref and len(t) > 20 and t[:40] not in seen:
                seen.add(t[:40])
                td = _tender("IAM", t[:200], "Maroc Telecom", dl, url, ref.group(1) if ref else "")
                if td: results.append(td)
        log(f"✅ IAM: {len(results)} marchés")
        return results[:20]
    except Exception as e:
        log(f"⚠ IAM: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 6: SNRT — Télévision Marocaine
# ══════════════════════════════════════════════════════════
def scrape_snrt(s: requests.Session, log) -> list:
    url = "https://ao.snrt.ma"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        # Look for tender objects in cards/rows
        for elem in soup.find_all(["div","article","li","tr"], class_=re.compile(r'card|item|row|offre|tender|appel', re.I)):
            t  = elem.get_text(" ", strip=True)
            dl = _extract_date(t)
            if len(t) > 20 and t[:40] not in seen:
                seen.add(t[:40])
                td = _tender("SNRT", t[:200], "SNRT", dl, url)
                if td: results.append(td)
        # Also look for direct objet mentions
        for p in soup.find_all(text=re.compile(r'Objet\s*:', re.I)):
            objet = re.sub(r'Objet\s*:\s*', '', p.string or "").strip()
            if len(objet) > 15 and objet[:30] not in seen:
                seen.add(objet[:30])
                td = _tender("SNRT", objet, "SNRT", "", url)
                if td: results.append(td)
        log(f"✅ SNRT: {len(results)} marchés")
        return results[:20]
    except Exception as e:
        log(f"⚠ SNRT: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 7: Crédit Agricole Maroc
# ══════════════════════════════════════════════════════════
def scrape_creditagricole(s: requests.Session, log) -> list:
    url = "https://www.creditagricole.ma/fr/appel-offres"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all(["tr","div","article","li"]):
            t  = row.get_text(" ", strip=True)
            dl = _extract_date(t)
            if len(t) > 25 and ("offre" in t.lower() or "marché" in t.lower() or "appel" in t.lower()):
                if t[:40] not in seen:
                    seen.add(t[:40])
                    td = _tender("Crédit Agricole", t[:200], "Crédit Agricole du Maroc", dl, url)
                    if td: results.append(td)
        log(f"✅ Crédit Agricole: {len(results)} marchés")
        return results[:15]
    except Exception as e:
        log(f"⚠ Crédit Agricole: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 8: BCP — Banque Populaire
# ══════════════════════════════════════════════════════════
def scrape_bcp(s: requests.Session, log) -> list:
    url = "https://www.groupebcp.com/fr/appels-doffres"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all(["tr","div","article","li"]):
            t  = row.get_text(" ", strip=True)
            dl = _extract_date(t)
            if len(t) > 25 and ("offre" in t.lower() or "appel" in t.lower() or "consultation" in t.lower()):
                if t[:40] not in seen:
                    seen.add(t[:40])
                    td = _tender("BCP", t[:200], "Banque Centrale Populaire", dl, url)
                    if td: results.append(td)
        log(f"✅ BCP: {len(results)} marchés")
        return results[:15]
    except Exception as e:
        log(f"⚠ BCP: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 9: Ministère de l'Équipement
# ══════════════════════════════════════════════════════════
def scrape_equipement(s: requests.Session, log) -> list:
    url = "http://appels-offres.equipement.gov.ma"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2: continue
            objet = cells[0].get_text(strip=True)
            dl    = _extract_date(" ".join(c.get_text() for c in cells))
            if len(objet) > 10 and objet[:30] not in seen:
                seen.add(objet[:30])
                acheteur = cells[1].get_text(strip=True) if len(cells) > 1 else "Ministère de l'Équipement"
                td = _tender("Équipement", objet, acheteur, dl, url)
                if td: results.append(td)
        log(f"✅ Équipement: {len(results)} marchés")
        return results[:30]
    except Exception as e:
        log(f"⚠ Équipement: {e}"); return []

# ══════════════════════════════════════════════════════════
# SOURCE 10: AMMC
# ══════════════════════════════════════════════════════════
def scrape_ammc(s: requests.Session, log) -> list:
    url = "https://www.ammc.ma/fr/appel-d-offres"
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200: return []
        soup = BS(r.text, "lxml")
        results = []
        seen = set()
        for row in soup.find_all(["tr","div","li","article"]):
            t  = row.get_text(" ", strip=True)
            dl = _extract_date(t)
            if len(t) > 20 and ("appel" in t.lower() or "offre" in t.lower()):
                if t[:40] not in seen:
                    seen.add(t[:40])
                    td = _tender("AMMC", t[:200], "AMMC", dl, url)
                    if td: results.append(td)
        log(f"✅ AMMC: {len(results)} marchés")
        return results[:10]
    except Exception as e:
        log(f"⚠ AMMC: {e}"); return []

# ══════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════
SCRAPERS = [
    ("ONDA",            scrape_onda),
    ("Le Matin",        scrape_lematin),
    ("ONEE",            scrape_onee),
    ("ONCF",            scrape_oncf),
    ("IAM",             scrape_iam),
    ("SNRT",            scrape_snrt),
    ("Crédit Agricole", scrape_creditagricole),
    ("BCP",             scrape_bcp),
    ("Équipement",      scrape_equipement),
    ("AMMC",            scrape_ammc),
]

def run_all(known_ids: set, log_fn=print) -> list:
    """Lance tous les scrapers et retourne les nouveaux marchés."""
    s = _session()
    results = []
    errors = []
    stats = {}

    log_fn("═" * 48)
    log_fn("  ATLAS PRO Multi-Source Scraper v2.0")
    log_fn(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log_fn("═" * 48)

    for name, scraper_fn in SCRAPERS:
        t0 = time.time()
        try:
            items = scraper_fn(s, log_fn)
            new = [i for i in items if i["id"] not in known_ids]
            results.extend(new)
            stats[name] = len(new)
            time.sleep(0.5 + random.random())
        except Exception as e:
            errors.append(name)
            stats[name] = 0
            log_fn(f"❌ {name}: {e}")
            logger.error(f"[multi_scraper] {name}: {e}", exc_info=True)

    log_fn("═" * 48)
    log_fn(f"  {len(results)} nouveaux marchés | {len(errors)} erreurs")
    if stats:
        active = [f"{k}({v})" for k, v in stats.items() if v > 0]
        if active:
            log_fn(f"  Actifs: {', '.join(active)}")
    if errors:
        log_fn(f"  ❌ {', '.join(errors)}")
    log_fn("═" * 48)
    return results
