# -*- coding: utf-8 -*-
"""L'envoi des invitations par email à toutes les entreprises joignables.

Jusqu'ici l'email partait à la main, fiche par fiche. Le fondateur a choisi
le 20/10/2026 de l'envoyer à toutes les adresses collectées. Ce qui fait la
différence avec un publipostage tient alors dans ce que chaque message
contient et dans ceux qu'on ne contacte pas:

- **le contenu reste la preuve**: les marchés ouverts du secteur de
  l'entreprise (app/services/campagne.py). Sans marché ouvert, rien ne part;
- **un lien personnel**: l'invitation pré-remplit le profil et dit qui a
  ouvert et qui s'est inscrit;
- **on écarte**: « Pas intéressé », « Ne plus contacter », les abonnés et
  essais en cours, les entreprises déjà écrites par email, et les adresses
  déjà inscrites comme membres. Une même adresse ne reçoit qu'un message;
- **le quota**: Brevo gratuit accepte 295 envois par jour, inscriptions et
  alertes comprises. Un lot s'arrête à PLAFOND_JOUR pour leur laisser la
  place, et après trois échecs de suite — c'est le signe d'un quota épuisé
  ou d'une clé refusée, insister n'enverrait rien de plus.
"""
import asyncio
import logging
import secrets
from datetime import datetime

from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.envoi_lot")

PLAFOND_JOUR = 200
PAUSE_SECONDES = 4
ECHECS_DE_SUITE_MAX = 3

# Ceux à qui l'on n'écrit pas.
STATUTS_EXCLUS = ("refus", "ne_pas_contacter", "abonne", "essai")


class EnvoiState:
    running = False
    total = envoyes = echecs = ignores = 0
    started = finished = arret = ""
    logs: list = []

    @classmethod
    def log(cls, msg: str):
        cls.logs.append(f"{datetime.now().strftime('%H:%M:%S')} │ {msg}")
        del cls.logs[:-300]
        logger.info(f"[envoi] {msg}")

    @classmethod
    def etat(cls) -> dict:
        return {k: getattr(cls, k) for k in ("running", "total", "envoyes", "echecs",
                                              "ignores", "started", "finished", "arret")} \
            | {"logs": cls.logs[-40:]}


def candidats() -> list:
    """Les entreprises à inviter, une par adresse, dans l'ordre des marchés gagnés."""
    exclus = ",".join("?" * len(STATUTS_EXCLUS))
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            f"""SELECT c.* FROM companies c
                LEFT JOIN prospection p ON p.company_id = c.id
                WHERE TRIM(c.email) != ''
                  AND COALESCE(p.statut, 'a_appeler') NOT IN ({exclus})
                  AND NOT (COALESCE(p.canal, '') = 'email'
                           AND COALESCE(p.dernier_contact, '') != '')
                  AND LOWER(TRIM(c.email)) NOT IN
                      (SELECT LOWER(TRIM(email)) FROM members WHERE email != '')
                ORDER BY c.wins DESC, c.id""", STATUTS_EXCLUS).fetchall()]
    finally:
        db.close()
    vues, uniques = set(), []
    for c in lignes:
        adresse = c["email"].strip().lower()
        if adresse not in vues:
            vues.add(adresse)
            uniques.append(c)
    return uniques


def _jeton(db, cid: int) -> str:
    """Le lien personnel de l'entreprise — celui qu'elle a déjà, sinon un neuf.

    « Envoyée » ne se note qu'une fois l'email parti (_noter): un échec ne
    doit pas compter comme une invitation reçue.
    """
    ligne = db.execute("SELECT token FROM invitations WHERE company_id=? "
                       "ORDER BY created_at DESC", (cid,)).fetchone()
    if ligne:
        return ligne["token"]
    jeton = secrets.token_urlsafe(9)
    db.execute("""INSERT INTO invitations(token,company_id,canal,created_at,sent_at)
                  VALUES(?,?,'email',?,'')""", (jeton, cid, datetime.now().isoformat()))
    return jeton


def _noter(db, cid: int, jeton: str):
    maintenant = datetime.now().isoformat()
    db.execute("UPDATE invitations SET sent_at=?, canal='email' WHERE token=?",
               (maintenant, jeton))
    db.execute("""INSERT INTO prospection(company_id,statut,canal,notes,dernier_contact,
                     prochain_contact,appels,created_at,updated_at)
                  VALUES(?,'a_appeler','email','',?,'',0,?,?)
                  ON CONFLICT(company_id) DO UPDATE SET
                     canal='email', dernier_contact=excluded.dernier_contact,
                     updated_at=excluded.updated_at""",
               (cid, maintenant[:10], maintenant, maintenant))


async def envoyer(plafond: int = PLAFOND_JOUR, pause: float = PAUSE_SECONDES):
    """Envoie le lot en fond; la page suit EnvoiState."""
    from app.services.campagne import marches_du_secteur, message_email
    from app.services.notifications import email_send

    S = EnvoiState
    S.running, S.envoyes, S.echecs, S.ignores, S.arret = True, 0, 0, 0, ""
    S.logs, S.started, S.finished = [], datetime.now().isoformat(), ""
    try:
        liste = candidats()
        S.total = min(len(liste), plafond)
        S.log(f"{len(liste)} entreprises à inviter — lot de {S.total}")
        de_suite = 0
        for entreprise in liste:
            if S.envoyes >= plafond:
                S.arret = f"plafond du jour atteint ({plafond})"
                break
            # Sans marché ouvert dans le secteur, rien ne part — et aucun
            # lien n'est créé pour rien.
            if not marches_du_secteur(entreprise.get("sector", ""))[1]:
                S.ignores += 1
                S.log(f"— {entreprise['legal_name'][:50]}: aucun marché ouvert dans son secteur")
                continue
            db = get_db()
            try:
                jeton = _jeton(db, entreprise["id"])
                db.commit()
            finally:
                db.close()
            objet, corps = message_email(entreprise, f"{cfg.SITE_URL}/invitation/{jeton}")
            ok = await asyncio.to_thread(email_send, entreprise["email"], objet, corps)
            if ok:
                db = get_db()
                try:
                    _noter(db, entreprise["id"], jeton)
                    db.commit()
                finally:
                    db.close()
                S.envoyes += 1
                de_suite = 0
                S.log(f"✓ {entreprise['legal_name'][:50]} <{entreprise['email']}>")
            else:
                S.echecs += 1
                de_suite += 1
                S.log(f"✗ {entreprise['legal_name'][:50]} <{entreprise['email']}>")
                if de_suite >= ECHECS_DE_SUITE_MAX:
                    S.arret = "trois échecs de suite: quota Brevo épuisé ou clé refusée"
                    break
            await asyncio.sleep(pause)
        S.log(f"Terminé — {S.envoyes} envoyés, {S.echecs} échecs, {S.ignores} sans marché"
              + (f" · arrêt: {S.arret}" if S.arret else ""))
    except Exception as e:
        S.arret = f"erreur: {e}"
        S.log(S.arret)
        logger.exception("[envoi] lot interrompu")
    finally:
        S.running = False
        S.finished = datetime.now().isoformat()
