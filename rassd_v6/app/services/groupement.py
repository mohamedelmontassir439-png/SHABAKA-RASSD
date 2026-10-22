# -*- coding: utf-8 -*-
"""Former un groupement pour un marché qu'on ne peut pas porter seul.

Un marché exige deux qualifications et l'entreprise n'en a qu'une: elle
peut s'associer avec une autre, en groupement conjoint ou solidaire. Ce qui
manque, c'est de savoir qui. Les membres ont déclaré leurs qualifications
(app/services/eligibilite.py) et leur profil de sous-traitance: on propose
ceux qui comblent le manque.

La mise en relation respecte chacun: la proposition part avec le nom de la
société qui propose et son message; les coordonnées des deux ne sont
échangées que si le destinataire accepte.
"""
import json
import logging
from datetime import datetime

from app.core.config import cfg
from app.core.database import get_db
from app.services import eligibilite

logger = logging.getLogger("atlas.groupement")


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def partenaires(member_id: int, t: dict, limite: int = 12) -> list:
    """Les membres qui apportent ce qui manque pour ce marché.

    D'abord ceux qui détiennent une qualification exigée que le membre n'a
    pas (à la bonne classe); à défaut d'exigence lisible, ceux dont le
    profil de sous-traitance couvre le secteur du marché et qui se disent
    disponibles.
    """
    exigees = eligibilite.exigences(t.get("description") or "") if (t.get("id") or "").startswith("ao_") else []
    miennes = {q["code"]: q for q in eligibilite.mes_qualifications(member_id)}
    manquantes = [e for e in exigees if not (e["code"] in miennes and
                  eligibilite.rang(miennes[e["code"]]["classe"]) <= eligibilite.rang(e["classe"]))]
    db = get_db()
    try:
        candidats = {}
        if manquantes:
            for e in manquantes:
                for r in db.execute(
                        """SELECT q.member_id, q.code, q.classe, m.company, m.nom
                           FROM qualifs_membre q JOIN members m ON m.id = q.member_id
                           WHERE q.code=? AND q.member_id != ? AND m.actif = 1""",
                        (e["code"], member_id)).fetchall():
                    if eligibilite.rang(r["classe"]) <= eligibilite.rang(e["classe"]):
                        c = candidats.setdefault(r["member_id"], {"member_id": r["member_id"],
                                                                  "societe": r["company"] or r["nom"],
                                                                  "apports": []})
                        c["apports"].append(f"{r['code']} — classe {r['classe']}")
        if not candidats and t.get("secteur"):
            for r in db.execute(
                    """SELECT p.member_id, p.raison_sociale, p.metiers, p.zones, m.company, m.nom
                       FROM subcontract_profiles p JOIN members m ON m.id = p.member_id
                       WHERE p.disponible = 1 AND p.member_id != ? AND m.actif = 1""",
                    (member_id,)).fetchall():
                try:
                    metiers = json.loads(r["metiers"] or "[]")
                except ValueError:
                    metiers = []
                if t["secteur"] in metiers:
                    candidats[r["member_id"]] = {"member_id": r["member_id"],
                                                 "societe": r["raison_sociale"] or r["company"] or r["nom"],
                                                 "apports": []}
        deja = {r[0] for r in db.execute(
            "SELECT to_member FROM propositions_groupement WHERE from_member=? AND tender_id=?",
            (member_id, t.get("id") or "")).fetchall()}
    finally:
        db.close()
    liste = list(candidats.values())[:limite]
    for c in liste:
        c["deja"] = c["member_id"] in deja
    return {"manquantes": manquantes, "partenaires": liste}


def proposer(de: dict, a_id: int, t: dict, message: str) -> tuple:
    if a_id == de["id"]:
        return False, "soi"
    db = get_db()
    try:
        dest = db.execute("SELECT * FROM members WHERE id=? AND actif=1", (a_id,)).fetchone()
        if not dest:
            return False, "inconnu"
        if db.execute("SELECT 1 FROM propositions_groupement WHERE from_member=? AND to_member=? "
                      "AND tender_id=?", (de["id"], a_id, t["id"])).fetchone():
            return False, "deja"
        db.execute("""INSERT INTO propositions_groupement(tender_id,objet,from_member,to_member,message,
                         statut,created_at,updated_at) VALUES(?,?,?,?,?,'envoyee',?,?)""",
                   (t["id"], (t.get("objet") or "")[:300], de["id"], a_id, (message or "").strip()[:1500],
                    _maintenant(), _maintenant()))
        db.commit()
    finally:
        db.close()
    try:
        from app.services.notifications import email_send
        email_send(dest["email"], f"Proposition de groupement : {(t.get('objet') or '')[:70]}",
                   f'<div style="font-family:Arial,sans-serif;max-width:580px;margin:auto;padding:20px;'
                   f'background:#f8f1e1"><p><b>{de.get("company") or de.get("nom")}</b> vous propose de '
                   f'répondre ensemble, en groupement, au marché :</p><p><b>{(t.get("objet") or "")[:200]}</b></p>'
                   f'<p style="white-space:pre-wrap">{(message or "")[:1500]}</p>'
                   f'<p>Vos coordonnées ne lui sont communiquées que si vous acceptez.</p>'
                   f'<p style="text-align:center"><a href="{cfg.SITE_URL}/groupements" style="background:#f2662d;'
                   f'color:#fff;padding:11px 20px;border-radius:9px;text-decoration:none;font-weight:700">'
                   f'Répondre</a></p></div>')
    except Exception as e:
        logger.warning(f"[groupement] email: {e}")
    return True, "ok"


def repondre(member_id: int, pid: int, accepte: bool) -> bool:
    db = get_db()
    try:
        p = db.execute("SELECT * FROM propositions_groupement WHERE id=? AND to_member=? AND statut='envoyee'",
                       (pid, member_id)).fetchone()
        if not p:
            return False
        db.execute("UPDATE propositions_groupement SET statut=?, updated_at=? WHERE id=?",
                   ("acceptee" if accepte else "declinee", _maintenant(), pid))
        db.commit()
        de = db.execute("SELECT * FROM members WHERE id=?", (p["from_member"],)).fetchone()
        a = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    finally:
        db.close()
    try:
        from app.services.notifications import email_send
        if accepte:
            email_send(de["email"], f"Groupement accepté : {(p['objet'] or '')[:70]}",
                       f"<p><b>{a['company'] or a['nom']}</b> accepte de former un groupement pour "
                       f"« {(p['objet'] or '')[:200]} ».</p><p>Contact : {a['nom'] or ''} · "
                       f"{a['phone'] or ''} · {a['email']}</p>")
        else:
            email_send(de["email"], f"Proposition de groupement déclinée",
                       f"<p>{a['company'] or a['nom']} ne donne pas suite pour « {(p['objet'] or '')[:200]} ».</p>")
    except Exception as e:
        logger.warning(f"[groupement] réponse: {e}")
    return True


def mes_propositions(member_id: int) -> dict:
    db = get_db()
    try:
        recues = [dict(r) for r in db.execute(
            """SELECT p.*, m.company AS de_societe, m.nom AS de_nom, m.phone AS de_tel, m.email AS de_email
               FROM propositions_groupement p JOIN members m ON m.id = p.from_member
               WHERE p.to_member=? ORDER BY p.id DESC""", (member_id,)).fetchall()]
        envoyees = [dict(r) for r in db.execute(
            """SELECT p.*, m.company AS a_societe, m.nom AS a_nom, m.phone AS a_tel, m.email AS a_email
               FROM propositions_groupement p JOIN members m ON m.id = p.to_member
               WHERE p.from_member=? ORDER BY p.id DESC""", (member_id,)).fetchall()]
    finally:
        db.close()
    return {"recues": recues, "envoyees": envoyees}
