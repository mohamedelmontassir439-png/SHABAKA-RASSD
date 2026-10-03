# -*- coding: utf-8 -*-
"""Le nom de l'acheteur, tel qu'on peut le lire.

La source colle une étiquette de famille devant le nom, et pas toujours de
la même façon. L'email d'alerte affichait « ACHETEUR : casablanca BAIA
SOCIETE CASABLANCA BAÏA » — le client lit deux fois le même nom et doute du
sérieux de la veille.

Le principe qui gouverne ces tests: **ne jamais corrompre un nom**. Entre
laisser un libellé brut et en afficher un que personne n'a porté, on laisse
le brut.
"""
import pytest

from app.core.acheteurs import lisible


class TestEtiquetteCollee:
    """Sans séparateur: le libellé se termine par son propre début."""

    def test_le_cas_de_lemail(self):
        assert lisible("casablanca BAIA SOCIETE CASABLANCA BAÏA") == "SOCIETE CASABLANCA BAÏA"

    def test_le_doublon_simple(self):
        assert lisible("Ofppt OFPPT") == "OFPPT"

    def test_la_casse_et_les_accents_ne_comptent_pas(self):
        assert lisible("Societe Generale SOCIÉTÉ GÉNÉRALE") == "SOCIÉTÉ GÉNÉRALE"


class TestBarreOblique:
    def test_la_gauche_disparait_si_elle_se_repete(self):
        assert lisible("Cnss /CNSS DIRECTION REGIONALE ANFA") == "CNSS DIRECTION REGIONALE ANFA"

    def test_une_etiquette_de_classement_disparait(self):
        assert lisible("Autres societes / société Club Med") == "société Club Med"
        assert lisible("Autres organismes particuliers / DISTRICT SANITAIRE TANGER") \
            == "DISTRICT SANITAIRE TANGER"

    def test_un_organisme_different_est_conserve(self):
        """« Marsa maroc » est l'organisme, « DIRECTION DES ACHATS » son service:
        jeter la gauche ferait disparaître Marsa Maroc."""
        assert lisible("Marsa maroc /DIRECTION DES ACHATS") \
            == "Marsa maroc — DIRECTION DES ACHATS"

    def test_rien_a_droite_garde_la_gauche(self):
        assert lisible("Marsa maroc /") == "Marsa maroc"


class TestOnNeCorromptPas:
    def test_un_nom_propre_reste_intact(self):
        for nom in ("COMMUNE DE CASABLANCA", "MINISTERE DE L'INTERIEUR",
                    "CENTRE HOSPITALIER UNIVERSITAIRE MOHAMMED VI"):
            assert lisible(nom) == nom

    def test_un_libelle_ambigu_reste_brut(self):
        """Une répétition au milieu ne prouve rien: couper ici laissait
        « Sante et de la protection sociale DELEGUE… », un nom qui n'existe pas."""
        brut = ("Ministère De La Sante et de la protection sociale "
                "DELEGUE DU MINISTERE DE LA SANTE A SAFI")
        assert lisible(brut) == brut

    def test_jamais_de_resultat_vide(self):
        for brut in ("", "   ", "OFPPT", "A / B", "x x"):
            assert lisible(brut) == lisible(brut).strip()
            if brut.strip():
                assert lisible(brut).strip()

    def test_les_espaces_multiples_sont_reduits(self):
        assert lisible("  COMMUNE   DE    RABAT  ") == "COMMUNE DE RABAT"


class TestAffichage:
    def test_lemail_dalerte_montre_le_nom_nettoye(self):
        from app.services.notifications import build_email
        html = build_email({"id": "t1", "objet": "TRAVAUX",
                            "acheteur": "casablanca BAIA SOCIETE CASABLANCA BAÏA",
                            "secteur": "T101", "region": "Casablanca",
                            "montant": "1 000 000 MAD", "date_limite": "30/12/2026"}, "")
        assert "SOCIETE CASABLANCA BAÏA" in html
        assert "casablanca BAIA SOCIETE" not in html

    def test_le_filtre_est_disponible_dans_les_gabarits(self):
        import main
        assert "acheteur" in main.templates.env.globals
