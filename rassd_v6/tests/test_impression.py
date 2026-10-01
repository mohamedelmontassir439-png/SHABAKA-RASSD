"""Un document imprimé par un abonné ne doit emporter que lui-même.

Relevé le 01/10/2026 sur le reçu REC-2026-0002, imprimé en PDF par un
membre: la barre de navigation, le sélecteur de langue, la pastille de
profil et le pied de page du site encadraient le document. La règle
d'impression existait dans document.html mais visait « .nav-wrap », une
classe qui n'existe pas — la barre s'appelle « nav ».
"""
import re

import pytest


def _base():
    return open("templates/base_public.html", encoding="utf-8").read()


def _bloc_impression(texte):
    i = texte.index("@media print")
    profondeur, debut = 0, texte.index("{", i)
    for j in range(debut, len(texte)):
        if texte[j] == "{":
            profondeur += 1
        elif texte[j] == "}":
            profondeur -= 1
            if profondeur == 0:
                return texte[i:j + 1]
    return texte[i:]


class TestCeQuiDisparait:
    @pytest.mark.parametrize("element", [
        "nav", ".footer", "footer", ".lang-switch", ".nav-avatar",
        ".doc-actions", ".dec-actions",
    ])
    def test_l_habillage_du_site_ne_s_imprime_pas(self, element):
        bloc = _bloc_impression(_base())
        cible = bloc[:bloc.index("display: none")]
        assert element in cible, element

    def test_la_regle_vit_dans_la_mise_en_page_commune(self):
        """Posée dans un seul gabarit, elle ne valait que pour lui."""
        assert "@media print" in _base()

    def test_aucun_selecteur_fantome(self):
        # « .nav-wrap » et « .app-topbar » n'existent nulle part: une règle
        # qui les vise ne cache rien.
        document = open("templates/document.html", encoding="utf-8").read()
        for fantome in (".nav-wrap", ".app-topbar", ".app-sidebar", ".site-footer"):
            assert fantome not in document, fantome


class TestMiseEnPage:
    def test_le_format_de_page_est_defini(self):
        base = _base()
        assert "@page" in base and "A4" in base

    def test_les_aplats_de_couleur_sont_conserves(self):
        """Sans cela, l'en-tête et les bandeaux sortent blancs sur blanc."""
        assert "print-color-adjust: exact" in _bloc_impression(_base())

    def test_le_recu_ne_se_coupe_pas_en_deux(self):
        document = open("templates/document.html", encoding="utf-8").read()
        assert "page-break-inside: avoid" in document


class TestFormulation:
    def test_le_pied_du_document_annonce_le_semi_public(self):
        # Il échappait aux passes précédentes en écrivant « &amp; ».
        document = open("templates/document.html", encoding="utf-8").read()
        for ligne in document.splitlines():
            if "Plateforme de veille" in ligne:
                assert "semi-public" in ligne, ligne.strip()[:90]
