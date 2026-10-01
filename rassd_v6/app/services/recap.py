# -*- coding: utf-8 -*-
"""Le récapitulatif du jour d'un membre, à lui envoyer de la main à la main.

Le canal WhatsApp automatique demande un compte Meta approuvé et un modèle
de message validé. En attendant, l'envoi reste manuel — et c'est très bien
pour les premiers abonnés: un message écrit par le fondateur vaut mieux
qu'une notification de plus.

Ce qui manquait n'était pas le canal mais la matière: il fallait, pour
chaque membre, retrouver ses marchés du jour, les mettre en forme, et
produire un lien partageable. C'est ce que fait ce module.

Le lien est signé plutôt que stocké: l'adresse contient l'identifiant du
membre, la date, et une signature calculée avec la clé du serveur. Aucune
table, aucun nettoyage, et un lien qui ne vaut que pour un membre et un
jour — on ne peut pas deviner celui du voisin ni remonter dans le temps.
"""
import hashlib
import hmac
from datetime import date, datetime, timedelta

from app.core.config import cfg
from app.core.database import get_db
from app.core.sectors import get_label
from app.services.matching import matches

# Au-delà, le message devient un mur de texte que personne ne lit.
MAX_PAR_RECAP = 25
# Un lien de récapitulatif n'a pas vocation à survivre: il porte le jour.
JOURS_VALIDITE = 7


def _signature(member_id: int, jour: str) -> str:
    message = f"recap:{member_id}:{jour}".encode()
    return hmac.new(cfg.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:24]


def jeton(member_id: int, jour: str = "") -> str:
    """Le jeton d'un membre pour un jour: « 12-2026-10-01-a1b2c3… »."""
    jour = jour or date.today().strftime("%Y-%m-%d")
    return f"{member_id}-{jour}-{_signature(member_id, jour)}"


def lire_jeton(jeton_recu: str) -> tuple:
    """Rend (member_id, jour) si le jeton est authentique et récent, sinon (0, "").

    La comparaison est faite en temps constant: comparer deux signatures
    caractère par caractère laisse deviner la bonne, un octet à la fois.
    """
    morceaux = (jeton_recu or "").split("-")
    if len(morceaux) != 5:
        return 0, ""
    try:
        member_id = int(morceaux[0])
    except ValueError:
        return 0, ""
    jour, signature = "-".join(morceaux[1:4]), morceaux[4]
    if not hmac.compare_digest(signature, _signature(member_id, jour)):
        return 0, ""
    try:
        age = (date.today() - datetime.strptime(jour, "%Y-%m-%d").date()).days
    except ValueError:
        return 0, ""
    return (member_id, jour) if 0 <= age <= JOURS_VALIDITE else (0, "")


def marches_du_jour(member: dict, jour: str = "") -> list:
    """Les marchés collectés ce jour-là qui correspondent au profil du membre.

    On repart du moteur de correspondance plutôt que du journal d'envoi: le
    récapitulatif doit montrer ce qui concerne le membre, qu'une alerte soit
    partie ou non.
    """
    jour = jour or date.today().strftime("%Y-%m-%d")
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT * FROM tenders
               WHERE statut='actif' AND DATE(REPLACE(scraped_at,'T',' ')) = ?
               ORDER BY scraped_at DESC LIMIT 600""", (jour,)).fetchall()]
    finally:
        db.close()
    retenus = [t for t in lignes if matches(member, t)[0]]
    return retenus[:MAX_PAR_RECAP]


def message_whatsapp(member: dict, nombre: int, lien: str) -> str:
    """Le texte que le fondateur enverra, déjà écrit.

    Court volontairement: un message long sur WhatsApp se lit mal et ne
    s'envoie pas depuis un lien wa.me sans être tronqué.
    """
    prenom = (member.get("nom") or "").split()[0] if member.get("nom") else ""
    salut = f"Bonjour {prenom}," if prenom else "Bonjour,"
    if not nombre:
        return (f"{salut}\n\nAucun marché ne correspond à vos secteurs aujourd'hui. "
                f"Je vous écris dès qu'il y en a un.\n\nMaroc Entrepreneuriat")
    marche = "marché" if nombre == 1 else "marchés"
    return (f"{salut}\n\n{nombre} {marche} correspondant à vos secteurs ont été "
            f"publiés aujourd'hui. Le détail est ici :\n{lien}\n\n"
            f"Maroc Entrepreneuriat")


def membres_a_prevenir(jour: str = "") -> list:
    """Chaque membre actif, avec son compte de marchés du jour.

    Trié par nombre décroissant: on commence par ceux qui ont de quoi lire.
    """
    jour = jour or date.today().strftime("%Y-%m-%d")
    db = get_db()
    try:
        membres = [dict(m) for m in db.execute(
            "SELECT * FROM members WHERE actif=1 ORDER BY created_at DESC").fetchall()]
    finally:
        db.close()
    sortie = []
    for membre in membres:
        trouves = marches_du_jour(membre, jour)
        lien = f"{cfg.SITE_URL}/recap/{jeton(membre['id'], jour)}"
        sortie.append({
            "membre": membre,
            "nombre": len(trouves),
            "lien": lien,
            "message": message_whatsapp(membre, len(trouves), lien),
        })
    sortie.sort(key=lambda x: x["nombre"], reverse=True)
    return sortie
