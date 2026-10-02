# -*- coding: utf-8 -*-
"""Un membre ne voit que ses secteurs.

Un abonné paie pour une veille, pas pour un annuaire: lui présenter les
mille sept cents marchés actifs quand trente le concernent, c'est lui
demander de faire lui-même le tri qu'on lui vend.

Un profil sans secteur ne restreint rien — filtrer sur une liste vide
rendrait zéro résultat partout, et la plateforme paraîtrait cassée à
l'instant précis où un nouveau venu la découvre.
"""
from datetime import date, timedelta

import pytest


def _membre(db, email="cloison@example.com", secteurs='["T101"]', jeton="jeton-cloison-aa"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", jeton, 1, secteurs, 1))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid, secteur, objet=None, procedure="marche"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,'COMMUNE',?,'Casablanca','1 200 000,00 MAD','actif',
                  '2026-10-02 08:00:00',?,'Public',?)""",
               (tid, objet or f"MARCHE {secteur}", secteur,
                (date.today() + timedelta(days=12)).strftime("%d/%m/%Y"), procedure))
    db.commit()


@pytest.fixture()
def membre(client, db):
    _membre(db)
    client.cookies.set("_session", "jeton-cloison-aa")
    return client


@pytest.fixture()
def sans_secteur(client, db):
    _membre(db, email="vide@example.com", secteurs="[]", jeton="jeton-cloison-bb")
    client.cookies.set("_session", "jeton-cloison-bb")
    return client


class TestListes:
    def test_les_marches_dun_autre_secteur_nappraissent_pas(self, membre, db):
        _marche(db, "t_sien", "T101", "MARCHE DE MON METIER")
        _marche(db, "t_autre", "S901", "MARCHE D UN AUTRE METIER")
        page = membre.get("/tenders").text
        assert "MARCHE DE MON METIER" in page
        assert "MARCHE D UN AUTRE METIER" not in page

    def test_les_bons_de_commande_suivent_la_meme_regle(self, membre, db):
        _marche(db, "bc_sien", "T101", "BON DE MON METIER", "bon_commande")
        _marche(db, "bc_autre", "S901", "BON D UN AUTRE METIER", "bon_commande")
        page = membre.get("/bons-de-commande").text
        assert "BON DE MON METIER" in page and "BON D UN AUTRE METIER" not in page

    def test_les_resultats_aussi(self, membre, db):
        db.execute("""INSERT INTO tender_results(id,objet,acheteur,adjudicataire,secteur,
                      region,montant,scraped_at) VALUES
                      ('r1','ADJUDICATION MIENNE','C','GAGNANT','T101','Casa','1','2026-10-01'),
                      ('r2','ADJUDICATION AUTRE','C','GAGNANT','S901','Casa','1','2026-10-01')""")
        db.commit()
        page = membre.get("/resultats").text
        assert "ADJUDICATION MIENNE" in page and "ADJUDICATION AUTRE" not in page

    def test_le_menu_des_secteurs_ne_propose_que_les_siens(self, membre, db):
        _marche(db, "t_sien", "T101")
        _marche(db, "t_autre", "S901")
        page = membre.get("/tenders").text
        assert 'value="T101"' in page and 'value="S901"' not in page

    def test_un_filtre_hors_profil_est_ignore_et_non_contourne(self, membre, db):
        """Taper le code d'un autre secteur dans l'adresse ne doit rien ouvrir."""
        _marche(db, "t_sien", "T101", "MARCHE DE MON METIER")
        _marche(db, "t_autre", "S901", "MARCHE D UN AUTRE METIER")
        page = membre.get("/tenders?s=S901").text
        assert "MARCHE D UN AUTRE METIER" not in page
        assert "MARCHE DE MON METIER" in page


class TestFiche:
    def test_une_fiche_hors_secteur_est_refusee(self, membre, db):
        _marche(db, "t_autre", "S901")
        r = membre.get("/tenders/t_autre")
        assert r.status_code == 404
        assert "Hors de vos secteurs" in r.text

    def test_un_favori_reste_accessible(self, membre, db):
        """Le lui cacher reviendrait à lui retirer ce qu'il a rangé."""
        mid = db.execute("SELECT id FROM members WHERE email='cloison@example.com'").fetchone()["id"]
        _marche(db, "t_autre", "S901", "MARCHE RANGE")
        db.execute("INSERT INTO favorites(member_id,tender_id,created_at) VALUES(?,?,?)",
                   (mid, "t_autre", "2026-10-01"))
        db.commit()
        r = membre.get("/tenders/t_autre")
        assert r.status_code == 200 and "MARCHE RANGE" in r.text

    def test_sa_fiche_souvre_normalement(self, membre, db):
        _marche(db, "t_sien", "T101", "MARCHE DE MON METIER")
        assert membre.get("/tenders/t_sien").status_code == 200


class TestApi:
    def test_lapi_applique_la_meme_regle(self, membre, db):
        _marche(db, "t_sien", "T101")
        _marche(db, "t_autre", "S901")
        data = membre.get("/api/v1/tenders").json()
        assert {r["secteur"] for r in data["results"]} == {"T101"}

    def test_lapi_refuse_un_secteur_hors_profil(self, membre, db):
        _marche(db, "t_autre", "S901")
        r = membre.get("/api/v1/tenders?secteur=S901")
        assert r.status_code == 403

    def test_lapi_ne_rend_pas_une_fiche_hors_secteur(self, membre, db):
        _marche(db, "t_autre", "S901")
        assert membre.get("/api/v1/tenders/t_autre").status_code == 404


class TestProfilSansSecteur:
    def test_il_voit_tout(self, sans_secteur, db):
        _marche(db, "t_a", "T101", "PREMIER MARCHE")
        _marche(db, "t_b", "S901", "SECOND MARCHE")
        page = sans_secteur.get("/tenders").text
        assert "PREMIER MARCHE" in page and "SECOND MARCHE" in page

    def test_la_page_lui_dit_pourquoi(self, sans_secteur, db):
        _marche(db, "t_a", "T101")
        assert "Choisissez vos secteurs" in sans_secteur.get("/tenders").text

    def test_le_membre_avec_secteurs_ne_voit_pas_ce_bandeau(self, membre, db):
        _marche(db, "t_sien", "T101")
        assert "Choisissez vos secteurs" not in membre.get("/tenders").text


class TestTableauDeBord:
    def test_les_compteurs_ne_portent_que_sur_ses_secteurs(self, membre, db):
        _marche(db, "t_1", "T101")
        _marche(db, "t_2", "T101")
        _marche(db, "t_3", "S901")
        page = membre.get("/dashboard").text
        assert page.count(">3<") == 0 or ">2<" in page
