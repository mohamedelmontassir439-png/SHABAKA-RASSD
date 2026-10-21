# -*- coding: utf-8 -*-
"""Le coffre du dossier administratif: les pièces, leur validité, les rappels.

Une offre est écartée avant d'être lue quand une pièce du dossier
administratif manque ou a expiré — l'attestation fiscale, celle de la CNSS,
le certificat de qualification. L'entreprise le découvre la veille du dépôt,
parfois le jour de l'ouverture des plis. Le coffre garde les pièces, sait
quand chacune expire, prévient avant, et dit pour chaque marché si le
dossier tient jusqu'à la date limite.

Les durées proposées sont celles que les acheteurs appliquent le plus
souvent; elles restent modifiables, car c'est la date écrite sur la pièce
qui fait foi, pas notre règle.

Les fichiers sont rangés à côté de la base (volume persistant), sous un
nom aléatoire: aucun nom fourni par l'utilisateur ne touche le disque.
"""
import json
import logging
import os
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta

from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.coffre")

DOSSIER = os.path.join(os.path.dirname(cfg.DB_PATH) or "data", "coffre")
TAILLE_MAX = 10 * 1024 * 1024
EXTENSIONS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".png": "image/png"}
# Les premiers octets de chaque format: un fichier doit être ce que son
# extension annonce.
SIGNATURES = {".pdf": b"%PDF", ".png": bytes.fromhex("89504e47"),
              ".jpg": bytes.fromhex("ffd8"), ".jpeg": bytes.fromhex("ffd8")}
# Seuils de rappel avant expiration, en jours.
RAPPELS = (30, 7)

# code: (libellé fr, libellé ar, validité en mois proposée ou None, requise
# pour un appel d'offres, aide fr, aide ar)
TYPES = {
    "fiscale": ("Attestation de régularité fiscale", "شهادة الوضعية الجبائية", 12, True,
                "Délivrée par la DGI. Les acheteurs l'exigent datée de moins d'un an.",
                "تسلّمها المديرية العامة للضرائب. يشترط أصحاب المشاريع ألّا يتجاوز تاريخها سنة."),
    "cnss": ("Attestation d'affiliation CNSS", "شهادة الانخراط في الضمان الاجتماعي", 12, True,
             "Atteste que l'entreprise est à jour de ses déclarations. Moins d'un an.",
             "تثبت أنّ المقاولة أدّت تصريحاتها. أقلّ من سنة."),
    "rc": ("Certificat d'immatriculation au RC", "شهادة التسجيل في السجلّ التجاري", 3, True,
           "Modèle 7 ou 9. Beaucoup d'acheteurs le veulent récent : trois mois est prudent.",
           "النموذج 7 أو 9. كثير من أصحاب المشاريع يطلبونه حديثًا: ثلاثة أشهر أحوط."),
    "qualification": ("Certificat de qualification et classification",
                      "شهادة التأهيل والتصنيف", None, False,
                      "Pour les travaux et études : sa date d'expiration est écrite dessus.",
                      "للأشغال والدراسات: تاريخ انتهائها مكتوب عليها."),
    "agrement": ("Agrément", "الاعتماد", None, False,
                 "Exigé par certains marchés (études, laboratoires, gardiennage…).",
                 "تشترطه بعض الصفقات (الدراسات، المختبرات، الحراسة…)."),
    "taxe_pro": ("Attestation de taxe professionnelle", "شهادة الرسم المهني", 12, False,
                 "Anciennement patente.", "الضريبة المهنية سابقًا."),
    "statuts": ("Statuts de la société", "النظام الأساسي للشركة", None, False,
                "Sans date d'expiration ; à remplacer après une modification.",
                "بلا تاريخ انتهاء؛ يُعوَّض بعد أيّ تعديل."),
    "pouvoirs": ("Pouvoirs du signataire", "تفويض الموقّع", None, False,
                 "Procuration ou PV désignant le gérant habilité à signer l'offre.",
                 "وكالة أو محضر يعيّن المسيّر المخوَّل له توقيع العرض."),
    "rib": ("Attestation bancaire / RIB", "شهادة بنكية / RIB", None, False,
            "Pour le paiement des décomptes.", "لأداء المستحقّات."),
    "assurance": ("Assurance responsabilité civile", "تأمين المسؤولية المدنية", 12, False,
                  "Souvent demandée avant l'ordre de service.", "تُطلب غالبًا قبل الأمر بالخدمة."),
    "references": ("Attestations de références", "شهادات المراجع", None, False,
                   "Attestations des marchés déjà exécutés.", "شهادات الصفقات المنجزة سابقًا."),
}


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _jour(texte: str):
    try:
        return datetime.strptime((texte or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def expiration_proposee(code: str, delivre_le: str) -> str:
    """La date d'expiration proposée à partir de la date de délivrance."""
    mois = TYPES.get(code, (None,) * 3)[2]
    d = _jour(delivre_le)
    if not mois or not d:
        return ""
    annee, m = divmod(d.month - 1 + mois, 12)
    jour = min(d.day, 28)
    return date(d.year + annee, m + 1, jour).isoformat()


def statut(expire_le: str, a_la_date: date = None) -> tuple:
    """(« valide » | « bientot » | « expire » | « permanent », jours restants)."""
    fin = _jour(expire_le)
    if not fin:
        return "permanent", None
    reste = (fin - (a_la_date or date.today())).days
    if reste < 0:
        return "expire", reste
    if reste <= RAPPELS[0]:
        return "bientot", reste
    return "valide", reste


# ─── Les pièces ──────────────────────────────────────────────────────────

def pieces(member_id: int) -> dict:
    """La pièce la plus récente de chaque type, avec son statut."""
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            "SELECT * FROM coffre_pieces WHERE member_id=? ORDER BY created_at DESC, id DESC",
            (member_id,)).fetchall()]
    finally:
        db.close()
    par_type = {}
    for p in lignes:
        if p["type"] not in par_type:
            p["statut"], p["reste"] = statut(p["expire_le"])
            par_type[p["type"]] = p
    return par_type


def _nom_lisible(nom: str) -> str:
    base = unicodedata.normalize("NFKD", nom or "piece")
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (base or "piece")[:80]


def enregistrer(member_id: int, code: str, contenu: bytes, nom_original: str,
                delivre_le: str = "", expire_le: str = "", libelle: str = "") -> tuple:
    """(True, id) ou (False, code d'erreur). Le fichier est vérifié avant écriture."""
    if code not in TYPES:
        return False, "type"
    ext = os.path.splitext(nom_original or "")[1].lower()
    if ext not in EXTENSIONS:
        return False, "format"
    if not contenu:
        return False, "vide"
    if len(contenu) > TAILLE_MAX:
        return False, "taille"
    # Le contenu doit être ce que l'extension annonce: un .pdf qui n'en est
    # pas un ne s'ouvrira pas chez l'acheteur non plus.
    signatures = SIGNATURES
    if not contenu.startswith(signatures[ext]):
        return False, "format"
    if delivre_le and not _jour(delivre_le):
        return False, "date"
    if expire_le and not _jour(expire_le):
        return False, "date"
    expire_le = expire_le or expiration_proposee(code, delivre_le)

    dossier = os.path.join(DOSSIER, str(int(member_id)))
    os.makedirs(dossier, exist_ok=True)
    fichier = secrets.token_hex(16) + ext
    with open(os.path.join(dossier, fichier), "wb") as f:
        f.write(contenu)
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO coffre_pieces(member_id,type,libelle,fichier,nom_original,taille,
                  delivre_le,expire_le,rappels_faits,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,'[]',?,?)""",
            (member_id, code, (libelle or "")[:120], fichier, _nom_lisible(nom_original),
             len(contenu), delivre_le, expire_le, _maintenant(), _maintenant()))
        db.commit()
        return True, cur.lastrowid
    finally:
        db.close()


def piece(member_id: int, piece_id: int):
    """Une pièce du membre — jamais celle d'un autre."""
    db = get_db()
    try:
        r = db.execute("SELECT * FROM coffre_pieces WHERE id=? AND member_id=?",
                       (piece_id, member_id)).fetchone()
    finally:
        db.close()
    return dict(r) if r else None


def chemin(p: dict) -> str:
    return os.path.join(DOSSIER, str(int(p["member_id"])), os.path.basename(p["fichier"]))


def supprimer(member_id: int, piece_id: int) -> bool:
    p = piece(member_id, piece_id)
    if not p:
        return False
    try:
        os.remove(chemin(p))
    except OSError:
        pass
    db = get_db()
    try:
        db.execute("DELETE FROM coffre_pieces WHERE id=? AND member_id=?", (piece_id, member_id))
        db.commit()
    finally:
        db.close()
    return True


# ─── Pour un marché ──────────────────────────────────────────────────────

def _limite(t: dict):
    try:
        return datetime.strptime((t.get("date_limite") or "")[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def pour_marche(member_id: int, t: dict) -> list:
    """Le dossier administratif face à ce marché: chaque pièce attendue, et
    si elle sera valide **à la date limite** — une attestation qui expire la
    veille du dépôt ne vaut rien ce jour-là.
    """
    from app.core.conditions import conditions_avis
    t = dict(t)
    attendues = [c for c, v in TYPES.items() if v[3]]
    if t.get("type_procedure") != "bon_commande" and (t.get("id") or "").startswith("ao_"):
        cond = conditions_avis(t.get("description") or "")
        if cond.get("qualifications"):
            attendues.append("qualification")
        if cond.get("agrements"):
            attendues.append("agrement")
    a_la_date = _limite(t) or date.today()
    mes = pieces(member_id)
    resultat = []
    for code in attendues:
        p = mes.get(code)
        if not p:
            etat = "manquante"
        else:
            s, _ = statut(p["expire_le"], a_la_date)
            etat = "ok" if s in ("valide", "bientot", "permanent") else "expiree_a_la_date"
        resultat.append({"code": code, "etat": etat, "piece": p})
    return resultat


# ─── Rappels ─────────────────────────────────────────────────────────────

def rappels_dus(aujourdhui: date = None) -> list:
    """Les pièces qui franchissent un seuil de rappel et n'ont pas été rappelées."""
    aujourdhui = aujourdhui or date.today()
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT p.*, m.email, m.nom FROM coffre_pieces p
               JOIN members m ON m.id = p.member_id
               WHERE p.expire_le != '' AND m.actif = 1""").fetchall()]
    finally:
        db.close()
    # Seule la pièce la plus récente d'un type compte: une ancienne
    # attestation remplacée n'a plus à sonner.
    recentes = {}
    for p in sorted(lignes, key=lambda x: (x["created_at"], x["id"]), reverse=True):
        recentes.setdefault((p["member_id"], p["type"]), p)
    dus = []
    for p in recentes.values():
        fin = _jour(p["expire_le"])
        if not fin:
            continue
        reste = (fin - aujourdhui).days
        faits = json.loads(p.get("rappels_faits") or "[]")
        seuil = next((s for s in sorted(RAPPELS) if reste <= s and s not in faits), None)
        if seuil is not None and reste >= -1:
            p["reste"], p["seuil"] = reste, seuil
            dus.append(p)
    return dus


def marquer_rappel(piece_id: int, seuil: int):
    db = get_db()
    try:
        r = db.execute("SELECT rappels_faits FROM coffre_pieces WHERE id=?", (piece_id,)).fetchone()
        faits = json.loads((r["rappels_faits"] if r else "") or "[]")
        # Un rappel à 7 jours rend inutile celui à 30, s'il n'était pas parti.
        faits = sorted(set(faits) | {s for s in RAPPELS if s >= seuil})
        db.execute("UPDATE coffre_pieces SET rappels_faits=? WHERE id=?", (json.dumps(faits), piece_id))
        db.commit()
    finally:
        db.close()


def envoyer_rappels(aujourdhui: date = None) -> int:
    """Un email par pièce qui approche de son expiration. Rend le nombre envoyé."""
    from app.services.notifications import email_send
    envoyes = 0
    for p in rappels_dus(aujourdhui):
        libelle = TYPES.get(p["type"], ("Pièce",))[0]
        quand = "aujourd'hui" if p["reste"] == 0 else (
            "est expirée" if p["reste"] < 0 else f"expire dans {p['reste']} jour(s)")
        sujet = f"{libelle} : {quand}"
        corps = (
            f'<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:22px;'
            f'background:#f8f1e1;color:#2b211b">'
            f'<p style="font-size:15px">Bonjour {p.get("nom") or ""},</p>'
            f'<p style="font-size:15px;line-height:1.6">Votre <b>{libelle}</b> '
            f'{"expire le " + p["expire_le"] if p["reste"] >= 0 else "a expiré le " + p["expire_le"]}. '
            f'Une pièce expirée à la date d\'ouverture des plis fait écarter l\'offre sans examen.</p>'
            f'<p style="font-size:15px;line-height:1.6">Demandez la nouvelle dès maintenant, puis '
            f'déposez-la dans votre coffre : les marchés que vous suivez seront revérifiés.</p>'
            f'<p style="text-align:center;margin:22px 0"><a href="{cfg.SITE_URL}/coffre" '
            f'style="background:#f2662d;color:#fff;padding:12px 22px;border-radius:9px;'
            f'text-decoration:none;font-weight:700">Ouvrir mon coffre</a></p></div>')
        if email_send(p["email"], sujet, corps):
            marquer_rappel(p["id"], p["seuil"])
            envoyes += 1
    return envoyes
