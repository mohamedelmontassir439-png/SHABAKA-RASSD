"""Le secteur décide qui reçoit quoi: une erreur ici fait manquer le marché.

La correspondance se faisait par simple sous-chaîne, sans frontière de mot.
Sur 64 mots-clés de cinq lettres ou moins, l'effet était ravageur. Relevé en
production le 30/09/2026: les marchés de produits de dératisation étaient
classés en développement informatique.
"""
import pytest

from app.core.sectors import classify


class TestFrontieresDeMots:
    """Un mot-clé caché dans un mot plus long ne doit rien déclencher."""

    @pytest.mark.parametrize("objet, interdit", [
        ("Achat d'insecticides et de raticides", "S901"),      # « tic »
        ("Transport du personnel administratif", "T204"),      # « port »
        ("Rapport d'activité annuel", "T204"),                 # « port »
        ("Travaux d'isolation thermique", "T107"),             # « sol »
        ("Planification des interventions", "T501"),           # « plan »
    ])
    def test_sous_chaine_ne_classe_pas(self, objet, interdit):
        assert classify(objet) != interdit, objet

    def test_le_mot_entier_classe_toujours(self):
        assert classify("Travaux au port de Nador") == "T204"

    def test_le_prefixe_de_mot_compte(self):
        # « outil » doit continuer d'attraper « outillage ».
        assert classify("Achat d'outillage d'atelier") == "P823"


class TestAccents:
    """Les avis marocains sont saisis en capitales, sans accents."""

    @pytest.mark.parametrize("sans, avec", [
        ("ACHAT DE PRODUITS POUR DERATISATION", "Achat de produits pour dératisation"),
        ("TRAVAUX D ELECTRICITE", "Travaux d'électricité"),
        ("TRAVAUX D ETANCHEITE", "Travaux d'étanchéité"),
    ])
    def test_meme_classement_avec_ou_sans_accents(self, sans, avec):
        assert classify(sans) == classify(avec)
        assert classify(sans) != "S904", "ne doit pas tomber en « divers »"


class TestCollisionsResolues:
    """Un même mot peut appartenir à deux métiers: le contexte tranche."""

    def test_reseau_d_eau_n_est_pas_informatique(self):
        assert classify("Maintenance du réseau d'eau potable") == "T201"

    def test_reseau_informatique_le_reste(self):
        assert classify("Maintenance du réseau informatique") == "P818"

    def test_tuyaux_vont_a_l_hydraulique(self):
        assert classify("Achat et fourniture de tuyaux polyéthylène") == "P806"


class TestCasReelsDeProduction:
    """Objets relevés en base le 30/09/2026, avec le secteur attendu."""

    @pytest.mark.parametrize("objet, attendu", [
        ("Fourniture et pose des climatiseurs", "P814"),
        ("ACHAT DE PRODUIT PESTICIDES ET INSECTICIDES", "P841"),
        ("Achat de matériel informatique", "P818"),
        ("Travaux de construction d'un bâtiment", "T101"),
        ("Taille et élagage des arbres et arbustes", "T111"),
        ("Prestations de nettoyage des locaux", "P841"),
    ])
    def test_classement_attendu(self, objet, attendu):
        assert classify(objet) == attendu, objet


class TestExpressionsComposees:
    """Le français glisse des articles et pluralise chaque mot."""

    def test_liaison_toleree_entre_les_mots(self):
        # Relevé le 30/09/2026: « système d' information territorial » tombait
        # en « Prestations diverses », le mot-clé étant « système information ».
        assert classify("Conception et déploiement d'un système d'information "
                        "territorial") == "S901"

    def test_pluriel_sur_chaque_mot(self):
        # « espace vert » doit reconnaître « espaces verts ».
        assert classify("Aménagement des espaces verts de la commune") == "T111"

    def test_expression_l_emporte_sur_le_mot_isole(self):
        # « développement informatique » (Études TIC) est plus précis que le
        # simple « informatique » (Équipements informatiques), présent aussi.
        assert classify("Développement informatique sur mesure") == "S901"
        assert classify("Achat de matériel informatique") == "P818"


class TestVocabulaireCourant:
    """Mots relevés dans les marchés tombés en « Prestations diverses ».

    Sur un échantillon de 800 marchés actifs, 281 finissaient sans secteur
    précis faute de mot-clé. Les plus fréquents sont ici.
    """

    @pytest.mark.parametrize("objet, attendu", [
        ("Achat de rames de papier A4", "P825"),
        ("Achat de toner et de cartouches", "P825"),
        ("Pause café et petit déjeuner pour les participants", "S911"),
        ("Achat d'eau minérale et de gâteaux", "S911"),
        ("Fourniture de lampes d'éclairage", "T401"),
        ("Achat de billets d'avion aller retour", "S915"),
        ("Achat des imprimés administratifs", "P836"),
    ])
    def test_classement_du_vocabulaire_courant(self, objet, attendu):
        assert classify(objet) == attendu, objet


class TestAmbiguitesAssumees:
    def test_un_consommable_nomme_avec_sa_machine_reste_ambigu(self):
        """« Toner pour imprimante » touche deux secteurs à poids égal.

        Le consommable relève des fournitures de bureau, la machine des
        équipements informatiques, et les deux mots pèsent pareil. Aucun
        départage n'est plus juste que l'autre ici: on constate le résultat
        au lieu de tordre le classeur pour un cas que le vocabulaire ne
        tranche pas.
        """
        assert classify("Fourniture de toner pour imprimante") in ("P825", "P818")
