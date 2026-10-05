# -*- coding: utf-8 -*-
"""Le jeu d'icônes, et l'interdiction de revenir aux emoji.

Un emoji n'est pas dessiné par nous: il l'est par le système de celui qui
regarde. Le même 📡 est bleu et plat sur Windows, rond et dégradé sur
Android, gris sur iOS. Tant qu'il en reste, la cohérence demandée est
impossible, quoi qu'on fasse du reste de la page. Mesure du 05/10/2026: 48
symboles distincts, dont une trentaine en couleur, répartis sur 25 gabarits.

Ce que ces tests tiennent:

- aucun emoji en couleur ne revient, sauf les six marqueurs de journaux,
  que le gabarit **compare** pour colorer ses lignes;
- une seule grammaire pour tout le jeu, car c'est elle qui fait l'unité;
- un nom d'icône inconnu se voit, au lieu de rendre une page de travers.
"""
import glob
import os
import re

import pytest

from app.core import marque

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARITS = os.path.join(RACINE, "templates")

# Les plans de l'Unicode où vivent les emoji en couleur, plus quatre isolés.
EMOJI = re.compile("[\U0001F300-\U0001FAFF⭐⚡✅❌]")

# Les seuls tolérés: ils viennent des messages de journal écrits en Python,
# et admin.html les compare pour choisir la couleur de la ligne. Les
# remplacer casserait la coloration sans rien embellir.
MARQUEURS = {"admin.html"}


def _gabarits():
    for chemin in sorted(glob.glob(os.path.join(GABARITS, "*.html"))):
        with open(chemin, encoding="utf-8") as f:
            yield os.path.basename(chemin), f.read()


class TestPlusAucunEmoji:
    def test_aucun_gabarit_ne_porte_demoji_en_couleur(self):
        fautifs = {}
        for nom, contenu in _gabarits():
            if nom in MARQUEURS:
                continue
            trouves = sorted(set(EMOJI.findall(contenu)))
            if trouves:
                fautifs[nom] = trouves
        assert not fautifs, f"emoji en couleur: {fautifs}"

    def test_les_marqueurs_de_journal_restent_comparés(self):
        """S'ils cessaient d'être comparés, ils n'auraient plus de raison
        d'être là — et ce test devrait tomber avec eux."""
        with open(os.path.join(GABARITS, "admin.html"), encoding="utf-8") as f:
            contenu = f.read()
        assert "'❌' in l" in contenu or "includes('❌')" in contenu


class TestUneSeuleGrammaire:
    @pytest.mark.parametrize("nom", marque.icones_connues())
    def test_chaque_icone_suit_la_meme_regle(self, nom):
        svg = marque.icone(nom)
        assert 'viewBox="0 0 24 24"' in svg, "grille commune"
        assert 'stroke="currentColor"' in svg, "la couleur vient du texte"
        assert 'fill="none"' in svg, "aucun aplat"
        assert 'stroke-linecap="round"' in svg

    def test_toutes_partagent_la_meme_epaisseur(self):
        epaisseurs = {re.search(r'stroke-width="([\d.]+)"', marque.icone(n)).group(1)
                      for n in marque.icones_connues()}
        assert len(epaisseurs) == 1, f"plusieurs épaisseurs: {epaisseurs}"

    def test_aucune_couleur_nest_ecrite_en_dur(self):
        """Une teinte figée ferait une icône orange dans une carte verte."""
        for nom in marque.icones_connues():
            assert "#" not in marque.icone(nom), nom

    def test_les_formes_tiennent_dans_la_grille(self):
        """Ce qui déborde du carré de 24 se fait rogner au rendu.

        On ne lit que les formes dont les coordonnées sont absolues —
        cercles, rectangles, polygones, et les `M` des chemins. Les nombres
        d'un chemin sont, pour la plupart, des **déplacements relatifs**:
        les comparer à la grille n'a aucun sens, et une première version de
        ce test déclarait vingt icônes hors cadre alors que la mesure du
        navigateur les trouvait toutes dedans.
        """
        deborde = {}
        for nom in marque.icones_connues():
            svg = marque.icone(nom)
            points = []
            for cx, cy, r in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', svg):
                points += [float(cx) - float(r), float(cx) + float(r),
                           float(cy) - float(r), float(cy) + float(r)]
            for x, y, w, h in re.findall(
                    r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg):
                points += [float(x), float(x) + float(w), float(y), float(y) + float(h)]
            for pts in re.findall(r'points="([^"]+)"', svg):
                for couple in pts.split():
                    points += [float(v) for v in couple.split(",")]
            for depart in re.findall(r'[Mm] ?(-?[\d.]+) (-?[\d.]+)', svg):
                points += [float(v) for v in depart]
            if points and (max(points) > 24.05 or min(points) < -0.05):
                deborde[nom] = (round(min(points), 1), round(max(points), 1))
        assert not deborde, f"hors grille: {deborde}"


class TestLesAppelsSontValides:
    def test_tout_nom_appele_existe(self):
        """Un nom inconnu rend un carré vide: visible, mais il ne faut pas
        qu'il parte en production."""
        connues = set(marque.icones_connues())
        inconnues = {}
        for nom, contenu in _gabarits():
            appeles = set(re.findall(r"ico\(['\"]([a-z]+)['\"]", contenu))
            manquants = appeles - connues
            if manquants:
                inconnues[nom] = sorted(manquants)
        assert not inconnues, f"icônes inconnues: {inconnues}"

    def test_un_nom_inconnu_rend_un_carre_visible(self):
        """Plutôt que rien: on voit qu'il manque une icône, au lieu de
        chercher pourquoi la ligne a l'air de travers."""
        assert "<rect" in marque.icone("nexistepas")

    def test_le_rail_rend_le_trace_et_non_son_code(self):
        """Sans `|safe`, Jinja échappe le SVG et le rail affiche sa source."""
        with open(os.path.join(GABARITS, "admin_base.html"), encoding="utf-8") as f:
            assert '{{ icone|safe }}' in f.read()

    def test_la_globale_ne_sappelle_pas_comme_le_parametre_de_la_macro(self):
        """La macro du rail a un paramètre nommé `icone`: une globale de ce
        nom serait masquée à l'intérieur, et le rail perdrait ses icônes."""
        with open(os.path.join(RACINE, "main.py"), encoding="utf-8") as f:
            main = f.read()
        assert 'globals["ico"]' in main
        assert 'globals["icone"]' not in main


class TestRenduReel:
    def test_la_page_daccueil_sert_des_traces(self, client):
        page = client.get("/").text
        assert page.count('stroke="currentColor"') >= 9, "les huit cartes et le canal"
        assert not EMOJI.search(page), "un emoji est passé jusqu'à la page"

    def test_le_rail_de_ladministration_aussi(self, admin):
        page = admin.get("/admin/annuaires").text
        rail = page[page.index('class="rail"'):page.index("</nav>")]
        assert rail.count("<svg") >= 13, "treize destinations, treize icônes"
        assert not EMOJI.search(rail)
