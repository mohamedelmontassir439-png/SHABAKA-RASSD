# -*- coding: utf-8 -*-
"""Les douze régions, quelle que soit l'écriture du lieu dans l'avis."""
import json

import pytest

from app.core.regions import NOMS, region_de
from app.services.matching import matches as match_tender
from tests.test_cloisonnement import membre, _membre  # noqa: F401  (fixture)


@pytest.mark.parametrize("lieu, region", [
    ("Agadir Ida Ou Tanane", "Souss-Massa"),
    ("Taroudannt", "Souss-Massa"),
    ("Maroc, Tanger-Assilah", "Tanger-Tétouan-Al Hoceïma"),
    ("Al haouz", "Marrakech-Safi"),
    ("Assa-Zag", "Guelmim-Oued Noun"),
    ("Sidi Ifni", "Guelmim-Oued Noun"),
    ("Ifrane", "Fès-Meknès"),
    ("El Aioun Sidi Mellouk", "L'Oriental"),
    ("Laayoune", "Laâyoune-Sakia El Hamra"),
    ("Province de Khemissat", "Rabat-Salé-Kénitra"),
    ("Region de fes - meknes", "Fès-Meknès"),
    ("Aousserd", "Dakhla-Oued Ed-Dahab"),
])
def test_region_de(lieu, region):
    assert region_de(lieu) == region


def test_etranger_et_national_sans_region():
    assert region_de("Danemark") == "" and region_de("Toutes les villes") == ""


def test_douze_regions():
    assert len(NOMS) == 12


class TestAlertes:
    def test_une_region_couvre_ses_provinces(self):
        m = {"secteurs": "[]", "notif_regions": json.dumps(["Souss-Massa"])}
        assert match_tender(m, {"region": "Taroudannt", "objet": "x"})[0]
        assert not match_tender(m, {"region": "Settat", "objet": "x"})[0]

    def test_ancienne_selection_toujours_valable(self):
        m = {"secteurs": "[]", "notif_regions": json.dumps(["Taroudannt"])}
        assert match_tender(m, {"region": "Taroudannt", "objet": "x"})[0]


class TestPages:
    def test_filtre_des_marches_par_region(self, membre, db):
        for i, lieu in enumerate(("Taroudannt", "Agadir Ida Ou Tanane", "Settat")):
            db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url,region)
                          VALUES(?,?,'A','T101','actif','2026-10-20','u',?)""",
                       (f"r{i}", f"MARCHE REGION {lieu.upper()}", lieu))
        db.commit()
        page = membre.get("/tenders?r=Souss-Massa").text
        assert "MARCHE REGION TAROUDANNT" in page and "MARCHE REGION AGADIR IDA OU TANANE" in page
        assert "MARCHE REGION SETTAT" not in page

    def test_parametres_proposent_les_douze_regions(self, membre, db):
        page = membre.get("/settings").text
        assert page.count('name="notif_regions_sel"') == 12
