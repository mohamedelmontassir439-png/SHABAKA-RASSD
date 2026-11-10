"""« Puis-je répondre à ce marché ? » — la réponse en tête de fiche.

La fiche contient déjà tout (qualification, dossier administratif, caution,
dates), mais réparti sur une page très longue: le membre devait tout lire
pour savoir s'il pouvait y aller. Ici, les mêmes vérifications sont réunies
en un verdict, quatre points et les prochaines dates, sans rien calculer de
neuf: chaque point reprend un service existant (eligibilite, coffre, suivi).
"""
import re

# Points: (cle, etat) où etat vaut ok | attention | bloquant | info.
ETATS = ("ok", "info", "attention", "bloquant")


def _qualification(elig: dict, lang: str = "fr") -> dict:
    etat = (elig or {}).get("etat", "libre")
    lignes = (elig or {}).get("lignes") or []
    if etat == "libre":
        return {"cle": "qualif", "etat": "ok", "msg": "syn_qualif_libre", "args": {}}
    cl = "الصنف" if lang == "ar" else "cl."
    exigee = ", ".join(f"{l['code']} {cl} {l['classe']}" for l in lignes)
    if etat == "eligible":
        return {"cle": "qualif", "etat": "ok", "msg": "syn_qualif_ok", "args": {"exigee": exigee}}
    if etat == "inconnu":
        return {"cle": "qualif", "etat": "attention", "msg": "syn_qualif_inconnu",
                "args": {"exigee": exigee}, "lien": "/coffre#qualifs"}
    return {"cle": "qualif", "etat": "bloquant", "msg": "syn_qualif_non",
            "args": {"exigee": exigee}, "lien": "/groupements"}


def _dossier(pieces: list) -> dict:
    if not pieces:
        return None
    pretes = sum(1 for p in pieces if p["etat"] == "ok")
    total = len(pieces)
    if pretes == total:
        return {"cle": "dossier", "etat": "ok", "msg": "syn_dossier_ok", "args": {"n": total}}
    return {"cle": "dossier", "etat": "attention", "msg": "syn_dossier_manque",
            "args": {"n": pretes, "total": total, "reste": total - pretes}, "lien": "/coffre"}


def _caution(texte: str, echeances: list) -> dict:
    texte = (texte or "").strip()
    if not texte or texte == "par_lot":
        return None
    if texte == "aucune" or not re.search(r"[1-9]", texte):
        return {"cle": "caution", "etat": "ok", "msg": "syn_caution_aucune", "args": {}}
    avant = next((e for e in echeances if e["cle"] == "caution"), None)
    if avant and avant["reste"] >= 0:
        return {"cle": "caution", "etat": "info", "msg": "syn_caution_avant",
                "args": {"montant": texte, "jour": avant["jour"].strftime("%d/%m/%Y")},
                "lien": "/financement"}
    return {"cle": "caution", "etat": "attention", "msg": "syn_caution_vite",
            "args": {"montant": texte}, "lien": "/financement"}


def _delai(echeances: list) -> dict:
    depot = next((e for e in echeances if e["cle"] == "depot"), None)
    if not depot:
        return None
    r = depot["reste"]
    if r < 0:
        return {"cle": "delai", "etat": "bloquant", "msg": "syn_delai_clos", "args": {}}
    if r <= 3:
        return {"cle": "delai", "etat": "attention", "msg": "syn_delai_serre", "args": {"n": r}}
    if r <= 7:
        return {"cle": "delai", "etat": "info", "msg": "syn_delai_court", "args": {"n": r}}
    return {"cle": "delai", "etat": "ok", "msg": "syn_delai_ok", "args": {"n": r}}


def pour_marche(elig: dict, pieces: list, echeances: list, caution: str = "", lang: str = "fr") -> dict:
    """{"verdict": go | a_regler | non | clos, "points": [...], "dates": [...]}"""
    echeances = echeances or []
    points = [p for p in (_qualification(elig, lang), _dossier(pieces),
                          _caution(caution, echeances), _delai(echeances)) if p]
    etats = {p["etat"] for p in points}
    if any(p["cle"] == "delai" and p["etat"] == "bloquant" for p in points):
        verdict = "clos"
    else:
        verdict = "non" if "bloquant" in etats else ("a_regler" if "attention" in etats else "go")
    a_venir = [e for e in echeances if e["reste"] >= 0]
    return {"verdict": verdict, "points": points, "dates": a_venir,
            "a_regler": sum(1 for p in points if p["etat"] == "attention")}
