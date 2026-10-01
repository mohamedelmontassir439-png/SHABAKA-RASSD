# -*- coding: utf-8 -*-
"""Les gagnants de marchés, de l'avis d'attribution à la file d'appel."""
import pytest

from app.services.companies import normalize_company_name
from app.services.gagnants import _nettoyer, noms_gagnants


class TestDecoupage:
    """Le champ « adjudicataire » tel que la source l'écrit."""

    def test_nom_simple_inchange(self):
        assert noms_gagnants("STE ATLAS BTP SARL") == ["STE ATLAS BTP SARL"]

    def test_vide(self):
        assert noms_gagnants("") == []
        assert noms_gagnants(None) == []

    @pytest.mark.parametrize("brut", [
        "Infructueux", "Annulé", "annulée.", "Néant", "NEANT", "voir pv",
        "Voir détail des lots au niveau du PV",
    ])
    def test_etat_de_procedure_nest_pas_une_entreprise(self, brut):
        assert noms_gagnants(brut) == []

    def test_deux_lots_deux_societes(self):
        assert noms_gagnants("lot 1 STE OUBNITRA SARL lot 2: STE SOLANOUR SARL") == [
            "STE OUBNITRA SARL", "STE SOLANOUR SARL"]

    def test_un_lot_attribue_un_lot_infructueux(self):
        assert noms_gagnants("NS DENTAL (lot 1) infructueux (lot 2)") == ["NS DENTAL"]

    def test_societe_avant_le_marqueur(self):
        assert noms_gagnants(
            "ENTREPRISE OKACHA ABDERRAHIM SARL AU (lot 1) STE BAICHOU TRAV SARL") == [
            "ENTREPRISE OKACHA ABDERRAHIM SARL AU", "STE BAICHOU TRAV SARL"]

    def test_point_virgule_separe_aussi(self):
        assert noms_gagnants("lot 1: expert pin lot 2; damana kit") == [
            "expert pin", "damana kit"]

    def test_meme_societe_sur_deux_lots_compte_une_fois(self):
        assert noms_gagnants("lot 1: STE ALPHA SARL; lot 2: Ste Alpha") == [
            "STE ALPHA SARL"]


class TestNomLisible:
    """Ce que le fondateur lit dans sa liste d'appels."""

    @pytest.mark.parametrize("brut,attendu", [
        ("LOT 1 & 2 & 3: M2M SERVICES", "M2M SERVICES"),
        ("LOT 1 & 2 :STE BAICHOU TRAV SARL", "STE BAICHOU TRAV SARL"),
        ("LOT 1& 2 :STE EXTRA BT SARL", "STE EXTRA BT SARL"),
    ])
    def test_les_restes_de_numeros_de_lot_disparaissent(self, brut, attendu):
        assert noms_gagnants(brut) == [attendu]

    @pytest.mark.parametrize("nom", ["2SBT", "2LL HMI SARL AU", "3M MAROC"])
    def test_un_chiffre_colle_au_nom_est_conserve(self, nom):
        """« 2SBT » est une raison sociale, pas un numéro de lot."""
        assert _nettoyer(nom) == nom
        assert noms_gagnants(nom) == [nom]

    def test_le_nettoyage_ne_vide_jamais_un_nom(self):
        for brut in ("2 & 3: M2M", "& ALPHA", "1 BETA"):
            assert _nettoyer(brut)


class TestCleCanonique:
    """La clé qui relie un attributaire à son téléphone."""

    def test_les_formes_juridiques_ne_distinguent_pas(self):
        a = normalize_company_name(noms_gagnants("LOT 1 & 2 :STE BAICHOU TRAV SARL")[0])
        b = normalize_company_name("Baichou Trav")
        assert a == b == "baichou trav"

    def test_un_etat_de_procedure_na_pas_de_cle(self):
        assert [normalize_company_name(n) for n in noms_gagnants("Annulé")] == []
