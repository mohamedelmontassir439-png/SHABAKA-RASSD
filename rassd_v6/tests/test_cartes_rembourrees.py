# -*- coding: utf-8 -*-
"""Le texte d'une carte ne doit jamais toucher son cadre.

Le rembourrage d'une carte vit sur `.carte-b`. Une carte qui porte son
contenu directement n'en a donc aucun, et comme `.carte` est en
`overflow:hidden`, la première lettre de chaque ligne se trouve rasée. Sur
la fiche d'appel, cinq blocs étaient dans ce cas: « 0 appel(s) » perdait son
zéro, « Ne promettez jamais » son N.

Deux autres défauts de la même famille, trouvés en mesurant:

- un sélecteur seul sur sa ligne, sans accolade, se colle au suivant: dans
  la page Entreprises, `.lien-contact` transformait `.pagination` en
  `.lien-contact .pagination`, et la pagination perdait ses 18 px.
- `.empty` était posé dans huit pages et défini dans aucune.
"""
import glob
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARITS = os.path.join(RACINE, "templates")

ENVELOPPES = ("carte-b", "card-b", "carte-h", "card-h", "tableau-cadre")


def _admin():
    for chemin in sorted(glob.glob(os.path.join(GABARITS, "admin*.html"))):
        with open(chemin, encoding="utf-8") as f:
            yield os.path.basename(chemin), f.read()


def _bloc_style(contenu):
    m = re.search(r"\{%\s*block style\s*%\}(.*?)\{%\s*endblock\s*%\}", contenu, re.S)
    return m.group(1) if m else ""


class TestAucunSelecteurOrphelin:
    """Il ne crie pas: il détourne silencieusement la règle d'après."""

    @pytest.mark.parametrize("nom,contenu", list(_admin()))
    def test_chaque_selecteur_porte_son_bloc(self, nom, contenu):
        orphelins = []
        for i, ligne in enumerate(_bloc_style(contenu).splitlines(), 1):
            t = ligne.strip()
            if re.fullmatch(r"[.#][A-Za-z][\w-]*(\s*[>+~]\s*[.#]?[\w-]+)*", t):
                orphelins.append(f"l.{i}: {t}")
        assert not orphelins, f"{nom}: sélecteur sans accolade — {orphelins}"


class TestCartesRembourrees:
    def test_une_carte_sans_corps_declare_son_rembourrage(self):
        """Soit le contenu est enveloppé, soit la page rend le rembourrage à
        la carte elle-même. Sans l'un ni l'autre, le texte colle au cadre."""
        fautifs = {}
        for nom, contenu in _admin():
            # On cherche la règle dans toute la page: admin_login.html est une
            # coquille autonome, sans `{% block style %}`, et son `.card` porte
            # bien son rembourrage.
            if re.search(r"\.(carte|card)\s*\{[^}]*padding", contenu):
                continue  # la page le rend elle-même
            for m in re.finditer(r'<div class="(?:carte|card)"[^>]*>', contenu):
                suite = contenu[m.end():m.end() + 500]
                if any(f'class="{e}' in suite for e in ENVELOPPES):
                    continue
                # Un contenu textuel direct, et aucune enveloppe: le défaut.
                if re.search(r"<(h2|p|div class=\"(script|ligne|marche|empty)\")", suite):
                    ligne = contenu[:m.start()].count("\n") + 1
                    fautifs.setdefault(nom, []).append(ligne)
        assert not fautifs, f"cartes dont le texte touche le cadre: {fautifs}"


class TestEtatVide:
    def test_letat_vide_est_defini_la_ou_il_est_employe(self):
        """Huit pages l'affichaient; aucune feuille ne le décrivait."""
        employe = [nom for nom, c in _admin() if 'class="empty"' in c]
        assert employe, "aucune page n'utilise .empty — ce test a perdu son objet"
        with open(os.path.join(GABARITS, "admin_base.html"), encoding="utf-8") as f:
            coquille = f.read()
        assert re.search(r"^\.empty\{[^}]*padding", coquille, re.M), (
            f".empty employé par {employe} mais sans rembourrage dans la coquille")
