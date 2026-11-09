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
    "seo":        "Recherche Google (pages publiques)",
}

# Ceux qu'on ne met pas dans un lien: ils se déduisent de l'inscription.
CANAUX_DEDUITS = {
    "parrainage": "Parrainage d'un membre",
    "invitation": "Invitation (prospection)",
    "direct":     "Direct, bouche-à-oreille",
    "":           "Avant le suivi des sources",
}

# Déduits de la page d'où arrive le visiteur, quand le lien ne portait pas
# de « ?src= »: une recherche Google, un lien posé sur un autre site.
CANAUX_REFERENT = {
    "recherche": "Moteur de recherche (Google, Bing…)",
    "site":      "Lien depuis un autre site",
}

# La question « Comment avez-vous connu la plateforme ? » de l'inscription,
# dans l'ordre où elle s'affiche. C'est la source la plus sûre: le suivi
# des liens ne voit ni le bouche-à-oreille ni un lien recopié à la main.
CANAUX_DECLARES = {
    "recherche":  ("Recherche Google", "بحث في Google"),
    "facebook":   ("Facebook", "فيسبوك"),
    "instagram":  ("Instagram", "إنستغرام"),
    "linkedin":   ("LinkedIn", "لينكدإن"),
    "whatsapp":   ("WhatsApp", "واتساب"),
    "tiktok":     ("TikTok", "تيك توك"),
    "youtube":    ("YouTube", "يوتيوب"),
    "bouche":     ("Un collègue, un ami", "زميل أو صديق"),
    "email":      ("Un email reçu", "رسالة بريد إلكتروني"),
    "salon":      ("Salon, réunion, formation", "معرض، لقاء أو تكوين"),
    "presse":     ("Presse, radio", "الصحافة أو الإذاعة"),
    "partenaire": ("Fédération, CRI, chambre", "جامعة مهنية، مركز جهوي للاستثمار، غرفة"),
    "autre":      ("Autre", "مصدر آخر"),
}
_LIBELLES_DECLARES = {"bouche": "Bouche-à-oreille, un collègue", "autre": "Autre"}

# Hôtes des moteurs de recherche et des réseaux, pour lire le référent.
_REFERENTS = (
    (("google.", "bing.com", "yahoo.", "duckduckgo.com", "ecosia.org", "qwant.com",
      "yandex.", "search.brave.com"), "recherche"),
    (("facebook.com", "fb.com", "fb.me", "messenger.com"), "facebook"),
    (("instagram.com",), "instagram"),
    (("linkedin.com", "lnkd.in"), "linkedin"),
    (("whatsapp.com", "wa.me"), "whatsapp"),
    (("tiktok.com",), "tiktok"),
    (("youtube.com", "youtu.be"), "youtube"),
    (("mail.google.com", "outlook.", "mail.yahoo.", "mail."), "email"),
)

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
    return v if v in CANAUX or v in CANAUX_REFERENT else ""


def depuis_referent(referent: str, notre_hote: str = "") -> tuple:
    """(canal, hôte) d'après l'en-tête Referer, ou ("", "") s'il ne dit rien.

    Un référent vide ou venant du site lui-même ne prouve rien: on n'en
    déduit pas « direct », on laisse la place à un lien suivi plus tard.
    """
    from urllib.parse import urlparse
    try:
        hote = (urlparse(referent or "").hostname or "").lower()
    except ValueError:
        return "", ""
    if hote.startswith("www."):
        hote = hote[4:]
    notre = (notre_hote or "").lower().split(":")[0].removeprefix("www.")
    if not hote or (notre and (hote == notre or hote.endswith("." + notre))):
        return "", ""
    # Les webmails avant Google: mail.google.com n'est pas une recherche.
    for motifs, cle in sorted(_REFERENTS, key=lambda r: r[1] != "email"):
        if any(hote == m or hote.startswith(m) or ("." + m) in ("." + hote)
               for m in motifs):
            return cle, hote
    return "site", hote


def declare(brut: str) -> str:
    """La réponse à « Comment avez-vous connu la plateforme ? », ou ""."""
    v = (brut or "").strip().lower()
    return v if v in CANAUX_DECLARES else ""


def options_declarees(lang: str = "fr") -> list:
    return [(cle, ar if lang == "ar" else fr) for cle, (fr, ar) in CANAUX_DECLARES.items()]


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
    return (CANAUX.get(cle) or CANAUX_REFERENT.get(cle) or CANAUX_DEDUITS.get(cle)
            or _LIBELLES_DECLARES.get(cle) or cle)


def effective(source: str, declaree: str) -> str:
    """La source retenue: ce que le membre a répondu (ou que l'administration
    a corrigé) l'emporte sur le suivi des liens, qui ne voit pas tout."""
    return declaree or source or ""
