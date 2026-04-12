"""
Modern Business — Scraper marchespublics.gov.ma v7.0
══════════════════════════════════════════════════════
SOURCE UNIQUE: marchespublics.gov.ma (portail officiel)

ALGORITHME:
  1. Trouve le dernier ID connu en DB
  2. Scanne 30 IDs en arrière + 600 en avant
  3. Pour chaque page:
     a. Extrait l'OBJET depuis le tableau (pas les labels)
     b. Extrait la DATE LIMITE depuis les bons labels
     c. Si date < aujourd'hui → IGNORE immédiatement
     d. Si objet = label de date → IGNORE
  4. Sauvegarde uniquement les صفقات actives

RÈGLE ABSOLUE: date_limite < aujourd'hui → return None
══════════════════════════════════════════════════════
"""

import re, time, logging, hashlib
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("mb.scraper")

# ══════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════

BASE_URL = "https://marchespublics.gov.ma/bdc/entreprise/consultation"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
]

# Labels exacts pour l'OBJET du marché
OBJET_LABELS = [
    "objet du marché",
    "objet de la consultation",
    "objet de l'appel d'offres",
    "objet",
    "intitulé",
    "désignation",
    "nature des travaux",
    "nature des fournitures",
    "nature des prestations",
    "libellé du marché",
]

# Labels exacts pour la DATE LIMITE
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date et heure limite de dépôt des offres",
    "date limite de remise des offres",
    "date limite de remise des devis",
    "date limite de réception des offres",
    "date limite de réception des devis",
    "date de remise des offres",
    "date de clôture des offres",
    "date de clôture",
    "heure limite de remise des offres",
    "heure limite",
    "date limite",
]

# Labels pour ACHETEUR
ACHETEUR_LABELS = [
    "maître d'ouvrage",
    "maître d ouvrage",
    "organisme acheteur",
    "administration",
    "entité acheteuse",
    "organisme",
]

# Labels pour DATE DE PUBLICATION
PUBDATE_LABELS = [
    "date de publication",
    "date d'ouverture des plis",
    "date d'ouverture",
    "publication",
]

# Mots qui indiquent que ce n'est PAS un objet
NOT_OBJET_WORDS = [
    "date", "heure", "limite", "remise", "réception",
    "soumission", "dépôt", "publication", "ouverture",
    "montant", "maître", "organisme", "budget",
    "estimation", "cautionnement",
]

# ══════════════════════════════════════════════════════
# DATE ENGINE
# ══════════════════════════════════════════════════════

DATE_FMTS = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d/%m/%y",
]

DATE_PATTERN = re.compile(
    r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}\.\d{2}\.\d{4})'
    r'(?:\s*[àa]?\s*\d{1,2}[h:]\d{2})?'  # optionnel: heure "12:00" ou "10h00"
)


def _parse_date(s: str) -> Optional[date]:
    """Convertit string → date Python ou None"""
    if not s: return None
    s = str(s).strip()
    # Enlever la partie heure: "05/03/2026 12:00" → "05/03/2026"
    s = s.split()[0].replace("à", "").strip()
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def extract_date_from_text(text: str) -> str:
    """
    Cherche et retourne la première date valide dans un texte.
    Ex: "Date limite de réception05/03/2026 12:00" → "05/03/2026"
    Retourne: "DD/MM/YYYY" ou ""
    """
    if not text: return ""
    m = DATE_PATTERN.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""


def is_expired(date_str: str) -> bool:
    """
    True = date passée → ignorer cette صفقة.
    False = date future/aujourd'hui/pas de date → garder.
    
    Supporte: "05/03/2026", "Date limite...05/03/2026 12:00", "2026-03-05"
    """
    if not date_str: return False
    date_str = str(date_str).strip()
    if date_str in ("", "N/A", "—", "-", "null", "Non précisée"): return False

    today = date.today()

    # Chercher une date n'importe où dans le texte
    for pat, fmt in [
        (r'(\d{2}/\d{2}/\d{4})', "%d/%m/%Y"),
        (r'(\d{4}-\d{2}-\d{2})', "%Y-%m-%d"),
        (r'(\d{2}-\d{2}-\d{4})', "%d-%m-%Y"),
        (r'(\d{2}\.\d{2}\.\d{4})', "%d.%m.%Y"),
    ]:
        m = re.search(pat, date_str)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date() < today
            except (ValueError, TypeError):
                pass
    return False


# ══════════════════════════════════════════════════════
# PARSER HTML marchespublics
# ══════════════════════════════════════════════════════

@dataclass
class Tender:
    id:               str = ""
    objet:            str = ""
    acheteur:         str = ""
    region:           str = ""
    domaine:          str = ""
    type_marche:      str = ""
    montant:          str = ""
    budget_min:       float = 0.0
    budget_max:       float = 0.0
    date_publication: str = ""
    date_limite:      str = ""
    description:      str = ""
    statut:           str = "actif"
    source:           str = "marchespublics"
    source_url:       str = ""
    contact:          str = ""
    ai_score:         int = 50
    ai_category:      str = ""
    ai_reason:        str = ""
    date_extraction:  str = ""


def _cell(soup, *labels) -> str:
    """
    Cherche la valeur d'une cellule dans un tableau HTML.
    Cherche le label dans la 1ère colonne → retourne la 2ème colonne.
    """
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label_text = cells[0].get_text(strip=True).lower()
        # Enlever les caractères spéciaux du label
        label_clean = re.sub(r'[^\w\s]', '', label_text).strip()
        for label in labels:
            label_norm = re.sub(r'[^\w\s]', '', label.lower()).strip()
            if label_norm in label_clean or label_norm in label_text:
                # Retourner toutes les cellules suivantes concaténées
                value = " ".join(
                    c.get_text(strip=True) for c in cells[1:]
                ).strip()
                if value and len(value) > 1:
                    return value[:600]
    return ""


def parse_tender(html: str, tid: str) -> Optional[Tender]:
    """
    Parse une page marchespublics.gov.ma/show/{tid}
    Retourne Tender ou None si invalide/expiré.
    """
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # ══ 1. OBJET ══════════════════════════════════════
        objet = ""

        # Priorité 1: cellule tableau "objet du marché"
        objet = _cell(soup, *OBJET_LABELS)

        # Priorité 2: balises CSS spécifiques marchespublics
        if not objet:
            for selector in [
                ".consultation-objet",
                ".objet-marche",
                "[class*='objet']",
                "[class*='consultation-title']",
                "[class*='title']",
            ]:
                el = soup.select_one(selector)
                if el:
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600:
                        if not any(n in t.lower() for n in NOT_OBJET_WORDS):
                            objet = t
                            break

        # Priorité 3: h1/h2 si ce n'est pas un label de date
        if not objet:
            for tag in soup.find_all(["h1", "h2", "h3"])[:6]:
                t = tag.get_text(strip=True)
                if (10 < len(t) < 600
                        and not any(n in t.lower() for n in NOT_OBJET_WORDS)
                        and not any(n in t.lower() for n in ["accueil", "connexion", "portail", "liste"])):
                    objet = t
                    break

        if not objet:
            return None

        # IMPORTANT: Rejeter si l'objet ressemble à un label de date
        objet_lower = objet.lower()
        if any(lbl in objet_lower for lbl in [
            "date et heure", "date limite", "heure limite",
            "remise des", "réception des", "clôture des",
            "dépôt des", "soumission des",
        ]):
            return None

        # Nettoyer l'objet
        objet = re.sub(r'\s+', ' ', objet).strip()
        objet = re.sub(r'^[\s\-–•:]+', '', objet).strip()
        if len(objet) < 8:
            return None

        # ══ 2. DATE LIMITE ════════════════════════════════
        date_lim = ""

        # Priorité 1: cellule tableau avec labels spécifiques
        raw_dl = _cell(soup, *DATE_LABELS)
        if raw_dl:
            date_lim = extract_date_from_text(raw_dl)

        # Priorité 2: chercher dans le texte complet après les labels
        if not date_lim:
            full_lower = full_text.lower()
            for lbl in DATE_LABELS:
                idx = full_lower.find(lbl)
                if idx < 0:
                    continue
                # Chercher une date dans les 150 chars suivants
                snippet = full_text[idx:idx + 150]
                date_lim = extract_date_from_text(snippet)
                if date_lim:
                    break

        # ══ 3. VÉRIFICATION EXPIRATION ════════════════════
        # Règle absolue: si date passée → ignorer
        if date_lim and is_expired(date_lim):
            return None

        # ══ 4. VÉRIFICATION ANNULATION ════════════════════
        if any(w in full_text.lower() for w in ["annulé", "annulée", "annulation", "sans suite", "infructueux"]):
            return None

        # ══ 5. AUTRES CHAMPS ══════════════════════════════
        acheteur = _cell(soup, *ACHETEUR_LABELS).strip()

        date_pub_raw = _cell(soup, *PUBDATE_LABELS)
        date_pub = extract_date_from_text(date_pub_raw) if date_pub_raw else ""

        montant = _cell(soup, "montant estimé", "montant", "budget", "estimation") or ""
        if not montant:
            m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD|dirhams?)', full_text, re.I)
            if m:
                montant = m.group(0)[:80]

        # ══ 6. CONSTRUCTION DU TENDER ═════════════════════
        return Tender(
            id               = f"bdc_{tid}",
            objet            = objet[:400],
            acheteur         = acheteur[:200],
            region           = "",   # sera rempli par ClassifierAgent
            domaine          = "",   # sera rempli par ClassifierAgent
            type_marche      = "",   # sera rempli par ClassifierAgent
            montant          = montant[:80],
            date_publication = date_pub,
            date_limite      = date_lim,
            description      = full_text[:2000],
            statut           = "actif",
            source           = "marchespublics",
            source_url       = f"{BASE_URL}/show/{tid}",
            ai_score         = 50,
            date_extraction  = datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    except Exception as e:
        logger.error(f"[parse #{tid}] {e}")
        return None


# ══════════════════════════════════════════════════════
# SCRAPER PRINCIPAL
# ══════════════════════════════════════════════════════

def run_scraper(
    known_ids: set,
    log_fn=print,
    session=None,
) -> list:
    """
    Lance le scraper marchespublics.
    
    Args:
        known_ids: IDs déjà en DB (pour éviter re-scraping)
        log_fn: fonction de logging (print ou SLog.add)
        session: requests.Session optionnel (crée un si None)
    
    Returns:
        Liste de Tender objects (actifs uniquement)
    """
    import requests
    import random

    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        })
        session.verify = False

    # ── Calculer la plage de scan ──
    max_id = 312000  # minimum de sécurité
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id:
                    max_id = n
            except ValueError:
                pass

    # Si DB vide ou peu remplie → commencer à 312000+
    if max_id < 311000:
        max_id = 312500

    start_id = max(max_id - 30, 310000)
    end_id   = max_id + 600
    scan_ids = [
        str(i) for i in range(start_id, end_id + 1)
        if f"bdc_{i}" not in known_ids
    ]

    log_fn(f"═══ marchespublics.gov.ma ═══")
    log_fn(f"Max ID connu: #{max_id}")
    log_fn(f"Plage: #{start_id} → #{end_id} ({len(scan_ids)} IDs)")

    results      = []
    errors       = 0
    skipped_exp  = 0
    consec_empty = 0
    idx_user     = 0

    for idx, tid in enumerate(scan_ids):
        # Rotation User-Agent tous les 50 IDs
        if idx % 50 == 0:
            session.headers["User-Agent"] = USER_AGENTS[idx_user % len(USER_AGENTS)]
            idx_user += 1

        url = f"{BASE_URL}/show/{tid}"
        try:
            r = session.get(url, timeout=18)

            # Page inexistante ou trop petite
            if r.status_code == 404:
                consec_empty += 1
                if consec_empty > 50 and len(results) == 0:
                    log_fn(f"50 IDs vides consécutifs, arrêt prématuré")
                    break
                continue

            if r.status_code != 200 or len(r.text) < 1500:
                consec_empty += 1
                continue

            consec_empty = 0

            # Parser la page
            tender = parse_tender(r.text, tid)

            if tender is None:
                # Page parsée mais pas de صفقة valide
                # (peut être expired, annulé, ou pas d'objet)
                if is_expired(r.text[:2000]):
                    skipped_exp += 1
                continue

            results.append(tender)
            log_fn(
                f"✓ bdc_{tid} │ "
                f"{tender.objet[:50]} │ "
                f"⏰{tender.date_limite or '?'}"
            )

            # Petit délai pour ne pas surcharger le serveur
            time.sleep(0.4)

        except Exception as e:
            errors += 1
            consec_empty += 1
            if errors % 10 == 0:
                log_fn(f"⚠ {errors} erreurs accumulées")

    log_fn(
        f"═══ Terminé: {len(results)} marchés actifs | "
        f"{skipped_exp} expirés ignorés | {errors} erreurs ═══"
    )
    return results


# ══════════════════════════════════════════════════════
# ORCHESTRATEUR (utilisé par main.py)
# ══════════════════════════════════════════════════════

def run_all_scrapers(known_ids: set, sources: list, log_fn=print) -> list:
    """
    Point d'entrée unique pour le scraping.
    Ignore 'sources' — utilise uniquement marchespublics.
    """
    return run_scraper(known_ids, log_fn)
