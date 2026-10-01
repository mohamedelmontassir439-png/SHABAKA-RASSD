# -*- coding: utf-8 -*-
"""Présentation des quantités commandées.

La source publie deux champs séparés — « Unité de mesure: jour » et
« Quantité: 50 » — que la collecte recolle en « 50 jour ». Deux défauts à
l'affichage: le pluriel manque, et le libellé « quantité commandée » décrit
mal une location de pelle sur cinquante jours, qui est une durée.

Le travail se fait à l'affichage et non à la collecte, pour que les milliers
de fiches déjà en base en profitent sans être recollectées.
"""
import re

# Unités invariables: symboles et abréviations. « 50 kg », jamais « 50 kgs ».
_INVARIABLES = {
    "kg", "g", "t", "mg", "ml", "l", "m", "m2", "m²", "m3", "m³", "ml²",
    "km", "cm", "mm", "ha", "u", "ft", "qx", "kw", "kwh", "kva", "%",
}

# Toute unité qui ne contient pas de lettre minuscule au-delà d'un symbole —
# « m3 », « M² », « KG » — reste invariable: un symbole ne prend pas de « s ».
_SYMBOLE = re.compile(r"^[A-Za-z]{1,4}[0-9²³]?$")

# Unités de temps: ce n'est pas une quantité commandée mais une durée.
_TEMPORELLES = {
    "jour", "journee", "journée", "semaine", "mois", "an", "annee", "année",
    "heure", "trimestre", "semestre", "nuitee", "nuitée", "nuit",
}

# Pluriels irréguliers rencontrés sur le portail.
_PLURIELS = {
    "mois": "mois",        # déjà invariable
    "travail": "travaux",
    "bocal": "bocaux",
    "local": "locaux",
}


def _sans_accents(texte: str) -> str:
    import unicodedata
    d = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def _accorder(unite: str, nombre: float) -> str:
    """Met l'unité au pluriel quand la quantité le demande."""
    nu = _sans_accents(unite)
    if not unite or nu in _INVARIABLES or nombre <= 1:
        return unite
    if nu in _PLURIELS:
        return _PLURIELS[nu]
    # « m3 », « ML », « Qx »: un symbole ne prend pas la marque du pluriel,
    # et la liste explicite ne peut pas tous les prévoir.
    if _SYMBOLE.match(unite) and any(c.isdigit() for c in unite):
        return unite
    if unite.endswith(("s", "x", "z")):
        return unite
    return unite + "s"


def _nombre(brut: str) -> float:
    """« 1 500,50 » -> 1500.5, et 0 si le texte n'est pas un nombre."""
    t = brut.replace(" ", "").replace(" ", "").replace("\xa0", "")
    t = t.replace(".", "").replace(",", ".") if "," in t else t.replace(" ", "")
    try:
        return float(t)
    except ValueError:
        return 0.0


def formater(brut: str) -> tuple:
    """Rend (texte affichable, est_une_duree).

    « 50 jour »  -> (« 50 jours », True)
    « 3 unité »  -> (« 3 unités », False)
    « 1 Ft »     -> (« 1 Ft », False)   — forfait, invariable et au singulier
    « 120 kg »   -> (« 120 kg », False) — symbole invariable
    """
    brut = (brut or "").strip()
    if not brut:
        return "", False
    # Le nombre est pris en entier, l'unité commence à la première lettre.
    # Un quantificateur paresseux coupait « 1 500 litre » après le « 1 », et
    # l'unité devenait « 500 litre »: plus de pluriel, plus de durée reconnue.
    m = re.match(r"^([\d\s., \xa0]+)\s*([^\s\d].*)?$", brut)
    if not m:
        return brut, False
    chiffre = (m.group(1) or "").strip()
    unite = (m.group(2) or "").strip()
    n = _nombre(chiffre)
    duree = _sans_accents(unite) in _TEMPORELLES
    if not unite:
        return chiffre, False
    return f"{chiffre} {_accorder(unite, n)}", duree


def texte(brut: str) -> str:
    """La quantité seule, accordée."""
    return formater(brut)[0]


def est_duree(brut: str) -> bool:
    """Vrai si l'unité est une unité de temps."""
    return formater(brut)[1]
