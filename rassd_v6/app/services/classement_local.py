# -*- coding: utf-8 -*-
"""Le classement par le sens, sans clé d'API.

Le 25/10/2026, 3 984 intitulés de la base (marchés, bons de commande,
résultats) ont été classés à la main, un par un, sur ce qui est acheté ou
exécuté. Ce module apprend de ces exemples: un classifieur bayésien naïf,
en Python pur, entraîné au démarrage en moins d'une seconde.

Mesure sur des intitulés que le modèle n'a pas vus (validation croisée en
cinq parts, mêmes 3 984 exemples):

- mots-clés (app/core/sectors.py) : 40 % de bons secteurs ;
- ce modèle, tous avis confondus : 62 % ; famille (travaux, fournitures,
  services) juste dans 85 % des cas ;
- ce modèle quand il est sûr de lui (confiance ≥ 0,7, soit 86 % des
  avis) : 69 %, contre 43 % aux mots-clés sur ces mêmes avis.

Sous 0,7 les mots-clés font aussi bien ou mieux: on les garde. Les erreurs
qui restent tombent presque toutes entre secteurs voisins — études BTP et
analyses de laboratoire, assainissement et eau potable, fournitures de
bureau et informatique.

Le modèle s'enrichit seul: les classements écrits à la main depuis
l'administration (`secteur_ia` = « manuel:… ») rejoignent les exemples au
prochain entraînement. Un avis classé ici porte `secteur_ia` = « local:… »:
le jour où une clé d'API revient, le modèle de langage le relit.
"""
import json
import logging
import math
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from app.core.config import cfg

logger = logging.getLogger("atlas.classement_local")

FICHIER = Path(__file__).resolve().parent.parent / "data" / "classement_manuel.json"
SEUIL = 0.7
LISSAGE = 0.3
# Le modèle est réentraîné au plus toutes les six heures, pour prendre les
# classements faits à la main entre-temps.
DUREE_MODELE = 6 * 3600

# Des mots qui reviennent dans tous les secteurs et ne disent pas ce qu'on
# achète.
_VIDES = set("""les des une pour aux par sur dans avec relatif relative relatifs lot unique
province commune region ville prefecture avis appel offre offres simplifie ouvert profit
compte achat acquisition fourniture travaux""".split())


def _mots(objet: str) -> list:
    from app.core.sectors import _objet_utile, _sans_accents
    utile = _sans_accents(_objet_utile(objet or "")).lower()
    mots = [m for m in re.findall(r"[a-z0-9]+", utile)
            if len(m) >= 3 and m not in _VIDES and not m.isdigit()]
    # Les mots de l'objet utile, leurs paires, les trois premiers (ce qui
    # est acheté vient d'abord) et, avec un préfixe, l'objet entier: le
    # bénéficiaire aide parfois (« hôpital » pour du matériel médical).
    tout = [m for m in re.findall(r"[a-z]+", _sans_accents(objet or "").lower())
            if len(m) >= 4 and m not in _VIDES]
    return (mots + [a + "_" + b for a, b in zip(mots, mots[1:])]
            + ["^" + m for m in mots[:3]] + ["~" + m for m in tout])


class Modele:
    def __init__(self, exemples: list):
        self.classes = Counter()
        self.mots = defaultdict(Counter)
        vocabulaire = set()
        for objet, code in exemples:
            jetons = set(_mots(objet))
            self.classes[code] += 1
            self.mots[code].update(jetons)
            vocabulaire |= jetons
        self.taille = len(vocabulaire)
        self.total = {c: sum(self.mots[c].values()) for c in self.classes}
        self.n = sum(self.classes.values())

    def predire(self, objet: str) -> tuple:
        """(code, confiance entre 0 et 1). ("", 0) si le modèle est vide."""
        if not self.n:
            return "", 0.0
        jetons = set(_mots(objet))
        scores = {}
        for code, nb in self.classes.items():
            s = math.log(nb / self.n)
            base = math.log(self.total[code] + LISSAGE * self.taille)
            compte = self.mots[code]
            for j in jetons:
                s += math.log(compte[j] + LISSAGE) - base
            scores[code] = s
        meilleur = max(scores, key=scores.get)
        haut = scores[meilleur]
        return meilleur, 1.0 / sum(math.exp(v - haut) for v in scores.values())


def exemples_fichier() -> list:
    try:
        donnees = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(o, c) for o, c in donnees.get("exemples", []) if c in cfg.SECTEURS]


def exemples_base() -> list:
    """Les classements écrits à la main en production (`manuel:…`)."""
    from app.core.database import get_db
    db = get_db()
    try:
        lignes = []
        for table in ("tenders", "tender_results"):
            lignes += db.execute(
                f"SELECT objet, secteur FROM {table} WHERE secteur_ia LIKE 'manuel:%'").fetchall()
    except Exception:
        return []
    finally:
        db.close()
    return [(l["objet"] or "", l["secteur"]) for l in lignes if l["secteur"] in cfg.SECTEURS]


def exemples() -> list:
    """Fichier puis base, un exemple par intitulé — la base a le dernier mot."""
    vus = {}
    for objet, code in exemples_fichier() + exemples_base():
        cle = " ".join((objet or "").lower().split())
        if cle:
            vus[cle] = (objet, code)
    return list(vus.values())


_verrou = threading.Lock()
_cache = {"modele": None, "quand": 0.0}


def modele() -> Modele:
    with _verrou:
        maintenant = datetime.now().timestamp()
        if _cache["modele"] is None or maintenant - _cache["quand"] > DUREE_MODELE:
            _cache["modele"] = Modele(exemples())
            _cache["quand"] = maintenant
        return _cache["modele"]


def oublier():
    """Force le réentraînement au prochain appel (après un import manuel)."""
    with _verrou:
        _cache["modele"] = None


def predire(objet: str) -> tuple:
    return modele().predire(objet)


def classer_liste(items: list) -> int:
    """Classe en place les avis que le modèle de langage n'a pas lus.

    Seuls les avis où le modèle est sûr de lui changent de secteur; les
    autres gardent leur classement par mots-clés.
    """
    marque = "local:" + datetime.now().isoformat(timespec="seconds")
    n = 0
    for i in items:
        if i.get("secteur_ia") or not i.get("objet"):
            continue
        code, confiance = predire(i["objet"])
        if code and confiance >= SEUIL:
            i["secteur"] = code
            i["secteur_ia"] = marque
            n += 1
    return n


def reclasser_base(limite: int = 0) -> dict:
    """Passe le modèle sur les avis jamais lus par le sens, et les écrit."""
    from app.core.database import get_db
    stats = {"lus": 0, "classes": 0, "changes": 0}
    marque = "local:" + datetime.now().isoformat(timespec="seconds")
    m = modele()
    db = get_db()
    try:
        for table, filtre in (("tenders", "statut='actif' AND "), ("tender_results", "")):
            lignes = db.execute(
                f"SELECT id, objet, secteur FROM {table} "
                f"WHERE {filtre}COALESCE(secteur_ia,'')='' ORDER BY scraped_at DESC"
                + (f" LIMIT {int(limite)}" if limite else "")).fetchall()
            for l in lignes:
                stats["lus"] += 1
                code, confiance = m.predire(l["objet"] or "")
                if not code or confiance < SEUIL:
                    continue
                stats["classes"] += 1
                stats["changes"] += code != l["secteur"]
                db.execute(f"UPDATE {table} SET secteur=?, secteur_ia=? WHERE id=?",
                           (code, marque, l["id"]))
        db.commit()
    finally:
        db.close()
    logger.info(f"[classement_local] {stats['classes']} classés sur {stats['lus']} lus, "
                f"{stats['changes']} changés")
    return stats
