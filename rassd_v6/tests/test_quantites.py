"""« 50 jour » se lit mal, et ne décrit pas ce dont il s'agit.

La source publie « Unité de mesure: jour » et « Quantité: 50 » séparément;
la collecte les recolle. Relevé sur bdc_387502, « Location d'une pelle sur
pneus »: la fiche affichait « QUANTITÉ COMMANDÉE — 50 jour ». La donnée est
juste — cinquante jours de location — mais le pluriel manque et le libellé
décrit une quantité là où il s'agit d'une durée.

Le travail se fait à l'affichage: les milliers de fiches déjà collectées en
profitent sans être recollectées.
"""
import pytest

from app.core import quantites as Q


class TestAccord:
    @pytest.mark.parametrize("brut, attendu", [
        ("50 jour", "50 jours"),
        ("3 unité", "3 unités"),
        ("4 lot", "4 lots"),
        ("2 pièce", "2 pièces"),
        ("10 heure", "10 heures"),
        ("3 an", "3 ans"),
    ])
    def test_le_pluriel_est_pose(self, brut, attendu):
        assert Q.texte(brut) == attendu

    @pytest.mark.parametrize("brut", ["1 jour", "1 unité", "1 lot", "1 an"])
    def test_le_singulier_est_laisse(self, brut):
        assert Q.texte(brut) == brut

    @pytest.mark.parametrize("brut", ["120 kg", "12 m3", "12 m²", "5 Qx", "1 Ft"])
    def test_les_symboles_restent_invariables(self, brut):
        """Un symbole ne prend pas la marque du pluriel: « 120 kg »."""
        assert Q.texte(brut) == brut

    def test_mois_est_deja_invariable(self):
        assert Q.texte("2 mois") == "2 mois"

    def test_un_pluriel_irregulier_est_connu(self):
        assert Q.texte("2 travail") == "2 travaux"


class TestNombresEcritsAvecEspaces:
    """« 1 500 litre » doit rester un seul nombre.

    Une première version coupait après le « 1 »: l'unité devenait
    « 500 litre », le pluriel sautait et la durée n'était plus reconnue.
    """

    @pytest.mark.parametrize("brut, attendu", [
        ("1 500 litre", "1 500 litres"),
        ("2 400 jour", "2 400 jours"),
        ("12 000 m3", "12 000 m3"),
    ])
    def test_le_nombre_est_pris_en_entier(self, brut, attendu):
        assert Q.texte(brut) == attendu

    def test_une_decimale_ne_declenche_pas_de_pluriel_errone(self):
        assert Q.texte("1 500,5 kg") == "1 500,5 kg"


class TestDuree:
    @pytest.mark.parametrize("brut", ["50 jour", "2 mois", "1 an", "10 heure",
                                      "3 semaine", "2 trimestre"])
    def test_une_unite_de_temps_est_une_duree(self, brut):
        assert Q.est_duree(brut)

    @pytest.mark.parametrize("brut", ["3 unité", "120 kg", "4 lot", "1 Ft", "12 m3"])
    def test_le_reste_est_une_quantite(self, brut):
        assert not Q.est_duree(brut)

    def test_le_cas_releve_en_production(self):
        # « Location d'une pelle sur pneus », bdc_387502.
        texte, duree = Q.formater("50 jour")
        assert texte == "50 jours" and duree


class TestRobustesse:
    @pytest.mark.parametrize("brut", ["", None, "   "])
    def test_une_valeur_vide_ne_casse_rien(self, brut):
        assert Q.texte(brut) == ""
        assert not Q.est_duree(brut)

    def test_un_nombre_seul_passe_tel_quel(self):
        assert Q.texte("50") == "50"

    def test_un_texte_libre_n_est_pas_mutile(self):
        assert Q.texte("voir le cahier des charges") == "voir le cahier des charges"
