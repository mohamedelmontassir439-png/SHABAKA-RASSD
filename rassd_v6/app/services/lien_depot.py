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

3. **par l'acheteur.** Une entité dépose presque toujours sur la même
   plateforme: Madaëf sur safakat.cdg.ma, la CGI ou l'Institut Pasteur sur
   le portail national. Chaque lien lu dans un dossier enrichit un registre
   acheteur → plateforme; un avis du même acheteur dont le dossier ne dit
   rien reçoit ce lien, avec l'extrait du dossier précédent qui le prouve.

Ce qui est trouvé est dit avec sa provenance: « confirmé par la référence
sur le portail », « lu dans le dossier » ou « plateforme indiquée par cet
acheteur dans ses consultations précédentes ». Rien n'est deviné.
"""
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlparse

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


# ─── 3. Par l'acheteur ────────────────────────────────────────────────────

_SANS_SENS = {"societe", "ste", "sa", "sarl", "la", "le", "les", "de", "du", "des", "et", "d", "l",
              "s", "a", "au", "aux"}
# Une plateforme n'est attribuée à un acheteur que si elle est la sienne dans
# au moins deux dossiers sur trois.
PART_MIN = 2 / 3


def cle_acheteur(nom: str) -> str:
    nu = _nu(nom)
    nu = re.sub(r"^autres organismes particuliers\s*/\s*", "", nu)
    nu = re.sub(r"\([^)]*\)", " ", nu)
    return " ".join(m for m in re.findall(r"[a-z0-9]+", nu) if m not in _SANS_SENS)


def hote(url: str) -> str:
    h = urlparse(url if "://" in url else "https://" + url).hostname or ""
    return h[4:] if h.startswith("www.") else h


def cle_parent(nom: str) -> str:
    """« Marsa Maroc / Direction de l'exploitation au port de Nador » → Marsa Maroc."""
    nu = re.sub(r"^autres organismes particuliers\s*/\s*", "", _nu(nom))
    return cle_acheteur(nu.split("/")[0]) if "/" in nu else ""


def _hotes_tronques(hotes: Counter) -> dict:
    """Une adresse coupée à la lecture du PDF (« chats.marsamaroc.co.ma ») est
    rendue à sa forme entière (« achats.marsamaroc.co.ma ») quand celle-ci
    est vue au moins aussi souvent."""
    return {h: max((g for g in hotes if g != h and g.endswith(h) and hotes[g] >= hotes[h]),
                   key=lambda g: hotes[g])
            for h in hotes
            if any(g != h and g.endswith(h) and hotes[g] >= hotes[h] for g in hotes)}


def registre() -> dict:
    """{clé acheteur: {nom, hote, url, vus, total, extrait}} appris des dossiers lus.

    Une direction hérite de la plateforme de sa société (« Marsa Maroc /
    … ») sous la clé de celle-ci.
    """
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT acheteur, lien_depot, lien_depot_extrait FROM tenders
               WHERE lien_depot_origine='dossier' AND COALESCE(lien_depot,'')!=''
               ORDER BY scraped_at DESC""").fetchall()]
    finally:
        db.close()
    corrige = _hotes_tronques(Counter(hote(l["lien_depot"]) for l in lignes))
    par = defaultdict(list)
    for l in lignes:
        h = hote(l["lien_depot"])
        if not h:
            continue
        l["hote"] = corrige.get(h, h)
        for cle in {cle_acheteur(l["acheteur"] or ""), cle_parent(l["acheteur"] or "")} - {""}:
            par[cle].append(l)
    reg = {}
    for cle, vus in par.items():
        compte = Counter(l["hote"] for l in vus)
        h, n = compte.most_common(1)[0]
        if n / len(vus) < PART_MIN:
            continue
        exemple = next(l for l in vus if l["hote"] == h)
        nom = exemple["acheteur"] or ""
        societe = cle != cle_acheteur(nom)
        if societe:
            nom = re.sub(r"(?i)^autres organismes particuliers\s*/\s*", "", nom).split("/")[0].strip()
        reg[cle] = {"nom": nom, "hote": h, "url": "https://" + h, "societe": societe,
                    "vus": n, "total": len(vus), "extrait": exemple["lien_depot_extrait"] or ""}
    return reg


def par_acheteur(t: dict, reg: dict):
    nom = t.get("acheteur") or ""
    return reg.get(cle_acheteur(nom)) or (reg.get(cle_parent(nom)) if cle_parent(nom) else None)


def completer_par_acheteur(reg: dict = None) -> int:
    """Donne la plateforme de l'acheteur aux avis cherchés sans succès."""
    reg = registre() if reg is None else reg
    if not reg:
        return 0
    db = get_db()
    try:
        avis = [dict(r) for r in db.execute(
            """SELECT id, acheteur FROM tenders
               WHERE source='global-marches' AND statut='actif' AND COALESCE(lien_depot,'')=''
                 AND COALESCE(lien_depot_cherche,'')!='' AND description LIKE '%dépôt électronique%'
            """).fetchall()]
        # Les liens coupés à la lecture d'un dossier retrouvent leur forme entière.
        lus = db.execute("""SELECT id, lien_depot FROM tenders
                            WHERE lien_depot_origine='dossier' AND COALESCE(lien_depot,'')!=''""").fetchall()
        corrige = _hotes_tronques(Counter(hote(l["lien_depot"]) for l in lus))
        for l in lus:
            h = hote(l["lien_depot"])
            if h in corrige:
                db.execute("UPDATE tenders SET lien_depot=? WHERE id=?",
                           (l["lien_depot"].replace(h, corrige[h], 1), l["id"]))
        n = 0
        for t in avis:
            r = par_acheteur(t, reg)
            if r:
                db.execute("""UPDATE tenders SET lien_depot=?, lien_depot_origine='acheteur',
                                 lien_depot_extrait=? WHERE id=?""",
                           (r["url"], r["extrait"][:300], t["id"]))
                n += 1
        db.commit()
    finally:
        db.close()
    return n


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
        return {"lus": 0, "portail": 0, "dossier": 0, "acheteur": completer_par_acheteur()}
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
    # Ce que les dossiers n'ont pas dit, l'acheteur l'a peut-être dit ailleurs.
    bilan["acheteur"] = completer_par_acheteur()
    logger.info(f"[lien_depot] {bilan}")
    return bilan
