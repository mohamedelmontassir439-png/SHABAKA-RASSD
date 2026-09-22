"""Campagne d'invitation des entreprises collectées.

Une place de marché vide ne se remplit pas toute seule. 587 entreprises ont
été collectées avec leur téléphone: chacune reçoit un lien personnel qui
ouvre une page à son nom, montre les marchés réellement ouverts dans son
secteur, et crée son compte en deux champs — le reste vient de sa fiche.
"""
from datetime import date

import pytest

from app.core.config import cfg


def _entreprise(db, nom="BTP ATLAS SARL", secteur="T101", ville="Casablanca",
                phone="0612345678", email=""):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,subsector,city,
                  phone,email,source,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (nom, nom.lower(), secteur, "Entreprise de construction", ville,
                phone, email, "google-maps", "2026-09-01T09:00:00"))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE legal_name=?", (nom,)).fetchone()["id"]


def _marche(db, tid="t_inv", secteur="T101"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (tid, "TRAVAUX DE CONSTRUCTION D UNE ECOLE", "COMMUNE", secteur,
                "Casablanca", "1 200 000,00 MAD", "actif", "2026-09-22 08:00:00",
                "30/10/2026", "Public", "marche"))
    db.commit()


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _jeton(admin, db, cid):
    admin.get(f"/admin/prospection/{cid}")
    admin.post(f"/admin/prospection/{cid}/invitation",
               data={"canal": "whatsapp", "csrf_token": admin.cookies.get("_csrf")})
    return db.execute("SELECT token FROM invitations WHERE company_id=?", (cid,)).fetchone()[0]


class TestGenerationDuLien:
    def test_lien_cree_une_seule_fois(self, admin, db):
        cid = _entreprise(db)
        premier = _jeton(admin, db, cid)
        second = _jeton(admin, db, cid)
        assert premier == second, "relancer une entreprise ne change pas son lien"
        assert db.execute("SELECT COUNT(*) FROM invitations WHERE company_id=?",
                          (cid,)).fetchone()[0] == 1

    def test_message_pret_avec_le_lien_et_un_marche(self, admin, db):
        cid = _entreprise(db)
        _marche(db)
        token = _jeton(admin, db, cid)
        page = admin.get(f"/admin/prospection/{cid}")
        assert token in page.text
        assert "TRAVAUX DE CONSTRUCTION" in page.text
        assert "retirons vos coordonnées" in page.text, "le retrait doit être proposé"

    def test_generation_reservee_a_l_admin(self, client, db):
        cid = _entreprise(db)
        r = client.post(f"/admin/prospection/{cid}/invitation", data={})
        assert r.status_code in (401, 403)


class TestPageInvitation:
    def test_page_au_nom_de_l_entreprise(self, admin, client, db):
        cid = _entreprise(db)
        _marche(db)
        token = _jeton(admin, db, cid)

        page = client.get(f"/invitation/{token}")
        assert page.status_code == 200
        assert "BTP ATLAS SARL" in page.text
        assert "TRAVAUX DE CONSTRUCTION" in page.text, "des marchés réels, pas un argumentaire"

    def test_ouverture_tracee(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        assert db.execute("SELECT opened_at FROM invitations WHERE token=?",
                          (token,)).fetchone()[0] == ""
        client.get(f"/invitation/{token}")
        assert db.execute("SELECT opened_at FROM invitations WHERE token=?",
                          (token,)).fetchone()[0] != ""

    def test_jeton_inconnu(self, client):
        assert client.get("/invitation/nimportequoi").status_code == 404

    def test_page_accessible_sans_compte(self, admin, client, db):
        # Le middleware de vérification d'email ne doit pas bloquer une page
        # destinée à quelqu'un qui n'a pas encore de compte.
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        assert client.get(f"/invitation/{token}").status_code == 200


class TestInscriptionDepuisInvitation:
    def test_compte_prerempli_cree(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")

        r = client.post(f"/invitation/{token}", data={
            "email": "contact@btpatlas.ma", "pw": "MotDePasse1!",
            "csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 302 and "/verifier-email" in r.headers["location"]

        m = db.execute("SELECT * FROM members WHERE email=?", ("contact@btpatlas.ma",)).fetchone()
        assert m["company"] == "BTP ATLAS SARL"
        assert "T101" in m["secteurs"], "le métier vient de la fiche collectée"
        assert "Casablanca" in m["regions"]
        assert m["phone"] == "0612345678"
        assert m["subscription_status"] == "TRIAL"
        assert m["email_verified"] == 0, "l'adresse reste à confirmer"

    def test_profil_de_sous_traitance_demarre_rempli(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        client.post(f"/invitation/{token}", data={
            "email": "c@btpatlas.ma", "pw": "MotDePasse1!",
            "csrf_token": client.cookies.get("_csrf")})
        profil = db.execute("SELECT * FROM subcontract_profiles").fetchone()
        assert profil["raison_sociale"] == "BTP ATLAS SARL"
        assert "T101" in profil["metiers"] and "Casablanca" in profil["zones"]

    def test_entreprise_suivie_comme_essai_ouvert(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        client.post(f"/invitation/{token}", data={
            "email": "c2@btpatlas.ma", "pw": "MotDePasse1!",
            "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT statut FROM prospection WHERE company_id=?",
                          (cid,)).fetchone()[0] == "essai"
        assert db.execute("SELECT member_id FROM invitations WHERE token=?",
                          (token,)).fetchone()[0] > 0

    def test_email_deja_pris_refuse(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        for _ in range(2):
            r = client.post(f"/invitation/{token}", data={
                "email": "double@example.com", "pw": "MotDePasse1!",
                "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT COUNT(*) FROM members WHERE email=?",
                          ("double@example.com",)).fetchone()[0] == 1

    def test_mot_de_passe_faible_refuse(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        client.post(f"/invitation/{token}", data={
            "email": "faible@example.com", "pw": "123",
            "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT COUNT(*) FROM members WHERE email=?",
                          ("faible@example.com",)).fetchone()[0] == 0

    def test_sans_jeton_csrf_refuse(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        r = client.post(f"/invitation/{token}",
                        data={"email": "x@example.com", "pw": "MotDePasse1!"})
        assert r.status_code == 403

    def test_lien_deja_utilise_invite_a_se_connecter(self, admin, client, db):
        cid = _entreprise(db)
        token = _jeton(admin, db, cid)
        client.get(f"/invitation/{token}")
        client.post(f"/invitation/{token}", data={
            "email": "premier@example.com", "pw": "MotDePasse1!",
            "csrf_token": client.cookies.get("_csrf")})
        page = client.get(f"/invitation/{token}")
        assert "déjà été créé" in page.text
        assert 'name="pw"' not in page.text, "le formulaire disparaît"
