# -*- coding: utf-8 -*-
"""Le nom de l'acheteur, tel qu'on peut le lire.

La source préfixe le nom d'une étiquette de famille, et pas toujours de la
même façon:

    « Cnss /CNSS DIRECTION REGIONALE ANFA »
    « casablanca BAIA SOCIETE CASABLANCA BAÏA »      (aucun séparateur)
    « Ofppt OFPPT »                                  (quatorze fois)
    « Autres societes / société Club Med »
    « Marsa maroc /DIRECTION DES ACHATS »

Affiché tel quel, cela donne « ACHETEUR : casablanca BAIA SOCIETE CASABLANCA
BAÏA » dans l'email d'alerte: le client lit deux fois le même nom et doute
du sérieux de la source. Mesure du 03/10/2026: un tiers des acheteurs
portent un mot répété, et plus de la moitié des résultats d'adjudication
contiennent une barre.

La règle n'est pas « couper à la barre ». Dans « Marsa maroc / DIRECTION DES
ACHATS », la gauche est l'organisme et la droite son service: la jeter
ferait disparaître Marsa Maroc. On ne retire donc la gauche que lorsqu'elle
n'apprend rien — parce qu'elle se répète à droite, ou parce que c'est une
étiquette de classement de la source.
"""
import re
import unicodedata

# Étiquettes de classement de la source: elles ne désignent aucun acheteur.
_ETIQUETTES = {
    "autres societes", "autres organismes particuliers", "autres organismes",
    "autres etablissements", "divers", "autre",
}

# Mots trop communs pour prouver qu'une étiquette se répète. « société » n'en
# fait pas partie: l'écarter faisait couper « casablanca BAIA SOCIETE » au lieu
# de « casablanca BAIA », et le nom perdait son premier mot.
_VIDES = {"de", "du", "des", "la", "le", "les", "et", "au", "aux", "en", "pour"}

# Un nom d'organisme ne commence pas par un connecteur. Si une coupe laisse
# « et de la protection sociale … », c'est qu'on a coupé au mauvais endroit.
_DEBUTS_INTERDITS = {"et", "de", "du", "des", "la", "le", "les", "au", "aux",
                     "en", "pour", "a"}


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte or "")
                   if not unicodedata.combining(c))


def _mots(texte: str) -> list:
    """Les mots porteurs de sens, sans accents ni casse."""
    bruts = re.findall(r"[a-z0-9]+", _sans_accents(texte).lower())
    return [m for m in bruts if len(m) > 2 and m not in _VIDES]


def _redondant(gauche: str, droite: str) -> bool:
    """La gauche n'apprend-elle rien de plus que la droite ?"""
    g, d = _mots(gauche), set(_mots(droite))
    if not g:
        return True
    if _sans_accents(gauche).strip().lower() in _ETIQUETTES:
        return True
    return all(m in d for m in g)


def _normalise(texte: str) -> str:
    """Minuscules, sans accents, espaces réduits — pour comparer deux libellés."""
    return re.sub(r"\s+", " ", _sans_accents(texte).lower()).strip()


def _couper_prefixe_repete(texte: str) -> str:
    """Retire un début de chaîne qui se répète plus loin, sans séparateur.

    « casablanca BAIA SOCIETE CASABLANCA BAÏA » -> « SOCIETE CASABLANCA BAÏA »
    « Ofppt OFPPT »                              -> « OFPPT »

    La répétition doit être mot pour mot, articles compris. Comparer des
    listes de mots filtrées faisait paraître « MINISTERE DE LA SANTE »
    contigu à « Ministère De La Sante et de la », et il restait
    « protection sociale DELEGUE... » — un nom que personne n'a porté.
    Mieux vaut laisser le libellé brut que le corrompre.
    """
    mots = texte.split()
    for coupe in range(len(mots) - 1, 0, -1):
        gauche, droite = " ".join(mots[:coupe]), " ".join(mots[coupe:])
        premier = _sans_accents(droite.split()[0]).lower().strip(".,;:")
        if premier in _DEBUTS_INTERDITS:
            continue
        g, d = _normalise(gauche), _normalise(droite)
        # Le libellé se termine par son propre début: c'est la signature de
        # l'étiquette collée devant le nom. Chercher le préfixe n'importe où
        # dans la suite était trop large — « Ministère De La » se retrouvait au
        # milieu de « ... DU MINISTERE DE LA SANTE A SAFI » et la coupe laissait
        # « Sante et de la protection... », un nom que personne n'a porté.
        if g and d and d.endswith(g):
            return droite
    return texte


def lisible(brut: str) -> str:
    """Le nom de l'acheteur, débarrassé de l'étiquette de la source.

    Ne jette jamais une information: si la partie de gauche désigne autre
    chose que la droite — l'organisme dont elle est un service — les deux
    sont gardées, séparées par un tiret.
    """
    texte = re.sub(r"\s+", " ", (brut or "").strip())
    if not texte:
        return ""
    if "/" in texte:
        gauche, _, droite = texte.partition("/")
        gauche, droite = gauche.strip(), droite.strip()
        if not droite:
            return gauche
        if _redondant(gauche, droite):
            return droite
        return f"{gauche} — {droite}"
    return _couper_prefixe_repete(texte)
