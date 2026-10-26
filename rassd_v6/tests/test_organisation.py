# -*- coding: utf-8 -*-
"""L'organisation du site: menu par rubriques, « À faire », « À traiter »."""
from datetime import date, datetime, timedelta

from tests.test_cloisonnement import _membre, membre  # noqa: F401  (fixture)


class TestMenuMembre:
    def test_rubriques_et_guide(self, membre):
        page = membre.get("/dashboard").text
        for rubrique in ("Opportunités", "Mon travail", "Se développer", "Mon compte"):
            assert rubrique in page
        assert 'href="/guide/depot-electronique" class="side-link' in page
        assert 'href="/tarifs" class="side-link' not in page, "un abonné n'a pas « Offres » dans son menu"

    def test_accueil_mene_au_tableau_de_bord(self, membre):
        r = membre.get("/")
        assert r.status_code == 302 and r.headers["location"] == "/dashboard"


class TestAFaire:
    def test_echeance_et_piece_qui_expire(self, membre, db):
        mid = db.execute("SELECT id FROM members WHERE email='cloison@example.com'").fetchone()["id"]
        limite = (date.today() + timedelta(days=4)).strftime("%d/%m/%Y")
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url,date_limite)
                      VALUES('t1','TRAVAUX DE LA PISTE','A','T101','actif','2026-10-20','u',?)""", (limite,))
        maintenant = datetime.now().isoformat(timespec="seconds")
        db.execute("""INSERT INTO suivi_offres(member_id,tender_id,objet,acheteur,date_limite,etape,created_at,updated_at)
                      VALUES(?,'t1','TRAVAUX DE LA PISTE','A',?,'preparation',?,?)""",
                   (mid, limite, maintenant, maintenant))
        db.execute("""INSERT INTO coffre_pieces(member_id,type,libelle,fichier,nom_original,taille,delivre_le,
                      expire_le,rappels_faits,created_at,updated_at)
                      VALUES(?,'fiscale','','f.pdf','f.pdf',1,'2025-11-01',?,'[]',?,?)""",
                   (mid, (date.today() + timedelta(days=10)).isoformat(), maintenant, maintenant))
        db.commit()
        page = membre.get("/dashboard").text
        assert "À faire" in page
        assert "Date limite de dépôt" in page and "TRAVAUX DE LA PISTE" in page
        assert "Renouveler : Attestation de régularité fiscale" in page


class TestATraiter:
    def test_demande_de_financement_a_rappeler(self, admin, db):
        db.execute("""INSERT INTO demandes_financement(member_id,type,montant,tender_id,objet,echeance,message,
                      statut,created_at,updated_at)
                      VALUES(1,'caution_provisoire','50000','','x','','','nouvelle',datetime('now'),datetime('now'))""")
        db.commit()
        page = admin.get("/admin").text
        assert "À traiter" in page
        assert "demande(s) de caution ou de financement à rappeler" in page
        assert 'href="/admin/financement"' in page

    def test_une_passe_d_annuaire_ancienne_n_est_pas_une_panne(self, admin, db):
        db.execute("""INSERT INTO scraper_runs(source,status,records_found,records_saved,duplicates,errors,
                      duration_ms,message,started_at,finished_at)
                      VALUES('annuaire-charika-enrichir','SUCCESS',1,1,0,0,1,'','2026-10-01 10:00','2026-10-01 10:01')""")
        db.execute("""INSERT INTO scraper_runs(source,status,records_found,records_saved,duplicates,errors,
                      duration_ms,message,started_at,finished_at)
                      VALUES('marchespublics','FAILED',0,0,0,1,1,'','2026-10-01 10:00','2026-10-01 10:01')""")
        db.commit()
        page = admin.get("/admin").text
        assert '<b class="num">1</b><span>source(s) en échec' in page
