# -*- coding: utf-8 -*-
"""La campagne de prospection: par où commencer, et quoi envoyer.

Deux questions, une seule réponse: les marchés ouverts.

**Par où commencer.** Trois cent vingt-trois entreprises joignables, ce n'est
pas une liste à parcourir dans l'ordre alphabétique. La force d'un appel ne
vient pas du nombre d'entreprises d'un secteur mais du nombre de marchés
ouverts qu'on peut y citer: dire « il y a 107 marchés ouverts dans votre
domaine » à un fabricant de mobilier n'a rien à voir avec « il y en a 4 » à
un éditeur de logiciels. Le classement croise donc les deux, et le produit
des deux est l'ordre d'appel.

**Quoi envoyer.** Le message ne décrit pas la plateforme: il montre trois
marchés que l'entreprise peut encore déposer, avec acheteur et date limite.
C'est vérifiable en raccrochant, et c'est la seule chose qui distingue cet
envoi d'un démarchage.

Mesure du 02/10/2026: 1 777 marchés actifs, 323 entreprises joignables,
réparties sur six secteurs seulement.
"""
import logging

from app.core.config import cfg
from app.core.database import get_db
from app.core.sectors import get_label

logger = logging.getLogger("atlas.campagne")

# Trois marchés suffisent à prouver. Au-delà, le message devient un
# catalogue que personne ne lit jusqu'au bout.
MARCHES_PAR_MESSAGE = 3


def priorites(limite: int = 12) -> list:
    """Les secteurs par ordre d'appel: preuve disponible × entreprises à joindre.

    Un secteur sans marché ouvert ne vaut pas un appel aujourd'hui, quel que
    soit le nombre d'entreprises qu'il contient: on brûlerait des noms avec
    un argument faible. Il est donc exclu, pas classé en dernier.
    """
    db = get_db()
    try:
        ouverts = dict(db.execute(
            "SELECT secteur, COUNT(*) FROM tenders WHERE statut='actif' "
            "AND secteur!='' GROUP BY 1").fetchall())
        joignables = dict(db.execute(
            "SELECT sector, COUNT(*) FROM companies WHERE phone!='' "
            "AND sector!='' GROUP BY 1").fetchall())
        restants = dict(db.execute(
            """SELECT c.sector, COUNT(*) FROM companies c
               LEFT JOIN prospection p ON p.company_id = c.id
               WHERE c.phone!='' AND c.sector!=''
                 AND COALESCE(p.statut,'a_appeler') = 'a_appeler'
               GROUP BY 1""").fetchall())
    finally:
        db.close()

    lignes = []
    for secteur, n_entreprises in joignables.items():
        n_marches = ouverts.get(secteur, 0)
        if not n_marches:
            continue
        lignes.append({
            "secteur": secteur,
            "label": get_label(secteur) or secteur,
            "marches": n_marches,
            "entreprises": n_entreprises,
            "a_appeler": restants.get(secteur, 0),
            "force": n_marches * n_entreprises,
        })
    lignes.sort(key=lambda x: -x["force"])
    return lignes[:limite]


def villes_a_joindre(limite: int = 8) -> list:
    """Les villes où il reste des entreprises à appeler.

    On appelle une ville par séance: le script dit « et vous êtes à Rabat »,
    et changer de ville à chaque appel fait perdre cette phrase-là.
    """
    db = get_db()
    try:
        return [{"ville": v, "total": n, "a_appeler": r} for v, n, r in db.execute(
            """SELECT c.city, COUNT(*),
                      SUM(CASE WHEN COALESCE(p.statut,'a_appeler')='a_appeler' THEN 1 ELSE 0 END)
               FROM companies c LEFT JOIN prospection p ON p.company_id = c.id
               WHERE c.phone!='' AND c.city!=''
               GROUP BY 1 ORDER BY 2 DESC LIMIT ?""", (limite,)).fetchall()]
    finally:
        db.close()


def marches_du_secteur(secteur: str, limite: int = MARCHES_PAR_MESSAGE) -> tuple:
    """(les marchés à citer, le nombre total ouvert) pour un secteur."""
    if not secteur:
        return [], 0
    db = get_db()
    try:
        marches = [dict(r) for r in db.execute(
            """SELECT id, objet, acheteur, region, montant, date_limite
               FROM tenders WHERE statut='actif' AND secteur=?
               ORDER BY scraped_at DESC LIMIT ?""", (secteur, limite)).fetchall()]
        total = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND secteur=?",
                           (secteur,)).fetchone()[0]
    finally:
        db.close()
    return marches, total


def _accroche(entreprise: dict, total: int) -> str:
    metier = get_label(entreprise.get("sector", "")) or "votre domaine"
    ville = entreprise.get("city") or ""
    marche = "marché public ouvert" if total == 1 else "marchés publics ouverts"
    return (f"{total} {marche} en {metier}"
            + (f", et vous êtes à {ville}." if ville else "."))


def message_whatsapp(entreprise: dict, lien: str = "") -> str:
    """Le texte à envoyer sur WhatsApp, marchés compris.

    Volontairement court et sans mise en forme: WhatsApp n'affiche pas de
    tableau, et un message long se replie derrière « Lire la suite » —
    c'est-à-dire que la preuve disparaît avant d'avoir été lue.
    """
    marches, total = marches_du_secteur(entreprise.get("sector", ""))
    if not total:
        return ""
    lignes = [f"Bonjour, ici {cfg.FROM_NAME}.", "",
              f"Il y a actuellement {_accroche(entreprise, total)}", ""]
    for m in marches:
        objet = (m["objet"] or "")[:95]
        detail = " · ".join(x for x in [
            (m.get("acheteur") or "")[:42],
            f"limite {m['date_limite']}" if m.get("date_limite") else ""] if x)
        lignes.append(f"• {objet}" + (f"\n  {detail}" if detail else ""))
    lignes += ["", f"Votre lien personnel, {cfg.TRIAL_DAYS} jours gratuits, sans carte :",
               lien or f"{cfg.SITE_URL}", "",
               "Si vous ne souhaitez plus être contacté, répondez STOP et nous "
               "retirons vos coordonnées."]
    return "\n".join(lignes)


def message_email(entreprise: dict, lien: str = "") -> tuple:
    """(objet, corps HTML) de l'email, marchés compris.

    L'objet nomme le métier et le nombre: c'est ce qui se lit dans la boîte
    de réception, avant toute décision d'ouvrir. « Découvrez notre
    plateforme » n'y survit pas.
    """
    marches, total = marches_du_secteur(entreprise.get("sector", ""))
    if not total:
        return "", ""
    metier = get_label(entreprise.get("sector", "")) or "votre domaine"
    societe = (entreprise.get("legal_name") or "").strip()
    objet_mail = f"{total} marchés publics ouverts en {metier}"

    cartes = []
    for m in marches:
        bas = " · ".join(x for x in [
            (m.get("acheteur") or "")[:60],
            m.get("region") or "",
            f"limite&nbsp;: {m['date_limite']}" if m.get("date_limite") else ""] if x)
        cartes.append(
            f'<div style="border:1px solid #e8dcc5;border-radius:10px;padding:14px 16px;'
            f'margin-bottom:10px;background:#fff">'
            f'<div style="font-size:15px;font-weight:600;color:#2b211b;line-height:1.45">'
            f'{(m["objet"] or "")[:150]}</div>'
            f'<div style="font-size:13px;color:#8a7a6a;margin-top:6px">{bas}</div></div>')

    corps = f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:auto;
            background:#f8f1e1;padding:26px 22px">
  <div style="text-align:center;padding:2px 0 20px">
    <div style="height:2px;width:44px;background:#f2662d;margin:0 auto 13px"></div>
    <div style="font-family:Georgia,serif;font-weight:700;font-size:17px;
                letter-spacing:6.4px;color:#2b211b">MAROC</div>
    <div style="font-family:Georgia,serif;font-weight:700;font-size:17px;
                letter-spacing:1.1px;color:#2b211b">ENTREPRENEURIAT</div>
    <div style="height:2px;width:44px;background:#f2662d;margin:13px auto 0"></div>
  </div>
  <p style="font-size:15px;color:#4a3b32;line-height:1.7;margin:0 0 4px">
    Bonjour{' ' + societe if societe else ''},</p>
  <p style="font-size:15px;color:#4a3b32;line-height:1.7;margin:0 0 18px">
    Il y a actuellement <b>{_accroche(entreprise, total)}</b>
    En voici {len(marches)}&nbsp;:</p>
  {''.join(cartes)}
  <p style="text-align:center;margin:24px 0 8px">
    <a href="{lien or cfg.SITE_URL}" style="display:inline-block;padding:13px 26px;
       background:#f2662d;color:#fff;border-radius:9px;text-decoration:none;
       font-weight:700;font-size:15px">Voir les {total} marchés</a></p>
  <p style="font-size:13px;color:#8a7a6a;text-align:center;line-height:1.6;margin:0 0 20px">
    {cfg.TRIAL_DAYS} jours gratuits, sans carte bancaire.</p>
  <p style="font-size:11.5px;color:#b7a896;line-height:1.6;border-top:1px solid #e8dcc5;
            padding-top:14px;margin:0">
    Vous recevez ce message parce que votre entreprise figure dans un annuaire
    professionnel public. Répondez « STOP » et nous retirons vos coordonnées —
    conformément à la loi 09-08.</p>
</div>"""
    return objet_mail, corps
