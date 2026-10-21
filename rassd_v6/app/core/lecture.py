# -*- coding: utf-8 -*-
"""Les chiffres réels de l'encadré « Comprendre cet avis ».

L'encadré expliquait les règles en général — « prévoyez la caution
provisoire, son montant figure dans l'avis ». Le fondateur a demandé le
20/10/2026 qu'il donne les chiffres de ce marché-ci: la caution, l'heure
limite, la qualification, l'adresse du dossier, les articles d'un bon de
commande.

Ce que chaque source publie n'est pas le même, et l'encadré ne comble pas
les trous:

- **portail national (ao_)**: les champs de l'avis (app/core/conditions.py);
- **bons de commande (bdc_)**: l'heure limite de réception des devis, les
  articles avec unité et quantité, les garanties exigées, les pièces
  jointes — mesuré sur 679 bons actifs: heure 100 %, articles 97 %;
- **agrégateur privé (gm_)**: l'intitulé, l'acheteur, l'estimation et le
  jour limite, rien d'autre.

Une valeur absente est dite absente (`None`), jamais estimée: une caution
« d'environ 1,5 % » inventée ferait déposer un dossier faux.
"""
import re
from datetime import date, datetime

from app.core.conditions import conditions_avis

# Valeurs que les acheteurs écrivent pour « rien ».
_VIDE = {"", "-", "--", "/", "néant", "neant", "aucune", "aucun", "nan", "0"}


def _propre(v: str) -> str:
    v = re.sub(r"\s+", " ", v or "").strip(" .;:-–—/")
    return "" if v.lower() in _VIDE else v


def _jour_heure(texte: str):
    m = re.search(r"(\d{2}/\d{2}/\d{4})(?:\s+(?:à\s+)?(\d{2}:\d{2}))?", texte or "")
    return (m.group(1), m.group(2) or "") if m else ("", "")


def _jours_restants(jour: str):
    try:
        return (datetime.strptime(jour, "%d/%m/%Y").date() - date.today()).days
    except ValueError:
        return None


def _nul(montant: str) -> bool:
    return not re.search(r"[1-9]", montant or "")


# ─── Bons de commande ────────────────────────────────────────────────────

_ARTICLE = re.compile(
    r"#(\d{1,3})\s+(.+?)\s+Caractéristiques et spécifications\s+(.*?)\s*"
    r"Unité de mesure\s+(.+?)\s+Quantité\s+([\d\s.,]+?)\s+TVA", re.S)


def articles_bdc(texte: str) -> list:
    """Les lignes d'un avis d'achat: désignation, spécification, unité, quantité."""
    lignes = []
    for m in _ARTICLE.finditer(re.sub(r"\s+", " ", texte or "")):
        lignes.append({"n": int(m.group(1)), "designation": _propre(m.group(2))[:90],
                       "specification": _propre(m.group(3))[:140],
                       "unite": _propre(m.group(4))[:30],
                       "quantite": m.group(5).strip()})
    return lignes


def _garanties(texte: str) -> list:
    vues = []
    for g in re.findall(r"Garanties exigées\s+(.*?)(?=\s+--|\s+#\d|\s+Copyright|$)",
                        re.sub(r"\s+", " ", texte or "")):
        g = _propre(g)
        if g and g not in vues:
            vues.append(g[:120])
    return vues


def _pieces(texte: str) -> list:
    m = re.search(r"Pièces jointes\s+(.*?)\s+Articles\b", re.sub(r"\s+", " ", texte or ""))
    if not m:
        return []
    return [p for p in re.findall(r"[^\s][^.]*?\.(?:zip|pdf|rar|docx?|xlsx?)", m.group(1), re.I)][:4]


# ─── Qualifications ──────────────────────────────────────────────────────

def qualifications_lisibles(texte: str) -> list:
    """« Equipement / B- Travaux routiers / B.1- Terrassements / Classe 2 … »
    -> ["B.1 Terrassements — classe 2", …].

    Le portail enchaîne ministère, secteur, qualification et classe, puis
    recommence pour la suivante: le texte brut se lit mal à partir de deux.
    """
    t = re.sub(r"\s+", " ", texte or "").strip()
    if not t:
        return []
    # Chaque exigence finit par « / Classe X »; ce qui précède, jusqu'au
    # dernier « / », est la qualification elle-même. Le ministère et le
    # secteur qui la précèdent ne font que la situer.
    morceaux = re.split(r"\s*/\s*Classe\s*(\w+)\s*", t)
    lignes = []
    for segment, classe in zip(morceaux[0::2], morceaux[1::2]):
        libelle = segment.split("/")[-1].strip()
        libelle = re.sub(r"^([A-Z]{1,2}\.\d+(?:\.\d+)?|\d+(?:\.\d+)+)\s*[-.]?\s*", r"\1 ", libelle)
        ligne = f"{libelle.strip()} — classe {classe}"
        if libelle and ligne not in lignes:
            lignes.append(ligne)
    return lignes or [t[:220]]


# ─── L'encadré ────────────────────────────────────────────────────────────

def chiffres(t) -> dict:
    """Les valeurs réelles à placer dans l'encadré, par point. None = non publié."""
    t = dict(t) if t else {}
    desc = t.get("description") or ""
    tid = t.get("id") or ""
    bdc = t.get("type_procedure") == "bon_commande"
    out = {"source": "bdc" if bdc else ("portail" if tid.startswith("ao_") else "autre")}

    # La date limite: l'heure quand la source la donne.
    jour, heure = _jour_heure(t.get("date_limite") or "")
    if bdc:
        m = re.search(r"Date limite de réception des devis\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", desc)
        if m:
            jour, heure = m.group(1), m.group(2)
    cond = conditions_avis(desc) if out["source"] == "portail" else {}
    if cond.get("limite"):
        jour, heure = _jour_heure(cond["limite"])
    out["limite"] = {"jour": jour, "heure": heure, "restants": _jours_restants(jour)} if jour else None

    if bdc:
        art = articles_bdc(desc)
        out["articles"] = art
        out["garanties"] = _garanties(desc)
        out["pieces"] = _pieces(desc)
        out["nature"] = _propre(t.get("nature") or "")
        return out

    montant = _propre(t.get("montant") or "")
    out["estimation"] = montant if montant and not _nul(montant) else None

    if out["source"] != "portail":
        # Pas d'avis détaillé: ni qualification ni dossier. La caution, la
        # source privée la publie à côté du budget — gardée depuis le
        # 21/10/2026 (private_scraper._parse_caution).
        h = re.search(r"Date et heure limite de remise des plis\s*:\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", desc)
        if h:
            out["limite"] = {"jour": h.group(1), "heure": h.group(2),
                             "restants": _jours_restants(h.group(1))}
        m = re.search(r"Caution provisoire\s*:\s*([\d][\d\s.,]*\s*MAD)", desc)
        out["caution"] = {"valeur": m.group(1).strip()} if m and not _nul(m.group(1)) else None
        out["qualification"] = out["dossier"] = None
        return out

    lots = bool(re.search(r"[2-9]|\d{2}", cond.get("allotissement", "")))
    caution = _propre(cond.get("caution", ""))
    if caution and not _nul(caution):
        out["caution"] = {"valeur": caution}
    elif lots:
        out["caution"] = {"valeur": "", "par_lot": True}
    else:
        out["caution"] = {"valeur": "", "aucune": True}

    exigences = qualifications_lisibles(_propre(cond.get("qualifications", ""))) + \
        [x for x in [_propre(cond.get("agrements", ""))] if x]
    out["qualification"] = {"valeurs": exigences} if exigences else \
        ({"par_lot": True} if lots else {"aucune": True})

    retrait = _propre(cond.get("retrait", ""))
    prix = _propre(cond.get("prix_plans", ""))
    out["dossier"] = {
        "electronique": "marchespublics.gov.ma" in retrait.lower(),
        "adresse": retrait[:200],
        "gratuit": not prix or _nul(prix),
        "prix": prix if prix and not _nul(prix) else "",
    } if retrait else None
    return out
