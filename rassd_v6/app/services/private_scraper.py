"""
ATLAS PRO — Global Marches (appels d'offres privés)
Se connecte à global-marches.com avec le compte abonné (GM_USERNAME/GM_PASSWORD)
et récupère les nouveaux appels d'offres privés.
"""
import re, logging
from datetime import datetime
import requests

from app.core.config import cfg
from app.core.sectors import classify

logger = logging.getLogger("atlas.gm")

BASE = "https://global-marches.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"

# Paramètres fixes du formulaire de recherche "/aopriverecherche" — reproduits
# exactement (y compris NULL_INCLU_*/MOT_CLE_CRET_*) car le backend PHP renvoie
# une erreur 500 si l'un de ces champs est absent de la requête.
#
# Le site a retiré les filtres de date (DATE_PARUTION_*/DATE_LIMIT_*) de ce
# formulaire à un moment donné — les envoyer fait maintenant planter le
# backend (500 sur toute requête qui les contient, même vides). On ne filtre
# donc plus par date ici : le tri par défaut est décroissant sur la date de
# parution, et le dédoublonnage via known_ids couvre le reste (même principe
# que run_results() ci-dessous, qui n'a jamais utilisé de filtre de date).
SEARCH_PARAMS = [
    ("CAT_OFFRE", "Prive"),
    ("CLASSES[]", "%"), ("VILLE[]", "%"), ("ORG[]", "%"), ("Domaine[]", "%"),
    ("Secteur[]", "%"), ("Qualification[]", "%"), ("Classe[]", "%"),
    ("MOT_CLE_1", ""), ("MOT_CLE_CRET_1", "AND"),
    ("MOT_CLE_2", ""), ("MOT_CLE_CRET_2", "AND"), ("MOT_CLE_3", ""),
    ("CAUTION_1", ""), ("CAUTION_2", ""),
    ("NULL_INCLU_1", "1"), ("BUDJET_1", ""), ("BUDJET_2", ""), ("NULL_INCLU_2", "1"),
    ("ORDRE", ""), ("REFERENCE", ""), ("type_oa", ""), ("SAVE", ""),
]

ROW_RE   = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.S)
ID_RE    = re.compile(r'class="favimg_custom" id="(\d+)"')
ORG_RE   = re.compile(r'<b>Organisme\s*:</b>\s*(.*?)<br', re.S)
OBJ_RE   = re.compile(r'<b>Objet\s*:</b>\s*(.*?)</td>', re.S)
VILLE_RE = re.compile(r'<td>\s*-?\s*([^<]*?)<br', re.S)
DL_RE    = re.compile(r'(\d{2}/\d{2}/\d{4})')
DAO_RE   = re.compile(r'href="(/downoaldcps/[^"]+)"')
SHARE_RE = re.compile(r'https://global-marches\.com/share/[\w=]+')
SHARE_PO_RE = re.compile(r'https://global-marches\.com/share-po/[\w=]+')


def _clean(html_fragment: str) -> str:
    text = re.sub(r'<[^<]+?>', ' ', html_fragment or '')
    text = re.sub(r'&[a-z]+;', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _login(s: requests.Session) -> bool:
    s.get(BASE + "/", timeout=20)
    r = s.post(BASE + "/profile/signin",
               data={"LOGIN": cfg.GM_USERNAME, "PASSWORD": cfg.GM_PASSWORD, "CONNECT": "Se connecter"},
               timeout=20)
    return "PASSWORD_INPUT" not in r.text or "/homecompte" in r.url


def _search(s: requests.Session) -> str:
    r = s.get(BASE + "/listresultatao", params=SEARCH_PARAMS, timeout=30)
    r.raise_for_status()
    return r.text


_CELL_RE  = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# Format monétaire marocain: 1.160.000,00 — les dates (30/09/2026) et les
# références (71/26/S) ne correspondent pas à ce motif.
_MONEY_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")


# Un achat public chiffré sous ce seuil n'existe pas: en dessous, le nombre
# capté vient du texte de l'objet (une dimension, une quantité, un pourcentage)
# et non d'un budget.
_BUDGET_PLANCHER = 1000.0


def _parse_budget(row_html: str) -> str:
    """Extrait le budget estimé de la colonne « Caution/Budget ».

    La cellule contient deux montants: la caution provisoire puis le budget
    (la caution représente 1 à 3 % du budget, elle est donc toujours le plus
    petit des deux). On retient le plus élevé, ce qui reste correct même si
    l'ordre des deux valeurs changeait. Les lignes « ------ » signifient que
    le montant n'est pas publié: on renvoie une chaîne vide plutôt que de
    deviner un chiffre.

    Un repli balayait toute la ligne quand la cellule ne donnait rien, au cas
    où la structure du tableau changerait. Il inventait des montants: relevé
    en production le 30/09/2026, « Dimensions unifiées : 18,00 m × 12,00 m »
    dans l'objet est devenu « 18,00 MAD » pour des travaux de charpente. Un
    chiffre faux sur une fiche coûte plus cher qu'une case vide — c'est
    précisément la promesse d'exactitude qui fait acheter la plateforme. On
    ne lit donc plus que la cellule prévue, et on se tait si elle manque.
    """
    cells = _CELL_RE.findall(row_html)
    if len(cells) <= 3:
        return ""
    montants = _MONEY_RE.findall(cells[3])
    if not montants:
        return ""
    plus_eleve = max(montants, key=lambda v: float(v.replace(".", "").replace(",", ".")))
    if float(plus_eleve.replace(".", "").replace(",", ".")) < _BUDGET_PLANCHER:
        return ""
    return f"{plus_eleve} MAD"


def _parse_row(row_html: str):
    id_m = ID_RE.search(row_html)
    if not id_m:
        return None
    tid = id_m.group(1)

    org_m = ORG_RE.search(row_html)
    obj_m = OBJ_RE.search(row_html)
    acheteur = _clean(org_m.group(1)) if org_m else ""
    objet    = _clean(obj_m.group(1)) if obj_m else ""
    if not objet or len(objet) < 5:
        return None

    ville_m = VILLE_RE.search(row_html)
    region  = _clean(ville_m.group(1)) if ville_m else ""

    dl_m = DL_RE.search(row_html)
    date_limite = dl_m.group(1) if dl_m else ""

    dao_m   = DAO_RE.search(row_html)
    dao_url = BASE + dao_m.group(1) if dao_m else ""

    share_m = SHARE_RE.search(row_html)
    url = share_m.group(0) if share_m else (dao_url or f"{BASE}/aoprive")

    full_text = f"{acheteur} {objet}"

    return {
        "id":               f"gm_{tid}",
        "objet":            objet[:400],
        "acheteur":         acheteur[:200],
        "region":           region[:100],
        "date_publication": "",
        "date_limite":      date_limite,
        "montant":          _parse_budget(row_html),
        "secteur":          classify(objet, acheteur),
        "url":              url,
        "type_offre":       "Privé",
        "source":           "global-marches",
        "statut":           "actif",
        "description":      full_text[:3000],
        "scraped_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def run(known_ids: set, log_fn=print) -> list:
    """Récupère les appels d'offres privés publiés récemment sur global-marches.com."""
    if not cfg.GM_USERNAME or not cfg.GM_PASSWORD:
        log_fn("⚠ Marchés privés: identifiants non configurés")
        return []

    log_fn("═══ Marchés privés ═══")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    try:
        if not _login(s):
            log_fn("❌ Marchés privés: échec de connexion (identifiants invalides ?)")
            return []
    except Exception as e:
        log_fn(f"❌ Marchés privés: erreur connexion — {e}")
        logger.error(f"[gm login] {e}", exc_info=True)
        return []

    try:
        html = _search(s)
    except Exception as e:
        log_fn(f"❌ Marchés privés: erreur recherche — {e}")
        logger.error(f"[gm search] {e}", exc_info=True)
        return []

    results = []
    trouves = analyses = 0
    for row_m in ROW_RE.finditer(html):
        trouves += 1
        t = _parse_row(row_m.group(1))
        if not t:
            continue
        analyses += 1
        if t["id"] in known_ids:
            continue
        results.append(t)
        log_fn(f"✓ {t['id']} │ {t['secteur'][:16]:16} │ {t['objet'][:45]}")

    _bilan(log_fn, "Marchés privés", len(results), trouves, analyses)
    return results


# ══════════════════════════════════════════════════════════
# RÉSULTATS DES APPELS D'OFFRES (adjudications)
# ══════════════════════════════════════════════════════════

RESULTS_PARAMS = [
    ("CAT_OFFRE", "Prive"),
    ("CLASSES[]", "%"), ("Classe[]", "%"), ("Domaine[]", "%"),
    ("ORG[]", "%"), ("Qualification[]", "%"), ("Secteur[]", "%"), ("VILLE[]", "%"),
    ("MOT_CLE_1", ""), ("MOT_CLE_CRET_1", "AND"),
    ("MOT_CLE_2", ""), ("MOT_CLE_CRET_2", "AND"), ("MOT_CLE_3", ""),
    ("MONTANT_MARCHE_1", ""), ("MONTANT_MARCHE_2", ""),
    ("ANNEE", ""), ("MOIS", ""),
    ("REFERENCE", ""), ("Adjudicataire", ""), ("N_ORDRE", ""),
    ("WITHOUT_CLASSIFICATION", ""), ("SAVE", ""),
]

RESULT_BLOCK_RE = re.compile(r'<table width="100%" id="resultTable"[^>]*>.*?</table>', re.S)
RESULT_ID_RE    = re.compile(r'data-id="(\d+)"')
RESULT_REF_RE   = re.compile(r"<th width='9%'>R.f.rence</th>\s*<th width='80%'>([^<]*)</th>", re.S)
RESULT_ROW_RE   = re.compile(r'<th colspan="2">([^<]+):</th>\s*<td colspan="[24]">(.*?)</td>', re.S)
RESULT_DAO_RE   = re.compile(r'D\.A\.O\s*:</th>\s*<td colspan="2">\s*<a href="([^"]+)"')
RESULT_PV_RE    = re.compile(r'PV\s*:</th>\s*<td colspan="2">\s*<a href="([^"]+)"')


def _search_results(s: requests.Session) -> str:
    r = s.get(BASE + "/listresultataoresultat", params=RESULTS_PARAMS, timeout=30)
    r.raise_for_status()
    return r.text


def _parse_result_block(block_html: str):
    id_m = RESULT_ID_RE.search(block_html)
    if not id_m:
        return None
    rid = id_m.group(1)

    ref_m  = RESULT_REF_RE.search(block_html)
    fields = {_clean(k): _clean(v) for k, v in RESULT_ROW_RE.findall(block_html)}

    objet = fields.get("Objet", "")
    if not objet or len(objet) < 5:
        return None

    dao_m = RESULT_DAO_RE.search(block_html)
    pv_m  = RESULT_PV_RE.search(block_html)

    acheteur      = fields.get("Maitre d'ouvrage", "")
    adjudicataire = fields.get("Adjudicataire", "")
    full_text     = f"{acheteur} {objet}"

    return {
        "id":                f"gmr_{rid}",
        "reference":         _clean(ref_m.group(1)) if ref_m else "",
        "objet":             objet[:400],
        "acheteur":          acheteur[:200],
        "adjudicataire":     adjudicataire[:200],
        "region":            fields.get("Ville", "")[:100],
        "budget":            fields.get("Budget(DHs)", "")[:80],
        "montant":           fields.get("Montant(DHs)", "")[:80],
        "secteur":           classify(objet, acheteur),
        "date_adjudication": fields.get("Date des adjudications", ""),
        "date_ouverture":    fields.get("Date d'ouverture", ""),
        "date_affichage":    fields.get("Date d'affichage", ""),
        "dao_url":           BASE + dao_m.group(1) if dao_m else "",
        "pv_url":            BASE + pv_m.group(1) if pv_m else "",
        "scraped_at":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _bilan(log_fn, libelle: str, nouveaux: int, trouves: int, analyses: int) -> None:
    """Rend visible la différence entre « rien de neuf » et « plus rien ne sort ».

    Les quatre collecteurs n'annonçaient que le nombre de nouveautés. Or une
    page dont la structure change renvoie elle aussi zéro: une panne et une
    journée calme s'écrivaient exactement pareil dans le journal, et le
    silence pouvait durer des semaines sans que personne le remarque.

    Trois chiffres suffisent à les séparer:
      trouves=0             → le gabarit de la page a changé, rien à analyser
      trouves>0, analyses=0 → les champs ont bougé, les blocs ne se lisent plus
      analyses>0, nouveaux=0→ tout va bien, la source n'a rien publié
    """
    detail = f"{nouveaux} nouveaux · {analyses} lus · {trouves} trouvés"
    log_fn(f"═══ {libelle}: {detail} ═══")
    if trouves == 0:
        log_fn(f"⚠ {libelle}: aucun bloc trouvé — structure de la page à vérifier")
    elif analyses == 0:
        log_fn(f"⚠ {libelle}: {trouves} blocs trouvés mais aucun exploitable")


def run_results(known_ids: set, log_fn=print) -> list:
    """Récupère les résultats d'adjudication (gagnant, montant final) publiés
    récemment. Le site trie par défaut par date d'affichage décroissante, donc
    la première page (50 résultats) couvre toujours les plus récents — le
    dédoublonnage via known_ids gère le reste."""
    if not cfg.GM_USERNAME or not cfg.GM_PASSWORD:
        log_fn("⚠ Résultats des marchés: identifiants non configurés")
        return []

    log_fn("═══ Résultats des marchés ═══")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    try:
        if not _login(s):
            log_fn("❌ Résultats des marchés: échec de connexion")
            return []
    except Exception as e:
        log_fn(f"❌ Résultats des marchés: erreur connexion — {e}")
        logger.error(f"[gm results login] {e}", exc_info=True)
        return []

    try:
        html = _search_results(s)
    except Exception as e:
        log_fn(f"❌ Résultats des marchés: erreur recherche — {e}")
        logger.error(f"[gm results search] {e}", exc_info=True)
        return []

    results = []
    trouves = analyses = 0
    for block in RESULT_BLOCK_RE.findall(html):
        trouves += 1
        r = _parse_result_block(block)
        if not r:
            continue
        analyses += 1
        if r["id"] in known_ids:
            continue
        results.append(r)
        log_fn(f"✓ {r['id']} │ {r['adjudicataire'][:24]:24} │ {r['objet'][:40]}")

    _bilan(log_fn, "Résultats des marchés", len(results), trouves, analyses)
    return results


# ══════════════════════════════════════════════════════════
# BONS DE COMMANDE (procédure d'achat simplifiée, distincte des
# appels d'offres classiques) — mêmes pages/formulaires que ci-dessus
# mais sous /po-page (listing) et /po-result-page (résultats).
# ══════════════════════════════════════════════════════════

def _bc_search_params(cat_offre: str) -> list:
    return [
        ("CAT_OFFRE", cat_offre),
        ("CLASSES[]", "%"), ("VILLE[]", "%"), ("ORG[]", "%"), ("Domaine[]", "%"),
        ("Secteur[]", "%"), ("Qualification[]", "%"), ("Classe[]", "%"),
        ("MOT_CLE_1", ""), ("MOT_CLE_CRET_1", "AND"),
        ("MOT_CLE_2", ""), ("MOT_CLE_CRET_2", "AND"), ("MOT_CLE_3", ""),
        ("CAUTION_1", ""), ("CAUTION_2", ""),
        ("NULL_INCLU_1", "1"), ("BUDJET_1", ""), ("BUDJET_2", ""), ("NULL_INCLU_2", "1"),
        ("ORDRE", ""), ("REFERENCE", ""), ("type_oa", ""),
    ]

def _bc_results_params(cat_offre: str) -> list:
    return [
        ("CAT_OFFRE", cat_offre),
        ("CLASSES[]", "%"), ("Classe[]", "%"), ("Domaine[]", "%"),
        ("ORG[]", "%"), ("Qualification[]", "%"), ("Secteur[]", "%"), ("VILLE[]", "%"),
        ("MOT_CLE_1", ""), ("MOT_CLE_CRET_1", "AND"),
        ("MOT_CLE_2", ""), ("MOT_CLE_CRET_2", "AND"), ("MOT_CLE_3", ""),
        ("MONTANT_MARCHE_1", ""), ("MONTANT_MARCHE_2", ""),
        ("ANNEE", ""), ("REFERENCE", ""), ("Adjudicataire", ""), ("N_ORDRE", ""),
        ("WITHOUT_CLASSIFICATION", ""),
    ]


def _parse_po_row(row_html: str, type_offre: str):
    id_m = ID_RE.search(row_html)
    if not id_m:
        return None
    tid = id_m.group(1)

    org_m = ORG_RE.search(row_html)
    obj_m = OBJ_RE.search(row_html)
    acheteur = _clean(org_m.group(1)) if org_m else ""
    objet    = _clean(obj_m.group(1)) if obj_m else ""
    if not objet or len(objet) < 5:
        return None

    ville_m = VILLE_RE.search(row_html)
    region  = _clean(ville_m.group(1)) if ville_m else ""

    dl_m = DL_RE.search(row_html)
    date_limite = dl_m.group(1) if dl_m else ""

    share_m = SHARE_PO_RE.search(row_html)
    url = share_m.group(0) if share_m else f"{BASE}/po-page"

    full_text = f"{acheteur} {objet}"

    return {
        "id":               f"po_{tid}",
        "objet":            objet[:400],
        "acheteur":         acheteur[:200],
        "region":           region[:100],
        "date_publication": "",
        "date_limite":      date_limite,
        "montant":          _parse_budget(row_html),
        "secteur":          classify(objet, acheteur),
        "url":              url,
        "type_offre":       type_offre,
        "source":           "global-marches",
        "statut":           "actif",
        "description":      full_text[:3000],
        "scraped_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type_procedure":   "bon_commande",
    }


def run_bc(known_ids: set, log_fn=print) -> list:
    """Récupère les bons de commande (procédure d'achat public simplifiée,
    régie par la réglementation des marchés publics — il n'existe pas
    d'équivalent privé) publiés récemment, sur /po-page.

    Note: le paramètre CAT_OFFRE (Public/Prive) a été vérifié — il ne change
    rien au résultat pour ce type de contenu (constaté par comparaison directe
    des réponses), donc une seule requête suffit plutôt que d'interroger deux
    fois pour un résultat identique."""
    if not cfg.GM_USERNAME or not cfg.GM_PASSWORD:
        log_fn("⚠ Bons de commande: identifiants non configurés")
        return []

    log_fn("═══ Bons de commande ═══")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    try:
        if not _login(s):
            log_fn("❌ Bons de commande: échec de connexion")
            return []
    except Exception as e:
        log_fn(f"❌ Bons de commande: erreur connexion — {e}")
        logger.error(f"[bc login] {e}", exc_info=True)
        return []

    try:
        r = s.get(BASE + "/po-result-search-page", params=_bc_search_params("Public"), timeout=30)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        log_fn(f"❌ Bons de commande: erreur recherche — {e}")
        logger.error(f"[bc search] {e}", exc_info=True)
        return []

    results = []
    trouves = analyses = 0
    for row_m in ROW_RE.finditer(html):
        trouves += 1
        t = _parse_po_row(row_m.group(1), "Public")
        if not t:
            continue
        analyses += 1
        if t["id"] in known_ids:
            continue
        results.append(t)
        log_fn(f"✓ {t['id']} │ {t['secteur'][:16]:16} │ {t['objet'][:45]}")

    _bilan(log_fn, "Bons de commande", len(results), trouves, analyses)
    return results


def _parse_po_result_block(block_html: str):
    id_m = RESULT_ID_RE.search(block_html)
    if not id_m:
        return None
    rid = id_m.group(1)

    ref_m  = RESULT_REF_RE.search(block_html)
    fields = {_clean(k): _clean(v) for k, v in RESULT_ROW_RE.findall(block_html)}

    objet = fields.get("Objet", "")
    if not objet or len(objet) < 5:
        return None

    dao_m = RESULT_DAO_RE.search(block_html)
    pv_m  = RESULT_PV_RE.search(block_html)

    acheteur      = fields.get("Maitre d'ouvrage", "")
    adjudicataire = fields.get("Adjudicataire", "")
    full_text     = f"{acheteur} {objet}"

    return {
        "id":                f"por_{rid}",
        "reference":         _clean(ref_m.group(1)) if ref_m else "",
        "objet":             objet[:400],
        "acheteur":          acheteur[:200],
        "adjudicataire":     adjudicataire[:200],
        "region":            fields.get("Ville", "")[:100],
        "budget":            fields.get("Budget(DHs)", "")[:80],
        "montant":           fields.get("Montant(DHs)", "")[:80],
        "secteur":           classify(objet, acheteur),
        "date_adjudication": fields.get("Date des adjudications", ""),
        "date_ouverture":    fields.get("Date d'ouverture", ""),
        "date_affichage":    fields.get("Date d'affichage", ""),
        "dao_url":           BASE + dao_m.group(1) if dao_m else "",
        "pv_url":            BASE + pv_m.group(1) if pv_m else "",
        "scraped_at":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type_procedure":    "bon_commande",
    }


def run_bc_results(known_ids: set, log_fn=print) -> list:
    """Récupère les résultats des bons de commande (gagnant, montant final)
    sur /po-result-page. CAT_OFFRE vérifié sans effet sur ce contenu (même
    constat que run_bc) — une seule requête suffit."""
    if not cfg.GM_USERNAME or not cfg.GM_PASSWORD:
        log_fn("⚠ Résultats des bons de commande: identifiants non configurés")
        return []

    log_fn("═══ Résultats des bons de commande ═══")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    try:
        if not _login(s):
            log_fn("❌ Résultats des bons de commande: échec de connexion")
            return []
    except Exception as e:
        log_fn(f"❌ Résultats des bons de commande: erreur connexion — {e}")
        logger.error(f"[bc results login] {e}", exc_info=True)
        return []

    try:
        r = s.get(BASE + "/po-result-list-page", params=_bc_results_params("Public"), timeout=30)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        log_fn(f"❌ Résultats des bons de commande: erreur recherche — {e}")
        logger.error(f"[bc results search] {e}", exc_info=True)
        return []

    results = []
    trouves = analyses = 0
    for block in RESULT_BLOCK_RE.findall(html):
        trouves += 1
        res = _parse_po_result_block(block)
        if not res:
            continue
        analyses += 1
        if res["id"] in known_ids:
            continue
        results.append(res)
        log_fn(f"✓ {res['id']} │ {res['adjudicataire'][:24]:24} │ {res['objet'][:40]}")

    _bilan(log_fn, "Résultats des bons de commande", len(results), trouves, analyses)
    return results
