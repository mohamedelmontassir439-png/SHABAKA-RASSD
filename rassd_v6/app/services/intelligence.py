# -*- coding: utf-8 -*-
"""Ce que les marchés déjà attribués apprennent sur le prochain.

Avant de chiffrer, une entreprise veut savoir trois choses: combien ce
genre de marché a été payé, qui le remporte d'habitude, et ce que fait tel
concurrent. Les résultats d'adjudication les disent — à condition de ne
leur faire dire que ce qu'ils disent.

**Ce que ce module ne calcule pas: un « rabais habituel ».** Mesuré le
21/10/2026 sur 232 résultats chiffrés des deux côtés, le rapport montant
attribué / estimation tombe à 1,00 ou 1,20 dans la moitié des cas: l'une
des deux colonnes est souvent hors taxes, l'autre toutes taxes, sans que la
source dise laquelle. Un pourcentage tiré de là serait faux, et ferait
perdre un marché à qui le suivrait. On montre donc des faits — tel marché,
tel attributaire, tel montant, telle date —, jamais une moyenne de rapports.
"""
import re
import unicodedata
from collections import Counter

from app.core.attribution import est_attribue
from app.core.database import get_db
from app.core.villes import ville
from app.services.companies import normalize_company_name
from app.services.gagnants import noms_gagnants


# Le plus gros marché public marocain se compte en milliards, pas au-delà.
PLAFOND = 5_000_000_000


def montant(texte: str) -> float:
    """« 6.720.600.00 », « 5.916.000,00 », « 470 400,00 MAD » -> nombre.

    La source écrit les décimales tantôt après une virgule, tantôt après un
    point: les deux derniers chiffres après le dernier séparateur sont des
    centimes, tout le reste est la partie entière.
    """
    s = re.sub(r"[^\d.,]", "", texte or "")
    m = re.match(r"^(.*?)[.,](\d{2})$", s)
    entier = re.sub(r"\D", "", m.group(1) if m else s)
    valeur = float(entier) if entier else 0.0
    # Au-delà, c'est une erreur de saisie de la source (relevé: un montant
    # à dix-sept chiffres): on se tait plutôt que de l'afficher.
    return valeur if valeur <= PLAFOND else 0.0


def lisible(valeur: float) -> str:
    return f"{int(round(valeur)):,}".replace(",", " ") + " MAD" if valeur else ""


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", d).strip()


def cle_acheteur(nom: str) -> str:
    """« ministere de l'equipement /DIRECTION PROVINCIALE DE BOU- LEMANE »
    -> « direction provinciale de boulemane ».

    Le service qui achète est la partie après la barre; le ministère n'en
    est que la tutelle. Les coupures de mots de la source (« BOU- LEMANE »)
    sont recollées.
    """
    partie = (nom or "").split("/")[-1] if "/" in (nom or "") else (nom or "")
    partie = re.sub(r"(\w)-\s+(\w)", r"\1\2", partie)
    return _nu(partie)


def _resultats(where: str = "1=1", params: tuple = ()) -> list:
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            f"""SELECT id, objet, acheteur, adjudicataire, region, budget, montant, secteur,
                       date_adjudication, type_procedure
                FROM tender_results WHERE {where}""", params).fetchall()]
    finally:
        db.close()


def _forme(r: dict) -> dict:
    r["attribue"] = est_attribue(r.get("adjudicataire") or "")
    r["montant_n"] = montant(r.get("montant"))
    r["montant_txt"] = lisible(r["montant_n"])
    r["ville"] = ville(r.get("region") or "")
    return r


def _date_tri(r: dict) -> str:
    j = r.get("date_adjudication") or ""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", j)
    return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else ""


def comparables(t: dict, limite: int = 5) -> dict:
    """Les marchés attribués qui ressemblent le plus à celui-ci.

    Dans l'ordre: même acheteur, puis même secteur dans la même ville, puis
    même secteur. On dit lequel des trois a servi — « chez ce même
    acheteur » ne se lit pas comme « dans le secteur ».
    """
    secteur = t.get("secteur") or ""
    acheteur = cle_acheteur(t.get("acheteur") or "")
    v = ville(t.get("region") or "")
    tous = [_forme(r) for r in _resultats("secteur=? OR 1=1", (secteur,))]
    tous = [r for r in tous if r["attribue"]]

    meme_acheteur = [r for r in tous if acheteur and len(acheteur) > 6
                     and cle_acheteur(r["acheteur"]) == acheteur]
    if meme_acheteur:
        base, portee = meme_acheteur, "acheteur"
    else:
        meme_ville = [r for r in tous if secteur and r["secteur"] == secteur and v and r["ville"] == v]
        if len(meme_ville) >= 2:
            base, portee = meme_ville, "ville"
        else:
            base = [r for r in tous if secteur and r["secteur"] == secteur]
            portee = "secteur"
    base.sort(key=_date_tri, reverse=True)
    return {"portee": portee, "lignes": base[:limite], "total": len(base)}


def qui_gagne(secteur: str, region: str = "", limite: int = 5) -> list:
    """Les entreprises qui remportent le plus de marchés dans ce secteur."""
    if not secteur:
        return []
    v = ville(region) if region else ""
    compte, sommes, affiche = Counter(), Counter(), {}
    for r in _resultats("secteur=?", (secteur,)):
        if v and ville(r.get("region") or "") != v:
            continue
        noms = [n for n in noms_gagnants(r.get("adjudicataire") or "") if est_attribue(n)]
        # « ENTREPRISE HBAYOU- » et « ENTREPRISE HBAYOU » sont une seule
        # entreprise: on compte sur le nom réduit, on affiche le premier vu.
        noms = [affiche.setdefault(normalize_company_name(n) or n, n.strip(" -.")) for n in noms]
        for nom in noms:
            compte[nom] += 1
            # Plusieurs attributaires d'un même résultat: le montant n'est
            # pas réparti, on ne l'attribue donc qu'à un attributaire seul.
            if len(noms) == 1:
                sommes[nom] += montant(r.get("montant"))
    if not compte and v:
        # Rien dans cette ville: le secteur entier dit encore qui compte.
        return qui_gagne(secteur, "", limite)
    return [{"nom": n, "marches": c, "total": lisible(sommes[n])}
            for n, c in compte.most_common(limite)]


def profil_concurrent(nom: str) -> dict:
    """Tout ce que les résultats disent d'une entreprise."""
    q = (nom or "").strip()
    if len(q) < 3:
        return {}
    lignes = [_forme(r) for r in _resultats("adjudicataire LIKE ?", (f"%{q}%",))]
    lignes = [r for r in lignes if r["attribue"]]
    if not lignes:
        return {"nom": q, "marches": 0, "lignes": []}
    lignes.sort(key=_date_tri, reverse=True)
    from app.core.sectors import get_label
    secteurs = Counter(get_label(r["secteur"]) or r["secteur"] for r in lignes if r["secteur"])
    acheteurs = Counter((r["acheteur"] or "").split("/")[-1].strip()[:70] for r in lignes if r["acheteur"])
    villes = Counter(r["ville"] for r in lignes if r["ville"])
    return {
        "nom": q, "marches": len(lignes),
        "total": lisible(sum(r["montant_n"] for r in lignes)),
        "secteurs": secteurs.most_common(5), "acheteurs": acheteurs.most_common(5),
        "villes": villes.most_common(5), "lignes": lignes[:30],
    }


def classement(secteurs: list, limite: int = 10) -> list:
    """Les plus gros gagnants dans les secteurs suivis par le membre."""
    compte = Counter()
    for s in secteurs or []:
        for g in qui_gagne(s, limite=50):
            compte[g["nom"]] += g["marches"]
    return compte.most_common(limite)


# ─── Profil d'un acheteur ────────────────────────────────────────────────

def slug_acheteur(nom: str) -> str:
    """L'adresse d'un acheteur, entière: tronquée, « Direction provinciale de
    l'équipement… de Rabat » et « … de Guercif » se confondaient."""
    return re.sub(r"\s+", "-", cle_acheteur(nom))[:160]


def profil_acheteur(slug_demande: str) -> dict:
    """Ce que les avis et les résultats disent d'un acheteur public.

    Combien il publie, pour quels montants, dans quels secteurs; combien de
    ses consultations finissent infructueuses ou annulées — un acheteur qui
    annule une fois sur trois ne se prépare pas comme un autre —, et qui
    remporte ses marchés.
    """
    from app.core.attribution import issue
    from app.core.sectors import get_label
    db = get_db()
    try:
        avis = [dict(r) for r in db.execute(
            """SELECT id, objet, acheteur, secteur, region, montant, date_limite, statut, source
               FROM tenders WHERE acheteur != ''""").fetchall()]
    finally:
        db.close()
    siens = [a for a in avis if slug_acheteur(a["acheteur"]) == slug_demande]
    resultats = [_forme(r) for r in _resultats("acheteur != ''")
                 if slug_acheteur(r["acheteur"]) == slug_demande]
    if not siens and not resultats:
        return {}
    nom = (siens or resultats)[0]["acheteur"].split("/")[-1].strip()
    issues = Counter(issue(r.get("adjudicataire") or "") or "attribue" for r in resultats)
    montants = [montant(a["montant"]) for a in siens if montant(a["montant"])]
    gagnants = Counter()
    for r in resultats:
        for n in noms_gagnants(r.get("adjudicataire") or ""):
            if est_attribue(n):
                gagnants[n.strip(" -.")] += 1
    secteurs = Counter(get_label(a["secteur"]) or a["secteur"] for a in siens if a["secteur"])
    ouverts = [a for a in siens if a["statut"] == "actif"]
    total_res = sum(issues.values())
    return {
        "nom": nom, "slug": slug_demande, "avis": len(siens), "ouverts": ouverts[:15],
        "n_ouverts": len(ouverts),
        "montant_median": lisible(sorted(montants)[len(montants) // 2]) if montants else "",
        "secteurs": secteurs.most_common(6),
        "resultats": total_res,
        "taux_infructueux": round(100 * issues.get("infructueux", 0) / total_res) if total_res else None,
        "taux_annule": round(100 * (issues.get("annule", 0) + issues.get("sans_suite", 0)) / total_res)
        if total_res else None,
        "gagnants": gagnants.most_common(8),
        "derniers": sorted(resultats, key=_date_tri, reverse=True)[:12],
    }
