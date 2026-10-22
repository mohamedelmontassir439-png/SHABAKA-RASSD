# -*- coding: utf-8 -*-
"""Garanties et financement (7), groupements (8)."""
from datetime import date, timedelta

import pytest

AVIS = ("Référence 9/2026 Objet : x Caution provisoire : 20 000,00 MAD Qualifications : Equipement / "
        "B- Travaux routiers / B.1- Terrassements / Classe 3 Equipement / B- Travaux routiers / "
        "B.3- Assainissement / Classe 2 Agréments : Variante : Non")


def _membre(db, mid, jeton, email, company):
    db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,'0612345678',?,'pro','ACTIVE',?,'x',?,1,'["T101"]',1)""",
               (mid, f"Gérant {mid}", email, company, (date.today() + timedelta(days=90)).isoformat(), jeton))
    db.commit()


def _marche(db):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,scraped_at,date_limite,
                  type_offre,type_procedure,source,description)
                  VALUES('ao_7','Route de Taza','DP Taza','T101','Taza','actif','2026-10-01',?,'Public',
                  'marche','marchespublics',?)""",
               ((date.today() + timedelta(days=20)).strftime("%d/%m/%Y"), AVIS))
    db.commit()


@pytest.fixture()
def emails(monkeypatch):
    partis = []
    monkeypatch.setattr("app.services.notifications.email_send",
                        lambda to, s, h: partis.append((to, s, h)) or True)
    return partis


class TestFinancement:
    def test_formulaire_prerempli_par_le_marche(self, client, db):
        _membre(db, 1, "jeton-fin-1", "a@x.ma", "SIMAC"); _marche(db)
        client.cookies.set("_session", "jeton-fin-1")
        page = client.get("/financement?tender=ao_7&type=caution_provisoire").text
        assert 'value="20 000,00 MAD"' in page and "Route de Taza" in page

    def test_demande_enregistree_et_equipe_prevenue(self, client, db, emails):
        _membre(db, 1, "jeton-fin-1", "a@x.ma", "SIMAC"); _marche(db)
        client.cookies.set("_session", "jeton-fin-1")
        client.get("/financement")
        r = client.post("/financement", data={"type_demande": "caution_provisoire", "montant": "20 000 MAD",
                                              "tender_id": "ao_7", "csrf_token": client.cookies.get("_csrf")},
                        follow_redirects=False)
        assert "ok=1" in r.headers["location"]
        d = db.execute("SELECT * FROM demandes_financement").fetchone()
        assert d["objet"] == "Route de Taza" and d["statut"] == "nouvelle"
        assert "SIMAC" in emails[0][2]
        assert "Reçue" in client.get("/financement").text

    def test_type_inconnu_refuse(self, db):
        from app.services.financement import creer
        _membre(db, 1, "jeton-fin-1", "a@x.ma", "SIMAC")
        assert creer({"id": 1}, "pret_magique", "1 MAD") == (False, "type")


class TestGroupement:
    def test_partenaires_qui_comblent_le_manque(self, db):
        from app.services import eligibilite, groupement
        _membre(db, 1, "jeton-grp-1", "a@x.ma", "SIMAC")
        _membre(db, 2, "jeton-grp-2", "b@x.ma", "ATLAS ASSAINISSEMENT")
        _membre(db, 3, "jeton-grp-3", "c@x.ma", "PETITE SARL")
        _marche(db)
        eligibilite.ajouter(1, "B.1", "2")
        eligibilite.ajouter(2, "B.3", "1")
        eligibilite.ajouter(3, "B.3", "5")   # classe insuffisante
        t = dict(db.execute("SELECT * FROM tenders WHERE id='ao_7'").fetchone())
        g = groupement.partenaires(1, t)
        assert [e["code"] for e in g["manquantes"]] == ["B.3"]
        assert [p["societe"] for p in g["partenaires"]] == ["ATLAS ASSAINISSEMENT"]

    def test_coordonnees_apres_acceptation_seulement(self, client, db, emails):
        from app.services import eligibilite
        _membre(db, 1, "jeton-grp-1", "a@x.ma", "SIMAC")
        _membre(db, 2, "jeton-grp-2", "b@x.ma", "ATLAS ASSAINISSEMENT")
        _marche(db)
        eligibilite.ajouter(2, "B.3", "1")
        client.cookies.set("_session", "jeton-grp-1")
        page = client.get("/tenders/ao_7").text
        assert "ATLAS ASSAINISSEMENT" in page and "Répondre en groupement" in page
        client.post("/groupements/proposer", data={"tender_id": "ao_7", "to_member": 2, "message": "On y va ?",
                                                   "csrf_token": client.cookies.get("_csrf")})
        assert "b@x.ma" == emails[-1][0] and "a@x.ma" not in emails[-1][2], "pas de coordonnées avant accord"
        client.cookies.set("_session", "jeton-grp-2")
        recues = client.get("/groupements").text
        assert "SIMAC" in recues and "a@x.ma" not in recues
        pid = db.execute("SELECT id FROM propositions_groupement").fetchone()[0]
        client.post(f"/groupements/{pid}/repondre", data={"accepte": 1, "csrf_token": client.cookies.get("_csrf")})
        assert "a@x.ma" in client.get("/groupements").text
        assert "b@x.ma" in emails[-1][2], "le proposant reçoit le contact"

    def test_on_ne_repond_pas_a_la_place_d_un_autre(self, db):
        from app.services import groupement
        _membre(db, 1, "jeton-grp-1", "a@x.ma", "SIMAC")
        _membre(db, 2, "jeton-grp-2", "b@x.ma", "ATLAS")
        _marche(db)
        groupement.proposer({"id": 1, "company": "SIMAC"}, 2, {"id": "ao_7", "objet": "x"}, "")
        pid = db.execute("SELECT id FROM propositions_groupement").fetchone()[0]
        assert groupement.repondre(1, pid, True) is False

    def test_modele(self, client, db):
        _membre(db, 1, "jeton-grp-1", "a@x.ma", "SIMAC"); _marche(db)
        client.cookies.set("_session", "jeton-grp-1")
        page = client.get("/groupements/modele?tender=ao_7").text
        assert "CONVENTION DE GROUPEMENT" in page and "9/2026" in page and "Route de Taza" in page
