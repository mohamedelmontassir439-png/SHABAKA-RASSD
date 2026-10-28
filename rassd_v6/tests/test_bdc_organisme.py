# -*- coding: utf-8 -*-
"""Bons de commande: le filtre Public / Semi-public / Privé, comme sur /tenders."""
from tests.test_cloisonnement import _marche, membre  # noqa: F401


def test_filtre_par_nature_de_lacheteur(membre, db):
    _marche(db, "bdc_1", "T101", "BON D UNE COMMUNE", "bon_commande")
    _marche(db, "bdc_2", "T101", "BON DE L ONEE", "bon_commande")
    db.execute("UPDATE tenders SET organisme='public' WHERE id='bdc_1'")
    db.execute("UPDATE tenders SET organisme='semi_public' WHERE id='bdc_2'")
    db.commit()
    page = membre.get("/bons-de-commande").text
    assert 'name="t"' in page and "BON D UNE COMMUNE" in page and "BON DE L ONEE" in page
    page = membre.get("/bons-de-commande?t=semi_public").text
    assert "BON DE L ONEE" in page and "BON D UNE COMMUNE" not in page
    assert 'value="semi_public" selected' in page.replace("  ", " ").replace("  ", " ")
    page = membre.get("/bons-de-commande?t=public").text
    assert "BON D UNE COMMUNE" in page and "BON DE L ONEE" not in page


def test_valeur_inconnue_ignoree(membre, db):
    _marche(db, "bdc_3", "T101", "BON QUELCONQUE", "bon_commande")
    assert "BON QUELCONQUE" in membre.get("/bons-de-commande?t=nimporte").text
