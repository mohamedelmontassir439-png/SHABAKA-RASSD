"""
Modern Business — Scraper marchespublics.gov.ma
Scan séquentiel des IDs autour du dernier connu.
"""
import re, time, requests
from datetime import datetime
from bs4 import BeautifulSoup as BS
from app.core.dates import extract_deadline, is_expired, format_deadline
from app.core.config import cfg

BASE = "https://marchespublics.gov.ma/bdc/entreprise/consultation"

# Labels dans le tableau HTML de marchespublics
OBJET_LABELS = [
    "objet du marché", "objet de la consultation", "objet",
    "intitulé", "désignation", "nature des travaux",
    "nature des fournitures", "nature des prestations", "libellé",
]
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres",
    "date limite de remise des devis",
    "date limite de réception des offres",
    "date limite de réception des devis",
    "date de remise des offres",
    "date de clôture", "heure limite", "date limite",
]
NOT_OBJET = [
    "date", "heure", "limite", "remise", "réception",
    "soumission", "dépôt", "publication", "montant",
    "maître", "organisme",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0"


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.verify = False
    return s


def _cell(soup, *labels):
    """Cherche la valeur dans un tableau HTML par label"""
    for row in soup.find_all("tr"):
        tds = row.find_all(["td", "th"])
        if len(tds) < 2: continue
        lbl = tds[0].get_text(strip=True).lower()
        for label in labels:
            if label.lower() in lbl:
                val = " ".join(t.get_text(strip=True) for t in tds[1:])
                if val.strip(): return val.strip()[:500]
    return ""


def parse_page(html: str, tid: str) -> dict | None:
    """Parse une page marchespublics → dict tender ou None"""
    soup = BS(html, "html.parser")
    full = soup.get_text(" ", strip=True)

    # ── Objet ──
    objet = _cell(soup, *OBJET_LABELS)
    if not objet:
        for sel in [".consultation-objet", ".objet-marche", "[class*='objet']", "h1", "h2"]:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if 10 < len(t) < 600 and not any(n in t.lower() for n in NOT_OBJET):
                    objet = t; break
    if not objet: return None

    # Rejeter si objet est un label de date
    if any(lbl in objet.lower() for lbl in ["date et heure", "date limite", "heure limite", "remise des"]):
        return None

    # ── Date limite ──
    date_lim = ""
    raw_dl = _cell(soup, *DATE_LABELS)
    if raw_dl:
        m = re.search(r'(\d{2}/\d{2}/\d{4})', raw_dl)
        if m: date_lim = m.group(1)

    if not date_lim:
        fl = full.lower()
        for lbl in DATE_LABELS:
            idx = fl.find(lbl)
            if idx < 0: continue
            m = re.search(r'(\d{2}/\d{2}/\d{4})', full[idx:idx+120])
            if m: date_lim = m.group(1); break

    # Ignorer si expiré
    if date_lim and is_expired(date_lim):
        return None

    # ── Autres champs ──
    acheteur = _cell(soup, "maître d'ouvrage", "organisme", "administration").strip()
    date_pub  = _cell(soup, "date de publication", "publication")
    montant   = _cell(soup, "montant estimé", "montant", "budget") or ""
    if not montant:
        m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
        if m: montant = m.group(0)[:80]

    return {
        "id":               f"bdc_{tid}",
        "objet":            objet[:400],
        "acheteur":         acheteur[:200],
        "date_publication": date_pub[:20] if date_pub else "",
        "date_limite":      date_lim,
        "description":      full[:2000],
        "montant":          montant[:80],
        "url":              f"{BASE}/show/{tid}",
        "source":           "marchespublics",
        "statut":           "annule" if "annulé" in full.lower() else "actif",
    }


def run(known_ids: set, log_fn=print) -> list:
    """
    Scrape marchespublics. known_ids = IDs déjà en DB.
    Retourne liste de tenders dicts.
    """
    # Calculer la plage de scan
    max_id = 312000
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id: max_id = n
            except: pass

    if max_id < 311000: max_id = 312000

    start_id = max(max_id - 30, 310000)
    end_id   = max_id + 500
    scan_ids = [str(i) for i in range(start_id, end_id + 1)
                if f"bdc_{i}" not in known_ids]

    log_fn(f"Max connu: #{max_id} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

    s = _session()
    results = []
    errors  = 0
    consec_errors = 0

    for idx, tid in enumerate(scan_ids):
        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=15)
            if r.status_code != 200 or len(r.text) < 2000:
                consec_errors += 1
                if consec_errors > 40 and len(results) == 0:
                    log_fn(f"Trop d'erreurs ({consec_errors}), arrêt")
                    break
                continue
            consec_errors = 0
            t = parse_page(r.text, tid)
            if not t: continue
            results.append(t)
            log_fn(f"✓ #{tid} │ {t['objet'][:50]} │ ⏰{t['date_limite'] or '?'}")
        except Exception as e:
            errors += 1
            consec_errors += 1

    log_fn(f"marchespublics: {len(results)} trouvés | {errors} erreurs")
    return results
