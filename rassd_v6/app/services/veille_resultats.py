# -*- coding: utf-8 -*-
"""Les résultats qui concernent un membre: un concurrent qui gagne, un
marché qu'il suivait qui est attribué.

L'entreprise qui a déposé une offre attend le résultat des semaines, et
le découvre souvent par hasard. Celle qui regarde un concurrent veut
savoir où il gagne. Les résultats arrivent chaque jour dans la base: il
suffit de les rapprocher de ce que chaque membre suit, et de le lui dire —
en un seul email par membre et par collecte, pas un par résultat.
"""
import logging
import re
import unicodedata
from datetime import datetime

from app.core.attribution import est_attribue
from app.core.config import cfg
from app.core.database import get_db
from app.services.companies import normalize_company_name

logger = logging.getLogger("atlas.veille_resultats")


def _empreinte(objet: str) -> str:
    """Même signature que main._empreinte: casse, accents et ponctuation ôtés."""
    base = unicodedata.normalize("NFD", (objet or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", base).strip()[:110]


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Concurrents suivis ──────────────────────────────────────────────────

def suivre(member_id: int, nom: str) -> bool:
    cle = normalize_company_name(nom or "")
    if len(cle) < 3:
        return False
    db = get_db()
    try:
        db.execute("""INSERT OR IGNORE INTO concurrents_suivis(member_id,nom,nom_norm,created_at)
                      VALUES(?,?,?,?)""", (member_id, nom.strip()[:120], cle, _maintenant()))
        db.commit()
    finally:
        db.close()
    return True


def ne_plus_suivre(member_id: int, nom: str):
    db = get_db()
    try:
        db.execute("DELETE FROM concurrents_suivis WHERE member_id=? AND nom_norm=?",
                   (member_id, normalize_company_name(nom or "")))
        db.commit()
    finally:
        db.close()


def suivis(member_id: int) -> list:
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM concurrents_suivis WHERE member_id=? ORDER BY created_at DESC",
            (member_id,)).fetchall()]
    finally:
        db.close()


# ─── Rapprochement des nouveaux résultats ────────────────────────────────

def _correspondances(nouveaux: list) -> dict:
    """{member_id: {"email", "nom", "concurrents": [...], "suivis": [...]}}."""
    if not nouveaux:
        return {}
    db = get_db()
    try:
        concurrents = [dict(r) for r in db.execute(
            """SELECT c.member_id, c.nom, c.nom_norm, m.email, m.nom AS membre
               FROM concurrents_suivis c JOIN members m ON m.id = c.member_id
               WHERE m.actif = 1""").fetchall()]
        try:
            offres = [dict(r) for r in db.execute(
                """SELECT s.member_id, s.objet, m.email, m.nom AS membre
                   FROM suivi_offres s JOIN members m ON m.id = s.member_id
                   WHERE m.actif = 1 AND s.etape NOT IN ('gagne', 'perdu', 'abandonne')""").fetchall()]
        except Exception:
            offres = []
    finally:
        db.close()

    par_membre = {}

    def case(mid, email, nom):
        return par_membre.setdefault(mid, {"email": email, "nom": nom,
                                           "concurrents": [], "suivis": []})

    for r in nouveaux:
        adj = r.get("adjudicataire") or ""
        if est_attribue(adj):
            norm = normalize_company_name(adj)
            for c in concurrents:
                if c["nom_norm"] and c["nom_norm"] in norm:
                    case(c["member_id"], c["email"], c["membre"])["concurrents"].append(r)
        empreinte = _empreinte(r.get("objet") or "")[:80]
        for o in offres:
            if empreinte and _empreinte(o["objet"] or "")[:80] == empreinte:
                case(o["member_id"], o["email"], o["membre"])["suivis"].append(r)
    return par_membre


def _ligne(r: dict) -> str:
    gagnant = r.get("adjudicataire") or "—"
    montant = r.get("montant") or ""
    return (f'<div style="border:1px solid #e2e1d8;border-radius:10px;padding:12px 14px;'
            f'margin-bottom:8px;background:#fff"><div style="font-weight:600;color:#14201b">'
            f'{(r.get("objet") or "")[:160]}</div><div style="font-size:13px;color:#68756e;'
            f'margin-top:5px">{(r.get("acheteur") or "")[:80]} · <b>{gagnant[:80]}</b>'
            f'{" · " + montant if montant else ""}</div></div>')


def notifier(nouveaux: list) -> int:
    """Un email par membre concerné. Rend le nombre d'emails envoyés."""
    from app.services.notifications import email_send
    envoyes = 0
    for mid, c in _correspondances(nouveaux).items():
        if not c["concurrents"] and not c["suivis"]:
            continue
        blocs = []
        if c["suivis"]:
            blocs.append('<h3 style="font-size:16px;color:#14201b">Résultat d\'un marché que vous suiviez</h3>'
                         + "".join(_ligne(r) for r in c["suivis"][:10]))
        if c["concurrents"]:
            blocs.append('<h3 style="font-size:16px;color:#14201b">Vos concurrents ont remporté</h3>'
                         + "".join(_ligne(r) for r in c["concurrents"][:10]))
        sujet = ("Résultat d'un marché que vous suiviez" if c["suivis"]
                 else f"{len(c['concurrents'])} marché(s) remporté(s) par vos concurrents")
        corps = (f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:22px;'
                 f'background:#f6f5f0"><p style="font-size:15px;color:#33413a">Bonjour {c["nom"] or ""},</p>'
                 + "".join(blocs) +
                 f'<p style="text-align:center;margin:20px 0"><a href="{cfg.SITE_URL}/intelligence" '
                 f'style="background:#b8863b;color:#fff;padding:12px 22px;border-radius:9px;'
                 f'text-decoration:none;font-weight:700">Voir l\'analyse</a></p></div>')
        if email_send(c["email"], sujet, corps):
            envoyes += 1
    if envoyes:
        logger.info(f"[veille_resultats] {envoyes} email(s)")
    return envoyes
