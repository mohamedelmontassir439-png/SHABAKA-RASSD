# -*- coding: utf-8 -*-
"""Une ville, quelle que soit la façon dont l'avis l'écrit.

Le portail écrit le lieu d'exécution comme l'acheteur l'a saisi: « El Kelaa
Des Sraghna » et « El kelaa sraghna », « Agadir Ida Ou Tanane » pour la
préfecture d'Agadir, « Oujda-Angad », « Province d'Ifrane MAROC ». Pour une
page « appels d'offres à Agadir », ce sont la même ville: on les réunit
sous un seul nom et une seule adresse.
"""
import re
import unicodedata


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", d).strip()


# Les mots qui entourent un nom de ville sans en faire partie.
_BRUIT = re.compile(r"\b(maroc|province|prefecture|commune|ville|region|de|d|du|des|la|le)\b")

# Formes relevées en base -> nom retenu. La clé est la forme réduite (_cle).
_ALIAS = {
    "agadir ida ou tanane": "Agadir", "agadir ida outanane": "Agadir",
    "oujda angad": "Oujda", "tanger assilah": "Tanger", "tanger assila": "Tanger",
    "el kelaa sraghna": "El Kelaa des Sraghna", "kelaa sraghna": "El Kelaa des Sraghna",
    "fes": "Fès", "sale": "Salé", "meknes": "Meknès", "tetouan": "Tétouan",
    "kenitra": "Kénitra", "el jadida": "El Jadida", "beni mellal": "Béni Mellal",
    "laayoune": "Laâyoune", "skhirate temara": "Skhirate-Témara",
    "inezgane ait melloul": "Inezgane-Aït Melloul", "mohammadia": "Mohammédia",
    "casa": "Casablanca", "casablanca anfa": "Casablanca", "taroudant": "Taroudannt",
}


def _cle(region: str) -> str:
    return re.sub(r"\s+", " ", _BRUIT.sub(" ", _nu(region))).strip()


def ville(region: str) -> str:
    """Le nom de ville retenu, ou "" pour une valeur vide ou illisible."""
    cle = _cle(region)
    if len(cle) < 3:
        return ""
    if cle in _ALIAS:
        return _ALIAS[cle]
    # Ni alias ni bruit: on garde l'écriture de l'avis, proprement capitalisée.
    propre = re.sub(r"[\s,]*\bMAROC\b[\s,.]*$", "", (region or "").strip(), flags=re.I)
    propre = re.sub(r"^(Province|Préfecture|Prefecture)\s+(d'|de\s+)?", "", propre, flags=re.I)
    return " ".join(m[:1].upper() + m[1:] if m.islower() else m for m in propre.split())


def slug(nom: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", _nu(nom))).strip("-")[:50]
