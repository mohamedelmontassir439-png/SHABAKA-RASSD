"""Sous-traitance: opportunités déduites des marchés attribués.

Une bourse d'annonces attend que quelqu'un publie. Avec deux membres, il ne
se passe rien. Or la plateforme sait une chose qu'aucune bourse d'annonces
ne sait: **qui vient de remporter quel marché, pour quel montant, et où**.
Une entreprise qui gagne un chantier d'assainissement de 48 millions aura
besoin de terrassement, d'électricité, de transport — avant même d'avoir
publié quoi que ce soit.

Ce module transforme donc les adjudications en pistes de sous-traitance, et
prévient les membres dont le métier correspond.
"""
import json
import logging
import re

from app.core.config import cfg
from app.core.database import get_db
from app.core.sectors import get_label

logger = logging.getLogger("atlas.soustraitance")

# Seuil en dirhams à partir duquel un marché attribué intéresse un
# sous-traitant: en dessous, l'attributaire exécute seul.
SEUIL_MONTANT = 300_000


def _liste(valeur) -> list:
    """Les filtres du membre sont stockés en JSON, parfois vides ou cassés."""
    if isinstance(valeur, list):
        return valeur
    try:
        v = json.loads(valeur or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def parse_montant(brut: str) -> float:
    """« 48 516 000,00 MAD », « 1.189.476.00 » → nombre.

    Le portail et l'agrégateur écrivent les montants dans des formats
    différents; un montant illisible vaut 0 plutôt qu'une exception.
    """
    if not brut:
        return 0.0
    texte = re.sub(r"[^\d,.]", "", str(brut))
    if not texte:
        return 0.0
    # Le dernier séparateur suivi de 1 ou 2 chiffres est décimal; les autres
    # séparent les milliers.
    m = re.search(r"[.,](\d{1,2})$", texte)
    decimales = m.group(1) if m else ""
    entier = texte[: m.start()] if m else texte
    entier = re.sub(r"[^\d]", "", entier)
    try:
        return float(f"{entier or 0}.{decimales or 0}")
    except ValueError:
        return 0.0


def _norm(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").strip().lower())


def opportunites_pour(member: dict, limite: int = 30, jours: int = 60) -> list:
    """Marchés récemment attribués qui correspondent au profil du membre.

    On ne propose jamais au membre un marché qu'il a lui-même remporté, ni
    un marché trop petit pour être sous-traité.
    """
    secteurs = _liste(member.get("secteurs"))
    if not secteurs:
        return []
    zones = [_norm(z) for z in _liste(member.get("regions") or member.get("notif_regions"))]

    db = get_db()
    try:
        ph = ",".join("?" * len(secteurs))
        lignes = [dict(r) for r in db.execute(
            f"""SELECT r.*, c.phone AS contact_phone, c.email AS contact_email,
                       c.city AS contact_ville, c.id AS company_id
                FROM tender_results r
                LEFT JOIN companies c
                       ON c.normalized_name = LOWER(TRIM(r.adjudicataire))
                WHERE r.adjudicataire != ''
                  AND r.secteur IN ({ph})
                  AND r.scraped_at >= datetime('now', ?)
                ORDER BY r.scraped_at DESC LIMIT 400""",
            secteurs + [f"-{int(jours)} days"]).fetchall()]
    finally:
        db.close()

    resultats = []
    ma_societe = _norm(member.get("company") or "")
    for ligne in lignes:
        if parse_montant(ligne.get("montant")) < SEUIL_MONTANT:
            continue
        if ma_societe and ma_societe == _norm(ligne.get("adjudicataire")):
            continue
        if zones:
            region = _norm(ligne.get("region"))
            if region and not any(z in region or region in z for z in zones):
                continue
        ligne["montant_num"] = parse_montant(ligne.get("montant"))
        ligne["secteur_label"] = get_label(ligne.get("secteur", ""))
        resultats.append(ligne)
        if len(resultats) >= limite:
            break
    return resultats


def message_de_contact(member: dict, opportunite: dict) -> str:
    """Texte prêt à envoyer à l'attributaire — le membre n'a qu'à l'adapter."""
    metier = get_label(opportunite.get("secteur", "")) or "notre spécialité"
    societe = member.get("company") or member.get("nom") or ""
    return (
        f"Bonjour, je vous contacte au sujet du marché « "
        f"{(opportunite.get('objet') or '')[:110]} » que vous venez de remporter"
        f"{' à ' + opportunite['region'] if opportunite.get('region') else ''}.\n\n"
        f"{societe} intervient en {metier} et peut prendre en charge une partie "
        f"des travaux en sous-traitance. Nous pouvons vous transmettre nos "
        f"références et un devis sous 48 heures.\n\n"
        f"Cordialement,\n{societe}"
    )


def membres_a_prevenir(post: dict) -> list:
    """Membres dont le métier et la zone correspondent à une annonce.

    On ne prévient jamais l'auteur de l'annonce, ni un membre sans accès.
    """
    from app.core.security import has_access

    db = get_db()
    try:
        membres = [dict(m) for m in db.execute(
            "SELECT * FROM members WHERE actif=1 AND id!=? AND email_verified=1",
            (post.get("member_id"),)).fetchall()]
    finally:
        db.close()

    secteur = post.get("secteur") or ""
    region = _norm(post.get("region"))
    retenus = []
    for m in membres:
        if not has_access(m):
            continue
        secteurs = _liste(m.get("secteurs"))
        if secteur and secteurs and secteur not in secteurs:
            continue
        zones = [_norm(z) for z in _liste(m.get("regions") or m.get("notif_regions"))]
        if region and zones and not any(z in region or region in z for z in zones):
            continue
        retenus.append(m)
    return retenus


def notifier_nouvelle_annonce(post: dict) -> int:
    """Alerte les sous-traitants concernés — sinon personne ne voit l'annonce.

    Les alertes marchés partaient déjà par email et Telegram; une annonce de
    sous-traitance restait, elle, invisible jusqu'à ce qu'un membre pense à
    consulter la page.
    """
    from app.services.notifications import email_send, tg_send

    lien = f"{cfg.SITE_URL}/sous-traitance/{post.get('id')}"
    titre = (post.get("titre") or "")[:120]
    lieu = post.get("region") or ""
    metier = get_label(post.get("secteur", ""))
    envoyes = 0
    for m in membres_a_prevenir(post):
        corps = f"""
        <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto">
          <h2 style="color:#1e1611;font-size:19px;margin:0 0 10px">Nouvelle demande de sous-traitance</h2>
          <p style="color:#4a4a4a;font-size:15px;line-height:1.7;margin:0 0 6px"><b>{titre}</b></p>
          <p style="color:#4a4a4a;font-size:14px;margin:0 0 18px">
            {metier}{' · ' + lieu if lieu else ''}
            {'· Budget indicatif : ' + post['budget'] if post.get('budget') else ''}
          </p>
          <a href="{lien}" style="display:inline-block;padding:12px 24px;background:#f2662d;
             color:#fff;border-radius:8px;text-decoration:none;font-weight:600">Proposer une offre</a>
          <p style="color:#98a1b3;font-size:11px;margin-top:22px">
            MAROC ENTREPRENEURIAT · <a href="{cfg.SITE_URL}/settings" style="color:#6b7488">Gérer mes alertes</a></p>
        </div>"""
        touche = False
        if m.get("notif_email") and m.get("email"):
            touche = email_send(m["email"], f"Sous-traitance : {titre[:60]}", corps) or touche
        if m.get("notif_tg") and m.get("telegram"):
            texte = (f"🤝 <b>Sous-traitance</b>\n\n<b>{titre}</b>\n{metier}"
                     f"{' · ' + lieu if lieu else ''}\n\n🔗 {lien}")
            touche = tg_send(m["telegram"], texte) or touche
        if touche:
            envoyes += 1
    if envoyes:
        logger.info(f"[sous-traitance] annonce {post.get('id')}: {envoyes} membre(s) prévenu(s)")
    return envoyes
