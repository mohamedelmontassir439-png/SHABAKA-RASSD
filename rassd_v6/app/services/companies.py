"""
Maroc Entrepreneuriat — Base entreprises (normalisation + déduplication)

Une même entreprise apparaît sous des orthographes très différentes selon la
source ("STE ATLAS BTP SARL", "Atlas B.T.P. s.a.r.l", "ATLAS BTP"). Ce module
ramène ces variantes à une forme canonique et attribue un score de confiance
avant de fusionner, plutôt que d'écraser des lignes sur une simple égalité de
chaîne.

Aucune provenance n'est perdue: chaque source ayant mentionné l'entreprise est
conservée dans company_sources, même après fusion.
"""
import logging
import re
import unicodedata
from datetime import datetime

logger = logging.getLogger("atlas.companies")

# Formes juridiques et préfixes commerciaux marocains courants: ils ne
# distinguent pas deux entreprises et parasitent le rapprochement.
_LEGAL_TOKENS = {
    "sarl", "sa", "sas", "sasu", "snc", "scs", "sca", "sarlau", "au",
    "ste", "societe", "soc", "eurl", "spa", "gie", "cie", "co",
    "etablissements", "ets", "entreprise", "ent", "groupe", "group",
    "et", "de", "du", "des", "la", "le", "les", "l", "d",
}

# Le champ "adjudicataire" contient parfois un état de procédure au lieu d'un
# nom d'entreprise ("Annulée.", "Voir détail des lots au niveau du PV").
# Une simple liste de mots ne suffit pas: ces libellés sont des phrases dont
# seuls certains mots sont des marqueurs. On rejette donc dès qu'un marqueur
# de procédure apparaît, quelle que soit sa position.
_PROCEDURE_RE = re.compile(
    r"\b(infructueux|infructueuse|annul\w*|neant|desert\w*|report\w*|"
    r"sans suite|non attribu\w*|declare\w*|voir|pv|lots?)\b"
)


def strip_accents(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_company_name(raw: str) -> str:
    """Forme canonique d'un nom d'entreprise, utilisée comme clé de rapprochement.

    'STE ATLAS B.T.P. SARL AU' et 'Atlas BTP' donnent tous deux 'atlas btp'.
    Retourne '' si le nom ne contient aucun élément distinctif.
    """
    if not raw:
        return ""
    txt = strip_accents(str(raw)).lower()
    # Sigles pointés d'abord: "B.T.P." et "s.a.r.l" doivent devenir "btp" et
    # "sarl", sinon la ponctuation les éclate en lettres isolées et deux
    # écritures du même nom ne se rapprochent plus.
    txt = re.sub(r"\b(?:[a-z]\.){2,}[a-z]?\b", lambda m: m.group(0).replace(".", ""), txt)
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    # Filet de sécurité pour les sigles espacés ("B T P" -> "btp")
    txt = re.sub(r"\b(?:[a-z] ){1,}[a-z]\b", lambda m: m.group(0).replace(" ", ""), txt)
    if _PROCEDURE_RE.search(txt):
        return ""
    tokens = [t for t in txt.split() if t and t not in _LEGAL_TOKENS and not t.isdigit()]
    if not tokens:
        return ""
    return " ".join(tokens)


def normalize_phone(raw: str) -> str:
    """Numéro marocain en format international sans '+' (212XXXXXXXXX)."""
    if not raw:
        return ""
    p = "".join(ch for ch in str(raw) if ch.isdigit())
    if p.startswith("00"):
        p = p[2:]
    if p.startswith("0") and len(p) == 10:
        p = "212" + p[1:]
    if p.startswith("212") and len(p) == 12:
        return p
    return p if 8 <= len(p) <= 15 else ""


def normalize_email(raw: str) -> str:
    if not raw:
        return ""
    e = str(raw).strip().lower().strip(".,;:")
    return e if re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", e) else ""


def normalize_website(raw: str) -> str:
    if not raw:
        return ""
    w = str(raw).strip().lower()
    w = re.sub(r"^https?://", "", w).rstrip("/")
    w = re.sub(r"^www\.", "", w)
    return w if "." in w else ""


def duplicate_score(a: dict, b: dict) -> int:
    """Score de rapprochement entre deux fiches entreprise.

    0 = entreprises différentes · 1 = doublon possible · 2 = doublon fort.
    Un identifiant officiel identique (ICE ou RC) suffit à conclure; sinon il
    faut le nom canonique plus un second signal concordant, pour éviter de
    fusionner deux sociétés homonymes de villes différentes.
    """
    ice_a, ice_b = (a.get("ice") or "").strip(), (b.get("ice") or "").strip()
    if ice_a and ice_a == ice_b:
        return 2
    rc_a, rc_b = (a.get("rc") or "").strip(), (b.get("rc") or "").strip()
    if rc_a and rc_a == rc_b:
        return 2

    na = a.get("normalized_name") or normalize_company_name(a.get("legal_name", ""))
    nb = b.get("normalized_name") or normalize_company_name(b.get("legal_name", ""))
    if not na or not nb:
        return 0

    if na == nb:
        corroborating = 0
        for field, norm in (("phone", normalize_phone), ("email", normalize_email),
                            ("website", normalize_website)):
            va, vb = norm(a.get(field, "")), norm(b.get(field, ""))
            if va and va == vb:
                corroborating += 1
        city_a, city_b = strip_accents(a.get("city", "")).lower(), strip_accents(b.get("city", "")).lower()
        if city_a and city_a == city_b:
            corroborating += 1
        return 2 if corroborating else 1

    return 0


def find_duplicate(db, candidate: dict):
    """Cherche une fiche existante correspondant au candidat.

    Le pré-filtre SQL se fait sur les identifiants officiels et le nom
    canonique (tous indexés) pour ne pas parcourir toute la table.
    """
    norm = candidate.get("normalized_name") or normalize_company_name(candidate.get("legal_name", ""))
    rows = []
    ice = (candidate.get("ice") or "").strip()
    if ice:
        rows += db.execute("SELECT * FROM companies WHERE ice=? AND ice!=''", (ice,)).fetchall()
    if norm:
        rows += db.execute("SELECT * FROM companies WHERE normalized_name=?", (norm,)).fetchall()
    best, best_score = None, 0
    for row in rows:
        score = duplicate_score(dict(row), candidate)
        if score > best_score:
            best, best_score = dict(row), score
    return best, best_score


def upsert_company(db, data: dict) -> tuple:
    """Insère ou enrichit une entreprise. Retourne (company_id, action).

    En cas de doublon, les champs vides de la fiche existante sont complétés
    par ceux du candidat — on enrichit sans jamais écraser une donnée déjà
    renseignée par une valeur vide.
    """
    now  = datetime.now().isoformat()
    name = (data.get("legal_name") or "").strip()
    norm = normalize_company_name(name)
    if not norm:
        return 0, "rejected"

    candidate = {
        "legal_name": name[:200],
        "trade_name": (data.get("trade_name") or "").strip()[:200],
        "normalized_name": norm,
        "sector": (data.get("sector") or "").strip()[:20],
        "subsector": (data.get("subsector") or "").strip()[:80],
        "city": (data.get("city") or "").strip()[:80],
        "region": (data.get("region") or "").strip()[:80],
        "address": (data.get("address") or "").strip()[:250],
        "phone": normalize_phone(data.get("phone", "")),
        "mobile": normalize_phone(data.get("mobile", "")),
        "email": normalize_email(data.get("email", "")),
        "website": normalize_website(data.get("website", "")),
        "ice": (data.get("ice") or "").strip()[:30],
        "if_num": (data.get("if_num") or "").strip()[:30],
        "rc": (data.get("rc") or "").strip()[:30],
        "source": (data.get("source") or "").strip()[:60],
        "source_url": (data.get("source_url") or "").strip()[:400],
        "source_type": (data.get("source_type") or "").strip()[:40],
    }

    existing, score = find_duplicate(db, candidate)
    if existing and score >= 1:
        updates, params = [], []
        for field in ("trade_name", "sector", "subsector", "city", "region", "address",
                      "phone", "mobile", "email", "website", "ice", "if_num", "rc"):
            if candidate[field] and not (existing.get(field) or "").strip():
                updates.append(f"{field}=?")
                params.append(candidate[field])
        updates.append("updated_at=?"); params.append(now)
        params.append(existing["id"])
        db.execute(f"UPDATE companies SET {', '.join(updates)} WHERE id=?", params)
        cid, action = existing["id"], ("merged" if score == 2 else "merged_weak")
    else:
        cur = db.execute(
            """INSERT INTO companies(legal_name,trade_name,normalized_name,sector,subsector,
               city,region,address,phone,mobile,email,website,ice,if_num,rc,
               source,source_url,source_type,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (candidate["legal_name"], candidate["trade_name"], candidate["normalized_name"],
             candidate["sector"], candidate["subsector"], candidate["city"], candidate["region"],
             candidate["address"], candidate["phone"], candidate["mobile"], candidate["email"],
             candidate["website"], candidate["ice"], candidate["if_num"], candidate["rc"],
             candidate["source"], candidate["source_url"], candidate["source_type"], now, now))
        cid, action = cur.lastrowid, "created"

    db.execute(
        "INSERT INTO company_sources(company_id,source,source_url,raw_name,seen_at) VALUES(?,?,?,?,?)",
        (cid, candidate["source"], candidate["source_url"], name[:200], now))
    return cid, action


def seed_from_tender_results(db, limit: int = 5000) -> dict:
    """Alimente la base entreprises depuis les adjudicataires déjà collectés.

    Ce sont des entreprises ayant réellement remporté un marché au Maroc: la
    source la plus fiable dont dispose la plateforme, et déjà présente en base.
    Les libellés qui ne sont pas des noms d'entreprise (marché infructueux,
    annulé...) sont écartés par normalize_company_name.
    """
    stats = {"scanned": 0, "created": 0, "merged": 0, "rejected": 0}
    rows = db.execute("""
        SELECT adjudicataire, secteur, region, MAX(scraped_at) AS seen, COUNT(*) AS wins
        FROM tender_results
        WHERE adjudicataire!='' AND LENGTH(TRIM(adjudicataire))>3
        GROUP BY UPPER(TRIM(adjudicataire))
        ORDER BY wins DESC LIMIT ?""", (limit,)).fetchall()
    for row in rows:
        stats["scanned"] += 1
        cid, action = upsert_company(db, {
            "legal_name": row["adjudicataire"],
            "sector": row["secteur"],
            "region": row["region"],
            "source": "tender_results",
            "source_type": "adjudication",
        })
        if action == "created":
            stats["created"] += 1
            db.execute("UPDATE companies SET wins=? WHERE id=?", (row["wins"], cid))
        elif action == "rejected":
            stats["rejected"] += 1
        else:
            stats["merged"] += 1
            db.execute("UPDATE companies SET wins=wins+? WHERE id=?", (row["wins"], cid))
    db.commit()
    logger.info(f"[companies] {stats}")
    return stats
