# -*- coding: utf-8 -*-
"""Le semi-public, filtrable comme les autres natures d'acheteur.

La plateforme classe les acheteurs en public, semi-public et privé partout:
listes, détail, documents, recherche. Partout sauf dans les réglages
d'alerte, où la case n'existait pas — un membre ne pouvait donc pas
demander les seuls marchés d'établissements publics (ONEE, OCP, ADM…),
qui sont précisément ceux que beaucoup visent.
"""
from datetime import date, timedelta

import pytest

from app.services.matching import matches


def _membre(types):
    import json
    return {"secteurs": "[]", "notif_regions": "[]", "notif_keywords": "",
            "notif_min_budget": 0, "notif_types": json.dumps(types)}


def _marche(organisme="public", type_offre="Public"):
    return {"id": "t1", "objet": "TRAVAUX", "acheteur": "ONEE",
            "secteur": "T101", "region": "Casablanca", "montant": "1 000 000",
            "type_offre": type_offre, "type_procedure": "marche",
            "organisme": organisme}


class TestFiltreParNature:
    def test_semi_public_demande_semi_public_recu(self):
        ok, raison = matches(_membre(["semi_public"]), _marche("semi_public"))
        assert ok, raison

    def test_semi_public_demande_public_ecarte(self):
        ok, raison = matches(_membre(["semi_public"]), _marche("public"))
        assert not ok and raison == "type"

    def test_public_demande_semi_public_ecarte(self):
        """Un \u00e9tablissement public n'est pas l'\u00c9tat: la distinction tient."""
        ok, _ = matches(_membre(["semi_public"]), _marche("public", "Public"))
        assert not ok

    def test_sans_filtre_tout_passe(self):
        assert matches(_membre([]), _marche("semi_public"))[0]

    def test_les_autres_natures_restent_filtrables(self):
        assert matches(_membre(["Priv\u00e9"]), _marche("prive", "Priv\u00e9"))[0]
        assert matches(_membre(["Public"]), _marche("public", "Public"))[0]

    def test_un_marche_sans_organisme_ne_casse_rien(self):
        marche = _marche()
        del marche["organisme"]
        assert matches(_membre(["Public"]), marche)[0]


class TestReglages:
    @pytest.fixture()
    def connecte(self, client, db):
        db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                      pw_hash,session_token,actif,secteurs,email_verified)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   ("Ahmed", "sp@example.com", "pro", "ACTIVE",
                    (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                    "x", "jeton-semi-public-x", 1, '["T101"]', 1))
        db.commit()
        client.cookies.set("_session", "jeton-semi-public-x")
        return client

    def test_la_case_est_proposee(self, connecte):
        page = connecte.get("/settings").text
        assert 'value="semi_public"' in page

    def test_les_quatre_natures_sont_la(self, connecte):
        page = connecte.get("/settings").text
        for valeur in ("Public", "semi_public", "bon_commande"):
            assert f'value="{valeur}"' in page, valeur
