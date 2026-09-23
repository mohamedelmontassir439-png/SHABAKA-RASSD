"""Surveillance de la plateforme — personne ne regarde les logs.

Une veille qui s'arrête ne prévient pas: le site reste debout, les pages
s'affichent, et les membres cessent simplement de recevoir des marchés. Le
jour où quelqu'un s'en aperçoit, il est trop tard pour l'abonné qui a raté
une consultation.

Ce module compare l'état réel de la base à ce qu'on attend d'elle, envoie
une alerte immédiate quand un indicateur sort des clous, et un bilan
quotidien sur Telegram.
"""
import logging
import os
from datetime import datetime, timedelta

from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.supervision")

# Une collecte tourne toutes les heures: au-delà de 6 h sans le moindre
# marché, quelque chose est cassé (portail en panne, scraper en erreur,
# conteneur qui ne redémarre pas).
HEURES_SANS_MARCHE = 6
ECHECS_RUNS_ALERTE = 3      # sur 24 h
ECHECS_NOTIF_ALERTE = 10    # sur 24 h
JOURS_SANS_SAUVEGARDE = 2
# Dossier surveillé pour la fraîcheur des sauvegardes (les tests le déplacent).
DOSSIER_SAUVEGARDES = "data/backups"


def _un(db, sql, *params):
    ligne = db.execute(sql, params).fetchone()
    return ligne[0] if ligne else 0


def collecter_indicateurs() -> dict:
    """Photographie de l'état de la plateforme, sans interprétation."""
    db = get_db()
    try:
        dernier = _un(db, "SELECT MAX(scraped_at) FROM tenders") or ""
        heures = 999.0
        if dernier:
            try:
                heures = (datetime.now() - datetime.strptime(dernier[:19], "%Y-%m-%d %H:%M:%S")
                          ).total_seconds() / 3600
            except ValueError:
                pass
        ind = {
            "dernier_marche": dernier,
            "heures_sans_marche": round(heures, 1),
            "marches_actifs": _un(db, "SELECT COUNT(*) FROM tenders WHERE statut='actif'"),
            "marches_24h": _un(db, "SELECT COUNT(*) FROM tenders WHERE scraped_at>=datetime('now','-24 hours')"),
            "runs_echec_24h": _un(db, """SELECT COUNT(*) FROM scraper_runs
                                         WHERE status='FAILED' AND started_at>=datetime('now','-24 hours')"""),
            "notif_ok_24h": _un(db, """SELECT COUNT(*) FROM notif_log
                                       WHERE status='SENT' AND sent_at>=datetime('now','-24 hours')"""),
            "notif_echec_24h": _un(db, """SELECT COUNT(*) FROM notif_log
                                          WHERE status='FAILED' AND sent_at>=datetime('now','-24 hours')"""),
            "membres": _un(db, "SELECT COUNT(*) FROM members WHERE actif=1"),
            "essais": _un(db, "SELECT COUNT(*) FROM members WHERE subscription_status='TRIAL' AND actif=1"),
            "abonnes": _un(db, "SELECT COUNT(*) FROM members WHERE subscription_status='ACTIVE' AND actif=1"),
            "expirent_7j": _un(db, """SELECT COUNT(*) FROM members WHERE subscription_status='ACTIVE'
                                      AND subscription_end!='' AND subscription_end<=date('now','+7 day')"""),
            "annonces_st": _un(db, "SELECT COUNT(*) FROM subcontract_posts WHERE statut='actif'"),
            "entreprises": _un(db, "SELECT COUNT(*) FROM companies WHERE phone!='' OR email!=''"),
            "erreurs_24h": 0,
        }
        try:
            ind["erreurs_24h"] = _un(db, """SELECT COUNT(*) FROM error_log
                                            WHERE created_at>=datetime('now','-24 hours')""")
        except Exception:
            pass
    finally:
        db.close()

    # Fraîcheur des sauvegardes: le dossier vit à côté de la base.
    ind["heures_sauvegarde"] = 999.0
    try:
        dossier = DOSSIER_SAUVEGARDES
        fichiers = [os.path.join(dossier, f) for f in os.listdir(dossier)
                    if f.startswith("atlas_") and f.endswith(".db")]
        if fichiers:
            recent = max(os.path.getmtime(f) for f in fichiers)
            ind["heures_sauvegarde"] = round((datetime.now().timestamp() - recent) / 3600, 1)
    except OSError:
        pass
    return ind


def anomalies(ind: dict) -> list:
    """Ce qui mérite de réveiller quelqu'un, formulé en clair."""
    alertes = []
    if ind["heures_sans_marche"] > HEURES_SANS_MARCHE:
        alertes.append(f"Aucun marché collecté depuis {ind['heures_sans_marche']} h "
                       f"(dernier : {ind['dernier_marche'][:16] or 'jamais'})")
    if ind["runs_echec_24h"] >= ECHECS_RUNS_ALERTE:
        alertes.append(f"{ind['runs_echec_24h']} collecte(s) en échec sur 24 h")
    if ind["notif_echec_24h"] >= ECHECS_NOTIF_ALERTE:
        alertes.append(f"{ind['notif_echec_24h']} alerte(s) non délivrée(s) sur 24 h — "
                       f"vérifier l'expéditeur email")
    if ind["heures_sauvegarde"] > JOURS_SANS_SAUVEGARDE * 24:
        alertes.append(f"Aucune sauvegarde depuis {ind['heures_sauvegarde']} h")
    if ind["marches_actifs"] == 0:
        alertes.append("Aucun marché actif en base — le site est vide pour les membres")
    return alertes


def bilan_texte(ind: dict) -> str:
    """Bilan quotidien: court, chiffré, lisible sur un téléphone."""
    return "\n".join([
        f"📊 <b>Bilan du {datetime.now().strftime('%d/%m/%Y')}</b>",
        "",
        f"Marchés actifs : <b>{ind['marches_actifs']}</b>  (+{ind['marches_24h']} en 24 h)",
        f"Dernière collecte : il y a {ind['heures_sans_marche']} h",
        f"Alertes envoyées : {ind['notif_ok_24h']}"
        + (f"  ⚠️ {ind['notif_echec_24h']} en échec" if ind["notif_echec_24h"] else ""),
        "",
        f"Membres : <b>{ind['membres']}</b>  ·  essais : {ind['essais']}  ·  abonnés : {ind['abonnes']}"
        + (f"\n⏳ {ind['expirent_7j']} abonnement(s) expirent sous 7 jours" if ind["expirent_7j"] else ""),
        f"Sous-traitance : {ind['annonces_st']} annonce(s) · {ind['entreprises']} entreprise(s) contactables",
        "",
        (f"⚠️ {ind['erreurs_24h']} erreur(s) applicative(s) en 24 h" if ind["erreurs_24h"]
         else "✅ Aucune erreur applicative"),
        f"Sauvegarde : il y a {ind['heures_sauvegarde']} h",
    ])


def verifier(envoyer_bilan: bool = False) -> dict:
    """Vérifie, alerte si nécessaire, et renvoie les indicateurs.

    Les alertes ne sont pas répétées à chaque passage: une anomalie connue
    depuis moins de 6 heures ne redéclenche pas de message, sinon le canal
    devient du bruit et plus personne ne le lit.
    """
    from app.services.notifications import tg_admin

    ind = collecter_indicateurs()
    problemes = anomalies(ind)
    ind["anomalies"] = problemes

    if problemes:
        db = get_db()
        try:
            signature = " | ".join(problemes)[:300]
            deja = db.execute(
                """SELECT COUNT(*) FROM notif_log WHERE channel='supervision'
                   AND error=? AND sent_at>=datetime('now','-6 hours')""",
                (signature,)).fetchone()[0]
            if not deja:
                tg_admin("🚨 <b>Alerte plateforme</b>\n\n• " + "\n• ".join(problemes)
                         + f"\n\n{cfg.SITE_URL}/admin")
                db.execute("""INSERT INTO notif_log(member_id,tender_id,channel,sent_at,status,error)
                              VALUES(0,'supervision','supervision',?,'SENT',?)""",
                           (datetime.now().isoformat(), signature))
                db.commit()
                logger.warning(f"[supervision] alerte envoyée: {signature}")
        finally:
            db.close()

    if envoyer_bilan:
        tg_admin(bilan_texte(ind))
    return ind
