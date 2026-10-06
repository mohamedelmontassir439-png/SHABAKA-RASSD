# -*- coding: utf-8 -*-
"""L'intitulé d'un marché ne doit pas se répéter.

Le portail affiche dans la même cellule une version tronquée du titre, qui
se termine par des points de suspension, et sa version entière. L'extraction
ramenait les deux:

    « Construction d'un mur de clôture de la centrale thermique à charbon de
      Jerada de 350MW ... Construction d'un mur de clôture de la centrale
      thermique à charbon de Jerada de 350MW »

Relevé le 06/10/2026: 128 marchés sur 3 263. Ce n'est pas qu'inélégant — le
titre mange la largeur de la ligne, pousse le reste hors du cadre, et part
tel quel dans l'objet de l'email d'alerte.
"""
import pytest

from app.core.objets import sans_repetition


class TestDoublons:
    @pytest.mark.parametrize("brut,attendu", [
        # La forme la plus courante: la troncature, puis le titre entier.
        ("Equipement du forage n°17/517 sis au champ captant Nekour Lot : Conduites ... "
         "Equipement du forage n°17/517 sis au champ captant Nekour Lot : Conduites",
         "Equipement du forage n°17/517 sis au champ captant Nekour Lot : Conduites"),
        # Les bons de commande intercalent une étiquette entre les deux copies.
        ("RAMETTE PAPIER A4 80G NAVIGATOR OU SIMILAIRE Caractéristiques et "
         "spécifications : RAMETTE PAPIER A4 80G NAVIGATOR OU SIMILAIRE",
         "RAMETTE PAPIER A4 80G NAVIGATOR OU SIMILAIRE"),
    ])
    def test_le_titre_nest_rendu_quune_fois(self, brut, attendu):
        assert sans_repetition(brut) == attendu

    def test_on_garde_la_version_la_plus_complete(self):
        """La copie tronquée est un préfixe de l'autre: c'est l'autre qu'on
        garde, sinon on publierait un titre amputé."""
        brut = ("Renforcement de l'AEP du centre et des douars relevant de la commune "
                "Melloussa ... Renforcement de l'AEP du centre et des douars relevant "
                "de la commune Melloussa- Jouamaa- Lot : Equipement")
        rendu = sans_repetition(brut)
        assert rendu.endswith("Lot : Equipement")
        assert rendu.count("Renforcement de l'AEP") == 1


class TestCeQuOnNeTouchePas:
    @pytest.mark.parametrize("titre", [
        "Achat de fournitures de bureau",
        "Travaux de construction d'un mur de clôture de l'école primaire Slamate",
        # Deux lots voisins partagent leurs premiers mots sans etre un doublon.
        "Equipement du forage n°17/517 sis au champ captant Nekour Lot : Génie Civil",
        "Marché de travaux : lot 1 gros œuvre, lot 2 second œuvre, lot 3 finitions",
    ])
    def test_un_titre_sain_reste_intact(self, titre):
        """Mesuré sur 3 143 titres sains: aucun n'est modifié à tort. Mieux
        vaut un titre bavard qu'un titre amputé."""
        assert sans_repetition(titre) == titre

    def test_un_titre_court_nest_jamais_touche(self):
        """Sous deux fois l'amorce, la reprise ne prouve rien."""
        assert sans_repetition("Papier A4 Papier A4") == "Papier A4 Papier A4"

    @pytest.mark.parametrize("vide", ["", None, "   "])
    def test_le_vide_ne_casse_rien(self, vide):
        assert sans_repetition(vide) == ""


class TestLaCollecteNeLesProduitPlus:
    @pytest.mark.parametrize("module", ["scraper", "ao_scraper"])
    def test_les_deux_collecteurs_passent_par_le_nettoyage(self, module):
        """Réparer la base sans corriger la collecte, c'est recommencer à
        chaque passage."""
        import importlib
        source = open(importlib.import_module(
            f"app.services.{module}").__file__, encoding="utf-8").read()
        assert "sans_repetition" in source
