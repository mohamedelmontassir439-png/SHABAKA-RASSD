# -*- coding: utf-8 -*-
"""L'intitulé d'un marché, débarrassé de sa répétition.

Le portail affiche deux fois le même titre dans la même cellule: une version
tronquée, qui se termine par des points de suspension, et la version entière.
Notre extracteur prenait le texte de la cellule entière et ramenait les deux:

    « Construction d'un mur de clôture de la centrale thermique à charbon de
      Jerada de 350MW ... Construction d'un mur de clôture de la centrale
      thermique à charbon de Jerada de 350MW »

Relevé le 06/10/2026: 120 marchés sur 3 263 portaient leur titre en double,
dont 118 avec les points de suspension au milieu. Les deux autres venaient
d'une fiche de bon de commande, où l'intitulé est repris après l'étiquette
« Caractéristiques et spécifications ».

Un titre affiché deux fois n'est pas qu'inélégant: il mange la largeur de la
ligne, pousse le reste hors du cadre, et se retrouve tel quel dans l'objet de
l'email d'alerte.
"""
import re

# Il faut une reprise franche pour conclure a une repetition. Quarante
# caracteres: deux marches voisins d'un meme lot partagent souvent leurs
# premiers mots — « Equipement du forage n°17/517 sis au champ captant
# Nekour Lot : … » — et il ne faut pas les confondre avec un doublon.
_AMORCE = 40

# Ce qui traine en fin de premiere copie: les points de suspension de la
# version tronquee, et l'etiquette que les bons de commande intercalent.
_QUEUE = re.compile(r"(?:\s*caract[ée]ristiques et sp[ée]cifications\s*:?)?[\s.…:–—-]*$",
                    re.IGNORECASE)


def sans_repetition(objet: str) -> str:
    """Rend l'intitulé une seule fois, dans sa version la plus complète.

    Le principe: la copie tronquee est un **prefixe** de la copie entiere.
    C'est cela qu'on verifie, et rien d'autre — comparer ce qui separe les
    deux copies ne marchait pas, puisque la premiere porte deja la moitie du
    titre.

    Ne touche a rien si la reprise n'est pas franche: mieux vaut un titre
    bavard qu'un titre ampute.
    """
    t = re.sub(r"\s+", " ", objet or "").strip()
    if len(t) < 2 * _AMORCE:
        return t

    bas = t.lower()
    # La derniere reprise du debut du titre: s'il se repete trois fois, on
    # garde la copie la plus complete, qui est la derniere.
    i = bas.rfind(bas[:_AMORCE])
    if i <= 0:
        return t

    gauche = _QUEUE.sub("", t[:i])
    droite = t[i:].strip()
    if not gauche:
        return droite

    if droite.lower().startswith(gauche.lower()):
        return droite          # la gauche etait la version tronquee
    if gauche.lower().startswith(droite.lower()):
        return gauche          # la droite etait la version tronquee
    return t                   # deux titres voisins, pas un doublon


def _sans_accents(texte: str) -> str:
    import unicodedata
    d = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")
