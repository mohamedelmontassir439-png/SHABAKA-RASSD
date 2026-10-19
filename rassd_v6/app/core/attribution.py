# -*- coding: utf-8 -*-
"""Un marché attribué, et un marché qui ne l'a pas été.

Le portail inscrit dans la colonne « attributaire » le resultat de la
procedure, quel qu'il soit. Quand aucune offre n'a convenu, il y ecrit
« Infructueux »; quand la consultation a ete retiree, « Annule ». Ce ne sont
pas des entreprises.

Mesure du 19/10/2026 sur 522 resultats d'adjudication: **135, soit 26 %**,
portaient une mention de procedure a la place d'un nom. La page des
resultats les affichait donc en vert, sous l'intitule « Attributaire », et
la sous-traitance proposait d'aller demarcher une societe nommee
« Infructueux ».

Un filtre existait deja, mais il ne servait qu'a la page des prospects de
l'administration — la ou le fondateur cherche qui appeler. Les membres,
eux, voyaient tout. C'est la meme notion: elle vit ici, et chacun s'en sert.
"""
import re
import unicodedata

# Les mentions relevees en production. On compare sans accents ni casse:
# « Annulé », « ANNULE » et « annule » sont le meme mot.
_MENTIONS = {
    "infructueux": "infructueux",
    "declare infructueux": "infructueux",
    "annule": "annule",
    "sans suite": "sans_suite",
    "non attribue": "sans_suite",
    "abandonne": "sans_suite",
    "neant": "sans_suite",
    "sans objet": "sans_suite",
    "voir pv": "sans_suite",
}


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").strip().lower())
    sans = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans)


def issue(adjudicataire: str) -> str:
    """L'issue de la procedure: "infructueux", "annule", "sans_suite" — ou "".

    Rend "" quand la valeur est un vrai nom d'entreprise, c'est-a-dire quand
    le marche a bien ete attribue.
    """
    return _MENTIONS.get(_nu(adjudicataire), "")


def est_attribue(adjudicataire: str) -> bool:
    """Le marche a-t-il trouve preneur ?

    Un nom de trois lettres ou moins ne designe personne non plus: on a vu
    « — », « NC » et « x » dans cette colonne.
    """
    nom = (adjudicataire or "").strip()
    return len(nom) > 3 and not issue(nom)


# Garde le nom par lequel le reste du code la connaissait.
NON_COMPANY_ADJUDICATAIRE = set(_MENTIONS) | {"annulé", "néant", "non attribué",
                                              "abandonné", "déclaré infructueux"}
