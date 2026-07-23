"""
ATLAS PRO — Global Marches (appels d'offres privés)
Se connecte à global-marches.com avec le compte abonné (GM_USERNAME/GM_PASSWORD)
et récupère les nouveaux appels d'offres privés.
"""
import re, logging
from datetime import datetime, timedelta
import requests

from app.core.config import cfg
from app.core.sectors import classify

logger = logging.getLogger("atlas.gm")

BASE = "https://global-marches.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"

# Paramètres fixes du formulaire de recherche "/aopriverecherche" — reproduits
# exactement (y compris NULL_INCLU_*/MOT_CLE_CRET_*) car le backend PHP renvoie
# une erreur 500 si l'un de ces champs est absent de la requête.
SEARCH_PARAMS = [
    ("CAT_OFFRE", "Prive"),
    ("CLASSES[]", "%"), ("VILLE[]", "%"), ("ORG[]", "%"), ("Domaine[]", "%"),
    ("Secteur[]", "%"), ("Qualification[]", "%"), ("Classe[]", "%"),
    ("MOT_CLE_1", ""), ("MOT_CLE_CRET_1", "AND"),
    ("MOT_CLE_2", ""), ("MOT_CLE_CRET_2", "AND"), ("MOT_CLE_3", ""),
    ("DATE_LIMIT_1", ""), ("DATE_LIMIT_2", ""),
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


def _search(s: requests.Session, date_from: str, date_to: str) -> str:
    params = [("DATE_PARUTION_1", date_from), ("DATE_PARUTION_2", date_to)] + SEARCH_PARAMS
    r = s.get(BASE + "/listresultatao", params=params, timeout=30)
    r.raise_for_status()
    return r.text


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
        "montant":          "",
        "secteur":          classify(full_text),
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
        log_fn("⚠ Global Marches: GM_USERNAME/GM_PASSWORD non configurés")
        return []

    log_fn("═══ Global Marches — Appels d'offres privés ═══")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    try:
        if not _login(s):
            log_fn("❌ Global Marches: échec de connexion (identifiants invalides ?)")
            return []
    except Exception as e:
        log_fn(f"❌ Global Marches: erreur connexion — {e}")
        logger.error(f"[gm login] {e}", exc_info=True)
        return []

    # Fenêtre de quelques jours en arrière pour couvrir tout intervalle de scan
    # manqué (redéploiement, panne...), le dédoublonnage se fait via known_ids.
    date_to   = datetime.now().strftime("%d/%m/%Y")
    date_from = (datetime.now() - timedelta(days=3)).strftime("%d/%m/%Y")

    try:
        html = _search(s, date_from, date_to)
    except Exception as e:
        log_fn(f"❌ Global Marches: erreur recherche — {e}")
        logger.error(f"[gm search] {e}", exc_info=True)
        return []

    results = []
    for row_m in ROW_RE.finditer(html):
        t = _parse_row(row_m.group(1))
        if not t or t["id"] in known_ids:
            continue
        results.append(t)
        log_fn(f"✓ {t['id']} │ {t['secteur'][:16]:16} │ {t['objet'][:45]}")

    log_fn(f"═══ {len(results)} nouveaux marchés privés ═══")
    return results
