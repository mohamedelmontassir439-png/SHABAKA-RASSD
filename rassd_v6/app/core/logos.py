# -*- coding: utf-8 -*-
"""L'emblème de l'acheteur, posé devant son nom dans les listes de marchés.

On reconnaît un acheteur à son emblème avant de lire son nom. Trois cas:

- une administration, une collectivité ou un établissement public sans
  sigle connu: les armoiries du Royaume (domaine public, Wikimedia Commons);
- un établissement ou une entreprise publique connue par son sigle (ONEE,
  OFPPT, CNSS…): une pastille portant ce sigle;
- un acheteur privé: une pastille à ses initiales.

On ne reproduit pas les logos déposés des organismes: ce sont des marques,
et une pastille au sigle se lit aussi vite.
"""
import re
import zlib
from html import escape

from markupsafe import Markup

from app.core.acheteurs import lisible
from app.core.organismes import ETAT, PARA, _MOTIFS_SIGLES, _nu, categorie

ARMOIRIES = "/static/img/logos/armoiries.webp"

# Mots qui ne donnent pas d'initiale: « Société Rabat Région » → SRR, pas SRRDL.
_VIDES = {"de", "du", "des", "la", "le", "les", "l", "d", "et", "a", "au", "aux",
          "pour", "en", "sur", "sa", "sarl", "s"}

# Un sigle déclaré entre parenthèses: « Société Royale … (SOREC) ».
_ENTRE_PARENTHESES = re.compile(r"\(\s*([A-Za-z]{2,6})\s*\)")


def _initiales(nom: str) -> str:
    mots = [m for m in re.split(r"[^a-z0-9]+", _nu(nom)) if m and m not in _VIDES]
    return "".join(m[0] for m in mots[:3]).upper() or "?"


# Les grands établissements publics écrits en toutes lettres par la source.
_NOMS_LONGS = [
    ("office national de l electricite", "ONEE"), ("office national des aeroports", "ONDA"),
    ("office national des chemins de fer", "ONCF"), ("autoroutes du maroc", "ADM"),
    ("caisse nationale de securite sociale", "CNSS"), ("office de la formation professionnelle", "OFPPT"),
    ("office cherifien des phosphates", "OCP"), ("royal air maroc", "RAM"),
    ("societe nationale de radiodiffusion", "SNRT"), ("agence marocaine du medicament", "AMMPS"),
    ("office national de securite sanitaire", "ONSSA"), ("barid al maghrib", "BAM"),
    ("agence nationale des ports", "ANP"), ("office national des hydrocarbures", "ONHYM"),
]


def _sigle(brut: str) -> str:
    trouve = _ENTRE_PARENTHESES.search(brut)
    if trouve:
        return trouve.group(1).upper()
    n = _nu(brut).replace("'", " ").replace("-", " ")
    n = re.sub(r"\s+", " ", n)
    for expression, sigle in _NOMS_LONGS:
        if expression in n:
            return sigle
    m = _MOTIFS_SIGLES.search(n)
    if m:
        return m.group(1).upper()
    seul = brut.strip()
    if re.fullmatch(r"[A-Za-z]{2,5}", seul) and seul.isupper():
        return seul
    return ""


def embleme(acheteur: str, type_offre: str = "") -> dict:
    """{"img": url} ou {"sigle": "ONEE", "teinte": 0-359}."""
    brut = acheteur or ""
    if not brut.strip():
        return {"img": ARMOIRIES}
    sigle = _sigle(brut)
    if not sigle:
        if categorie(brut, type_offre) in (ETAT, PARA):
            return {"img": ARMOIRIES}
        sigle = _initiales(lisible(brut) or brut)
    return {"sigle": sigle[:5], "teinte": zlib.crc32(sigle.encode()) % 360}


def logo_html(acheteur: str, type_offre: str = "", taille: str = "") -> Markup:
    """La vignette prête à poser; le style `.org-logo` vit dans les coquilles."""
    e = embleme(acheteur, type_offre)
    cls = "org-logo" + (f" org-logo-{taille}" if taille else "")
    if "img" in e:
        return Markup(f'<span class="{cls}" aria-hidden="true"><img src="{e["img"]}" alt="" '
                      f'width="24" height="25" loading="lazy" decoding="async"></span>')
    long = " org-logo-long" if len(e["sigle"]) > 3 else ""
    return Markup(f'<span class="{cls} org-logo-sigle{long}" style="--teinte:{e["teinte"]}" '
                  f'aria-hidden="true">{escape(e["sigle"])}</span>')
