"""Les trois listes se filtrent de la même façon.

Les marchés et les bons de commande cachaient leurs filtres dans une
colonne de trois cents pixels, que la liste perdait sur toute sa hauteur,
tandis que les résultats les présentaient en une barre. Même page, même
geste: la barre l'emporte, et une fenêtre d'échéance s'y ajoute.
"""
from datetime import date, datetime, timedelta

import pytest


def _membre(db, email="f@example.com"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-filtres", 1, '["T101"]', 1))
    db.commit()
    return "jeton-filtres"


def _marche(db, tid, jours_restants=20, secteur="T101", region="Casablanca",
            procedure="marche", type_offre="Public"):
    limite = (date.today() + timedelta(days=jours_restants)).strftime("%d/%m/%Y")
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,'actif',?,?,?,?)""",
               (tid, f"TRAVAUX {tid}", "COMMUNE", secteur, region,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), limite,
                type_offre, procedure))
    db.commit()


@pytest.fixture()
def connecte(client, db):
    client.cookies.set("_session", _membre(db))
    return client


class TestFenetreEcheance:
    """« Clôture sous 7 jours » est le filtre qu'attend un entrepreneur.

    Au-delà il consulte, il ne monte plus de dossier. Le montant, lui, ne
    servirait à rien ici: la source ne le publie que pour trois pour cent
    des avis.
    """

    @pytest.mark.parametrize("page, procedure", [
        ("/tenders", "marche"),
        ("/bons-de-commande", "bon_commande"),
    ])
    def test_elle_ecarte_ce_qui_cloture_plus_tard(self, connecte, db, page, procedure):
        _marche(db, "t_proche", jours_restants=2, procedure=procedure)
        _marche(db, "t_lointain", jours_restants=60, procedure=procedure)
        html = connecte.get(f"{page}?e=7").text
        assert "t_proche" in html and "t_lointain" not in html

    def test_une_echeance_passee_est_exclue(self, connecte, db):
        # Un marché clos n'est pas « à clôturer dans 7 jours ».
        _marche(db, "t_passe", jours_restants=-5)
        assert "t_passe" not in connecte.get("/tenders?e=7").text

    def test_sans_filtre_tout_remonte(self, connecte, db):
        _marche(db, "t_proche", jours_restants=2)
        _marche(db, "t_lointain", jours_restants=60)
        html = connecte.get("/tenders").text
        assert "t_proche" in html and "t_lointain" in html

    def test_une_date_sans_echeance_ne_casse_rien(self, connecte, db):
        _marche(db, "t_vide")
        db.execute("UPDATE tenders SET date_limite='' WHERE id='t_vide'")
        db.commit()
        assert connecte.get("/tenders?e=7").status_code == 200

    def test_les_deux_formats_de_date_sont_compris(self, connecte, db):
        # La source écrit « 30/09/2026 », l'import ancien « 2026-09-30 ».
        _marche(db, "t_iso", jours_restants=3)
        db.execute("UPDATE tenders SET date_limite=? WHERE id='t_iso'",
                   ((date.today() + timedelta(days=3)).strftime("%Y-%m-%d"),))
        db.commit()
        assert "t_iso" in connecte.get("/tenders?e=7").text


class TestFiltresEnBarre:
    @pytest.mark.parametrize("gabarit", ["templates/tenders.html",
                                         "templates/bons_commande.html"])
    def test_la_colonne_de_filtres_a_disparu(self, gabarit):
        page = open(gabarit, encoding="utf-8").read()
        assert "filtres-ligne" in page
        assert "filter-panel-title" not in page

    @pytest.mark.parametrize("gabarit", ["templates/tenders.html",
                                         "templates/bons_commande.html"])
    def test_le_tri_n_est_propose_qu_une_fois(self, gabarit):
        # Deux commandes pour la même chose se contredisaient dès qu'on en
        # touchait une.
        page = open(gabarit, encoding="utf-8").read()
        assert 'class="sort-tabs"' not in page
        assert page.count('name="sort"') == 1

    @pytest.mark.parametrize("page", ["/tenders", "/bons-de-commande"])
    def test_le_filtre_survit_a_la_pagination(self, connecte, db, page):
        for i in range(30):
            _marche(db, f"t{i}", jours_restants=3,
                    procedure="bon_commande" if "bons" in page else "marche")
        html = connecte.get(f"{page}?e=7").text
        assert "e=7" in html, "les liens de page perdaient le filtre"


class TestListesReelles:
    def test_les_secteurs_proposes_existent_en_base(self, connecte, db):
        """Offrir les 83 secteurs quand trente sont représentés mène à des
        pages vides."""
        _marche(db, "t1", secteur="T101")
        html = connecte.get("/tenders").text
        assert 'value="T101"' in html
        assert 'value="S930"' not in html
