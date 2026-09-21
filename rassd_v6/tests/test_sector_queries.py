"""Termes de recherche annuaire pour les 83 secteurs.

Les cas vérifiés correspondent à des mesures réelles sur Google Maps
(Casablanca, 09/09/2026): chaque correction listée ici répare une requête
qui ramenait le mauvais métier.
"""
import pytest

from app.core.sectors import SECTORS
from app.services.sector_queries import (
    REQUETES, IMPRECIS, requete_secteur, secteurs_sans_requete,
)


class TestCouverture:
    def test_les_83_secteurs_ont_une_requete(self):
        assert secteurs_sans_requete() == []

    def test_tous_les_secteurs_sont_curates(self):
        manquants = [c for c in SECTORS if c not in REQUETES]
        assert manquants == [], f"secteurs sans requête curatée: {manquants}"

    def test_aucune_requete_orpheline(self):
        """Une requête pour un code inexistant signale une faute de frappe."""
        orphelins = [c for c in REQUETES if c not in SECTORS]
        assert orphelins == []

    def test_requetes_non_vides_et_lisibles(self):
        for code, req in REQUETES.items():
            assert len(req.strip()) >= 6, f"{code}: requête trop courte"
            assert req == req.strip()


class TestCorrectionsMesurees:
    """Chaque cas ci-dessous ramenait le mauvais métier avant correction."""

    def test_electricite_vise_les_installateurs(self):
        """Ramenait des magasins de luminaires au lieu d'électriciens."""
        req = requete_secteur("T401")
        assert "installation électrique" in req
        assert "éclairage public" not in req

    def test_produits_chimiques_non_tronques(self):
        """« para-chimiques » coupé sur le tiret donnait « produits chimiques para »."""
        req = requete_secteur("P832")
        assert req == "produits chimiques industriels"
        assert not req.endswith("para")

    def test_amenagement_distinct_de_la_construction(self):
        """Ramenait les mêmes entreprises générales que T101."""
        assert requete_secteur("T112") != requete_secteur("T101")
        assert "aménagement intérieur" in requete_secteur("T112")

    def test_ascenseurs_pas_seulement_monte_charge(self):
        """Le découpage sur le tiret perdait « Ascenseurs »."""
        assert "ascenseurs" in requete_secteur("T109").lower()

    def test_sono_video_garde_son_metier(self):
        assert "sonorisation" in requete_secteur("P804").lower()


class TestSecteursImprecis:
    def test_les_fourre_tout_sont_signales(self):
        """Ces libellés n'ont pas d'équivalent en annuaire: c'est documenté."""
        assert "S904" in IMPRECIS      # « Prestations diverses »
        assert IMPRECIS <= set(SECTORS)

    def test_ils_ont_quand_meme_une_requete(self):
        for code in IMPRECIS:
            assert requete_secteur(code).strip()


class TestRepli:
    def test_code_inconnu_retombe_sur_le_libelle(self):
        assert requete_secteur("XX999") == ""

    def test_les_deux_moteurs_partagent_le_meme_mapping(self):
        from app.services.maps_scraper import requete_secteur as maps_req
        from app.services.places_scraper import _requete_secteur as places_req
        for code in ("T101", "T401", "P832", "S931"):
            assert maps_req(code) == places_req(code) == requete_secteur(code)
