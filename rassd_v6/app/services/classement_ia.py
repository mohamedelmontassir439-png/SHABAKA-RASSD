# -*- coding: utf-8 -*-
"""Le classement des marchés par leur sens, et non par leurs mots.

Le classement par mots-clés (app/core/sectors.py) se trompait sur quatre
avis sur dix — audit manuel de 90 avis, bons de commande et résultats le
24/10/2026. La raison est toujours la même: un mot gagne même quand il ne
dit pas ce qu'on achète. « Nettoyage des bâtiments de l'Institut de
Formation » partait en Formation; « Renouvellement du système de
climatisation de la Fondation » en Fondations spéciales; « Études et suivi
des travaux de construction » en Constructions; « Billet d'avion » en
location de véhicules.

Un modèle de langage lit l'intitulé comme un acheteur: il cherche **ce qui
est acheté ou exécuté**, et ignore le bénéficiaire, le lieu et l'acheteur.
On lui donne les 83 secteurs officiels et il ne peut répondre que par l'un
d'eux (schéma JSON à énumération fermée). Les avis passent par lots de
vingt-cinq: une requête, vingt-cinq classements.

Sans clé d'API, ou si l'appel échoue, rien ne casse: le modèle interne
appris des classements faits à la main prend le relais
(app/services/classement_local.py), à défaut le classement par mots-clés,
et le marché sera repris au passage suivant.
"""
import json
import logging
import os
from datetime import datetime

from app.core.config import cfg

logger = logging.getLogger("atlas.classement_ia")

MODELE = "claude-opus-5-5"
LOT = 25
# Un intitulé suffit le plus souvent; le début de l'avis lève les doutes
# (« lot n°2 : traitement des façades » ne dit pas de quoi il s'agit seul).
CONTEXTE_MAX = 400


def disponible() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _consignes() -> str:
    lignes = []
    for groupe, secteurs in cfg.SECTOR_GROUPS.items():
        lignes.append(f"\n{groupe.split(' ', 1)[-1]}")
        for code, label in secteurs.items():
            lignes.append(f"{code} — {label}")
    referentiel = "\n".join(lignes)
    return f"""Tu classes des avis de marchés publics, semi-publics et privés marocains, des bons de commande et des résultats d'attribution dans le référentiel officiel des secteurs ci-dessous.

Règle principale : classe selon CE QUI EST ACHETÉ OU EXÉCUTÉ — la nature de la prestation — jamais selon le bénéficiaire, l'acheteur, le lieu ou le bâtiment concerné.
- « Nettoyage des locaux de l'Institut de Formation » → un service de nettoyage, pas la formation.
- « Acquisition de matériel informatique pour une école » → du matériel informatique, pas l'enseignement.
- « Travaux de construction d'un lycée » → construction de bâtiments.
- « Climatisation des salles de la Fondation X » → climatisation ; le mot « Fondation » est un nom propre.
- « Étude, suivi, contrôle ou assistance technique de travaux » → les études (études BTP, études générales ou TIC selon le domaine), pas les travaux eux-mêmes.
- « Entretien, maintenance, réparation de X » → maintenance, sauf si un secteur plus précis décrit exactement la prestation.
- « Location de X » → la location correspondante ; un billet d'avion ou un séjour → les services de voyage ou d'événementiel les plus proches.
- « Fourniture, livraison et installation de X » → le secteur du bien X.
- Un lot ou un intitulé vague : lis le contexte de l'avis fourni.
- « Prestations diverses » (S904) seulement quand aucun autre secteur ne convient vraiment.

Réponds uniquement par le JSON demandé, un classement par avis, avec l'identifiant reçu.

Référentiel des secteurs :{referentiel}
"""


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "classements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "secteur": {"type": "string", "enum": sorted(cfg.SECTEURS)},
                    },
                    "required": ["id", "secteur"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classements"],
        "additionalProperties": False,
    }


def _texte_avis(item: dict) -> str:
    parties = [f"[{item['id']}] {(item.get('objet') or '').strip()[:400]}"]
    if item.get("nature"):
        parties.append(f"  nature : {item['nature'][:120]}")
    desc = (item.get("description") or "").strip()
    if desc and desc[:80] != (item.get("objet") or "")[:80]:
        parties.append(f"  contexte : {desc[:CONTEXTE_MAX]}")
    return "\n".join(parties)


def _client():
    import anthropic
    return anthropic.Anthropic()


def classer_lot(items: list, client=None) -> dict:
    """{id: code} pour un lot d'avis. {} si l'appel échoue — jamais d'exception."""
    if not items or (client is None and not disponible()):
        return {}
    import anthropic
    client = client or _client()
    try:
        reponse = client.beta.messages.create(
            model=MODELE,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": _consignes(), "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _schema()}},
            messages=[{"role": "user", "content": "Classe ces avis :\n\n" +
                       "\n\n".join(_texte_avis(i) for i in items)}],
        )
    except anthropic.APIStatusError as e:
        logger.warning(f"[classement_ia] API {e.status_code}: {e.message}")
        return {}
    except anthropic.APIConnectionError as e:
        logger.warning(f"[classement_ia] connexion: {e}")
        return {}
    if reponse.stop_reason in ("refusal", "max_tokens"):
        logger.warning(f"[classement_ia] arrêt: {reponse.stop_reason}")
        return {}
    texte = next((b.text for b in reponse.content if b.type == "text"), "")
    try:
        donnees = json.loads(texte)
    except ValueError:
        return {}
    attendus = {i["id"] for i in items}
    return {c["id"]: c["secteur"] for c in donnees.get("classements", [])
            if c.get("id") in attendus and c.get("secteur") in cfg.SECTEURS}


def classer_liste(items: list, client=None) -> int:
    """Classe en place une liste d'avis à enregistrer. Rend le nombre classé.

    Chaque avis classé reçoit `secteur` (le code) et `secteur_ia` (l'heure):
    l'enregistrement les écrit, et le marché ne sera pas repris.
    """
    if not items:
        return 0
    n = 0
    if client is not None or disponible():
        maintenant = datetime.now().isoformat(timespec="seconds")
        for debut in range(0, len(items), LOT):
            lot = [i for i in items[debut:debut + LOT] if i.get("id") and i.get("objet")]
            codes = classer_lot(lot, client)
            for i in lot:
                if i["id"] in codes:
                    i["secteur"] = codes[i["id"]]
                    i["secteur_ia"] = maintenant
                    n += 1
    # Sans clé, ou pour ce que l'API n'a pas rendu: le modèle appris des
    # classements faits à la main (app/services/classement_local.py).
    try:
        from app.services import classement_local
        n += classement_local.classer_liste(items)
    except Exception as e:
        logger.warning(f"[classement_local] {e}")
    return n


# ─── Reprise de la base existante ────────────────────────────────────────

class ReclassementState:
    running = False
    total = faits = changes = 0
    started = finished = arret = ""
    exemples: list = []

    @classmethod
    def etat(cls) -> dict:
        return {k: getattr(cls, k) for k in ("running", "total", "faits", "changes",
                                              "started", "finished", "arret")} \
            | {"exemples": cls.exemples[-30:]}


def a_reprendre(limite: int = 0) -> list:
    """(table, ligne) des avis jamais lus par le modèle de langage: marchés ouverts
    et résultats. Ceux du modèle interne (« local:… ») en font partie."""
    from app.core.database import get_db
    db = get_db()
    try:
        tenders = [("tenders", dict(r)) for r in db.execute(
            """SELECT id, objet, nature, description, secteur FROM tenders
               WHERE statut='actif' AND (COALESCE(secteur_ia,'')='' OR secteur_ia LIKE 'local:%')
               ORDER BY scraped_at DESC""").fetchall()]
        resultats = [("tender_results", dict(r)) for r in db.execute(
            """SELECT id, objet, '' AS nature, '' AS description, secteur FROM tender_results
               WHERE COALESCE(secteur_ia,'')='' OR secteur_ia LIKE 'local:%'
               ORDER BY scraped_at DESC""").fetchall()]
    finally:
        db.close()
    tout = tenders + resultats
    return tout[:limite] if limite else tout


def reclasser(limite: int = 0, client=None):
    """Reprend les avis existants, par lots, et écrit le nouveau secteur."""
    from app.core.database import get_db
    from app.core.sectors import get_label
    S = ReclassementState
    S.running, S.faits, S.changes, S.arret, S.exemples = True, 0, 0, "", []
    S.started, S.finished = datetime.now().isoformat(timespec="seconds"), ""
    try:
        liste = a_reprendre(limite)
        S.total = len(liste)
        echecs_de_suite = 0
        for debut in range(0, len(liste), LOT):
            lot = liste[debut:debut + LOT]
            items = [l for _, l in lot]
            codes = classer_lot(items, client)
            if not codes:
                echecs_de_suite += 1
                if echecs_de_suite >= 3:
                    S.arret = "trois lots de suite sans réponse : clé, quota ou panne de l'API"
                    break
                continue
            echecs_de_suite = 0
            maintenant = datetime.now().isoformat(timespec="seconds")
            db = get_db()
            try:
                for table, l in lot:
                    code = codes.get(l["id"])
                    if not code:
                        continue
                    if code != l["secteur"]:
                        S.changes += 1
                        S.exemples.append({"objet": (l["objet"] or "")[:110],
                                           "avant": get_label(l["secteur"]) or l["secteur"],
                                           "apres": get_label(code)})
                    db.execute(f"UPDATE {table} SET secteur=?, secteur_ia=? WHERE id=?",
                               (code, maintenant, l["id"]))
                    S.faits += 1
                db.commit()
            finally:
                db.close()
        logger.info(f"[classement_ia] {S.faits} reclassés, {S.changes} changés"
                    + (f" — arrêt: {S.arret}" if S.arret else ""))
    except Exception as e:
        S.arret = f"erreur: {e}"
        logger.exception("[classement_ia] reprise interrompue")
    finally:
        S.running = False
        S.finished = datetime.now().isoformat(timespec="seconds")
