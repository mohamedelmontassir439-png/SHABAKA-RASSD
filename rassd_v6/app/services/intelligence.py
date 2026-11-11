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


# Mots qui ne disent rien de la nature des travaux: on ne rapproche pas deux
# marchés parce qu'ils sont tous deux « relevant de la commune ».
VIDES = set("""travaux travail realisation realiser execution relatif relatifs relative relatives
relevant releve commune communes province provinciale prefecture region regionale regional
direction centre ville dans pour avec ainsi que les des une aux sur sous entre leur leurs
lot lots unique marche marches appel offre offres ouvert ouverte simplifie simplifiee
divers diverses douar douars rurale rural urbaine urbain cadre programme projet projets
tranche phase annee annees niveau secteur site sites siege lieu lieux maroc royaume
partie parties premiere deuxieme troisieme etat cours selon type objet consultation
majoration rabais bon commande prix
construction installation fourniture fournitures acquisition livraison amenagement
equipement equipements materiel materiels mise service services technique techniques
etude etudes generale generaux general neuf neuve existant existante destine destinee
destines destinees compte besoin besoins""".split())

NATURES = (
    ("etude", r"\b(etude|etudes|controle|suivi|assistance|laboratoire|essais?|topograph|expertise|"
              r"audit|conception|diagnostic|plans?|levee?s?|geotechni)"),
    ("service", r"\b(nettoiement|proprete|blanchissage|nettoyage|gardiennage|entretien|maintenance|location|transport|restauration|"
                r"jardinage|formation|impression|reparation|exploitation)"),
    ("fourniture", r"\b(acquisition|fourniture|achat|livraison)"),
    ("travaux", r"\b(travaux|construction|realisation|amenagement|rehabilitation|renforcement|"
                r"elargissement|extension|refection|revetement|creation|equipement)"),
)


def nature(objet: str) -> str:
    """Travaux, fourniture, étude ou service — d'après les premiers mots de
    l'objet, qui disent ce qu'on achète (« Contrôle des travaux de… » est une
    étude, pas des travaux)."""
    debut = " ".join(_nu(objet).split()[:6])
    for nom, motif in NATURES:
        if re.search(motif, debut):
            return nom
    return ""


def themes(objet: str) -> set:
    """Les mots porteurs de l'objet: piste, ecole, assainissement, voirie…"""
    mots = set()
    for m in _nu(objet).split():
        if len(m) < 4 or m in VIDES or m.isdigit():
            continue
        mots.add(m[:-1] if m.endswith("s") and len(m) > 4 else m)
    return mots


def _proximite_montant(a: float, b: float) -> float:
    """1 pour deux montants égaux, 0 au-delà d'un facteur dix."""
    import math
    if not a or not b:
        return 0.0
    return max(0.0, 1 - abs(math.log10(a / b)))


def comparables(t: dict, limite: int = 5) -> dict:
    """Les marchés attribués qui ressemblent le plus à celui-ci.

    Un marché attribué n'est retenu que s'il partage au moins un mot porteur
    de l'objet (piste, école, assainissement…) ou le même acheteur, et
    jamais s'il est d'une autre nature (un contrôle de travaux n'est pas un
    marché de travaux). Les retenus sont classés par mots communs, montant
    proche de l'estimation, même acheteur, même ville, puis date.
    """
    secteur = t.get("secteur") or ""
    acheteur = cle_acheteur(t.get("acheteur") or "")
    v = ville(t.get("region") or "")
    mes_themes = themes(t.get("objet") or "")
    ma_nature = nature(t.get("objet") or "")
    estimation = montant(t.get("montant") or "")
    tous = [_forme(r) for r in _resultats()]
    for r in tous:
        r["_themes"] = themes(r.get("objet") or "")
    # Un mot présent dans plus d'un résultat sur seize (« profit »,
    # « prestations »…) ne distingue rien: il ne compte pas comme point commun.
    frequence = Counter(m for r in tous for m in r["_themes"])
    seuil = max(3, len(tous) / 16)
    mes_themes = {m for m in mes_themes if frequence[m] <= seuil}
    retenus = []
    for r in tous:
        if not r["attribue"]:
            continue
        sa_nature = nature(r.get("objet") or "")
        if ma_nature and sa_nature and sa_nature != ma_nature:
            continue
        communs = mes_themes & r["_themes"]
        # Un seul mot commun sur un objet qui en compte dix est un hasard —
        # sauf s'il est rare (« dédoublement », « hydroponique »): il dit alors
        # exactement de quoi il s'agit.
        if (len(communs) == 1 and len(mes_themes) > 5
                and frequence[next(iter(communs))] > 5):
            communs = set()
        meme_acheteur = bool(acheteur) and len(acheteur) > 6 and cle_acheteur(r["acheteur"]) == acheteur
        if not communs and not meme_acheteur:
            continue
        score = (2.0 * len(communs) / (len(mes_themes) or 1) + (0.5 if communs else 0)
                 + 1.5 * _proximite_montant(estimation, r["montant_n"])
                 + (1.0 if meme_acheteur else 0) + (0.5 if v and r["ville"] == v else 0)
                 + (0.3 if secteur and r["secteur"] == secteur else 0))
        r["communs"] = sorted(communs)
        r["meme_acheteur"] = meme_acheteur
        r.pop("_themes", None)
        retenus.append((score, _date_tri(r), r))
    # Dès qu'il existe des marchés de même objet, eux seuls: un mobilier de
    # bureau n'éclaire pas un achat d'habillement parce que l'acheteur est le
    # même. Faute de quoi, les marchés de ce même acheteur, annoncés comme tels.
    similaires = [x for x in retenus if x[2]["communs"]]
    if similaires:
        retenus, portee = similaires, "similaires"
    else:
        portee = "acheteur"
    retenus.sort(key=lambda x: (x[0], x[1]), reverse=True)
    lignes = [r for _, _, r in retenus[:limite]]
    return {"portee": portee, "lignes": lignes, "total": len(retenus)}


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
