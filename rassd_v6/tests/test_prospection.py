"""Module de prospection: appeler les entreprises collectées.

Le point clé n'est pas la liste mais la fiche d'appel: elle doit montrer des
marchés réellement ouverts dans le secteur de l'entreprise, et respecter un
refus d'être rappelé — obligation de la loi 09-08.
"""
from datetime import date, timedelta

import pytest

from app.core.config import cfg


def _entreprise(db, nom="BTP ATLAS SARL", secteur="T101", ville="Casablanca",
                phone="0612345678", email=""):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,subsector,
                  city,phone,email,source,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (nom, nom.lower(), secteur, "Entreprise de construction", ville,
                phone, email, "google-maps", "2026-09-01T09:00:00"))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE legal_name=?", (nom,)).fetchone()["id"]


def _marche(db, tid="t_p1", secteur="T101", jours=10):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (tid, "TRAVAUX DE CONSTRUCTION", "COMMUNE DE CASABLANCA",
                secteur, "Casablanca", "1 200 000,00 MAD", "actif",
                "2026-09-22 08:00:00",
                (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y"),
                "Public", "marche"))
    db.commit()


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


class TestAcces:
    def test_liste_reservee_a_l_admin(self, client):
        r = client.get("/admin/prospection")
        assert r.status_code == 302 and "/admin/login" in r.headers["location"]

    def test_fiche_reservee_a_l_admin(self, client, db):
        cid = _entreprise(db)
        r = client.get(f"/admin/prospection/{cid}")
        assert r.status_code == 302 and "/admin/login" in r.headers["location"]


class TestListe:
    def test_entreprise_avec_telephone_listee(self, admin, db):
        _entreprise(db)
        page = admin.get("/admin/prospection")
        assert page.status_code == 200
        assert "BTP ATLAS SARL" in page.text and "0612345678" in page.text

    def test_entreprise_sans_contact_exclue(self, admin, db):
        _entreprise(db, nom="SANS CONTACT SARL", phone="", email="")
        assert "SANS CONTACT SARL" not in admin.get("/admin/prospection").text

    def test_refus_de_contact_masque_par_defaut(self, admin, db):
        cid = _entreprise(db, nom="REFUS SARL")
        admin.post(f"/admin/prospection/{cid}", data={
            "statut": "ne_pas_contacter", "notes": "a demandé le retrait",
            "csrf_token": admin.cookies.get("_csrf")})
        assert "REFUS SARL" not in admin.get("/admin/prospection").text
        # Mais reste consultable en filtrant explicitement: la trace du refus
        # doit survivre, sinon la même entreprise est rappelée un mois plus tard.
        assert "REFUS SARL" in admin.get("/admin/prospection?statut=ne_pas_contacter").text

    def test_filtre_par_ville(self, admin, db):
        _entreprise(db, nom="RABAT TRAVAUX", ville="Rabat")
        _entreprise(db, nom="AGADIR TRAVAUX", ville="Agadir")
        page = admin.get("/admin/prospection?ville=Rabat")
        assert "RABAT TRAVAUX" in page.text and "AGADIR TRAVAUX" not in page.text


class TestFicheAppel:
    def test_affiche_les_marches_du_secteur(self, admin, db):
        cid = _entreprise(db)
        _marche(db)
        page = admin.get(f"/admin/prospection/{cid}")
        assert page.status_code == 200
        assert "TRAVAUX DE CONSTRUCTION" in page.text
        assert "1 200 000,00 MAD" in page.text

    def test_pas_de_marche_d_un_autre_secteur(self, admin, db):
        cid = _entreprise(db, secteur="T101")
        _marche(db, tid="t_autre", secteur="S911")
        assert "TRAVAUX DE CONSTRUCTION" not in admin.get(f"/admin/prospection/{cid}").text

    def test_marche_clos_non_propose(self, admin, db):
        cid = _entreprise(db)
        _marche(db, tid="t_clos")
        db.execute("UPDATE tenders SET statut='expire' WHERE id='t_clos'")
        db.commit()
        assert "TRAVAUX DE CONSTRUCTION" not in admin.get(f"/admin/prospection/{cid}").text

    def test_avertissement_si_ne_pas_contacter(self, admin, db):
        cid = _entreprise(db)
        admin.post(f"/admin/prospection/{cid}", data={
            "statut": "ne_pas_contacter", "csrf_token": admin.cookies.get("_csrf")})
        assert "ne plus être contactée" in admin.get(f"/admin/prospection/{cid}").text


class TestEnregistrement:
    def test_statut_notes_et_rappel_conserves(self, admin, db):
        cid = _entreprise(db)
        demain = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        r = admin.post(f"/admin/prospection/{cid}", data={
            "statut": "rappeler", "notes": "Rappeler après le chantier",
            "prochain": demain, "appel": "1",
            "csrf_token": admin.cookies.get("_csrf")})
        assert r.status_code == 302

        ligne = db.execute("SELECT * FROM prospection WHERE company_id=?", (cid,)).fetchone()
        assert ligne["statut"] == "rappeler"
        assert ligne["notes"] == "Rappeler après le chantier"
        assert ligne["prochain_contact"] == demain
        assert ligne["appels"] == 1
        assert ligne["dernier_contact"] == date.today().strftime("%Y-%m-%d")

    def test_les_appels_s_additionnent(self, admin, db):
        cid = _entreprise(db)
        for _ in range(3):
            admin.post(f"/admin/prospection/{cid}", data={
                "statut": "injoignable", "appel": "1",
                "csrf_token": admin.cookies.get("_csrf")})
        assert db.execute("SELECT appels FROM prospection WHERE company_id=?",
                          (cid,)).fetchone()[0] == 3

    def test_mise_a_jour_sans_appel_ne_compte_pas(self, admin, db):
        cid = _entreprise(db)
        admin.post(f"/admin/prospection/{cid}", data={
            "statut": "interesse", "csrf_token": admin.cookies.get("_csrf")})
        assert db.execute("SELECT appels FROM prospection WHERE company_id=?",
                          (cid,)).fetchone()[0] == 0

    def test_statut_inconnu_refuse(self, admin, db):
        cid = _entreprise(db)
        admin.post(f"/admin/prospection/{cid}", data={
            "statut": "n_importe_quoi", "csrf_token": admin.cookies.get("_csrf")})
        assert db.execute("SELECT statut FROM prospection WHERE company_id=?",
                          (cid,)).fetchone()[0] == "a_appeler"

    def test_sans_jeton_csrf_refuse(self, admin, db):
        cid = _entreprise(db)
        r = admin.post(f"/admin/prospection/{cid}", data={"statut": "abonne"})
        assert r.status_code == 403
