"""
ATLAS PRO — Real-Time Scraper v1.0
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
logger = logging.getLogger("atlas.rt")

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
    try:
        from app.core.sectors import classify, get_label
        code = classify(str(text))
        return f"{code} – {get_label(code)}"
    except Exception:
        return "S904 – Prestations diverses"


