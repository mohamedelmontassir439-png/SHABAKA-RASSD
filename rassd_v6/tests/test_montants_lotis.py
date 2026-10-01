"""Un marché loti ne vaut pas mille milliards de dirhams.

La source écrit parfois plusieurs montants dans la même case:
« LOT 1: 1.888.272,00 / LOT 2: 3.500.000,00 ». La lecture retirait tous les
séparateurs et collait les chiffres bout à bout. Relevé le 01/10/2026 en
base: treize marchés valaient jusqu'à 1 188 827 200 220 980 739 884 187 648
dirhams — et sortaient en tête de tout tri par montant, donc en tête des
pistes de sous-traitance proposées aux membres.
"""
import pytest

from app.services.soustraitance import PLAFOND_MONTANT, parse_montant


class TestMontantSimple:
    @pytest.mark.parametrize("brut, attendu", [
        ("48 516 000,00 MAD", 48_516_000.0),
        ("1.188.827.200,00", 1_188_827_200.0),
        ("70 693 353.60", 70_693_353.60),
        ("2 619 000,00", 2_619_000.0),
    ])
    def test_les_formats_de_la_source(self, brut, attendu):
        assert abs(parse_montant(brut) - attendu) < 0.01


class TestMarcheLoti:
    @pytest.mark.parametrize("brut, attendu", [
        ("LOT 1: 1.888.272,00 / LOT 2: 3.500.000,00", 5_388_272.0),
        ("LOT 1 : 8.355.612,00 & LOT 2 : 1.000.000,00", 9_355_612.0),
        ("Lot N° 1:535 317,55 / LOT 2: 100 000,00", 635_317.55),
        ("lot 1; 178 800.00 lot 2: 50 000,00", 228_800.0),
    ])
    def test_les_lots_sont_additionnes(self, brut, attendu):
        """C'est le total attribué qui intéresse, pas un chiffre collé."""
        assert abs(parse_montant(brut) - attendu) < 0.01

    def test_le_numero_de_lot_n_est_pas_un_montant(self):
        # Sans ce garde-fou, « LOT 1 » et « LOT 2 » ajoutaient 3 dirhams.
        assert parse_montant("LOT 1: 1 000,00 / LOT 2: 2 000,00") == 3_000.0

    @pytest.mark.parametrize("forme", ["LOT 3", "lot n° 3", "Lot N 3", "lots 3"])
    def test_les_ecritures_du_numero(self, forme):
        assert parse_montant(f"{forme}: 1 000,00") == 1_000.0


class TestPlafond:
    def test_un_total_absurde_vaut_zero(self):
        """Mieux vaut une case vide qu'un chiffre impossible sur une fiche."""
        assert parse_montant("99.999.999.999.999,00") == 0.0

    def test_le_plafond_laisse_passer_les_vrais_gros_marches(self):
        # Le plus gros marché de la base avoisine quatre milliards.
        assert parse_montant("4.186.896.012,00") == 4_186_896_012.0
        assert 4_186_896_012.0 < PLAFOND_MONTANT


class TestRobustesse:
    @pytest.mark.parametrize("brut", ["", None, "néant", "non communiqué", "---"])
    def test_rien_d_exploitable_vaut_zero(self, brut):
        assert parse_montant(brut) == 0.0
