# -*- coding: utf-8 -*-
"""Aucune page d'administration ne doit être plus large que la fenêtre.

Mesuré le 03/10/2026: à 1113 px de fenêtre, le tableau de bord faisait
1129 px. L'utilisateur voyait une barre de défilement horizontale, et en
faisant défiler, les textes et les boutons apparaissaient coupés à gauche.

Deux causes, toutes deux invisibles à la lecture du code:

1. Une piste de grille `1fr` ne descend jamais sous la largeur minimale de
   son contenu. Un tableau aux en-têtes insécables la bloque, et c'est la
   page entière qui déborde. `minmax(0, 1fr)` autorise la piste à rétrécir.
   Le piège vaut aussi pour une piste unique: `grid-template-columns: 1fr`
   dans une règle mobile gardait les cartes à 599 px dans une fenêtre de 546.

2. Un tableau sans cadre n'a nulle part où se replier. Enfermé dans un
   conteneur qui défile, il reste lisible sans pousser la page.

Ces vérifications sont statiques: elles ne lancent pas de navigateur, donc
elles tiennent dans une suite de tests ordinaire.
"""
import glob
import os
import re

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARITS = os.path.join(RACINE, "templates")


def _admin():
    for chemin in sorted(glob.glob(os.path.join(GABARITS, "admin*.html"))):
        with open(chemin, encoding="utf-8") as f:
            yield os.path.basename(chemin), f.read()


class TestGrilles:
    def test_toute_piste_de_grille_peut_retrecir(self):
        """« 1fr » seul bloque la piste à la largeur de son contenu."""
        fautifs = {}
        for nom, contenu in _admin():
            # On cherche les déclarations qui contiennent un « 1fr » nu,
            # c'est-à-dire pas enveloppé dans minmax(0, …).
            for m in re.finditer(r"grid-template-columns:\s*([^;}]+)", contenu):
                valeur = m.group(1)
                sans_minmax = re.sub(r"minmax\([^)]*\)", "", valeur)
                if re.search(r"\b1fr\b", sans_minmax):
                    fautifs.setdefault(nom, []).append(valeur.strip()[:60])
        assert not fautifs, f"pistes qui ne peuvent pas rétrécir: {fautifs}"


class TestTableaux:
    def test_chaque_tableau_a_son_cadre_defilant(self):
        """Sans cadre, un tableau large pousse la page au lieu de défiler."""
        fautifs = {}
        for nom, contenu in _admin():
            for m in re.finditer(r"<table\b", contenu):
                avant = contenu[max(0, m.start() - 260):m.start()]
                if "tableau-cadre" not in avant:
                    ligne = contenu[:m.start()].count("\n") + 1
                    fautifs.setdefault(nom, []).append(ligne)
        assert not fautifs, f"tableaux sans cadre: {fautifs}"

    def test_le_cadre_defile_bien(self):
        with open(os.path.join(GABARITS, "admin_base.html"), encoding="utf-8") as f:
            base = f.read()
        assert re.search(r"\.tableau-cadre\s*\{[^}]*overflow-x:\s*auto", base)


class TestContenant:
    def test_la_zone_de_contenu_ne_fixe_pas_de_largeur_minimale(self):
        """Une largeur minimale sur le conteneur rendrait tout le reste vain."""
        with open(os.path.join(GABARITS, "admin_base.html"), encoding="utf-8") as f:
            base = f.read()
        corps = re.search(r"\.corps\s*\{([^}]*)\}", base)
        assert corps and "min-width" not in corps.group(1)
