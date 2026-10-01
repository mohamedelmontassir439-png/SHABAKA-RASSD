# -*- coding: utf-8 -*-
"""Nature de l'organisme acheteur: État, para-public, ou privé.

La plateforme ne connaissait que deux catégories, héritées non pas de la
nature de l'acheteur mais de la source qui publiait l'avis: ce qui venait du
portail national était « Public », le reste « Privé ». Un même type
d'organisme se retrouvait donc des deux côtés. Mesuré le 01/10/2026 sur les
marchés actifs: cent soixante-sept avis d'établissements et entreprises
publics, dont cent dix classés « Public » et cinquante-sept « Privé ».

Or au Maroc cette famille — les EEP: ADM, ONEE, ONCF, OCP, CNSS, Marsa
Maroc, les agences, les régies, les sociétés régionales — pèse une part
considérable de la commande, avec ses propres règles d'achat et ses propres
habitudes de paiement. Un entrepreneur qui travaille avec elles ne cherche
pas la même chose qu'un fournisseur de commune rurale.

La nature se lit donc sur le nom de l'acheteur, pas sur la provenance de
l'avis. La reconnaissance est volontairement prudente: dans le doute, on
laisse la catégorie d'origine plutôt que d'étiqueter à tort.
"""
import re
import unicodedata

ETAT = "public"
PARA = "semi_public"
PRIVE = "prive"

# Établissements et entreprises publics marocains, par leur nom usuel ou leur
# sigle. Les sigles courts sont encadrés par des frontières de mot: « ADM »
# ne doit pas se déclencher sur « ADMINISTRATION », ni « SIE » sur
# « SIEGE ».
_SIGLES = [
    "adm", "onee", "oncf", "ocp", "onda", "anp", "cdg", "cnss", "cnops",
    "ofppt", "anapec", "onhym", "masen", "sie", "ampl", "ancfcc", "amdie",
    "onmt", "ram", "sodep", "srm", "radeef", "radeema", "radeec", "radeeo",
    "radeel", "radeeta", "ramsa", "redal", "lydec", "amendis", "onssa",
    "omt", "cmr", "tgr", "anra", "acaps", "anrt", "andzoa",
]

_EXPRESSIONS = [
    "autoroutes du maroc", "office national", "office cherifien",
    "royal air maroc", "marsa maroc", "barid al", "poste maroc",
    "al omrane", "agence urbaine", "agence nationale", "agence du bassin",
    "agence pour la promotion", "agence de developpement", "agence marocaine",
    "agence regionale", "agence speciale", "agence judiciaire",
    "societe regionale multiservices", "societe de developpement local",
    "societe de developpement regional", "regie autonome",
    "caisse de depot", "caisse nationale", "caisse marocaine",
    "fonds d equipement", "credit agricole du maroc", "bank al maghrib",
    "centre hospitalier", "centre regional d investissement",
    "universite", "cite universitaire", "academie regionale",
    "chambre de commerce", "chambre d agriculture", "chambre des metiers",
    "etablissement public", "entreprise publique",
    "office regional de mise en valeur",
]


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


# L'État au sens strict: administrations centrales et collectivités. La liste
# sert à redresser une provenance mal étiquetée — « Administration des Douanes
# et Impôts Indirects » arrivait classée « Privé » parce que l'avis venait de
# l'agrégateur, alors que c'est une administration d'État.
_EXPRESSIONS_ETAT = [
    "ministere", "administration", "direction provinciale", "direction regionale",
    "direction generale", "commune", "province", "prefecture", "wilaya",
    "conseil regional", "conseil provincial", "conseil communal", "gouverneur",
    "tribunal", "cour d appel", "cour des comptes", "gendarmerie", "surete",
    "douane", "tresorerie", "haut commissariat", "secretariat general",
    "inspection generale", "delegation provinciale", "delegation regionale",
    "forces armees", "protection civile", "sapeurs pompiers",
]


def _motif(expression: str) -> str:
    """Chaque mot de l'expression peut porter sa marque du pluriel.

    « academie regionale » doit reconnaître « Academies regionales », forme
    sous laquelle le portail les publie.
    """
    return r"\s+".join(re.escape(mot) + r"s?" for mot in expression.split())


_MOTIFS_SIGLES = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _SIGLES) + r")\b")
_MOTIFS_PARA = re.compile("|".join(_motif(e) for e in _EXPRESSIONS))
_MOTIFS_ETAT = re.compile("|".join(_motif(e) for e in _EXPRESSIONS_ETAT))


def est_para_public(acheteur: str) -> bool:
    """Vrai si le nom désigne un établissement ou une entreprise publique.

    On exige une correspondance franche: un sigle en mot entier, ou une
    expression complète. « Commune rurale de Tansifte » reste l'État au sens
    large, « Societe Régionale Multiservices Oriental » est para-publique.
    """
    n = _nu(acheteur)
    return bool(n and (_MOTIFS_PARA.search(n) or _MOTIFS_SIGLES.search(n)))


def est_etat(acheteur: str) -> bool:
    """Vrai si le nom désigne une administration ou une collectivité."""
    n = _nu(acheteur)
    return bool(n and _MOTIFS_ETAT.search(n))


def categorie(acheteur: str, type_offre: str = "") -> str:
    """Rend la nature de l'organisme: État, para-public ou privé.

    Le type d'origine ne sert que de dernier repli: il porte la provenance de
    l'avis, qui ne dit rien de la nature de l'acheteur. Une administration
    reconnue reste l'État même si l'agrégateur l'a publiée comme « Privé ».
    """
    if est_para_public(acheteur):
        return PARA
    if est_etat(acheteur):
        return ETAT
    return PRIVE if (type_offre or "").strip().lower().startswith("priv") else ETAT
