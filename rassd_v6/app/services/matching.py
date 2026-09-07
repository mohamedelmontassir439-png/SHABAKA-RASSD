"""
Maroc Entrepreneuriat — Moteur de correspondance marché ↔ membre

Fonctions pures (aucun accès base ni réseau) : un marché est confronté aux
filtres d'un membre et le résultat est déterministe, donc testable isolément.

Règle générale appliquée à chaque filtre : un filtre vide = "pas de
restriction". Un membre qui n'a rien configuré reçoit tout ce qui correspond
à son secteur, comme avant l'introduction de ces filtres.
"""
import json
import re
import unicodedata

# Un montant marocain arrive sous des formes très variables:
# "1 250 000,00 DH", "1.250.000 MAD", "250000", "1 250 000,00"
_AMOUNT_RE = re.compile(r"\d[\d\s., ]*")


def parse_amount(raw) -> float:
    """Extrait un montant numérique d'un libellé libre. Retourne 0 si illisible.

    Les séparateurs de milliers (espace, point, insécable) sont retirés et la
    virgule décimale est convertie. On ne devine jamais un montant absent:
    une chaîne sans chiffre retourne 0, ce qui neutralise le filtre budget
    plutôt que d'exclure le marché à tort.
    """
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    m = _AMOUNT_RE.search(str(raw))
    if not m:
        return 0.0
    txt = m.group(0).strip().replace(" ", "").replace(" ", "")
    # Si les deux séparateurs coexistent, le dernier rencontré est le décimal.
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        # "1250,50" = décimal ; "1,250,000" = séparateurs de milliers
        txt = txt.replace(",", ".") if len(txt.split(",")[-1]) <= 2 else txt.replace(",", "")
    elif txt.count(".") > 1:
        txt = txt.replace(".", "")
    elif "." in txt and len(txt.split(".")[-1]) == 3:
        # "1.250" en contexte marocain = millier, pas 1,25
        txt = txt.replace(".", "")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _norm(text: str) -> str:
    """Minuscule, sans accents, ponctuation ramenée à des espaces.

    Nécessaire pour que 'Casablanca-Settat', 'casablanca settat' et
    'Casablanca–Settat' soient reconnus comme la même région: les libellés
    saisis par les membres et ceux des sources n'utilisent pas les mêmes
    séparateurs.
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", stripped)).strip()


def _as_list(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return [x for x in raw if x]
    try:
        val = json.loads(raw)
        return [x for x in val if x] if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_keywords(raw: str) -> list:
    """Découpe une saisie libre ('béton, électricité; plomberie') en mots-clés."""
    if not raw:
        return []
    parts = re.split(r"[,;\n]+", str(raw))
    return [p.strip() for p in parts if p.strip()]


def member_filters(member: dict) -> dict:
    """Extrait les filtres d'un membre sous une forme normalisée."""
    return {
        "secteurs": _as_list(member.get("secteurs")),
        "regions":  _as_list(member.get("notif_regions")),
        "keywords": parse_keywords(member.get("notif_keywords", "")),
        "min_budget": float(member.get("notif_min_budget") or 0),
        "types":    _as_list(member.get("notif_types")),
    }


def matches(member: dict, tender: dict) -> tuple:
    """Le marché correspond-il aux filtres du membre ?

    Retourne (bool, raison) — la raison sert aux journaux de diagnostic pour
    comprendre pourquoi une alerte n'est pas partie.
    """
    f = member_filters(member)

    if f["secteurs"] and tender.get("secteur") not in f["secteurs"]:
        return False, "secteur"

    if f["regions"]:
        t_region = _norm(tender.get("region", ""))
        if not t_region or not any(_norm(r) in t_region or t_region in _norm(r) for r in f["regions"]):
            return False, "region"

    if f["types"]:
        # Un marché sans type explicite est considéré public (défaut du schéma).
        t_type = (tender.get("type_procedure") or "marche")
        t_offre = (tender.get("type_offre") or "Public")
        wanted = {_norm(x) for x in f["types"]}
        got = {_norm(t_type), _norm(t_offre)}
        if not (wanted & got):
            return False, "type"

    if f["min_budget"] > 0:
        amount = parse_amount(tender.get("montant"))
        # Montant inconnu (0) : on n'exclut pas — l'absence d'information ne
        # doit pas faire manquer une opportunité au membre.
        if amount and amount < f["min_budget"]:
            return False, "budget"

    if f["keywords"]:
        haystack = _norm(" ".join([
            str(tender.get("objet", "")),
            str(tender.get("acheteur", "")),
            str(tender.get("description", ""))[:1500],
        ]))
        if not any(_norm(k) in haystack for k in f["keywords"]):
            return False, "keywords"

    return True, "ok"
