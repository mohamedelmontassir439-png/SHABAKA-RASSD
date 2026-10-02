# -*- coding: utf-8 -*-
"""Le lot du soir: préparé par la machine, envoyé de la main du fondateur.

L'envoi WhatsApp reste manuel — c'est un choix. Mais la liste était
recalculée à chaque ouverture de la page, et rien ne disait qui avait déjà
reçu son message: un membre servi deux fois, un autre oublié.
"""
from datetime import date, timedelta

import pytest

from app.core.config import cfg
from app.services import recap

JOUR = date.today().strftime("%Y-%m-%d")


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _membre(db, email="lot@example.com", secteurs='["T101"]', phone="0612345678"):
    db.execute("""INSERT INTO members(nom,email,phone,plan,subscription_status,trial_ends,
                  actif,secteurs,email_verified) VALUES(?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, phone, "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                1, secteurs, 1))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid="t_lot1", secteur="T101"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,'TRAVAUX DE CONSTRUCTION','COMMUNE',?,'Casablanca',
                  '1 200 000,00 MAD','actif',?,?,'Public','marche')""",
               (tid, secteur, f"{JOUR} 08:00:00",
                (date.today() + timedelta(days=12)).strftime("%d/%m/%Y")))
    db.commit()


class TestPreparation:
    def test_elle_fige_une_ligne_par_membre(self, db):
        _membre(db)
        _membre(db, email="b@example.com")
        stats = recap.preparer(JOUR)
        assert stats["membres"] == 2
        assert db.execute("SELECT COUNT(*) FROM recap_envois WHERE jour=?",
                          (JOUR,)).fetchone()[0] == 2

    def test_elle_compte_les_marches_du_membre(self, db):
        mid = _membre(db)
        _marche(db)
        recap.preparer(JOUR)
        n = db.execute("SELECT nombre FROM recap_envois WHERE member_id=? AND jour=?",
                       (mid, JOUR)).fetchone()[0]
        assert n == 1

    def test_un_membre_sans_marche_est_quand_meme_prepare(self, db):
        """Sa ligne existe, à zéro: on doit voir qu'il n'y a rien à lui dire."""
        mid = _membre(db, secteurs='["T999"]')
        _marche(db)
        recap.preparer(JOUR)
        assert db.execute("SELECT nombre FROM recap_envois WHERE member_id=?",
                          (mid,)).fetchone()[0] == 0

    def test_relancer_nefface_pas_les_envois_deja_marques(self, db):
        """Une collecte tardive ajoute des marchés; elle ne défait pas un envoi."""
        mid = _membre(db)
        recap.preparer(JOUR)
        recap.marquer_envoye(mid, JOUR)
        _marche(db)
        recap.preparer(JOUR)
        ligne = db.execute("SELECT nombre, envoye_at FROM recap_envois WHERE member_id=?",
                           (mid,)).fetchone()
        assert ligne["nombre"] == 1 and ligne["envoye_at"]

    def test_les_membres_inactifs_sont_ignores(self, db):
        mid = _membre(db)
        db.execute("UPDATE members SET actif=0 WHERE id=?", (mid,))
        db.commit()
        assert recap.preparer(JOUR)["membres"] == 0


class TestTraceDEnvoi:
    def test_marquer_puis_defaire(self, db):
        mid = _membre(db)
        recap.preparer(JOUR)
        recap.marquer_envoye(mid, JOUR)
        assert recap.lot_du_jour(JOUR)["envoyes"] == 1
        recap.annuler_envoi(mid, JOUR)
        assert recap.lot_du_jour(JOUR)["envoyes"] == 0

    def test_les_restants_ne_comptent_que_ceux_qui_ont_des_marches(self, db):
        _membre(db)                                   # avec marché
        _membre(db, email="vide@example.com", secteurs='["T999"]')
        _marche(db)
        recap.preparer(JOUR)
        assert recap.lot_du_jour(JOUR)["restants"] == 1

    def test_les_envoyes_passent_en_bas(self, db):
        premier = _membre(db)
        _membre(db, email="second@example.com")
        _marche(db)
        recap.preparer(JOUR)
        recap.marquer_envoye(premier, JOUR)
        ordre = [l["membre"]["id"] for l in recap.lot_du_jour(JOUR)["lignes"]]
        assert ordre[-1] == premier


class TestPage:
    def test_la_page_montre_le_lot(self, admin, db):
        _membre(db)
        _marche(db)
        r = admin.get("/admin/recap")
        assert r.status_code == 200
        assert "à envoyer" in r.text

    def test_elle_prepare_a_la_demande_si_le_soir_nest_pas_passe(self, admin, db):
        _membre(db)
        admin.get("/admin/recap")
        assert db.execute("SELECT COUNT(*) FROM recap_envois").fetchone()[0] == 1

    def test_le_bouton_marque_lenvoi(self, admin, db):
        mid = _membre(db)
        _marche(db)
        admin.get("/admin/recap")
        r = admin.post("/admin/recap/envoye",
                       data={"member_id": mid, "jour": JOUR,
                             "csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert r.status_code in (302, 303)
        assert db.execute("SELECT envoye_at FROM recap_envois WHERE member_id=?",
                          (mid,)).fetchone()[0]

    def test_le_marquage_exige_ladmin(self, client, db):
        mid = _membre(db)
        r = client.post("/admin/recap/envoye", data={"member_id": mid},
                        follow_redirects=False)
        assert "/admin/login" in r.headers.get("location", "")

    def test_le_message_contient_le_lien_du_membre(self, admin, db):
        mid = _membre(db)
        _marche(db)
        page = admin.get("/admin/recap").text
        assert f"/recap/{recap.jeton(mid, JOUR)}" in page
