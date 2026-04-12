"""
Modern Business — Master Date Engine
Règle absolue: date_limite < aujourd'hui → ignorer la صفقة
"""
import re
from datetime import datetime, date
from typing import Optional

_FMTS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y"]

_DATE_RE = re.compile(
    r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}\.\d{2}\.\d{4})'
    r'(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?'
)

_DEADLINE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres",
    "date limite de remise des devis",
    "date limite de réception des offres",
    "date limite de réception des devis",
    "date de remise des offres",
    "date de clôture", "date limite", "heure limite",
    "remise des offres", "remise des plis",
    "dépôt des offres", "avant le", "au plus tard",
    "clôture", "échéance", "soumission",
    "آخر أجل", "الأجل", "تاريخ الإيداع",
]


def parse_date(s: str) -> Optional[date]:
    """String → date ou None"""
    if not s: return None
    s = str(s).strip().split()[0].split("T")[0]
    for fmt in _FMTS:
        try: return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError): pass
    return None


def extract_deadline(text: str) -> Optional[date]:
    """
    Extrait la date limite depuis n'importe quel texte.
    Cherche les labels "date limite", "remise des offres", etc.
    """
    if not text: return None
    text = str(text)
    tl   = text.lower()

    found = []
    for m in _DATE_RE.finditer(text):
        d = parse_date(m.group(1))
        if d and date(2025, 1, 1) <= d <= date(2029, 12, 31):
            found.append((m.start(), d))

    if not found: return None

    # Priorité: date après label deadline
    for lbl in _DEADLINE_LABELS:
        idx = tl.find(lbl)
        if idx < 0: continue
        nearby = [(p, d) for p, d in found if idx <= p <= idx + 200]
        if nearby:
            return min(nearby, key=lambda x: x[0])[1]

    # Fallback: date future la plus proche
    today = date.today()
    future = [(p, d) for p, d in found if d >= today]
    if future:
        return min(future, key=lambda x: abs((x[1] - today).days))[1]

    return found[-1][1]


def is_expired(text: str) -> bool:
    """True = date passée → ignorer. False = futur ou pas de date → garder."""
    if not text: return False
    text = str(text).strip()
    if text in ("", "N/A", "—", "-", "null", "Non précisée"): return False
    dl = extract_deadline(text)
    if dl is None: return False
    return dl < date.today()


def format_deadline(text: str) -> str:
    """Retourne la date en DD/MM/YYYY ou ''"""
    dl = extract_deadline(str(text)) if text else None
    return dl.strftime("%d/%m/%Y") if dl else ""
