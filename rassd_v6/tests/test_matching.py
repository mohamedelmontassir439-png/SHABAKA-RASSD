"""Moteur de correspondance marché ↔ membre."""
import pytest

from app.services.matching import matches, parse_amount, parse_keywords, member_filters


TENDER = {
    "secteur": "T101",
    "region": "Casablanca-Settat",
    "montant": "1 250 000,00 MAD",
    "objet": "Travaux de construction et installation électrique",
    "acheteur": "Commune de Casablanca",
    "description": "Lot unique de plomberie et de peinture.",
    "type_offre": "Public",
    "type_procedure": "marche",
}


class TestParseAmount:
    @pytest.mark.parametrize("raw,expected", [
        ("1 250 000,00 DH", 1250000.0),
        ("1.250.000 MAD", 1250000.0),
        ("250000", 250000.0),
        ("1,250,000", 1250000.0),
        ("1250,50", 1250.5),
        (500000, 500000.0),
        ("", 0.0),
        (None, 0.0),
        ("Non précisé", 0.0),
    ])
    def test_formats_marocains(self, raw, expected):
        assert parse_amount(raw) == expected


class TestFiltres:
    def test_sans_filtre_tout_passe(self):
        assert matches({"secteurs": "[]"}, TENDER)[0] is True

    def test_secteur_correspondant(self):
        assert matches({"secteurs": '["T101"]'}, TENDER)[0] is True

    def test_secteur_non_correspondant(self):
        ok, reason = matches({"secteurs": '["T102"]'}, TENDER)
        assert ok is False and reason == "secteur"

    @pytest.mark.parametrize("region", [
        "Casablanca-Settat", "casablanca settat", "CASABLANCA-SETTAT", "Casablanca",
    ])
    def test_region_insensible_accents_et_separateurs(self, region):
        m = {"secteurs": "[]", "notif_regions": f'["{region}"]'}
        assert matches(m, TENDER)[0] is True

    def test_region_differente_exclut(self):
        m = {"secteurs": "[]", "notif_regions": '["Fès-Meknès"]'}
        ok, reason = matches(m, TENDER)
        assert ok is False and reason == "region"

    def test_budget_minimum_respecte(self):
        assert matches({"secteurs": "[]", "notif_min_budget": 500000}, TENDER)[0] is True

    def test_budget_minimum_trop_eleve(self):
        ok, reason = matches({"secteurs": "[]", "notif_min_budget": 5000000}, TENDER)
        assert ok is False and reason == "budget"

    def test_montant_inconnu_ne_bloque_jamais(self):
        """Une donnée absente ne doit pas faire manquer une opportunité."""
        sans_montant = dict(TENDER, montant="")
        assert matches({"secteurs": "[]", "notif_min_budget": 9999999}, sans_montant)[0] is True

    @pytest.mark.parametrize("kw", ["électricité", "ELECTRIQUE", "plomberie", "peinture, toiture"])
    def test_mots_cles_insensibles_casse_et_accents(self, kw):
        assert matches({"secteurs": "[]", "notif_keywords": kw}, TENDER)[0] is True

    def test_mot_cle_absent_exclut(self):
        ok, reason = matches({"secteurs": "[]", "notif_keywords": "informatique"}, TENDER)
        assert ok is False and reason == "keywords"

    def test_mot_cle_cherche_aussi_dans_acheteur(self):
        assert matches({"secteurs": "[]", "notif_keywords": "Commune"}, TENDER)[0] is True

    def test_type_correspondant(self):
        assert matches({"secteurs": "[]", "notif_types": '["Public"]'}, TENDER)[0] is True

    def test_type_non_correspondant(self):
        ok, reason = matches({"secteurs": "[]", "notif_types": '["bon_commande"]'}, TENDER)
        assert ok is False and reason == "type"

    def test_bon_de_commande_reconnu(self):
        bc = dict(TENDER, type_procedure="bon_commande")
        assert matches({"secteurs": "[]", "notif_types": '["bon_commande"]'}, bc)[0] is True

    def test_filtres_cumulables(self):
        m = {"secteurs": '["T101"]', "notif_regions": '["Casablanca-Settat"]',
             "notif_keywords": "électricité", "notif_min_budget": 100000}
        assert matches(m, TENDER)[0] is True

    def test_un_seul_filtre_en_echec_suffit_a_exclure(self):
        m = {"secteurs": '["T101"]', "notif_regions": '["Oriental"]',
             "notif_keywords": "électricité"}
        assert matches(m, TENDER)[0] is False


class TestParsingFiltres:
    def test_mots_cles_separateurs_multiples(self):
        assert parse_keywords("béton, électricité; plomberie\nzinc") == \
            ["béton", "électricité", "plomberie", "zinc"]

    def test_json_invalide_ne_casse_pas(self):
        f = member_filters({"secteurs": "pas du json", "notif_regions": None})
        assert f["secteurs"] == [] and f["regions"] == []


class TestFamillesDeMots:
    """Le repli sur radical évite de manquer une opportunité pour une variante."""

    @pytest.mark.parametrize("keyword,texte", [
        ("électricité", "travaux d'installation électrique"),
        ("plomberie", "recrutement d'un plombier qualifié"),
        ("construction", "marché de constructeur de bâtiments"),
        ("maintenance", "maintenances des équipements"),
    ])
    def test_variante_du_meme_mot_declenche_l_alerte(self, keyword, texte):
        t = dict(TENDER, objet=texte, description="", acheteur="")
        assert matches({"secteurs": "[]", "notif_keywords": keyword}, t)[0] is True

    def test_mot_court_n_est_pas_elargi(self):
        """'eau' ne doit pas rapprocher n'importe quel mot commençant par 'eau'."""
        t = dict(TENDER, objet="fourniture de bureaux", description="", acheteur="")
        assert matches({"secteurs": "[]", "notif_keywords": "eau"}, t)[0] is False

    def test_mot_sans_rapport_exclut_toujours(self):
        t = dict(TENDER, objet="travaux de peinture", description="", acheteur="")
        assert matches({"secteurs": "[]", "notif_keywords": "informatique"}, t)[0] is False

    def test_sous_chaine_interne_ne_declenche_pas(self):
        """'eau' ne doit pas correspondre à 'bureaux' (piège des sous-chaînes)."""
        from app.services.matching import keyword_hits
        assert keyword_hits("eau", "fourniture de bureaux") is False
        assert keyword_hits("eau", "adduction d eau potable") is True

    def test_expression_de_plusieurs_mots(self):
        from app.services.matching import keyword_hits
        assert keyword_hits("travaux publics", "marche de travaux publics urbains") is True
        assert keyword_hits("travaux publics", "travaux de peinture") is False
