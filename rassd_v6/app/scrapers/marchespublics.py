"""
Modern Business — Scraper marchespublics.gov.ma
Scan séquentiel des IDs autour du dernier connu.
"""
import re
import ssl
import time
import random
import logging

import requests
import urllib3
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter

from app.core.dates import extract_deadline, is_expired, format_deadline
from app.core.sectors import classify, get_label
from app.core.config import cfg

urllib3.disable_warnings()
logger = logging.getLogger("atlas.marchespublics")

# IMPORTANT: www. obligatoire — sans www. → DNS fail sur Railway
BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
# NOTE: /list suffix returns 404 — the listing page IS the base consultation URL
LIST_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Régions marocaines
REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": ["tanger", "tétouan", "tetouan", "al hoceima", "larache"],
    "Oriental": ["oujda", "nador", "berkane", "taourirt", "jerada"],
    "Fès-Meknès": ["fès", "fes", "meknès", "meknes", "ifrane", "taza"],
    "Rabat-Salé-Kénitra": ["rabat", "salé", "sale", "kénitra", "kenitra"],
    "Béni Mellal-Khénifra": ["béni mellal", "beni mellal", "khénifra", "khouribga"],
    "Casablanca-Settat": ["casablanca", "settat", "mohammedia", "berrechid"],
    "Marrakech-Safi": ["marrakech", "safi", "essaouira"],
    "Drâa-Tafilalet": ["errachidia", "ouarzazate", "zagora", "tinghir"],
    "Souss-Massa": ["agadir", "tiznit", "taroudant", "inezgane"],
    "Guelmim-Oued Noun": ["guelmim", "tan-tan", "sidi ifni"],
    "Laâyoune-Sakia El Hamra": ["laayoune", "laâyoune", "boujdour"],
    "Dakhla-Oued Ed-Dahab": ["dakhla", "aousserd"],
}

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

class TLSAdapter(HTTPAdapter):
    """Adapter SSL permissif pour marchespublics.gov.ma sur Railway."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _session():
    retry = urllib3.Retry(
        total=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", TLSAdapter(max_retries=retry))
    s.mount("http://", TLSAdapter(max_retries=retry))
    s.headers["User-Agent"] = random.choice(UA_POOL)
    s.verify = False
    return s


def _detect_region(text: str) -> str:
    """Détecte la région marocaine depuis le texte."""
    t = text.lower()
    for region, keywords in REGIONS.items():
        if any(kw in t for kw in keywords):
            return region
    return ""


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

    # Supprimer numéro de lot (#01, #1, etc.)
    objet = re.sub(r'^#\d+\s*', '', objet).strip()

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

    # Annulé → skip
    if any(w in full.lower() for w in ["annulé", "annulée", "annulation", "sans suite"]):
        return None

    # Classification secteur + région
    context = f"{objet} {acheteur} {full[:500]}"
    code = classify(context)
    secteur = f"{code} – {get_label(code)}"
    region = _detect_region(f"{acheteur} {full[:1000]}")

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "id":               f"bdc_{tid}",
        "objet":            objet[:400],
        "acheteur":         acheteur[:200],
        "secteur":          secteur,
        "region":           region,
        "date_publication": date_pub[:20] if date_pub else "",
        "date_limite":      date_lim,
        "description":      full[:3000],
        "montant":          montant[:80],
        "url":              f"{BASE}/show/{tid}",
        "source":           "marchespublics",
        "statut":           "actif",
        "scraped_at":       now,
        "updated_at":       now,
    }


def run(known_ids: set, log_fn=print) -> list:
    """
    Scrape marchespublics. known_ids = IDs déjà en DB.
    Retourne liste de tenders dicts.
    """
    # Déterminer la plage de scan
    max_id = 325000  # IDs actuels ~326xxx en avril 2026

    # Détection dynamique depuis listing
    s = _session()
    try:
        r = s.get(LIST_URL, timeout=20)
        if r.status_code == 200:
            ids = [int(m) for m in re.findall(r'/show/(\d+)', r.text)]
            if ids:
                detected = max(ids)
                if detected > max_id:
                    max_id = detected
                    log_fn(f"Max ID détecté: #{detected}")
    except (requests.RequestException, ValueError) as e:
        log_fn(f"⚠ Détection max ID: {e}")

    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id:
                    max_id = n
            except ValueError:
                pass

    if max_id < 320000:
        max_id = 325000

    start_id = max(max_id - 30, 310000)
    end_id = max_id + 600
    scan_ids = [str(i) for i in range(start_id, end_id + 1)
                if f"bdc_{i}" not in known_ids]

    log_fn(f"Max ID: #{max_id} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

    results = []
    errors = 0
    skipped_exp = 0
    consec_errors = 0

    for idx, tid in enumerate(scan_ids):
        # Rotation User-Agent tous les 80 requêtes
        if idx % 80 == 0 and idx > 0:
            s.headers["User-Agent"] = random.choice(UA_POOL)
        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=20)
            if r.status_code == 404:
                consec_errors += 1
                if consec_errors > 80 and len(results) == 0:
                    log_fn("80 IDs vides, arrêt")
                    break
                continue
            if r.status_code != 200 or len(r.text) < 1500:
                consec_errors += 1
                continue
            consec_errors = 0
            t = parse_page(r.text, tid)
            if not t:
                if is_expired(r.text[:2000]):
                    skipped_exp += 1
                continue
            results.append(t)
            log_fn(f"✓ #{tid} │ {t.get('secteur', '')[:20]:20} │ {t['objet'][:45]} │ ⏰{t['date_limite'] or '?'}")
            time.sleep(0.3)
        except Exception as e:
            errors += 1
            consec_errors += 1
            if errors <= 3:
                log_fn(f"⚠ [{tid}]: {e}")
            if consec_errors > 10 and errors > 5:
                log_fn("❌ Trop d'erreurs réseau, arrêt")
                break

    log_fn(f"marchespublics: {len(results)} trouvés | {skipped_exp} expirés | {errors} erreurs")
    return results
