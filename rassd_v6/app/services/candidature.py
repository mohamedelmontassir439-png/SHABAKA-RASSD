"""Le dossier de candidature d'un membre pour un marché.

Trois pièces suivent les modèles officiels de l'arrêté n° 1689-23 du
3 juillet 2023 (BO n° 7222 du 17/08/2023), pris pour l'application de
l'article 153 du décret n° 2-22-431 du 8 mars 2023:
- la déclaration sur l'honneur (modèle 9-1);
- l'acte d'engagement (modèle 1-1);
- le bordereau des prix-détail estimatif (modèle 5).

Elles sont préremplies avec la fiche de l'entreprise (saisie une fois) et
l'objet du marché, et le bordereau calcule ses totaux. Le membre imprime,
signe et cachète: la plateforme ne remplace pas la signature.
"""
import json
import re
from datetime import datetime

from app.core.database import get_db

# (clé, libellé fr, libellé ar, obligatoire)
CHAMPS = (
    ("statut", "Statut", "الصفة القانونية", True),
    ("raison_sociale", "Raison sociale", "الاسم التجاري", True),
    ("forme_juridique", "Forme juridique (SARL, SA…)", "الشكل القانوني", False),
    ("capital", "Capital social (MAD)", "رأس المال (درهم)", False),
    ("signataire", "Nom et prénom du signataire", "اسم الموقّع", True),
    ("qualite", "Qualité du signataire (gérant…)", "صفة الموقّع", True),
    ("adresse_siege", "Adresse du siège social", "عنوان المقر الاجتماعي", True),
    ("domicile_elu", "Adresse du domicile élu", "عنوان الموطن المختار", False),
    ("telephone", "Téléphone", "الهاتف", True),
    ("fax", "Fax", "الفاكس", False),
    ("email", "Adresse électronique", "البريد الإلكتروني", True),
    ("cnss", "N° d'affiliation CNSS", "رقم الانخراط في الضمان الاجتماعي", True),
    ("rc_ville", "Registre du commerce de (ville)", "السجل التجاري بمدينة", True),
    ("rc", "N° du registre du commerce", "رقم السجل التجاري", True),
    ("tp", "N° de taxe professionnelle", "رقم الرسم المهني", True),
    ("ice", "Identifiant commun de l'entreprise (ICE)", "المعرّف الموحد للمقاولة (ICE)", True),
    ("rib_type", "Compte", "نوع الحساب", True),
    ("rib", "RIB (24 chiffres)", "رقم الحساب البنكي RIB (24 رقماً)", True),
    ("rib_ville", "Banque: localité de l'agence", "مدينة الوكالة البنكية", False),
    ("ville_signature", "Fait à (ville)", "حُرّر بـ (المدينة)", False),
)
STATUTS = ("societe", "personne_physique", "auto_entrepreneur", "cooperative")
RIB_TYPES = ("bancaire", "postal", "TGR")


def _tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS profils_soumission(
        member_id INTEGER PRIMARY KEY, donnees TEXT DEFAULT '{}', maj TEXT DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS dossiers_offre(
        member_id INTEGER, tender_id TEXT, donnees TEXT DEFAULT '{}', maj TEXT DEFAULT '',
        PRIMARY KEY(member_id, tender_id))""")


def profil(member_id: int, membre: dict = None) -> dict:
    db = get_db()
    try:
        _tables(db)
        r = db.execute("SELECT donnees FROM profils_soumission WHERE member_id=?", (member_id,)).fetchone()
    finally:
        db.close()
    p = json.loads(r[0]) if r else {}
    if membre:
        # Ce que l'inscription connaît déjà, tant que la fiche ne dit pas autre chose.
        p.setdefault("raison_sociale", membre.get("company") or "")
        p.setdefault("signataire", membre.get("nom") or "")
        p.setdefault("telephone", membre.get("phone") or "")
        p.setdefault("email", membre.get("email") or "")
    p.setdefault("statut", "societe")
    p.setdefault("rib_type", "bancaire")
    return p


def nettoyer_profil(form: dict) -> dict:
    p = {}
    for cle, *_ in CHAMPS:
        p[cle] = re.sub(r"\s+", " ", str(form.get(cle) or "")).strip()[:300]
    if p["statut"] not in STATUTS:
        p["statut"] = "societe"
    if p["rib_type"] not in RIB_TYPES:
        p["rib_type"] = "bancaire"
    return p


def erreurs_profil(p: dict) -> list:
    """Les champs à corriger, en clés: ['rib', 'ice']."""
    e = []
    rib = re.sub(r"\D", "", p.get("rib") or "")
    if rib and len(rib) != 24:
        e.append("rib")
    ice = re.sub(r"\D", "", p.get("ice") or "")
    if ice and len(ice) != 15:
        e.append("ice")
    return e


def manquants(p: dict) -> list:
    morale = p.get("statut") in ("societe", "cooperative")
    sans = {"rc_ville", "rc", "tp", "cnss"} if p.get("statut") == "auto_entrepreneur" else set()
    return [c for c, _f, _a, obl in CHAMPS
            if obl and c not in sans and not (p.get(c) or "").strip()
            and (morale or c not in ("raison_sociale",))]


def enregistrer_profil(member_id: int, p: dict):
    db = get_db()
    try:
        _tables(db)
        db.execute("""INSERT INTO profils_soumission(member_id, donnees, maj) VALUES(?,?,?)
                      ON CONFLICT(member_id) DO UPDATE SET donnees=excluded.donnees, maj=excluded.maj""",
                   (member_id, json.dumps(p, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
        db.commit()
    finally:
        db.close()


# ─── Le dossier d'un marché ─────────────────────────────────────────────

def nombre(texte) -> float:
    """« 1 234,56 », « 1.234,56 », « 1234.5 » -> 1234.56."""
    s = re.sub(r"[^\d.,-]", "", str(texte or ""))
    if not s:
        return 0.0
    m = re.match(r"^(.*?)[.,](\d{1,2})$", s)
    entier = re.sub(r"\D", "", m.group(1) if m else s)
    try:
        return float(f"{entier or 0}.{m.group(2)}" if m else entier or 0)
    except ValueError:
        return 0.0


def dossier(member_id: int, tid: str) -> dict:
    db = get_db()
    try:
        _tables(db)
        r = db.execute("SELECT donnees FROM dossiers_offre WHERE member_id=? AND tender_id=?",
                       (member_id, tid)).fetchone()
    finally:
        db.close()
    d = json.loads(r[0]) if r else {}
    d.setdefault("lignes", [])
    d.setdefault("tva", 20.0)
    d.setdefault("rabais", "")
    return d


def enregistrer_dossier(member_id: int, tid: str, d: dict):
    db = get_db()
    try:
        _tables(db)
        db.execute("""INSERT INTO dossiers_offre(member_id, tender_id, donnees, maj) VALUES(?,?,?,?)
                      ON CONFLICT(member_id, tender_id) DO UPDATE SET donnees=excluded.donnees, maj=excluded.maj""",
                   (member_id, tid, json.dumps(d, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
        db.commit()
    finally:
        db.close()


def lignes_depuis_formulaire(form) -> list:
    """Les lignes du bordereau envoyées par la page (n_i, des_i, u_i, q_i, pu_i)."""
    lignes = []
    for i in range(400):
        des = (form.get(f"des_{i}") or "").strip()
        if not des and f"des_{i}" not in form:
            break
        if not des:
            continue
        lignes.append({"n": (form.get(f"n_{i}") or "").strip()[:12], "designation": des[:400],
                       "unite": (form.get(f"u_{i}") or "").strip()[:20],
                       "quantite": nombre(form.get(f"q_{i}")), "pu": nombre(form.get(f"pu_{i}"))})
    return lignes


def totaux(lignes: list, tva: float) -> dict:
    for l in lignes:
        l["total"] = round(l.get("quantite", 0) * l.get("pu", 0), 2)
    ht = round(sum(l["total"] for l in lignes), 2)
    montant_tva = round(ht * tva / 100, 2)
    return {"ht": ht, "tva": tva, "montant_tva": montant_tva, "ttc": round(ht + montant_tva, 2),
            "complet": bool(lignes) and all(l.get("pu") for l in lignes)}


def chiffres(v: float) -> str:
    """1234567.8 -> « 1 234 567,80 »."""
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


# ─── Montants en lettres ────────────────────────────────────────────────

_UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
           "onze", "douze", "treize", "quatorze", "quinze", "seize"]
_DIZAINES = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _moins_de_cent(n: int) -> str:
    if n <= 16:
        return _UNITES[n]
    if n < 20:
        return "dix-" + _UNITES[n - 10]
    d, u = divmod(n, 10)
    if d in (7, 9):
        base = "soixante" if d == 7 else "quatre-vingt"
        reste = 10 + u
        if d == 7 and u == 1:
            return "soixante et onze"
        return base + "-" + _moins_de_cent(reste)
    if d == 8:
        return "quatre-vingts" if u == 0 else "quatre-vingt-" + _UNITES[u]
    base = _DIZAINES[d]
    if u == 0:
        return base
    if u == 1:
        return base + " et un"
    return base + "-" + _UNITES[u]


def _moins_de_mille(n: int) -> str:
    c, r = divmod(n, 100)
    if c == 0:
        return _moins_de_cent(r)
    tete = "cent" if c == 1 else _UNITES[c] + " cent"
    if r == 0:
        return tete + ("s" if c > 1 else "")
    return tete + " " + _moins_de_cent(r)


def en_lettres_entier(n: int) -> str:
    if n == 0:
        return "zéro"
    morceaux = []
    for valeur, sing, plur in ((10**9, "milliard", "milliards"), (10**6, "million", "millions")):
        q, n = divmod(n, valeur)
        if q:
            morceaux.append(f"{en_lettres_entier(q)} {sing if q == 1 else plur}")
    q, n = divmod(n, 1000)
    if q:
        # « mille » est invariable; « quatre-vingts » et « deux cents » perdent
        # leur s devant lui.
        if q == 1:
            morceaux.append("mille")
        else:
            m = _moins_de_mille(q)
            if m.endswith(("cents", "vingts")):
                m = m[:-1]
            morceaux.append(m + " mille")
    if n:
        morceaux.append(_moins_de_mille(n))
    return " ".join(morceaux)


def en_lettres(montant: float) -> str:
    """234567.4 -> « deux cent trente-quatre mille cinq cent soixante-sept
    dirhams et quarante centimes »."""
    entier = int(round(montant * 100)) // 100
    centimes = int(round(montant * 100)) % 100
    texte = en_lettres_entier(entier) + (" dirham" if entier <= 1 else " dirhams")
    if entier >= 10**6 and entier % 10**6 == 0:
        texte = texte.replace(" dirhams", " de dirhams")
    if centimes:
        texte += " et " + en_lettres_entier(centimes) + (" centime" if centimes == 1 else " centimes")
    return texte


# ─── Ce que le dossier doit contenir ────────────────────────────────────

def pieces(t: dict, admin: list, d: dict, p: dict) -> list:
    """Les pièces du dossier, groupées, avec leur état pour ce membre.

    Liste de base de l'article 28 du décret n° 2-22-431; le règlement de
    consultation de chaque marché peut en ajouter (attestations de référence,
    chiffre d'affaires…): on le rappelle sur la page.
    """
    etat_admin = {x["code"]: x["etat"] for x in (admin or [])}
    from app.core.conditions import conditions_avis
    cond = conditions_avis(t.get("description") or "")
    caution = cond.get("caution", "")
    profil_ok = not manquants(p)
    tot = totaux([dict(l) for l in d.get("lignes", [])], d.get("tva", 20))

    def coffre(code):
        e = etat_admin.get(code)
        return "ok" if e == "ok" else ("a_faire" if e else "a_verifier")

    groupes = [
        ("admin", [
            ("declaration", "ok" if profil_ok else "a_faire", "doc"),
            ("caution", "a_faire" if caution and re.search(r"[1-9]", caution) else "sans_objet", "/financement"),
            ("pouvoirs", "a_verifier", ""),
            ("fiscale", coffre("fiscale"), "/coffre"),
            ("cnss", coffre("cnss"), "/coffre"),
            ("rc", coffre("rc"), "/coffre"),
        ]),
        ("technique", [
            ("qualification", coffre("qualification") if cond.get("qualifications") else "sans_objet", "/coffre"),
            ("moyens", "a_verifier", ""),
            ("references", "a_verifier", ""),
        ]),
        ("financier", [
            ("acte", "ok" if profil_ok and tot["complet"] else "a_faire", "doc"),
            ("bordereau", "ok" if tot["complet"] else "a_faire", "doc"),
        ]),
    ]
    return [{"groupe": g, "pieces": [{"cle": c, "etat": e, "lien": l} for c, e, l in ps]} for g, ps in groupes]


def mode_rabais(t: dict) -> bool:
    """Appel d'offres au rabais ou à majoration: l'acte porte un pourcentage."""
    texte = ((t.get("description") or "") + " " + (t.get("objet") or "")).lower()
    return bool(re.search(r"au rabais|à majoration|a majoration|rabais ou majoration", texte))


def procedure(t: dict) -> str:
    """« Appel d'offres ouvert · Sur offre de prix » -> « ouvert sur offre de prix »,
    pour suivre « Appel d'offres » dans l'acte d'engagement."""
    import re as _re
    from app.core.conditions import conditions_avis
    p = conditions_avis(t.get("description") or "").get("procedure", "")
    p = _re.sub(r"(?i)^\s*appel d.offres\s*", "", p)
    p = _re.sub(r"\s*[·|]\s*", " ", p).strip().lower()
    return p


def reference(t: dict) -> str:
    m = re.search(r"R[ée]f[ée]rence\s*:?\s*(\S+)", t.get("description") or "")
    return m.group(1) if m else ""
