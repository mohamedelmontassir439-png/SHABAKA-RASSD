# -*- coding: utf-8 -*-
"""Les pages que les moteurs de recherche peuvent lire.

Le site exposait l'accueil, les tarifs et 83 pages sectorielles. Les quatre
mille fiches de marchés renvoyaient vers la connexion: pour Google, elles
n'existaient pas. Or c'est ainsi qu'un entrepreneur cherche — « appel
d'offres peinture port Tanger », « marchés publics Guercif » — et il tombait
sur le portail officiel ou chez un concurrent.

Deux familles de pages s'ajoutent:

- **une page publique par appel d'offres du portail national**: intitulé,
  ville, secteur, date limite, estimation. L'acheteur, les conditions de
  l'avis et le lien officiel restent réservés aux membres — la même règle
  que les pages sectorielles. Seuls les avis de marchespublics.gov.ma ont
  une page: ils sont publics par nature. Ceux d'un agrégateur privé n'en
  ont pas — republier son travail n'est pas à nous de le faire;
- **une page par ville** ayant au moins SEUIL_VILLE marchés ouverts: en
  dessous, la page serait presque vide, et Google pénalise les pages
  minces plus qu'il ne récompense leur nombre.

Un marché clôturé garde sa page — des liens peuvent y mener — mais elle
sort du plan du site et passe en « noindex ».
"""
import re
import unicodedata
from datetime import date, datetime

from app.core.conditions import cartes, conditions_avis
from app.core.config import cfg
from app.core.database import get_db
from app.core.sectors import get_label
from app.core.villes import slug as slug_ville
from app.core.villes import ville

SEUIL_VILLE = 5
SOURCE_PUBLIQUE = "marchespublics"
PREFIXE = "ao_"
# Les bons de commande du portail national sont publics au même titre que
# ses appels d'offres, et on les cherche autant: « bon de commande Agadir
# fournitures de bureau ». Chaque nature a son adresse.
NATURES = {
    "ao_":  {"chemin": "/appel-offres/",    "libelle": "Appel d'offres"},
    "bdc_": {"chemin": "/bon-de-commande/", "libelle": "Bon de commande"},
}


def prefixe(tid: str) -> str:
    return next((p for p in NATURES if (tid or "").startswith(p)), "")


def slug(texte: str, longueur: int = 70) -> str:
    base = unicodedata.normalize("NFD", (texte or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:longueur]
    return base.rsplit("-", 1)[0] if len(base) == longueur and "-" in base else base


def slug_secteur(label: str) -> str:
    """L'adresse d'une page sectorielle — même calcul que main._slug, qui la sert."""
    base = unicodedata.normalize("NFD", (label or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return re.sub(r"-{2,}", "-", base)[:60]


def a_une_page(t) -> bool:
    """Seuls les avis du portail national ont une page publique."""
    return bool(t) and bool(prefixe(t["id"])) and (t["source"] or "") == SOURCE_PUBLIQUE


def chemin(t) -> str:
    """« /appel-offres/1043943-achevement-… » ou « /bon-de-commande/400227-achat-… »."""
    p = prefixe(t["id"])
    return f"{NATURES[p]['chemin']}{t['id'][len(p):]}-{slug(t['objet'])}"


def jour(texte: str):
    try:
        return datetime.strptime((texte or "")[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def marche(numero: str, p: str = PREFIXE):
    """Le marché derrière une adresse publique, ou None."""
    if not numero.isdigit():
        return None
    db = get_db()
    try:
        t = db.execute("SELECT * FROM tenders WHERE id=?", (p + numero,)).fetchone()
    finally:
        db.close()
    return dict(t) if a_une_page(t) else None


def fiche(t: dict) -> dict:
    """Ce que la page publique montre, et ce qu'elle annonce sans le montrer."""
    fin = jour(t.get("date_limite"))
    ouvert = t.get("statut") == "actif" and (fin is None or fin >= date.today())
    cond = conditions_avis(t.get("description") or "")
    # On dit quelles conditions l'avis pose — c'est ce que l'entreprise veut
    # savoir avant tout —, sans en livrer la valeur.
    exigences = [cle for cle, _, _, exige in cartes(cond) if exige and cle != "cond_limite"]
    p = prefixe(t.get("id") or "")
    return {
        "t": t, "ouvert": ouvert, "fin": fin,
        "nature": NATURES.get(p, NATURES[PREFIXE])["libelle"],
        "bdc": p == "bdc_",
        "jours": (fin - date.today()).days if fin else None,
        "ville": ville(t.get("region") or ""),
        "secteur": get_label(t.get("secteur") or "") or "",
        "secteur_slug": slug_secteur(get_label(t.get("secteur") or "") or ""),
        "procedure": cond.get("procedure", ""),
        "categorie": cond.get("categorie", ""),
        "reference": cond.get("reference", ""),
        "exigences": exigences,
    }


def voisins(t: dict, limite: int = 6) -> list:
    """Marchés ouverts du même secteur, avec une page publique."""
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT id, objet, region, date_limite, montant, source FROM tenders
               WHERE statut='actif' AND secteur=? AND id!=? AND source=? AND id LIKE ?
               ORDER BY scraped_at DESC LIMIT ?""",
            (t.get("secteur") or "", t["id"], SOURCE_PUBLIQUE,
             (prefixe(t["id"]) or PREFIXE) + "%", limite)).fetchall()]
    finally:
        db.close()
    for v in lignes:
        v["chemin"] = chemin(v)
        v["ville"] = ville(v.get("region") or "")
    return lignes


def marches_ouverts_publics() -> list:
    """Tous les marchés ouverts ayant une page — pour le plan du site."""
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT id, objet, source, scraped_at, date_limite FROM tenders
               WHERE statut='actif' AND source=? AND (id LIKE 'ao_%' OR id LIKE 'bdc_%')""",
            (SOURCE_PUBLIQUE,)).fetchall()]
    finally:
        db.close()
    aujourdhui = date.today()
    return [l for l in lignes if (jour(l["date_limite"]) or aujourdhui) >= aujourdhui]


# ─── Les villes ───────────────────────────────────────────────────────────

def villes_publiques() -> list:
    """Les villes ayant assez de marchés ouverts pour une page, les plus fournies d'abord."""
    db = get_db()
    try:
        lignes = db.execute(
            "SELECT region, COUNT(*) FROM tenders WHERE statut='actif' AND region!='' "
            "GROUP BY 1").fetchall()
    finally:
        db.close()
    compte = {}
    for region, n in lignes:
        nom = ville(region)
        if nom:
            compte[nom] = compte.get(nom, 0) + n
    return sorted(({"nom": nom, "slug": slug_ville(nom), "n": n}
                   for nom, n in compte.items() if n >= SEUIL_VILLE),
                  key=lambda v: -v["n"])


def page_ville(slug_demande: str):
    """(la ville, ses marchés à montrer, ses secteurs) ou None."""
    v = next((x for x in villes_publiques() if x["slug"] == slug_demande), None)
    if not v:
        return None
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT id, objet, region, secteur, date_limite, montant, source, scraped_at
               FROM tenders WHERE statut='actif' AND region!=''
               ORDER BY scraped_at DESC""").fetchall()]
    finally:
        db.close()
    siens = [l for l in lignes if ville(l["region"]) == v["nom"]]
    secteurs = {}
    for l in siens:
        if l["secteur"]:
            secteurs[l["secteur"]] = secteurs.get(l["secteur"], 0) + 1
    top = [{"label": get_label(s) or s, "slug": slug_secteur(get_label(s) or s), "n": n}
           for s, n in sorted(secteurs.items(), key=lambda x: -x[1])[:10]]
    montres = []
    for l in siens:
        if a_une_page(l):
            l["chemin"] = chemin(l)
            l["secteur_label"] = get_label(l["secteur"] or "") or ""
            montres.append(l)
        if len(montres) == 20:
            break
    return {"ville": v, "marches": montres, "secteurs": top}


def url_absolue(chemin_relatif: str) -> str:
    return cfg.SITE_URL.rstrip("/") + chemin_relatif
