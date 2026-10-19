# -*- coding: utf-8 -*-
"""Un avis de marché s'adresse à qui en a déjà lu cent.

Il suppose connus une dizaine de mots de métier: estimation, plis, caution
provisoire, qualification, classe. Celui qui soumissionne pour la première
fois perd son premier marché sur un détail de procédure, pas sur son prix —
un dossier déposé une minute trop tard n'est pas lu, si bon soit-il.

L'encadré dit cinq choses, pas davantage: un pavé d'explications ne se lit
pas plus qu'un avis.
"""
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gabarit():
    with open(os.path.join(RACINE, "templates", "detail.html"), encoding="utf-8") as f:
        return f.read()


class TestLEncadre:
    def test_il_est_sur_la_fiche(self):
        assert 'class="lire"' in _gabarit()

    def _branches(self):
        """Les deux versions de l'encadré, telles que le gabarit les écrit.

        Le fichier porte sept blocs: deux propres au bon de commande, deux
        propres à l'appel d'offres, trois communs. Cinq s'affichent à chaque
        fois — compter les blocs du fichier ne dit donc rien, il faut
        compter ceux de chaque branche.
        """
        g = _gabarit()
        debut = g.index("{% set bdc =")
        si = g.index("{% if bdc %}", debut)
        sinon = g.index("{% else %}", si)
        fin = g.index("{% endif %}", sinon)
        commun = g[fin:g.index('class="desc-section"', fin)]
        return (g[si:sinon] + commun, g[sinon:fin] + commun)

    def test_chaque_branche_tient_en_cinq_points(self):
        """Au-delà, il devient un mode d'emploi que personne n'ouvre."""
        for branche in self._branches():
            assert branche.count('class="lire-item"') == 5

    def test_il_distingue_le_bon_de_commande(self):
        """Un bon de commande n'a ni caution, ni ouverture de plis, ni
        estimation publiée: lui servir les règles de l'appel d'offres, ce
        serait expliquer de travers."""
        gabarit = _gabarit()
        assert "t.type_procedure == 'bon_commande'" in gabarit
        assert "lire_bdc_t" in gabarit and "lire_estim_t" in gabarit

    @pytest.mark.parametrize("cle", [
        "lire_titre", "lire_estim_t", "lire_estim_d", "lire_date_t", "lire_date_d",
        "lire_qualif_t", "lire_qualif_d", "lire_dossier_t", "lire_dossier_d",
        "lire_caution_t", "lire_caution_d", "lire_bdc_t", "lire_bdc_d",
        "lire_quantite_t", "lire_quantite_d",
    ])
    def test_chaque_texte_existe_dans_les_deux_langues(self, cle):
        from app.core.i18n import tr
        for langue in ("fr", "ar"):
            texte = tr(cle, langue)
            assert texte and texte != cle, f"{cle} manquant en {langue}"

    def test_il_ne_promet_pas_le_cahier_des_charges(self):
        """Nous publions l'avis, pas le CPS. Le dire évite la déception, et
        c'est honnête: le dossier se retire chez l'acheteur."""
        from app.core.i18n import tr
        assert "cahier des charges" in tr("lire_dossier_d", "fr")


class TestRenduReel:
    def test_chaque_procedure_recoit_ses_propres_regles(self):
        """Servir à un bon de commande les règles de l'appel d'offres, ce
        serait expliquer de travers — et faire chercher une caution qui
        n'existe pas."""
        bdc, appel = TestLEncadre()._branches()
        assert "lire_bdc_t" in bdc and "lire_quantite_t" in bdc
        assert "lire_caution_t" not in bdc and "lire_estim_t" not in bdc
        assert "lire_estim_t" in appel and "lire_caution_t" in appel
        assert "lire_bdc_t" not in appel
        # Les trois points communs sont dans les deux.
        for commun in ("lire_date_t", "lire_qualif_t", "lire_dossier_t"):
            assert commun in bdc and commun in appel, commun
