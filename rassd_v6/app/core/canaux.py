# -*- coding: utf-8 -*-
"""D'où vient chaque inscrit.

Une campagne qui passe par Facebook, LinkedIn, WhatsApp, une affiche et un
salon ne se pilote pas à l'impression: il faut savoir, inscription par
inscription, quel canal l'a amenée — et lequel amène des abonnés payants,
ce qui n'est pas la même chose.

Le mécanisme est le plus simple qui tienne: chaque lien publié porte
« ?src=facebook » (ou les « utm_source » que posent les régies). À la
première visite, le canal est gardé soixante jours dans un cookie; à
l'inscription, il est rangé sur la fiche du membre. On retient le premier
contact et non le dernier: c'est la publication qui a fait connaître la
plateforme qui mérite le crédit, pas le favori par lequel on revient
s'inscrire trois jours plus tard.

Seuls les canaux de la liste sont acceptés. Une valeur libre dans l'adresse
remplirait le bilan de « test », « xxx » et de fautes de frappe.
"""
import re

COOKIE = "_src"
DUREE_COOKIE = 60 * 86400

# Clé courte, rangée en base et écrite dans les liens — libellé pour l'admin.
CANAUX = {
    "facebook":   "Facebook",
    "instagram":  "Instagram",
    "linkedin":   "LinkedIn",
    "whatsapp":   "WhatsApp (statut, groupes)",
    "tiktok":     "TikTok",
    "youtube":    "YouTube",
    "google":     "Google Ads",
    "email":      "Email",
    "sms":        "SMS",
    "affiche":    "Affiche, flyer (QR code)",
    "salon":      "Salon, réunion, formation",
    "presse":     "Presse, radio",
    "partenaire": "Partenaire (fédération, CRI, chambre)",
}

# Ceux qu'on ne met pas dans un lien: ils se déduisent de l'inscription.
CANAUX_DEDUITS = {
    "parrainage": "Parrainage d'un membre",
    "invitation": "Invitation (prospection)",
    "direct":     "Direct, bouche-à-oreille",
    "":           "Avant le suivi des sources",
}

# Les régies écrivent le même canal de plusieurs façons.
_ALIAS = {
    "fb": "facebook", "meta": "facebook", "m.facebook.com": "facebook",
    "l.facebook.com": "facebook", "ig": "instagram", "li": "linkedin",
    "lnkd": "linkedin", "lnkd.in": "linkedin", "wa": "whatsapp",
    "qr": "affiche", "flyer": "affiche", "tt": "tiktok", "yt": "youtube",
    "adwords": "google", "gads": "google", "mail": "email",
    "newsletter": "email", "brevo": "email",
}


def canal(brut: str) -> str:
    """La clé du canal, ou "" si la valeur n'en désigne aucun."""
    v = (brut or "").strip().lower()
    v = _ALIAS.get(v, v)
    return v if v in CANAUX else ""


def campagne(brut: str) -> str:
    """Le nom de campagne, réduit à des lettres, chiffres et tirets."""
    return re.sub(r"[^a-z0-9-]", "", (brut or "").lower())[:40]


def lien(site: str, canal_cle: str, page: str = "/", nom_campagne: str = "") -> str:
    """L'adresse à publier sur un canal: elle dira d'où vient l'inscrit."""
    adresse = f"{site.rstrip('/')}{page}?src={canal_cle}"
    if nom_campagne:
        adresse += f"&cmp={campagne(nom_campagne)}"
    return adresse


def lire_cookie(valeur: str) -> tuple:
    """(canal, campagne) gardés à la première visite."""
    cle, _, nom = (valeur or "").partition("|")
    return canal(cle), campagne(nom)


def libelle(cle: str) -> str:
    return CANAUX.get(cle) or CANAUX_DEDUITS.get(cle) or cle
