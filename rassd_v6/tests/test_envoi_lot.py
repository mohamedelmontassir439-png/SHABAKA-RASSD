# -*- coding: utf-8 -*-
"""L'envoi des invitations par email, en lot.

Rien ne part pour de vrai ici: l'expéditeur est remplacé par une liste.
"""
import asyncio
from datetime import date, timedelta

import pytest


def _entreprise(db, cid, email, secteur="T101", wins=0):
    db.execute("""INSERT INTO companies(id,legal_name,normalized_name,sector,city,email,phone,wins)
                  VALUES(?,?,?,?,'Rabat',?,'',?)""",
               (cid, f"SOCIETE {cid}", f"societe {cid}", secteur, email, wins))
    db.commit()


def _marche(db, secteur="T101"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,'Rabat','500 000,00 MAD','actif','2026-10-01 08:00:00',?,
                  'Public','marche')""",
               (f"t_{secteur}", "TRAVAUX DE VOIRIE", "COMMUNE DE RABAT", secteur,
                (date.today() + timedelta(days=15)).strftime("%d/%m/%Y")))
    db.commit()


def _statut(db, cid, statut, canal="", dernier=""):
    db.execute("""INSERT INTO prospection(company_id,statut,canal,dernier_contact,created_at,updated_at)
                  VALUES(?,?,?,?,'','')""", (cid, statut, canal, dernier))
    db.commit()


@pytest.fixture()
def envois(monkeypatch):
    partis = []

    def faux(to, sujet, html):
        partis.append((to, sujet, html))
        return True
    monkeypatch.setattr("app.services.notifications.email_send", faux)
    return partis


def _lancer(**kw):
    from app.services.envoi_lot import envoyer
    asyncio.run(envoyer(pause=0, **kw))


class TestCandidats:
    def test_qui_est_ecarte(self, db):
        from app.services.envoi_lot import candidats
        for cid in range(1, 8):
            _entreprise(db, cid, f"c{cid}@x.ma")
        _statut(db, 2, "refus")
        _statut(db, 3, "ne_pas_contacter")
        _statut(db, 4, "abonne")
        _statut(db, 5, "a_appeler", "email", "2026-10-01")   # déjà écrite
        db.execute("INSERT INTO members(nom,email) VALUES('M','c6@x.ma')")  # déjà membre
        db.commit()
        assert sorted(c["id"] for c in candidats()) == [1, 7]

    def test_une_adresse_un_message(self, db):
        from app.services.envoi_lot import candidats
        _entreprise(db, 1, "meme@x.ma", wins=5)
        _entreprise(db, 2, " MEME@x.ma ")
        assert [c["id"] for c in candidats()] == [1]


class TestEnvoi:
    def test_chacun_recoit_ses_marches_et_son_lien(self, db, envois):
        _marche(db)
        _entreprise(db, 1, "a@x.ma")
        _lancer()
        (to, sujet, html), = envois
        assert to == "a@x.ma" and "TRAVAUX DE VOIRIE" in html
        jeton = db.execute("SELECT token, sent_at FROM invitations WHERE company_id=1").fetchone()
        assert f"/invitation/{jeton['token']}" in html and jeton["sent_at"]
        p = db.execute("SELECT canal, dernier_contact FROM prospection WHERE company_id=1").fetchone()
        assert p["canal"] == "email" and p["dernier_contact"]

    def test_un_second_lot_ne_reecrit_pas(self, db, envois):
        _marche(db)
        _entreprise(db, 1, "a@x.ma")
        _lancer()
        _lancer()
        assert len(envois) == 1

    def test_sans_marche_ouvert_rien_ne_part(self, db, envois):
        from app.services.envoi_lot import EnvoiState
        _marche(db, "T101")
        _entreprise(db, 1, "a@x.ma", secteur="F999")
        _lancer()
        assert envois == [] and EnvoiState.ignores == 1
        assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0

    def test_le_plafond(self, db, envois):
        _marche(db)
        for cid in range(1, 6):
            _entreprise(db, cid, f"c{cid}@x.ma")
        _lancer(plafond=3)
        assert len(envois) == 3

    def test_trois_echecs_de_suite_arretent_le_lot(self, db, monkeypatch):
        from app.services.envoi_lot import EnvoiState
        tentatives = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda *a: tentatives.append(a) or False)
        _marche(db)
        for cid in range(1, 7):
            _entreprise(db, cid, f"c{cid}@x.ma")
        _lancer()
        assert len(tentatives) == 3 and "quota" in EnvoiState.arret
        # Un échec ne compte pas comme une invitation reçue.
        assert db.execute("SELECT COUNT(*) FROM invitations WHERE sent_at!=''").fetchone()[0] == 0


class TestPage:
    def test_le_bouton_et_le_compte(self, admin, db):
        _entreprise(db, 1, "a@x.ma")
        r = admin.get("/admin/campagne")
        assert r.status_code == 200 and "Envoyer les invitations" in r.text
        assert "<b style=\"color:var(--t1)\">1</b> adresse(s)" in r.text

    def test_le_lancement_demande_l_admin(self, client, db):
        r = client.post("/admin/campagne/emails/lancer", follow_redirects=False)
        assert r.status_code in (302, 303, 403, 404)
