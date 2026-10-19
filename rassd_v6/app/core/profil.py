# -*- coding: utf-8 -*-
"""Ce qu'un profil de membre doit porter pour être utile.

Jusqu'au 19/10/2026, l'inscription n'exigeait que l'email, le mot de passe
et un secteur. Le nom, le téléphone et la société étaient facultatifs — et
restaient vides. Un marché se joue parfois en deux jours: sans numéro, on ne
peut pas prévenir, et la veille qu'on vend s'arrête à l'email.

Chaque contrôle est volontairement modeste. Une exigence trop stricte ne
produit pas de meilleures données: elle produit des « . », des « aaa » et
des « 0600000000 » — des cases pleines qui mentent, ce qui est pire qu'une
case vide, puisqu'on croit l'avoir.
"""
import re
import unicodedata

# Un numero marocain: 10 chiffres commencant par 06, 07 (mobiles) ou 05
# (fixes). On accepte l'indicatif, les espaces, les points et les tirets —
# personne ne saisit un numero de la meme facon.
_MOBILE_OU_FIXE = re.compile(r"^(?:212|0)?([567]\d{8})$")

# Une suite d'un seul caractere repete — « aaa », « ... », « 111 » — remplit
# la case sans rien dire.
_UNIFORME = re.compile(r"^(.)\1*$")


def _nu(texte: str) -> str:
    """Minuscules, sans accents, espaces reduits."""
    d = unicodedata.normalize("NFD", (texte or "").strip().lower())
    sans = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans)


def _a_du_fond(texte: str, minimum: int) -> bool:
    """Assez long, au moins une lettre, et pas un caractere repete.

    La regle du caractere repete ne s'applique qu'a partir de trois signes:
    « MM » est une raison sociale possible — c'en est une en production —
    alors que « aaa » n'en est jamais une. En dessous de trois, on n'a pas
    de quoi distinguer le sigle du remplissage, et on accorde le benefice
    du doute plutot que de refuser un abonne.
    """
    t = _nu(texte)
    if len(t) < minimum:
        return False
    compact = re.sub(r"\s", "", t)
    if len(compact) >= 3 and _UNIFORME.match(compact):
        return False
    return bool(re.search(r"[a-z؀-ۿ]", t))


def nom_valide(nom: str) -> bool:
    """Trois caracteres, une lettre, pas « aaa ».

    On n'exige pas deux mots: beaucoup s'inscrivent sous un seul nom, et
    refuser « Alaoui » ferait perdre un abonne pour rien.
    """
    return _a_du_fond(nom, 3)


def societe_valide(nom: str) -> bool:
    """Deux caracteres suffisent: « MM », « SIMAC », « 2SBT » existent."""
    return _a_du_fond(nom, 2)


def telephone_marocain(brut: str) -> bool:
    """Un numero marocain joignable, quelle que soit la facon de l'ecrire."""
    return bool(_MOBILE_OU_FIXE.match(re.sub(r"[^\d]", "", brut or "")))


def telephone_normalise(brut: str) -> str:
    """« +212 6 12 34 56 78 » -> « 0612345678 ». Rend "" si le numero est faux.

    On range une seule forme en base: deux ecritures du meme numero en font
    deux contacts differents, et l'un des deux ne sera jamais rappele.
    """
    m = _MOBILE_OU_FIXE.match(re.sub(r"[^\d]", "", brut or ""))
    return "0" + m.group(1) if m else ""


def profil_incomplet(membre) -> list:
    """Les champs qui manquent encore, dans l'ordre où on les demande.

    Sert aux membres inscrits avant que ces champs ne deviennent
    obligatoires: on ne les met pas dehors, on leur montre ce qui manque.
    """
    if not membre:
        return []
    lire = (lambda c: (membre[c] if c in membre.keys() else "")) \
        if hasattr(membre, "keys") else (lambda c: membre.get(c, ""))
    manque = []
    if not nom_valide(lire("nom")):
        manque.append("nom")
    if not telephone_marocain(lire("phone")):
        manque.append("phone")
    if not societe_valide(lire("company")):
        manque.append("company")
    return manque
