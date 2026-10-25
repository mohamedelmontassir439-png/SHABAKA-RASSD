# -*- coding: utf-8 -*-
"""Où déposer l'offre: le lien exact, trouvé sans intelligence artificielle.

La source privée dit « Soumission électronique : Oui » sans dire où (relevé
du 25/10/2026: aucun lien sur 24 fiches). Deux recherches le retrouvent:

1. **par la référence, sur le portail national.** La même consultation y
   figure souvent, déjà collectée par app/services/ao_scraper.py, avec sa
   page officielle. On la reconnaît à la référence ET à la date limite (ou
   à la date d'avant un report officiel) — « 01/2026 » seul désigne des
   dizaines de consultations — et, s'il en reste plusieurs, à l'acheteur.
2. **dans le dossier (DAO).** Le règlement de consultation dit où se fait
   la remise des offres. On lit le texte du dossier (app/services/
   analyse_dossier.py) et on retient les adresses web écrites près de
   « dépôt », « soumission », « remise des offres » ou « plateforme ».

Ce qui est trouvé est dit avec sa provenance: « confirmé par la référence
sur le portail » ou « lu dans le dossier ». Rien n'est deviné.
"""
import logging
import re
import unicodedata
from datetime import datetime

from app.core.conditions import conditions_avis
from app.core.database import get_db

logger = logging.getLogger("atlas.lien_depot")

PORTAIL = "marchespublics.gov.ma"


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def _ref(texte: str) -> str:
    return re.sub(r"[^0-9a-z]", "", _nu(texte))


def _mots(texte: str) -> set:
    return {m for m in re.findall(r"[a-z]{4,}", _nu(texte))
            if m not in {"region", "province", "commune", "prefecture", "royaume", "maroc",
                         "direction", "provinciale", "regionale", "societe", "autres"}}


# ─── 1. Par la référence, sur le portail ─────────────────────────────────

def index_portail() -> dict:
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT id, url, acheteur, date_limite, COALESCE(date_limite_initiale,'') AS initiale,
                      description FROM tenders WHERE source='marchespublics'""").fetchall()]
    finally:
        db.close()
    index = {}
    for l in lignes:
        ref = conditions_avis(l["description"] or "").get("reference", "")
        if ref and len(_ref(ref)) >= 4:
            index.setdefault(_ref(ref), []).append(l)
    return index


def par_reference(t: dict, index: dict):
    ref = conditions_avis(t.get("description") or "").get("reference", "")
    candidats = index.get(_ref(ref), []) if ref else []
    jour = (t.get("date_limite") or "")[:10]
    memes = [c for c in candidats if jour and jour in ((c["date_limite"] or "")[:10], c["initiale"][:10])]
    if len(memes) > 1:
        mots = _mots(t.get("acheteur") or "")
        memes.sort(key=lambda c: -len(mots & _mots(c["acheteur"] or "")))
        if mots and not (mots & _mots(memes[0]["acheteur"] or "")):
            return None
    return memes[0] if memes else None


# ─── 2. Dans le dossier ───────────────────────────────────────────────────

_URL = re.compile(r"\b(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:ma|com|org|net|gov\.ma)"
                  r"(?:/[^\s,;)»\"']*)?", re.I)
_PRES_DE = re.compile(r"d[ée]p[ôo]t|soumission|remise des offres|remis[e]? par voie|plateforme|portail"
                      r"|voie [ée]lectronique|e-?procurement|en ligne", re.I)


_DEPOT = re.compile(r"d[ée]p[ôo]t|remise des (?:offres|plis)|soumission|soumissionn", re.I)


def dans_le_dossier(texte: str) -> list:
    """Les adresses web citées près des mots du dépôt, la plus pertinente d'abord."""
    vues, trouvees = set(), []
    for m in _URL.finditer(texte or ""):
        url = m.group(0).rstrip("./")
        bas = url.lower()
        if "@" in texte[max(0, m.start() - 1):m.start()] or bas in vues:
            continue
        contexte = texte[max(0, m.start() - 220):m.end() + 120]
        if not _PRES_DE.search(contexte):
            continue
        vues.add(bas)
        # Une adresse citée pour la remise des offres vaut mieux qu'une
        # adresse citée pour télécharger le dossier.
        # Le mot doit précéder l'adresse de près: « téléchargeable sur X. La
        # remise des offres se fait sur Y » — c'est Y qui reçoit les offres.
        avant = texte[max(0, m.start() - 150):m.start()]
        depot = bool(_DEPOT.search(avant)) and not re.search(
            r"t[ée]l[ée]charg\w*\s+(?:\S+\s+){0,6}$", avant, re.I)
        trouvees.append({"url": url, "portail": PORTAIL in bas, "depot": depot,
                         "extrait": re.sub(r"\s+", " ", contexte).strip()[:300]})
    trouvees.sort(key=lambda x: (not x["depot"], not x["portail"]))
    return trouvees[:3]


# ─── La passe ────────────────────────────────────────────────────────────

def rapprocher(limite: int = 40, lire_dao: bool = True, recuperer=None) -> dict:
    """Cherche le lien de dépôt des avis électroniques de la source privée."""
    db = get_db()
    try:
        avis = [dict(r) for r in db.execute(
            """SELECT id, objet, acheteur, date_limite, description, dao_url FROM tenders
               WHERE source='global-marches' AND statut='actif'
                 AND fiche_lue LIKE 'v2:%' AND COALESCE(lien_depot_cherche,'')=''
                 AND description LIKE '%dépôt électronique%'
               ORDER BY scraped_at DESC LIMIT ?""", (limite,)).fetchall()]
    finally:
        db.close()
    if not avis:
        return {"lus": 0, "portail": 0, "dossier": 0}
    index = index_portail()
    if recuperer is None and lire_dao:
        from app.services.pieces import recuperer
    from app.services.analyse_dossier import extraire_texte
    bilan = {"lus": 0, "portail": 0, "dossier": 0}
    for t in avis:
        lien, origine, extrait = "", "", ""
        trouve = par_reference(t, index)
        if trouve and trouve.get("url"):
            lien, origine = trouve["url"], "portail_reference"
            bilan["portail"] += 1
        elif lire_dao and t.get("dao_url"):
            try:
                contenu, _, ext = recuperer(t["dao_url"])
                texte, _ = extraire_texte(contenu, f"dao.{ext or 'zip'}") if contenu else ("", [])
                liens = dans_le_dossier(texte)
                if liens:
                    lien, origine, extrait = liens[0]["url"], "dossier", liens[0]["extrait"]
                    if not lien.startswith("http"):
                        lien = "https://" + lien
                    bilan["dossier"] += 1
            except Exception as e:
                logger.warning(f"[lien_depot] DAO {t['id']}: {e}")
        db = get_db()
        try:
            db.execute("""UPDATE tenders SET lien_depot=?, lien_depot_origine=?, lien_depot_extrait=?,
                             lien_depot_cherche=? WHERE id=?""",
                       (lien[:400], origine, extrait[:300],
                        datetime.now().isoformat(timespec="seconds"), t["id"]))
            db.commit()
        finally:
            db.close()
        bilan["lus"] += 1
    logger.info(f"[lien_depot] {bilan}")
    return bilan
