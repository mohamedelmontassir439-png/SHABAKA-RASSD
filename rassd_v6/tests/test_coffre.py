# -*- coding: utf-8 -*-
"""Le coffre du dossier administratif."""
import os
from datetime import date, timedelta

import pytest

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture()
def coffre_vide(tmp_path, monkeypatch):
    from app.services import coffre
    monkeypatch.setattr(coffre, "DOSSIER", str(tmp_path / "coffre"))
    return coffre


def _membre(db, mid=1, jeton="jeton-coffre", email="c@x.ma"):
    db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,'pro','ACTIVE',?,'x',?,1,'["T101"]',1)""",
               (mid, "Ahmed Alaoui", email, "0612345678", "SIMAC",
                (date.today() + timedelta(days=90)).isoformat(), jeton))
    db.commit()


def _depot(client, code="fiscale", contenu=PDF, nom="attestation.pdf", **dates):
    client.get("/coffre")
    return client.post("/coffre/deposer",
                       data={"type_piece": code, "csrf_token": client.cookies.get("_csrf"), **dates},
                       files={"fichier": (nom, contenu, "application/pdf")},
                       follow_redirects=False)


class TestRegles:
    def test_expiration_proposee(self):
        from app.services.coffre import expiration_proposee
        assert expiration_proposee("fiscale", "2026-03-15") == "2027-03-15"
        assert expiration_proposee("rc", "2026-11-30") == "2027-02-28"
        assert expiration_proposee("statuts", "2026-03-15") == ""

    def test_statut(self):
        from app.services.coffre import statut
        auj = date(2026, 10, 21)
        assert statut("2026-10-20", auj)[0] == "expire"
        assert statut("2026-11-10", auj)[0] == "bientot"
        assert statut("2027-06-01", auj)[0] == "valide"
        assert statut("", auj)[0] == "permanent"

    def test_un_faux_pdf_est_refuse(self, db, coffre_vide):
        _membre(db)
        assert coffre_vide.enregistrer(1, "fiscale", b"MZ\x90\x00", "virus.pdf") == (False, "format")
        assert coffre_vide.enregistrer(1, "fiscale", PDF, "x.exe") == (False, "format")
        assert coffre_vide.enregistrer(1, "fiscale", PDF * 1, "x.pdf")[0] is True

    def test_taille(self, db, coffre_vide):
        _membre(db)
        gros = PDF + b"0" * coffre_vide.TAILLE_MAX
        assert coffre_vide.enregistrer(1, "fiscale", gros, "x.pdf") == (False, "taille")


class TestParcours:
    def test_depot_et_telechargement(self, client, db, coffre_vide):
        _membre(db)
        client.cookies.set("_session", "jeton-coffre")
        r = _depot(client, delivre_le="2026-10-01")
        assert r.status_code == 302 and "ok=fiscale" in r.headers["location"]
        p = coffre_vide.pieces(1)["fiscale"]
        assert p["expire_le"] == "2027-10-01"
        assert ".." not in p["fichier"] and p["fichier"].endswith(".pdf")
        f = client.get(f"/coffre/{p['id']}/fichier")
        assert f.status_code == 200 and f.content == PDF

    def test_un_membre_ne_lit_pas_le_coffre_d_un_autre(self, client, db, coffre_vide):
        _membre(db, 1, "jeton-coffre-a", "a@x.ma")
        _membre(db, 2, "jeton-coffre-b", "b@x.ma")
        ok, pid = coffre_vide.enregistrer(1, "cnss", PDF, "cnss.pdf")
        client.cookies.set("_session", "jeton-coffre-b")
        assert client.get(f"/coffre/{pid}/fichier").status_code == 404
        client.get("/coffre")
        client.post(f"/coffre/{pid}/supprimer", data={"csrf_token": client.cookies.get("_csrf")})
        assert coffre_vide.piece(1, pid), "la pièce de A est intacte"

    def test_la_page(self, client, db, coffre_vide):
        _membre(db)
        client.cookies.set("_session", "jeton-coffre")
        page = client.get("/coffre").text
        assert "Attestation de régularité fiscale" in page and "0 / 3" in page

    def test_anonyme(self, client, db):
        assert client.get("/coffre", follow_redirects=False).status_code == 302


class TestFaceAuMarche:
    def test_verifie_a_la_date_limite(self, db, coffre_vide):
        _membre(db)
        # Valide aujourd'hui, expirée avant la date limite du marché.
        coffre_vide.enregistrer(1, "fiscale", PDF, "f.pdf",
                                expire_le=(date.today() + timedelta(days=5)).isoformat())
        coffre_vide.enregistrer(1, "cnss", PDF, "c.pdf",
                                expire_le=(date.today() + timedelta(days=200)).isoformat())
        t = {"id": "ao_1", "type_procedure": "marche",
             "date_limite": (date.today() + timedelta(days=20)).strftime("%d/%m/%Y"),
             "description": "Qualifications : A.2 Travaux / Classe 3 Agréments : "}
        etats = {d["code"]: d["etat"] for d in coffre_vide.pour_marche(1, t)}
        assert etats == {"fiscale": "expiree_a_la_date", "cnss": "ok", "rc": "manquante",
                         "qualification": "manquante"}


class TestRappels:
    def test_un_rappel_par_seuil(self, db, coffre_vide, monkeypatch):
        _membre(db)
        envoyes = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envoyes.append(s) or True)
        coffre_vide.enregistrer(1, "fiscale", PDF, "f.pdf",
                                expire_le=(date.today() + timedelta(days=20)).isoformat())
        assert coffre_vide.envoyer_rappels() == 1
        assert coffre_vide.envoyer_rappels() == 0, "pas deux fois le même seuil"
        # Huit jours plus tard: le seuil de 7 jours sonne à son tour.
        assert coffre_vide.envoyer_rappels(date.today() + timedelta(days=14)) == 1
        assert "Attestation de régularité fiscale" in envoyes[0]

    def test_une_piece_remplacee_ne_sonne_plus(self, db, coffre_vide, monkeypatch):
        _membre(db)
        monkeypatch.setattr("app.services.notifications.email_send", lambda *a: True)
        coffre_vide.enregistrer(1, "cnss", PDF, "old.pdf",
                                expire_le=(date.today() + timedelta(days=3)).isoformat())
        coffre_vide.enregistrer(1, "cnss", PDF, "new.pdf",
                                expire_le=(date.today() + timedelta(days=360)).isoformat())
        assert coffre_vide.envoyer_rappels() == 0
