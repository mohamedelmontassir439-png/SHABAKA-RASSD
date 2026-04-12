"""
ATLAS PRO — Scraper marchespublics.gov.ma v4.0
═══════════════════════════════════════════════
Source principale: marchespublics.gov.ma (portail officiel)

Algorithme:
  1. Détecte dynamiquement le max ID depuis la page listing
  2. Scanne 30 IDs en arrière + 600 en avant
  3. Parse chaque page: objet, date limite, acheteur, montant
  4. Filtre: date expirée → ignore, annulé → ignore
  5. Classifie secteur + région automatiquement

Fonctionnalités:
  - TLSAdapter pour Railway (SSL SECLEVEL=1)
  - Retry automatique avec backoff exponentiel
  - Rotation User-Agent
  - Détection dynamique du max ID
  - Classification secteur via app.core.sectors
  - Détection région via mots-clés
"""
import re
import ssl
import time
import random
import logging
from datetime import datetime, date
from typing import Optional

import requests
import urllib3
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter

from app.core.dates import extract_deadline, is_expired, format_deadline, parse_date
from app.core.sectors import classify, get_label

urllib3.disable_warnings()
logger = logging.getLogger("atlas.scraper")

# ══════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════

# IMPORTANT: www. obligatoire — sans www. → DNS fail sur Railway
BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
LIST_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/list"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
]

OBJET_LABELS = [
    "objet du marché", "objet de la consultation",
    "objet de l'appel d'offres", "objet",
    "intitulé", "désignation",
    "nature des travaux", "nature des fournitures",
    "nature des prestations", "libellé du marché",
]

DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date et heure limite de dépôt des offres",
    "date limite de remise des offres",
    "date limite de remise des devis",
    "date limite de réception des offres",
    "date limite de réception des devis",
    "date de remise des offres",
    "date de clôture", "heure limite", "date limite",
]

ACHETEUR_LABELS = [
    "maître d'ouvrage", "maître d ouvrage",
    "organisme acheteur", "administration",
    "entité acheteuse", "organisme",
]

NOT_OBJET_WORDS = [
    "date", "heure", "limite", "remise", "réception",
    "soumission", "dépôt", "publication", "ouverture",
    "montant", "maître", "organisme", "budget",
]

DATE_RE = re.compile(
    r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}\.\d{2}\.\d{4})'
)

# Régions marocaines pour la détection automatique
REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": ["tanger", "tétouan", "tetouan", "al hoceima",
                                   "chefchaouen", "larache", "fnideq"],
    "Oriental": ["oujda", "nador", "berkane", "taourirt", "jerada", "driouch"],
    "Fès-Meknès": ["fès", "fes", "meknès", "meknes", "ifrane", "taza", "sefrou"],
    "Rabat-Salé-Kénitra": ["rabat", "salé", "sale", "kénitra", "kenitra", "témara"],
    "Béni Mellal-Khénifra": ["béni mellal", "beni mellal", "khénifra", "khouribga"],
    "Casablanca-Settat": ["casablanca", "settat", "mohammedia", "berrechid"],
    "Marrakech-Safi": ["marrakech", "safi", "essaouira", "youssoufia"],
    "Drâa-Tafilalet": ["errachidia", "ouarzazate", "zagora", "midelt", "tinghir"],
    "Souss-Massa": ["agadir", "tiznit", "taroudant", "inezgane"],
    "Guelmim-Oued Noun": ["guelmim", "tan-tan", "sidi ifni"],
    "Laâyoune-Sakia El Hamra": ["laayoune", "laâyoune", "boujdour", "tarfaya"],
    "Dakhla-Oued Ed-Dahab": ["dakhla", "aousserd"],
}


# ══════════════════════════════════════════════════════
# TLS ADAPTER — Obligatoire pour Railway
# ══════════════════════════════════════════════════════

class TLSAdapter(HTTPAdapter):
    """Adapter SSL permissif pour marchespublics.gov.ma sur Railway."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _make_session() -> requests.Session:
    """Crée une session HTTP avec TLS permissif + retry + headers réalistes."""
    retry = urllib3.Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", TLSAdapter(max_retries=retry))
    s.mount("http://", TLSAdapter(max_retries=retry))
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    })
    return s


# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def _cell(soup, *labels) -> str:
    """Cherche la valeur d'une cellule dans un tableau HTML par label."""
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        lbl = cells[0].get_text(strip=True).lower()
        lbl_clean = re.sub(r'[^\w\s]', '', lbl).strip()
        for label in labels:
            label_norm = re.sub(r'[^\w\s]', '', label.lower()).strip()
            if label_norm in lbl_clean or label_norm in lbl:
                value = " ".join(c.get_text(strip=True) for c in cells[1:]).strip()
                if value and len(value) > 1:
                    return value[:600]
    return ""


def _extract_date_from_text(text: str) -> str:
    """Extrait la première date valide d'un texte. Retourne DD/MM/YYYY ou ''."""
    if not text:
        return ""
    m = DATE_RE.search(str(text))
    if m:
        d = parse_date(m.group(1))
        if d:
            return d.strftime("%d/%m/%Y")
    return ""


def _detect_secteur(text: str) -> str:
    """Classifie le secteur en utilisant le moteur de app.core.sectors."""
    code = classify(str(text))
    return f"{code} – {get_label(code)}"


def _detect_region(text: str) -> str:
    """Détecte la région marocaine depuis le texte (acheteur + description)."""
    t = text.lower()
    for region, keywords in REGIONS.items():
        if any(kw in t for kw in keywords):
            return region
    return ""


# ══════════════════════════════════════════════════════
# DYNAMIC MAX ID DETECTION
# ══════════════════════════════════════════════════════

def _find_max_id(session: requests.Session, log_fn) -> Optional[int]:
    """Détecte le dernier ID depuis la page listing marchespublics."""
    try:
        r = session.get(LIST_URL, timeout=20)
        if r.status_code != 200:
            log_fn(f"⚠ Listing page: HTTP {r.status_code}")
            return None
        ids = [int(m) for m in re.findall(r'/show/(\d+)', r.text)]
        if ids:
            max_id = max(ids)
            log_fn(f"Max ID détecté depuis listing: #{max_id}")
            return max_id
    except Exception as e:
        log_fn(f"⚠ Détection max ID: {e}")
    return None


# ══════════════════════════════════════════════════════
# PAGE PARSER
# ══════════════════════════════════════════════════════

def parse_page(html: str, tid: str) -> Optional[dict]:
    """Parse une page marchespublics.gov.ma/show/{tid}.
    Retourne un dict tender ou None si invalide/expiré."""
    soup = BS(html, "html.parser")
    full = soup.get_text(" ", strip=True)

    # ── 1. OBJET ─────────────────────────────────────
    objet = _cell(soup, *OBJET_LABELS)

    if not objet:
        for sel in [".consultation-objet", ".objet-marche",
                    "[class*='objet']", "[class*='consultation-title']"]:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if 10 < len(t) < 600 and not any(n in t.lower() for n in NOT_OBJET_WORDS):
                    objet = t
                    break

    if not objet:
        for tag in soup.find_all(["h1", "h2", "h3"])[:6]:
            t = tag.get_text(strip=True)
            if (10 < len(t) < 600
                    and not any(n in t.lower() for n in NOT_OBJET_WORDS)
                    and not any(n in t.lower() for n in
                                ["accueil", "connexion", "portail", "liste"])):
                objet = t
                break

    if not objet:
        return None

    # Rejeter si l'objet ressemble à un label de date
    objet_lower = objet.lower()
    if any(lbl in objet_lower for lbl in [
        "date et heure", "date limite", "heure limite",
        "remise des", "réception des", "clôture des",
    ]):
        return None

    # Nettoyer l'objet
    objet = re.sub(r'\s+', ' ', objet).strip()
    objet = re.sub(r'^[\s\-–•:]+', '', objet).strip()
    if len(objet) < 8:
        return None

    # ── 2. DATE LIMITE ─────────────────────────────────
    date_lim = ""
    raw_dl = _cell(soup, *DATE_LABELS)
    if raw_dl:
        date_lim = _extract_date_from_text(raw_dl)

    if not date_lim:
        fl = full.lower()
        for lbl in DATE_LABELS:
            idx = fl.find(lbl)
            if idx < 0:
                continue
            date_lim = _extract_date_from_text(full[idx:idx + 150])
            if date_lim:
                break

    # ── 3. VÉRIFICATION EXPIRATION ─────────────────────
    if date_lim and is_expired(date_lim):
        return None

    # ── 4. VÉRIFICATION ANNULATION ─────────────────────
    full_lower = full.lower()
    if any(w in full_lower for w in
           ["annulé", "annulée", "annulation", "sans suite", "infructueux"]):
        return None

    # ── 5. AUTRES CHAMPS ──────────────────────────────
    acheteur = _cell(soup, *ACHETEUR_LABELS).strip()
    date_pub = _extract_date_from_text(
        _cell(soup, "date de publication", "date d'ouverture", "publication")
    )
    montant = _cell(soup, "montant estimé", "montant", "budget", "estimation") or ""
    if not montant:
        m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD|dirhams?)', full, re.I)
        if m:
            montant = m.group(0)[:80]

    # ── 6. CLASSIFICATION ─────────────────────────────
    context = f"{objet} {acheteur} {full[:500]}"
    secteur = _detect_secteur(context)
    region = _detect_region(f"{acheteur} {full[:1000]}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "id": f"bdc_{tid}",
        "objet": objet[:400],
        "acheteur": acheteur[:200],
        "secteur": secteur,
        "region": region,
        "montant": montant[:80],
        "date_publication": date_pub,
        "date_limite": date_lim,
        "description": full[:3000],
        "url": f"{BASE}/show/{tid}",
        "source": "marchespublics",
        "statut": "actif",
        "scraped_at": now,
        "updated_at": now,
    }


# ══════════════════════════════════════════════════════
# SCRAPER PRINCIPAL
# ══════════════════════════════════════════════════════

def run(known_ids: set, log_fn=print) -> list:
    """
    Scrape marchespublics.gov.ma — source principale.

    Args:
        known_ids: IDs déjà en DB (pour éviter re-scraping)
        log_fn: fonction de logging (print ou State.log)

    Returns:
        Liste de dicts tender (actifs uniquement)
    """
    session = _make_session()

    # ── Déterminer la plage de scan ──
    max_id = 312000  # minimum de sécurité

    # 1. Essayer la détection dynamique depuis le listing
    detected = _find_max_id(session, log_fn)
    if detected and detected > max_id:
        max_id = detected

    # 2. Chercher le max ID dans les IDs connus
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id:
                    max_id = n
            except ValueError:
                pass

    if max_id < 311000:
        max_id = 312500

    start_id = max(max_id - 30, 310000)
    end_id = max_id + 600
    scan_ids = [
        str(i) for i in range(start_id, end_id + 1)
        if f"bdc_{i}" not in known_ids
    ]

    log_fn(f"═══ marchespublics.gov.ma ═══")
    log_fn(f"Max ID: #{max_id} | Plage: #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

    results = []
    errors = 0
    skipped_exp = 0
    consec_empty = 0
    first_err = None

    for idx, tid in enumerate(scan_ids):
        # Rotation User-Agent tous les 80 requêtes
        if idx % 80 == 0 and idx > 0:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)

        url = f"{BASE}/show/{tid}"
        try:
            r = session.get(url, timeout=20)

            if r.status_code == 404:
                consec_empty += 1
                if consec_empty > 80 and len(results) == 0:
                    log_fn("80 IDs vides consécutifs sans résultat, arrêt")
                    break
                continue

            if r.status_code != 200 or len(r.text) < 1500:
                consec_empty += 1
                continue

            consec_empty = 0

            tender = parse_page(r.text, tid)
            if tender is None:
                if is_expired(r.text[:2000]):
                    skipped_exp += 1
                continue

            results.append(tender)
            log_fn(
                f"✓ {tid} │ {tender['secteur'][:20]:20} │ "
                f"{tender['objet'][:45]} │ ⏰{tender['date_limite'] or '?'}"
            )
            time.sleep(0.3)

        except Exception as e:
            errors += 1
            consec_empty += 1
            if not first_err:
                first_err = str(e)[:100]
                log_fn(f"⚠ [{tid}]: {first_err}")
            if consec_empty > 10 and errors > 5:
                log_fn("❌ Trop d'erreurs réseau consécutives, arrêt")
                break

    if errors > 0:
        log_fn(f"Erreurs: {errors} | {first_err or '?'}")
    log_fn(
        f"═══ Terminé: {len(results)} marchés actifs | "
        f"{skipped_exp} expirés | {errors} erreurs ═══"
    )
    return results


