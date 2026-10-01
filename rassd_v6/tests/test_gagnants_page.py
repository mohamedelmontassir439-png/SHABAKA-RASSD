# -*- coding: utf-8 -*-
"""La file d'appel côté page: les gagnants doivent y être visibles.

Un gagnant de marché arrive sans téléphone — Global Marché n'en publie pas.
La page d'appel ne montrant par défaut que les entreprises joignables, ces
prospects, qui sont les meilleurs, étaient invisibles.
"""
import pytest

from app.core.config import cfg


def _gagnant(db, nom="STE BAICHOU TRAV SARL", wins=2, phone="", ville="Marrakech"):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,city,
                  phone,email,wins,source,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (nom, nom.lower(), "T101", ville, phone, "", wins,
                "tender_results", "2026-09-01T09:00:00"))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE legal_name=?", (nom,)).fetchone()["id"]


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


class TestListe:
    def test_un_gagnant_sans_telephone_est_masque_par_defaut(self, admin, db):
        _gagnant(db)
        r = admin.get("/admin/prospection")
        assert r.status_code == 200
        assert "BAICHOU" not in r.text

    def test_le_filtre_gagnants_le_montre(self, admin, db):
        _gagnant(db)
        r = admin.get("/admin/prospection?gagnants=1")
        assert r.status_code == 200
        assert "BAICHOU" in r.text

    def test_la_page_propose_de_chercher_le_numero(self, admin, db):
        _gagnant(db)
        r = admin.get("/admin/prospection?gagnants=1")
        assert "chercher le num" in r.text

    def test_le_nombre_de_marches_gagnes_est_affiche(self, admin, db):
        _gagnant(db, wins=4)
        r = admin.get("/admin/prospection?gagnants=1")
        assert "4" in r.text

    def test_le_compteur_de_gagnants_apparait(self, admin, db):
        _gagnant(db)
        r = admin.get("/admin/prospection")
        assert "gagnants de march" in r.text


class TestSaisieDuContact:
    """Un numéro trouvé à la main doit survivre à la fermeture de l'onglet."""

    def test_la_fiche_offre_le_champ_telephone(self, admin, db):
        cid = _gagnant(db)
        r = admin.get(f"/admin/prospection/{cid}")
        assert r.status_code == 200
        assert 'name="phone"' in r.text

    def test_le_numero_saisi_est_enregistre(self, admin, db):
        cid = _gagnant(db)
        admin.get(f"/admin/prospection/{cid}")
        r = admin.post(f"/admin/prospection/{cid}",
                       data={"statut": "a_appeler", "phone": "06 12 34 56 78",
                             "csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert r.status_code in (302, 303)
        tel = db.execute("SELECT phone FROM companies WHERE id=?", (cid,)).fetchone()["phone"]
        assert tel and "612345678" in tel.replace(" ", "")

    def test_une_fois_joignable_il_apparait_sans_filtre(self, admin, db):
        cid = _gagnant(db)
        admin.get(f"/admin/prospection/{cid}")
        admin.post(f"/admin/prospection/{cid}",
                   data={"statut": "a_appeler", "phone": "0612345678",
                         "csrf_token": admin.cookies.get("_csrf")},
                   follow_redirects=False)
        assert "BAICHOU" in admin.get("/admin/prospection").text

    def test_un_email_invalide_ne_salit_pas_la_fiche(self, admin, db):
        cid = _gagnant(db)
        admin.get(f"/admin/prospection/{cid}")
        admin.post(f"/admin/prospection/{cid}",
                   data={"statut": "a_appeler", "email": "pas-un-email",
                         "csrf_token": admin.cookies.get("_csrf")},
                   follow_redirects=False)
        mail = db.execute("SELECT email FROM companies WHERE id=?", (cid,)).fetchone()["email"]
        assert not mail

    def test_le_tri_place_les_plus_gros_gagnants_en_tete(self, admin, db):
        _gagnant(db, nom="PETIT GAGNANT SARL", wins=1)
        _gagnant(db, nom="GROS GAGNANT SARL", wins=5)
        r = admin.get("/admin/prospection?gagnants=1")
        assert r.text.index("GROS GAGNANT") < r.text.index("PETIT GAGNANT")
