# -*- coding: utf-8 -*-
"""Le suivi des offres: chaque marché que l'entreprise prépare, étape par
étape, avec les rappels qui évitent de le perdre sur une date.

Préparer une offre, c'est tenir cinq échéances à la fois: la visite des
lieux, la caution à demander à la banque quelques jours avant, la date
limite des questions, le dépôt, l'ouverture des plis. Elles sont dans
l'avis; elles finissent dans un carnet, et l'une d'elles est oubliée. Le
suivi les tire de l'avis (app/core/conditions.py) et prévient à temps.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta

from app.core.conditions import conditions_avis
from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.suivi")

# Dans l'ordre où une offre avance.
ETAPES = ("etude", "preparation", "caution", "depose", "gagne", "perdu", "abandonne")
ACTIVES = ("etude", "preparation", "caution")
CLOSES = ("gagne", "perdu", "abandonne")
# Une caution se demande à la banque: quelques jours ouvrés.
DELAI_CAUTION = 7


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _jour(texte: str):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texte or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def ajouter(member_id: int, t: dict) -> int:
    db = get_db()
    try:
        db.execute(
            """INSERT OR IGNORE INTO suivi_offres(member_id,tender_id,objet,acheteur,date_limite,
                  etape,notes,montant_offre,rappels_faits,created_at,updated_at)
               VALUES(?,?,?,?,?,'etude','','','[]',?,?)""",
            (member_id, t["id"], (t.get("objet") or "")[:400], (t.get("acheteur") or "")[:200],
             t.get("date_limite") or "", _maintenant(), _maintenant()))
        db.commit()
        r = db.execute("SELECT id FROM suivi_offres WHERE member_id=? AND tender_id=?",
                       (member_id, t["id"])).fetchone()
        return r["id"] if r else 0
    finally:
        db.close()


def modifier(member_id: int, sid: int, etape: str = None, notes: str = None,
             montant_offre: str = None) -> bool:
    champs, valeurs = [], []
    if etape is not None:
        if etape not in ETAPES:
            return False
        champs.append("etape=?"); valeurs.append(etape)
    if notes is not None:
        champs.append("notes=?"); valeurs.append(notes.strip()[:2000])
    if montant_offre is not None:
        champs.append("montant_offre=?"); valeurs.append(montant_offre.strip()[:40])
    if not champs:
        return False
    db = get_db()
    try:
        cur = db.execute(f"UPDATE suivi_offres SET {', '.join(champs)}, updated_at=? "
                         "WHERE id=? AND member_id=?", (*valeurs, _maintenant(), sid, member_id))
        db.commit()
        return cur.rowcount > 0
    finally:
        db.close()


def retirer(member_id: int, sid: int):
    db = get_db()
    try:
        db.execute("DELETE FROM suivi_offres WHERE id=? AND member_id=?", (sid, member_id))
        db.commit()
    finally:
        db.close()


def pour_marche(member_id: int, tender_id: str):
    db = get_db()
    try:
        r = db.execute("SELECT * FROM suivi_offres WHERE member_id=? AND tender_id=?",
                       (member_id, tender_id)).fetchone()
    finally:
        db.close()
    return dict(r) if r else None


def echeances(t: dict, aujourdhui: date = None) -> list:
    """Les dates qui comptent pour ce marché, tirées de l'avis, dans l'ordre."""
    aujourdhui = aujourdhui or date.today()
    desc = (t or {}).get("description") or ""
    # Avis du portail, ou fiche de la source privée réécrite sous les mêmes
    # étiquettes (app/services/fiches_privees.py): les deux se lisent pareil.
    cond = conditions_avis(desc)
    limite = _jour(cond.get("limite") or t.get("date_limite") or "")
    liste = []
    if cond.get("visite") and _jour(cond["visite"]):
        liste.append(("visite", _jour(cond["visite"])))
    if cond.get("reunion") and _jour(cond["reunion"]):
        liste.append(("reunion", _jour(cond["reunion"])))
    if cond.get("echantillons") and _jour(cond["echantillons"]):
        liste.append(("echantillons", _jour(cond["echantillons"])))
    caution = cond.get("caution", "")
    if limite and caution and re.search(r"[1-9]", caution):
        liste.append(("caution", limite - timedelta(days=DELAI_CAUTION)))
    if limite:
        liste.append(("depot", limite))
    return [{"cle": c, "jour": j, "reste": (j - aujourdhui).days} for c, j in sorted(liste, key=lambda x: x[1])]


def tableau(member_id: int) -> dict:
    """Les offres suivies, rangées par étape, avec leur prochaine échéance."""
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT s.*, t.description, t.montant, t.region, t.secteur, t.statut, t.type_procedure
               FROM suivi_offres s LEFT JOIN tenders t ON t.id = s.tender_id
               WHERE s.member_id=? ORDER BY s.updated_at DESC""", (member_id,)).fetchall()]
    finally:
        db.close()
    par_etape = {e: [] for e in ETAPES}
    for l in lignes:
        l["id_marche"] = l["tender_id"]
        l["echeances"] = [e for e in echeances({"id": l["tender_id"], "description": l["description"],
                                                 "date_limite": l["date_limite"]}) if e["reste"] >= 0]
        l["prochaine"] = l["echeances"][0] if l["echeances"] else None
        par_etape.setdefault(l["etape"], []).append(l)
    return par_etape


# ─── Rappels ─────────────────────────────────────────────────────────────

# (clé d'échéance, jours avant) qui déclenchent un rappel.
SEUILS = {"visite": (2, 0), "reunion": (1,), "echantillons": (2,), "caution": (0,),
          "depot": (3, 1)}
LIBELLES = {"visite": "Visite des lieux", "reunion": "Réunion préparatoire",
            "echantillons": "Dépôt des échantillons", "caution": "Demander la caution provisoire",
            "depot": "Date limite de dépôt"}


def rappels_dus(aujourdhui: date = None) -> list:
    aujourdhui = aujourdhui or date.today()
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            f"""SELECT s.*, t.description, m.email, m.nom AS membre
                FROM suivi_offres s JOIN members m ON m.id = s.member_id
                LEFT JOIN tenders t ON t.id = s.tender_id
                WHERE m.actif = 1 AND s.etape IN ({','.join('?' * len(ACTIVES))})""",
            ACTIVES).fetchall()]
    finally:
        db.close()
    dus = []
    for l in lignes:
        faits = set(json.loads(l.get("rappels_faits") or "[]"))
        for e in echeances({"id": l["tender_id"], "description": l["description"],
                            "date_limite": l["date_limite"]}, aujourdhui):
            for seuil in SEUILS.get(e["cle"], ()):
                cle = f"{e['cle']}:{seuil}"
                # Une caution déjà demandée ne se rappelle plus.
                if e["cle"] == "caution" and l["etape"] == "caution":
                    continue
                if e["reste"] <= seuil and e["reste"] >= 0 and cle not in faits:
                    dus.append({"suivi": l, "echeance": e, "cle": cle})
                    break
    return dus


def envoyer_rappels(aujourdhui: date = None) -> int:
    from app.services.notifications import email_send
    par_membre = {}
    for d in rappels_dus(aujourdhui):
        par_membre.setdefault(d["suivi"]["member_id"], []).append(d)
    envoyes = 0
    for mid, liste in par_membre.items():
        s0 = liste[0]["suivi"]
        lignes = "".join(
            f'<div style="border:1px solid #e8dcc5;border-radius:10px;padding:12px 14px;margin-bottom:8px;'
            f'background:#fff"><div style="font-weight:700;color:#c94e1f">{LIBELLES[d["echeance"]["cle"]]} — '
            f'{d["echeance"]["jour"].strftime("%d/%m/%Y")}'
            f'{" (aujourd&#39;hui)" if d["echeance"]["reste"] == 0 else ""}</div>'
            f'<div style="color:#2b211b;margin-top:4px">{(d["suivi"]["objet"] or "")[:160]}</div></div>'
            for d in liste)
        sujet = f"{LIBELLES[liste[0]['echeance']['cle']]} : {liste[0]['echeance']['jour'].strftime('%d/%m')}" + (
            f" (+{len(liste) - 1})" if len(liste) > 1 else "")
        corps = (f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:22px;'
                 f'background:#f8f1e1"><p style="font-size:15px;color:#4a3b32">Bonjour {s0["membre"] or ""}, '
                 f'voici les échéances des offres que vous préparez :</p>{lignes}'
                 f'<p style="text-align:center;margin:20px 0"><a href="{cfg.SITE_URL}/suivi" '
                 f'style="background:#f2662d;color:#fff;padding:12px 22px;border-radius:9px;'
                 f'text-decoration:none;font-weight:700">Mon suivi des offres</a></p></div>')
        if email_send(s0["email"], sujet, corps):
            envoyes += 1
            db = get_db()
            try:
                for d in liste:
                    faits = set(json.loads(d["suivi"].get("rappels_faits") or "[]")) | {d["cle"]}
                    d["suivi"]["rappels_faits"] = json.dumps(sorted(faits))
                    db.execute("UPDATE suivi_offres SET rappels_faits=? WHERE id=?",
                               (d["suivi"]["rappels_faits"], d["suivi"]["id"]))
                db.commit()
            finally:
                db.close()
    return envoyes
