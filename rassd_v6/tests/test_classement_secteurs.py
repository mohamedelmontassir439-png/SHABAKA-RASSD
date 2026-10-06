"""Le secteur décide qui reçoit quoi: une erreur ici fait manquer le marché.

La correspondance se faisait par simple sous-chaîne, sans frontière de mot.
Sur 64 mots-clés de cinq lettres ou moins, l'effet était ravageur. Relevé en
production le 30/09/2026: les marchés de produits de dératisation étaient
classés en développement informatique.
"""
import pytest

from app.core import sectors
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
        # Corrigé le 06/10/2026: une PRESTATION de nettoyage est un service
        # (S907), pas un achat de PRODUITS de nettoyage (P841). Le test
        # figeait l'erreur qu'il était censé surveiller — les deux secteurs
        # partagent le mot « nettoyage », et seul le mot « prestations »
        # tranche.
        ("Prestations de nettoyage des locaux", "S907"),
        ("ACHAT DE DETERGENT ET PRODUITS D ENTRETIEN", "P841"),
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


class TestDefautsMesuresLe06Octobre:
    """Quatre défauts relevés sur 3 263 avis réels, et leur correctif.

    Le classement décide qui reçoit quoi. Une erreur ici ne se voit pas: le
    marché ne manque à personne en apparence, il manque seulement à celui
    qu'il concernait.
    """

    def test_l_ordre_du_fichier_ne_departage_plus(self):
        """`score > best` retenait le premier secteur déclaré. T101, écrit en
        tête, remportait 109 égalités; S911, déclaré soixante-huitième, en
        perdait 263. La place d'un secteur dans le fichier décidait de sa
        part — et ce biais était invisible."""
        source = open(sectors.__file__, encoding="utf-8").read()
        assert "score > best_score" not in source
        # Le départage se fait sur des critères parlants avant le code.
        assert "par_objet.get(kv[0]" in source

    def test_le_titre_pese_plus_que_le_corps(self):
        """Mille cinq cents caractères de formules administratives
        couvraient un titre de six mots."""
        assert sectors._POIDS_OBJET > sectors._POIDS_FOND

    @pytest.mark.parametrize("objet,attendu", [
        ("Travaux d'aménagement au niveau de la Direction Régionale", "T110"),
        ("Réalisation de travaux d'aménagement d'espaces", "T110"),
    ])
    def test_des_travaux_sans_specialite_restent_des_travaux(self, objet, attendu):
        """Ils tombaient en « Prestations diverses », un seau de services:
        182 avis sur 348 parlant de travaux étaient rangés hors des secteurs
        T, invisibles pour une entreprise du bâtiment."""
        assert classify(objet) == attendu

    def test_rien_ne_part_vers_un_seau_de_produits(self):
        """Un essai routait vers « Équipement technique divers » tout avis
        disant « achat »: 253 avis sans rapport y tombaient. Déplacer la
        décharge dans un secteur auquel des gens s'abonnent n'est pas
        classer. L'inconnu reste en « Prestations diverses », qui dit la
        vérité: on ne sait pas."""
        assert classify("Achat d'articles de sport") != "P820"

    @pytest.mark.parametrize("objet,interdit", [
        ("Réception des fonds de fouilles", "S911"),
        ("Travaux de construction d'un atelier mécanique", "S913"),
        ("Fourniture d'un salon pour la direction", "S917"),
        ("Mission A :", "S902"),
    ])
    def test_les_homonymes_ne_detournent_plus(self, objet, interdit):
        """« réception » d'un ouvrage n'est pas un cocktail, un « atelier »
        mécanique n'est pas une formation, un « salon » de direction n'est
        pas un salon professionnel."""
        assert classify(objet) != interdit

    @pytest.mark.parametrize("objet,attendu", [
        ("ACHAT DE DETERGENT ET PRODUITS D ENTRETIEN", "P841"),
        ("TRAVAUX D OUVRAGES D ART", "T101"),
        ("EXTENSION DU RESEAU D ASSAINISSEMENT", "T201"),
    ])
    def test_une_apostrophe_absente_ne_fait_plus_manquer_le_mot(self, objet, attendu):
        """Les avis marocains sont largement saisis en capitales, sans
        accents ni apostrophes. Dix mots-clés en portaient une et la
        cherchaient à la lettre — « ouvrage d'art », « réseau
        d'assainissement », « bureau d'étude »: du BTP de première ligne."""
        assert classify(objet) == attendu

    def test_le_classement_ne_depend_pas_de_la_casse_ni_des_accents(self):
        assert classify("TRAVAUX D ETANCHEITE") == classify("Travaux d'étanchéité")
