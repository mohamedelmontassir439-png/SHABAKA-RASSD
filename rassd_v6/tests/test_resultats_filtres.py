"""Retrouver une adjudication précise parmi des milliers.

La page n'offrait qu'une recherche en texte libre sur 1659 résultats. Ce
qu'un membre vient y chercher est pourtant précis: qui a gagné, à quel prix,
dans son secteur et sa région. L'information existait, elle était
inatteignable.
"""
from datetime import date, datetime, timedelta

import pytest


def _membre(db, email="f@example.com"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, "free", "TRIAL",
                (date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                "x", "jeton-test", 1, '["T101"]', 1))
    db.commit()
    return "jeton-test"


def _resultat(db, rid, secteur="T101", region="Casablanca", montant="1 000 000,00",
              type_procedure="marche", montant_num=1000000.0, minutes=0):
    quand = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""INSERT INTO tender_results(id,objet,acheteur,adjudicataire,region,
                  montant,montant_num,secteur,date_adjudication,scraped_at,type_procedure)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (rid, f"TRAVAUX {rid}", "COMMUNE", "STE " + rid, region,
                montant, montant_num, secteur, "01/09/2026", quand, type_procedure))
    db.commit()


@pytest.fixture()
def connecte(client, db):
    jeton = _membre(db)
    client.cookies.set("_session", jeton)
    return client


class TestFiltres:
    def test_par_type_de_procedure(self, connecte, db):
        _resultat(db, "r_marche", type_procedure="marche")
        _resultat(db, "r_bdc", type_procedure="bon_commande")
        page = connecte.get("/resultats?type_p=bon_commande").text
        assert "r_bdc" in page and "r_marche" not in page

    def test_par_secteur(self, connecte, db):
        _resultat(db, "r_btp", secteur="T101")
        _resultat(db, "r_info", secteur="S901")
        page = connecte.get("/resultats?secteur=T101").text
        assert "r_btp" in page and "r_info" not in page

    def test_par_region(self, connecte, db):
        _resultat(db, "r_casa", region="Casablanca")
        _resultat(db, "r_fes", region="Fès")
        page = connecte.get("/resultats?region=Casablanca").text
        assert "r_casa" in page and "r_fes" not in page

    def test_par_montant_minimum(self, connecte, db):
        _resultat(db, "r_gros", montant_num=5_000_000.0)
        _resultat(db, "r_petit", montant_num=50_000.0)
        page = connecte.get("/resultats?min_montant=1000000").text
        assert "r_gros" in page and "r_petit" not in page

    def test_les_filtres_se_combinent(self, connecte, db):
        _resultat(db, "r_cible", secteur="T101", region="Casablanca",
                  type_procedure="bon_commande", montant_num=2_000_000.0)
        _resultat(db, "r_autre", secteur="T101", region="Casablanca",
                  type_procedure="marche", montant_num=2_000_000.0)
        page = connecte.get(
            "/resultats?secteur=T101&region=Casablanca"
            "&type_p=bon_commande&min_montant=1000000").text
        assert "r_cible" in page and "r_autre" not in page

    def test_le_montant_saisi_accepte_les_formats_humains(self, connecte, db):
        # « 1 000 000 », « 1.000.000 », « 1000000 » doivent tous marcher:
        # personne ne tape un nombre nu dans un champ intitulé « montant ».
        _resultat(db, "r_gros", montant_num=5_000_000.0)
        _resultat(db, "r_petit", montant_num=50_000.0)
        for saisie in ("1 000 000", "1.000.000", "1000000"):
            page = connecte.get(f"/resultats?min_montant={saisie}").text
            assert "r_gros" in page and "r_petit" not in page, saisie


class TestTri:
    def test_par_montant_decroissant(self, connecte, db):
        _resultat(db, "r_petit", montant_num=10_000.0, minutes=1)
        _resultat(db, "r_gros", montant_num=9_000_000.0, minutes=60)
        page = connecte.get("/resultats?tri=montant").text
        assert page.index("r_gros") < page.index("r_petit")

    def test_par_defaut_les_plus_recents(self, connecte, db):
        _resultat(db, "r_vieux", minutes=600)
        _resultat(db, "r_neuf", minutes=1)
        page = connecte.get("/resultats").text
        assert page.index("r_neuf") < page.index("r_vieux")


class TestListesDeroulantes:
    def test_ne_proposent_que_ce_qui_existe(self, connecte, db):
        # Proposer les 83 secteurs du référentiel quand deux sont représentés
        # envoie le membre sur des pages vides.
        _resultat(db, "r1", secteur="T101", region="Casablanca")
        page = connecte.get("/resultats").text
        assert 'value="T101"' in page
        assert 'value="S901"' not in page
